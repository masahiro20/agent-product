"""現地写真レポート Web アプリ（FastAPI）。

画面: public/index.html（Vercel では public/ を CDN が配信）
API:
  GET  /api/health    動作確認
  GET  /api/catalog   入力画面の選択肢（外構の単価キー・施工条件・地域）
  POST /api/land      住所 → 公開データ（航空写真・標高・用途地域・地価・ハザード）
  POST /api/analyze   写真 → AI の読み取り結果
  POST /api/quantities 読み取り結果 → 建物の数量と食い違いチェック（確認画面用）
  POST /api/build     読み取り結果 → 概算サマリー / PDF / Excel / DXF
  /api/cases …        案件の保存・一覧・読み込み・削除（Vercel Blob）
  GET  /files/<id>/<形式>  期限付きリンクで資料をダウンロード（MCP の回答に載せる）
  POST /mcp           MCP サーバー（claude.ai のカスタムコネクタ用。認証は /oauth/* の Google ログイン）
"""
import hmac
import html
import os
import shutil
import tempfile
import traceback
import urllib.parse

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.requests import ClientDisconnect

from webapp import convert, land, links, mcp_server, oauth, reading, service, store
from webapp.engine import demolition, load_data

app = FastAPI(title="現地写真レポート")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")
MAX_PHOTOS = 12


@app.exception_handler(ClientDisconnect)
async def client_disconnect(request: Request, exc: ClientDisconnect):
    # 写真の送信が途中で切れた（回線の瞬断）。画面側が送り直すので、エラー落ちにしない
    return JSONResponse({"error": "通信が途中で切れました。もう一度お試しください。"}, status_code=503)


@app.middleware("http")
async def access_key(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health" and ACCESS_PASSWORD:
        key = request.headers.get("x-access-key", "")
        if not hmac.compare_digest(key.encode(), ACCESS_PASSWORD.encode()):
            return JSONResponse({"error": "アクセスキーが違います"}, status_code=401)
    return await call_next(request)


def _err(e, status=500):
    traceback.print_exc()
    return JSONResponse({"error": str(e) or e.__class__.__name__}, status_code=status)


@app.get("/api/health")
def health():
    return {"ok": True, "model": reading.MODEL, "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "auth": bool(ACCESS_PASSWORD)}


@app.get("/api/catalog")
def catalog():
    prices = load_data("demolition_unit_prices.json")
    factors = prices.get("region_factor", {})
    info = prices.get("region_info", {})
    regions = [{"key": k, "factor": factors.get(k, 1.0), "label": info[k]["label"], "basis": info[k]["basis"]}
               for k in info.get("order", []) if k in info]
    return {"exterior": reading.exterior_catalog(), "conditions": reading.condition_catalog(),
            "regions": regions, "layouts": reading.LAYOUTS, "structures": reading.STRUCTURES}


@app.post("/api/land")
async def api_land(request: Request):
    body = await request.json()
    address = (body.get("address") or "").strip()
    if not address:
        return JSONResponse({"error": "住所を入力してください"}, status_code=400)
    try:
        return land.fetch_land(address)
    except Exception as e:
        return _err(e)


@app.post("/api/analyze")
async def api_analyze(request: Request):
    body = await request.json()
    photos = body.get("photos") or []
    if not photos:
        return JSONResponse({"error": "写真を1枚以上選んでください"}, status_code=400)
    if len(photos) > MAX_PHOTOS:
        return JSONResponse({"error": f"写真は{MAX_PHOTOS}枚までです"}, status_code=400)
    mock = os.environ.get("SITE_MOCK_READING")  # 開発用: APIキー無しで画面を確認する
    if mock:
        import json
        with open(mock, encoding="utf-8") as f:
            return {"reading": json.load(f)["reading"], "usage": {"mock": True}}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"error": "AI の読み取りに必要な Claude API キーが未設定です。管理者が Vercel の環境変数 "
                                      "ANTHROPIC_API_KEY を設定してください。"}, status_code=503)
    try:
        r, usage = reading.read_site(photos, body.get("address"), body.get("notes"), body.get("land_info"),
                                     body.get("aerial_b64"), effort=body.get("effort"),
                                     outlines=body.get("outlines"))  # effort は精度検証用（既定は SITE_EFFORT）
        return {"reading": r, "usage": usage}
    except anthropic.AuthenticationError as e:
        return _err(RuntimeError("Claude API キーが無効です。設定されているキーを確認してください。"), 503)
    except anthropic.RateLimitError:
        return _err(RuntimeError("AI の利用が混み合っています。1分ほど待ってからもう一度お試しください。"), 429)
    except anthropic.APIStatusError as e:
        if e.status_code == 413:
            return _err(RuntimeError("写真の容量が大きすぎます。枚数を減らしてください。"), 413)
        if e.status_code in (500, 502, 503, 529):
            return _err(RuntimeError("AI 側が一時的に混み合っています。少し待ってからもう一度お試しください。"), 503)
        return _err(RuntimeError(f"AI の呼び出しでエラーになりました（{e.status_code}）: {e.message}"), 502)
    except anthropic.APIConnectionError:
        return _err(RuntimeError("AI に接続できませんでした。少し待ってからもう一度お試しください。"), 502)
    except Exception as e:
        return _err(e)


