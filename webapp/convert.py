"""読み取り結果（reading）＋公開データ（land）＋オプション → エンジン用の site.json（spec）。"""
import base64
import os

from .engine import terrain

COMPANY = os.environ.get("COMPANY_NAME", "ホームランディック")
ROT_BY_ROAD = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}


def _el(e):
    t = e["type"]
    label = e.get("label") or None
    x, z, w, h = e.get("x", 0), e.get("z", 0), e.get("w", 0), e.get("h", 0)
    if t == "stair":
        return {"type": t, "x0": x, "z0": z, "x1": x + w, "z1": z + h, "rail_h": 0.9, "label": label}
    if t == "stair_front":
        return {"type": t, "x": x, "w": w, "z0": z, "z1": z + h}
    if t == "pipe":
        return {"type": t, "x": x, "z0": z, "z1": z + max(h, 0.1)}
    if t == "post":
        return {"type": t, "x": x, "z": z, "h": h, "w": w or 0.1}
    if t == "block_wall":
        return {"type": t, "x": x, "w": w, "z": z, "courses": max(1, int(e.get("courses") or round(h / 0.2) or 1)),
                "label": label or None}
    if t == "tree":
        return {"type": t, "x": x, "h": h, "w": w or h * 0.6, **({"label": label} if label else {})}
    out = {"type": t, "x": x, "z": z, "w": w, "h": h, "label": label}
    if t == "window" and e.get("grille"):
        out["grille"] = True
    return out


def _save_photos(photos, job_dir):
    out = []
    for i, p in enumerate(photos, 1):
        path = os.path.join(job_dir, f"photo{i}.jpg")
        with open(path, "wb") as f:
            f.write(base64.b64decode(p["data"]))
        out.append(path)
    return out


def to_spec(reading, land, photos, options, job_dir):
    os.makedirs(job_dir, exist_ok=True)
    land = land or {}
    options = options or {}
    b = reading.get("building") or {}
    s = reading.get("site") or {}
    address = options.get("address") or land.get("address") or ""
    spec = {
        "project": {"name": options.get("project_name") or reading.get("project_name") or "現地写真 調査レポート",
                    "slug": "report", "address": address,
                    "purpose": options.get("purpose") or "解体概算・造成計画",
                    "author": f"{COMPANY} 現地写真AI推定（参考図）"},
        "region": options.get("region") or "default",
        "conditions": list(dict.fromkeys(reading.get("conditions") or [])),
        "summary": reading.get("summary") or [],
        "next_checks": reading.get("next_checks") or [],
        "land_info": land.get("land_info") or [],
        "market_notes": land.get("market_notes") or [],
        "data_attribution": land.get("attribution") or [],
    }

    paths = _save_photos(photos or [], job_dir)
    marks_by_idx = {p.get("photo_index"): p for p in reading.get("photos") or []}
    spec["photos"] = []
    for i, path in enumerate(paths, 1):
        pr = marks_by_idx.get(i) or {}
        spec["photos"].append({
            "no": i, "path": path, "caption": pr.get("caption") or (photos[i - 1].get("name") or ""),
            "marks": [{"bbox": [m["x0"], m["y0"], m["x1"], m["y1"]], "label": m["label"], "basis": m.get("basis", "")}
                      for m in pr.get("marks", []) if m["x1"] > m["x0"] and m["y1"] > m["y0"]]})

    # 建物
    if b.get("exists", True) and options.get("include_demolition", True):
        fl = [v for v in (b.get("floor_levels") or []) if v is not None] or [0.45, 3.2]
        faces = []
        for k, f in enumerate(b.get("faces") or []):
            faces.append({"name": f["name"], "width_m": f["width_m"], "eave_h": b["eave_h"], "floors": fl,
                          "wall_pattern": f.get("wall_pattern", "mortar"),
                          "roof": {"type": f["roof_type"], "ridge_h": b.get("ridge_h") or b["eave_h"],
                                   "overhang": b.get("roof_overhang_m") or 0.45,
                                   **({"label": b["roof_label"]} if k == 0 and b.get("roof_label") else {})},
                          "elements": [_el(e) for e in f.get("elements", [])]})
        annexes = []
        for a in b.get("annexes") or []:
            item = {"name": a["name"], "basis": a.get("basis", "")}
            if a.get("price_key") and a["price_key"] != "none":
                item.update({"price_key": a["price_key"], "qty": a.get("qty") or 1, "unit": a.get("unit") or "基"})
            annexes.append(item)
        spec["building"] = {
            "structure": b.get("structure", "wood"), "use": b.get("use", ""), "floors": b.get("floors", 2),
            "built_year_est": b.get("built_year_est"),
            "footprint": {"width_m": b["frontage_m"], "depth_m": b["depth_m"]}, "eave_h": b["eave_h"],
            "units": {"count": b.get("units_count") or 1, "layout": b.get("unit_layout") or "house_4LDK",
                      "area_each_m2": b.get("unit_area_m2") or None},
            "annexes": annexes, "measure_basis": b.get("measure_basis") or [], "elevations": faces,
            "finishes": b.get("finishes") or {},
            "floor_plans": [{**p, "w": b["frontage_m"], "d": b["depth_m"]} if p.get("floor") == 1 else p  # 1F の外形は建物の幅・奥行に合わせる
                            for p in b.get("floor_plans") or [] if p.get("area_m2") or (p.get("w") and p.get("d"))],
            "floor_levels": fl, "roof": {"pitch_sun": b.get("roof_pitch_sun"), "kind": b.get("roof_material") or "unknown",
                                         "overhang": b.get("roof_overhang_m") or 0.45, "ridge_h": b.get("ridge_h")},
            "foundation_type": b.get("foundation_type") or "unknown",
            "map_outline": next(({k: o[k] for k in ("no", "area_m2", "long_m", "short_m")}
                                 for o in land.get("outlines") or [] if o.get("no") == b.get("map_outline_no")), None),
        }
        spec["leftover"] = {"layout": b.get("unit_layout") or "house_4LDK", "occupied_units": b.get("occupied_units") or 0,
                            "extra_m3": b.get("outdoor_leftover_m3") or 0, "aircon_units": b.get("aircon_units") or 0}
        ext = []
        for e in reading.get("exterior") or []:
            if not e.get("qty"):
                continue
            item = {"key": e["key"], "label": e["label"], "qty": e["qty"], "unit": e.get("unit", ""), "basis": e.get("basis", "")}
            pts = [(e.get("x0", 0), e.get("y0", 0)), (e.get("x1", 0), e.get("y1", 0))]
            if any(v for p in pts for v in p):
                item["geom"] = [list(pts[0])] if pts[0] == pts[1] else [list(p) for p in pts]
                item["short"] = e["label"][:10]
            ext.append(item)
        spec["exterior"] = ext

    # 敷地（造成）
    if options.get("include_grading", True) and s.get("frontage_m") and s.get("depth_m"):
        F, D = s["frontage_m"], s["depth_m"]
        rw = s.get("road_width_m") or 4.0
        side = s.get("road_side", "unknown")
        site = {
            "boundary": [[0, 0], [F, 0], [F, D], [0, D]],
            "road": {"edge": [[0, 0], [F, 0]], "width_m": rw, "name": s.get("road_name") or "前面道路"},
            "north_rot_deg": ROT_BY_ROAD.get(side, 0.0),
            "existing": {"points": []},
            "existing_buildings": [],
            "plan": {"fh_mode": options.get("fh_mode") or "optimize", "slab_slope_pct": 1.0, "basins": 2},
            "soil": "default",
        }
        if side == "unknown":
            spec["next_checks"] = spec["next_checks"] + ["前面道路の方位が未確定（図の方位記号は仮）"]
        if b.get("exists", True) and b.get("frontage_m"):
            ox, oy = s.get("building_offset_left_m", 1.0), s.get("building_setback_m", 1.0)
            site["existing_buildings"].append({"polygon": [[ox, oy], [ox + b["frontage_m"], oy],
                                                           [ox + b["frontage_m"], oy + b["depth_m"]], [ox, oy + b["depth_m"]]],
                                               "label": "既存建物（解体）"})
            for r in s.get("extra_footprints") or []:
                site["existing_buildings"].append({"polygon": [[r["x"], r["y"]], [r["x"] + r["w"], r["y"]],
                                                               [r["x"] + r["w"], r["y"] + r["d"]], [r["x"], r["y"] + r["d"]]],
                                                   "label": r["label"]})
        spec["site"] = site
        if s.get("access"):
            spec["access"] = s["access"]
        spec["_level_points"] = s.get("level_points") or []
        spec["_road_center"] = [F / 2, -rw / 2]

    if s.get("access") and not spec.get("access"):
        spec["access"] = s["access"]

    # 公開データ
    if land.get("lat") is not None:
        spec["terrain"] = {"lat": land["lat"], "lon": land["lon"], "geocode_title": land.get("geocode_title"),
                           "dem_world": land.get("dem_world"), "dem_source": land.get("dem_source")}
        if land.get("aerial_b64"):
            ap = os.path.join(job_dir, "aerial.jpg")
            with open(ap, "wb") as f:
                f.write(base64.b64decode(land["aerial_b64"]))
            spec["terrain"]["aerial_photo"] = ap
    finalize_levels(spec)
    return spec


