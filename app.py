"""現地写真レポート Web アプリ（FastAPI）。

画面: public/index.html（Vercel では public/ を CDN が配信）
API:
  GET  /api/health    動作確認
  GET  /api/catalog   入力画面の選択肢（外構の単価キー・施工条件・地域）
  POST /api/land      住所 → 公開データ（航空写真・標高・用途地域・地価・ハザード）
  POST /api/analyze   写真 → AI の読み取り結果
  POST /api/build     読み取り結果 → 概算サマリー / PDF / Excel / DXF
"""
import hmac
import os
import shutil
import tempfile
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from webapp import convert, land, reading
from webapp.engine import load_data, report

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
    regions = {k: v for k, v in prices.get("region_factor", {}).items() if isinstance(v, (int, float))}
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
    try:
        r, usage = reading.read_site(photos, body.get("address"), body.get("notes"), body.get("land_info"),
                                     body.get("aerial_b64"))
        return {"reading": r, "usage": usage}
    except Exception as e:
        return _err(e)


@app.post("/api/build")
async def api_build(request: Request):
    body = await request.json()
    fmt = body.get("format", "summary")
    job = tempfile.mkdtemp(prefix="job_", dir="/tmp")
    try:
        spec = convert.to_spec(body["reading"], body.get("land"), body.get("photos"), body.get("options"), job)
        summary = report.build(spec, os.path.join(job, "out"), job)
        if fmt == "summary":
            return summary
        path = {"pdf": summary["pdf"], "xlsx": summary["xlsx"], "dxf": summary["dxf"]}.get(fmt)
        if not path or not os.path.exists(path):
            return JSONResponse({"error": f"{fmt} を作れませんでした"}, status_code=500)
        media = {"pdf": "application/pdf",
                 "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "dxf": "application/dxf"}[fmt]
        with open(path, "rb") as f:
            data = f.read()
        return Response(data, media_type=media)
    except Exception as e:
        return _err(e)
    finally:
        shutil.rmtree(job, ignore_errors=True)


if not os.environ.get("VERCEL"):
    # ローカル実行時だけ public/ を配信（Vercel では CDN が配信する）
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public"), html=True), name="public")
