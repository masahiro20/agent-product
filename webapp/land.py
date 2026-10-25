"""住所 → 公開データ（座標・航空写真・標高・用途地域・地価・ハザード・地形）。"""
import base64
import concurrent.futures as cf
import os
import tempfile

from . import footprint
from .engine import public_data, terrain


def fetch_land(address):
    job = tempfile.mkdtemp(prefix="land_", dir="/tmp")
    spec = {"project": {"address": address}}
    # 建物外形（基盤地図情報）は標高・用途地域などと並行して取る
    pool = cf.ThreadPoolExecutor(1)
    geo = None
    try:
        geo = public_data.geocode(address)
    except Exception:  # noqa: BLE001  住所が引けなければ terrain 側のエラーとして扱う
        pass
    fut = pool.submit(footprint.outlines, geo[0], geo[1]) if geo else None
    info = terrain.fetch(spec, job, half_size_m=35.0, step_m=1.0)
    t = spec.get("terrain", {})
    out = {
        "address": address,
        "lat": t.get("lat"), "lon": t.get("lon"), "geocode_title": t.get("geocode_title"),
        "dem_world": t.get("dem_world"), "dem_source": t.get("dem_source"),
        "land_info": spec.get("land_info", []),
        "attribution": spec.get("data_attribution", []),
        "warnings": [v for k, v in info.items() if k.endswith("_error")],
    }
    ap = t.get("aerial_photo")
    if ap and os.path.exists(ap):
        with open(ap, "rb") as f:
            out["aerial_b64"] = base64.b64encode(f.read()).decode()
    out["outlines"] = []
    if fut:
        try:
            fp = fut.result(timeout=40)
            out["outlines"] = fp["outlines"]
            if fp.get("attribution"):
                out["attribution"] = out["attribution"] + [fp["attribution"]]
        except Exception as e:  # noqa: BLE001
            out["warnings"].append(f"建物外形の取得に失敗: {e}")
    pool.shutdown(wait=False)
    # 航空写真の中心は terrain の座標。外形は同じ住所の座標なので、そのまま重ねられる
    if out.get("aerial_b64") and out["outlines"] and out.get("lat") is not None:
        out["aerial_b64"] = footprint.draw_on_aerial(out["aerial_b64"], out["lat"], out["outlines"])
    return out
