"""住所 → 公開データ（座標・航空写真・標高・用途地域・地価・ハザード・地形）。"""
import base64
import os
import tempfile

from .engine import terrain


def fetch_land(address):
    job = tempfile.mkdtemp(prefix="land_", dir="/tmp")
    spec = {"project": {"address": address}}
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
    return out
