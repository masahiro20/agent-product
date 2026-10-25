"""現地写真レポート Web アプリ（FastAPI）。

画面: public/index.html（Vercel では public/ を CDN が配信）
API:
  GET  /api/health    動作確認
  GET  /api/catalog   入力画面の選択肢（外構の単価キー・施工条件・地域）
  POST /api/land      住所 → 公開データ（航空写真・標高・用途地域・地価・ハザード）
  POST /api/analyze   写真 → AI の読み取り結果
  POST /api/quantities 読み取り結果 → 建物の数量と食い違いチェック（確認画面用）
  POST /api/build     読み取り結果 → 概算サマリー / PDF / Excel / DXF
"""
import hmac
import os
import shutil
import tempfile
import traceback

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from webapp import convert, land, reading
from webapp.engine import demolition, load_data, report

app = FastAPI(title="現地写真レポート")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")
MAX_PHOTOS = 12


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
    fmts = {"summary": (), "pdf": ("pdf",), "xlsx": ("xlsx",), "dxf": ("dxf",), "rfq_pdf": ("rfq_pdf",), "rfq_xlsx": ("rfq_xlsx",)}
    if fmt not in fmts:
        return JSONResponse({"error": f"不明な形式です: {fmt}"}, status_code=400)
    job = tempfile.mkdtemp(prefix="job_", dir="/tmp")
    try:
        opts = body.get("options") or {}
        spec = convert.to_spec(body["reading"], body.get("land"), body.get("photos"), opts, job)
        summary = report.build(spec, os.path.join(job, "out"), job, formats=fmts[fmt], rfq_opts=opts.get("rfq"))
        if fmt == "summary":
            return {k: v for k, v in summary.items() if k not in ("pdf", "xlsx", "dxf")}
        path = summary.get(fmt)
        if not path or not os.path.exists(path):
            return JSONResponse({"error": f"{fmt} を作れませんでした"}, status_code=500)
        media = {"pdf": "application/pdf", "rfq_pdf": "application/pdf", "dxf": "application/dxf"}.get(
            fmt, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with open(path, "rb") as f:
            data = f.read()
        return Response(data, media_type=media)
    except ValueError as e:
        return _err(e, 400)
    except Exception as e:
        return _err(e)
    finally:
        shutil.rmtree(job, ignore_errors=True)


if not os.environ.get("VERCEL"):
    # ローカル実行時だけ public/ を配信（Vercel では CDN が配信する）
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public"), html=True), name="public")
