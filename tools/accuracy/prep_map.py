"""各物件の座標から、地図の建物外形と番号付き航空写真を作る（本番の /api/land と同じ処理）。"""
import base64, json, os, sys, concurrent.futures as cf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
from webapp import footprint
from webapp.engine import public_data

E = os.environ.get("EVAL_DIR", os.path.join(os.path.dirname(__file__), "../../jobs/eval"))
coords = json.load(open(f"{E}/coords.json"))

def one(pid):
    lat, lon = coords[pid]
    d = f"{E}/{pid}"
    fp = footprint.outlines(lat, lon)
    ap = public_data.aerial_photo(lat, lon, zoom=19, size_px=768, out_path=f"{d}/aerial.jpg")
    b64 = base64.b64encode(open(f"{d}/aerial.jpg", "rb").read()).decode()
    marked = footprint.draw_on_aerial(b64, lat, fp["outlines"]) if fp["outlines"] else b64
    open(f"{d}/aerial_marked.jpg", "wb").write(base64.b64decode(marked))
    json.dump(fp["outlines"], open(f"{d}/outlines.json", "w"), ensure_ascii=False)
    return pid, len(fp["outlines"]), [(o["no"], o["area_m2"], o["contains_point"], o["dist_m"]) for o in fp["outlines"][:3]]

with cf.ThreadPoolExecutor(4) as ex:
    for r in ex.map(one, sorted(coords)):
        print(*r, flush=True)
