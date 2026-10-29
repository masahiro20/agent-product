"""SUUMO の中古戸建て（外観写真だけ）を本番の AI 読み取りにかけ、掲載の数値と比べる。

使い方: python3 run_eval.py <tag> [p01 p02 ...]
結果: eval/results_<tag>.json（読み取り結果・数量・正解との差）
"""
import base64
import concurrent.futures as cf
import glob
import io
import json
import os
import sys
import time
import urllib.request

from PIL import Image

BASE = os.environ.get("EVAL_BASE", "https://genchi-photo-report.vercel.app")
KEY = os.environ.get("EVAL_KEY", "")
EVAL = os.environ.get("EVAL_DIR", os.path.join(os.path.dirname(__file__), "../../jobs/eval"))


def post(path, body, timeout=330):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                                 {"content-type": "application/json", "x-access-key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def encode(path, long_side=1568, q=80):
    im = Image.open(path).convert("RGB")
    k = long_side / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode()


def run_one(folder):
    truth = json.load(open(os.path.join(folder, "truth.json"), encoding="utf-8"))
    photos = sorted(glob.glob(os.path.join(folder, "photo*.jpg")))
    caps = truth.get("photo_captions") or []
    names = [(c.get("category") if isinstance(c, dict) else str(c)) for c in caps]  # 広告文は渡さない
    payload = [{"name": (names[i] if i < len(names) and names[i] else os.path.basename(p)), "data": encode(p)} for i, p in enumerate(photos)]
    # 町名までの住所（番地なし）。航空写真は別の家が写るので渡さない＝外観写真だけで読む
    t0 = time.time()
    for attempt in range(6):
        try:
            body = {"photos": payload, "address": truth.get("address", ""), "notes": "", "land_info": []}
            if os.environ.get("EVAL_MAP") and os.path.exists(os.path.join(folder, "aerial_marked.jpg")):
                # 本番と同じく、番号付きの航空写真と地図の建物外形を渡す
                body["aerial_b64"] = base64.b64encode(open(os.path.join(folder, "aerial_marked.jpg"), "rb").read()).decode()
                body["outlines"] = [{k: v for k, v in o.items() if k != "poly_m"}
                                    for o in json.load(open(os.path.join(folder, "outlines.json"), encoding="utf-8"))]
            if os.environ.get("EVAL_EFFORT"):
                body["effort"] = os.environ["EVAL_EFFORT"]
            res = post("/api/analyze", body)
            if res.get("error"):  # 長い処理は 200 で本文に error を入れて返す
                raise RuntimeError(res["error"])
            break
        except Exception as e:  # 混雑時は少し待って再試行
            err = getattr(e, "read", lambda: b"")()[:300]
            print(os.path.basename(folder), "retry", attempt, e, err, flush=True)
            time.sleep(15 + 15 * attempt)
    else:
        return {"id": os.path.basename(folder), "error": "analyze failed"}
    secs = time.time() - t0
    reading = res["reading"]
    q = post("/api/quantities", {"reading": reading, "outlines": body.get("outlines") or []})
    b = reading["building"]
    s = reading["site"]
    return {"id": os.path.basename(folder), "secs": round(secs), "usage": res.get("usage"), "truth": truth,
            "pred": {"floor_area_m2": q.get("floor_area_m2"), "floors": b["floors"], "structure": b["structure"],
                     "built_year": b["built_year_est"], "frontage_m": b["frontage_m"], "depth_m": b["depth_m"],
                     "eave_h": b["eave_h"], "floor_plans": b.get("floor_plans"),
                     "site_area_m2": round(s["frontage_m"] * s["depth_m"], 1),
                     "map_outline_no": b.get("map_outline_no"), "roof_material": b.get("roof_material"), "roof_pitch": b.get("roof_pitch_sun"),
                     "foundation": b.get("foundation_type"), "measure_basis": b.get("measure_basis"),
                     "checks": q.get("checks"), "detail": q.get("detail")},
            "reading": reading}


def main():
    tag = sys.argv[1]
    ids = sys.argv[2:] or sorted(os.path.basename(p) for p in glob.glob(os.path.join(EVAL, "p[0-9]*")))
    out_path = os.path.join(EVAL, f"results_{tag}.json")
    done = {}
    if os.path.exists(out_path):
        done = {r["id"]: r for r in json.load(open(out_path, encoding="utf-8")) if not r.get("error")}
    todo = [i for i in ids if i not in done]
    with cf.ThreadPoolExecutor(3) as ex:
        for r in ex.map(lambda i: run_one(os.path.join(EVAL, i)), todo):
            done[r["id"]] = r
            print(r["id"], r.get("error") or f"{r['pred']['floor_area_m2']:.1f}㎡ vs {r['truth'].get('建物面積_m2')}", flush=True)
            json.dump(list(done.values()), open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