def finalize_levels(spec):
    """DEM を敷地に当てはめ、写真から読んだ高低差（道路中心からの差）を T.P. に直して現況点にする。"""
    site = spec.get("site")
    if not site:
        return
    rng = terrain.apply_dem(spec)
    rc = spec.pop("_road_center", None)
    lvl = spec.pop("_level_points", [])
    base = 0.0
    dem = site["existing"].get("dem")
    if dem and rc:
        from .engine import grading
        surf = grading.Surface({"dem": dem})
        base = surf.z(*rc)
    pts = []
    if not dem and rc:
        F = site["boundary"][1][0]
        pts += [{"x": rc[0], "y": rc[1], "z": base, "label": "道路中心", "basis": "高さの基準（KBM）"},
                {"x": 0.0, "y": rc[1], "z": base, "label": "道路中心（左）", "basis": "道路は平坦と仮定"},
                {"x": F, "y": rc[1], "z": base, "label": "道路中心（右）", "basis": "道路は平坦と仮定"}]
    for p in lvl:
        pts.append({"x": p["x"], "y": p["y"], "z": round(base + p["dz_from_road_center_m"], 3),
                    "label": p["label"], "basis": p.get("basis", "")})
    site["existing"]["points"] = pts
    site["existing"]["source"] = ("dem+points" if pts else "dem") if dem else "points"
    if not dem and not pts:
        # 高さの情報がまったく無いときは平坦とみなす
        F = site["boundary"][1][0]
        D = site["boundary"][2][1]
        site["existing"]["points"] = [{"x": x, "y": y, "z": 0.0, "label": "", "basis": "高低差の情報なし（平坦と仮定）"}
                                      for x, y in ((0, 0), (F, 0), (F, D), (0, D))]
    spec.setdefault("terrain", {})["dem_range"] = rng