@app.post("/api/quantities")
async def api_quantities(request: Request):
    """確認画面の編集中に、建物の数量（延床・外壁・屋根・基礎・廃材）と食い違いチェックだけを返す。"""
    body = await request.json()
    job = tempfile.mkdtemp(prefix="q_", dir="/tmp")
    try:
        spec = convert.to_spec(body["reading"], {"outlines": body.get("outlines") or []}, None, {"include_grading": False}, job)
        if not spec.get("building"):
            return {"detail": None, "checks": []}
        q = demolition.building_quantities(spec["building"], load_data("demolition_unit_prices.json").get("quantity_rates"))
        return {"floor_area_m2": q["floor_area_m2"], "detail": q["detail"], "checks": q["checks"]}
    except Exception as e:
        return _err(e, 400)
    finally:
        shutil.rmtree(job, ignore_errors=True)


@app.post("/api/build")
async def api_build(request: Request):
    body = await request.json()
    fmt = body.get("format", "summary")
    try:
        out = service.build(body["reading"], body.get("land"), body.get("photos"), body.get("options") or {}, fmt)
        if fmt == "summary":
            return out
        return Response(out[0], media_type=out[1])
    except ValueError as e:
        return _err(e, 400)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------- 案件の保存

def _need_store():
    if not store.enabled():
        raise RuntimeError("案件の保存先（Vercel Blob）が未設定です")


@app.get("/api/cases")
def api_cases():
    try:
        _need_store()
        return {"cases": store.list_cases()}
    except Exception as e:
        return _err(e)


@app.post("/api/cases")
async def api_case_save(request: Request):
    """新規保存（photos あり）または更新（id あり・photos なし）。"""
    body = await request.json()
    try:
        _need_store()
        if body.get("id"):
            case = store.load_case(body["id"])
            for k in ("title", "address", "reading", "land", "options", "summary", "actuals", "memo"):
                if k in body:
                    case[k] = body[k]
            return {"case": _brief_case(store.save_case(case))}
        # 新規: 写真は 4.5MB の上限に掛からないよう、続けて PUT /api/cases/<id>/photos/<n> で1枚ずつ送ってもらう
        opts = body.get("options") or {}
        names = body.get("photo_names") or []
        case = store.save_case({"title": opts.get("project_name") or body["reading"].get("project_name") or "",
                                "address": opts.get("address") or "", "reading": body["reading"], "land": body.get("land"),
                                "options": opts, "summary": body.get("summary"), "photo_names": names,
                                "photo_count": len(names), "source": "web"})
        return {"case": _brief_case(case)}
    except KeyError:
        return JSONResponse({"error": "案件が見つかりません"}, status_code=404)
    except Exception as e:
        return _err(e)


def _brief_case(case):
    return {k: case.get(k) for k in ("id", "title", "address", "created_at", "updated_at")}


@app.get("/api/cases/{case_id}")
def api_case_get(case_id: str):
    try:
        _need_store()
        return {"case": store.load_case(case_id)}
    except KeyError:
        return JSONResponse({"error": "案件が見つかりません"}, status_code=404)
    except Exception as e:
        return _err(e)


@app.get("/api/cases/{case_id}/photos/{no}")
def api_case_photo(case_id: str, no: int):
    try:
        return Response(store.load_photo(case_id, no), media_type="image/jpeg")
    except Exception as e:
        return _err(e, 404)


@app.put("/api/cases/{case_id}/photos/{no}")
async def api_case_photo_put(case_id: str, no: int, request: Request):
    try:
        _need_store()
        store.save_photo(case_id, no, await request.body())
        return {"ok": True}
    except Exception as e:
        return _err(e)


@app.delete("/api/cases/{case_id}")
def api_case_delete(case_id: str):
    try:
        _need_store()
        store.delete_case(case_id)
        return {"ok": True}
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------- 期限付きの資料リンク

FILE_NAMES = {"pdf": "調査レポート.pdf", "xlsx": "概算見積.xlsx", "dxf": "図面.dxf", "rfq_pdf": "見積依頼書.pdf", "rfq_xlsx": "見積依頼_数量表.xlsx"}


@app.get("/files/{case_id}/{fmt}")
def file_link(case_id: str, fmt: str, request: Request):
    q = dict(request.query_params)
    if fmt not in FILE_NAMES or not links.verify(case_id, fmt, q):
        return HTMLResponse("<p>リンクの有効期限が切れているか、正しくありません。Claude にもう一度リンクを作ってもらってください。</p>", status_code=403)
    try:
        case = store.load_case(case_id)
        opts = dict(case.get("options") or {})
        if fmt.startswith("rfq_"):
            opts["rfq"] = {"kind": q.get("kind", "demolition"), "due": q.get("due", ""), "contact": q.get("contact", "")}
        data, media = service.build(case["reading"], case.get("land"), service.case_photos(case), opts, fmt)
        label = "解体" if q.get("kind") != "grading" else "造成"
        name = (case.get("title") or case_id) + "_" + (label if fmt.startswith("rfq_") else "") + FILE_NAMES[fmt]
        return Response(data, media_type=media,
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})
    except KeyError:
        return HTMLResponse("<p>案件が見つかりません。</p>", status_code=404)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------- MCP（claude.ai のカスタムコネクタ）

def _base(request: Request):
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return os.environ.get("PUBLIC_BASE_URL") or f"{proto}://{host}"


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
def oauth_resource(request: Request):
    return oauth.protected_resource(_base(request))


@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/oauth-authorization-server/mcp")
def oauth_metadata(request: Request):
    return oauth.authorization_server(_base(request))


@app.post("/oauth/register")
async def oauth_register(request: Request):
    try:
        return JSONResponse(oauth.register(await request.json()), status_code=201)
    except ValueError as e:
        return JSONResponse({"error": "invalid_redirect_uri", "error_description": str(e)}, status_code=400)


def _oauth_page(msg, status=400):
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<title>現地写真レポート</title><div style='font-family:sans-serif;max-width:560px;margin:40px auto;padding:0 16px'>"
                        f"<h2>現地写真レポート</h2><p>{html.escape(msg)}</p></div>", status_code=status)


@app.get("/oauth/authorize")
def oauth_authorize(request: Request):
    if not oauth.configured():
        return _oauth_page("Google ログインの設定（GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET）がまだです。管理者に連絡してください。", 503)
    try:
        return RedirectResponse(oauth.authorize_url(_base(request), dict(request.query_params)), status_code=302)
    except ValueError as e:
        return _oauth_page(str(e))


@app.get("/oauth/google/callback")
def oauth_google_callback(request: Request):
    try:
        return RedirectResponse(oauth.google_callback(_base(request), dict(request.query_params)), status_code=302)
    except PermissionError as e:
        return _oauth_page(str(e), 403)
    except Exception as e:
        traceback.print_exc()
        return _oauth_page(str(e))


@app.post("/oauth/token")
async def oauth_token(request: Request):
    form = {k: v[0] for k, v in urllib.parse.parse_qs((await request.body()).decode()).items()}
    try:
        return JSONResponse(oauth.token(form), headers={"Cache-Control": "no-store"})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/mcp")
async def mcp(request: Request):
    base = _base(request)
    user = oauth.user_from_bearer(request.headers.get("authorization", ""))
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={
            "WWW-Authenticate": f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'})
    body = await request.json()
    msgs = body if isinstance(body, list) else [body]
    out = [r for r in (mcp_server.handle(m, user, base) for m in msgs) if r is not None]
    if not out:
        return Response(status_code=202)
    return Response(mcp_server.dumps(out if isinstance(body, list) else out[0]), media_type="application/json")


@app.get("/mcp")
@app.delete("/mcp")
def mcp_other():
    return Response(status_code=405, headers={"Allow": "POST"})


if not os.environ.get("VERCEL"):
    # ローカル実行時だけ public/ を配信（Vercel では CDN が配信する）
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public"), html=True), name="public")
