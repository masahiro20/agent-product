"""解体の数量算出と概算見積。

数量はすべて「写真からの推定値」。単価は data/demolition_unit_prices.json（出典付き）の
low / mid / high を使い、見積は 3 本立て（安め・標準・高め）で出す。
"""
import math

from .common import load_data, tsubo


def _poly_area(pts):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def _poly_perimeter(pts):
    return sum(math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


def building_quantities(b):
    """建物の数量（建築面積・延床・足場面積・廃材量・戸数）。"""
    q = {}
    fp = b.get("footprint", {})
    if fp.get("polygon"):
        area = _poly_area(fp["polygon"])
        perim = _poly_perimeter(fp["polygon"])
    else:
        w, d = fp["width_m"], fp["depth_m"]
        area = w * d
        perim = 2 * (w + d)
    floors = b.get("floors", 1)
    if b.get("floor_areas_m2"):
        nobe = sum(b["floor_areas_m2"])
    else:
        nobe = area * floors
    annex_area = 0.0
    annex_rows = []
    for a in b.get("annexes", []):
        aa = a.get("area_m2") or a.get("w", 0) * a.get("d", 0)
        cnt = a.get("count", 1)
        annex_rows.append({"name": a["name"], "area_m2": aa * cnt, "kind": a.get("kind", "")})
        if a.get("counts_in_floor_area"):
            annex_area += aa * cnt
    q["building_area_m2"] = area
    q["perimeter_m"] = perim
    q["floor_area_m2"] = nobe + annex_area
    q["floor_area_tsubo"] = tsubo(q["floor_area_m2"])
    q["annexes"] = annex_rows
    eave = b.get("eave_h", 3.0 * floors)
    # 足場架面積: 建物外周から 1m 離れた外周 × (軒高 + 1m)
    q["scaffold_m2"] = (perim + 8.0) * (eave + 1.0)
    q["eave_h"] = eave
    units = b.get("units") or {}
    if units:
        q["units_count"] = units.get("count")
        q["units_layout"] = units.get("layout")
        if units.get("area_each_m2"):
            q["units_area_check_m2"] = units["count"] * units["area_each_m2"]
    return q


def leftover_quantities(spec, prices):
    """残置物（家財）の推定数量。"""
    lo = spec.get("leftover") or {}
    std = load_data("leftover_standard.json") or {}
    b = spec["building"]
    units = b.get("units") or {}
    layout = lo.get("layout") or units.get("layout") or "house_4LDK"
    count = lo.get("occupied_units")
    if count is None:
        count = units.get("count", 1) if lo.get("assume_all_furnished", False) else 0
    rows = []
    total_m3 = 0.0
    per_layout = std.get("layouts", {}).get(layout, {})
    furniture = {}
    for key, n in per_layout.items():
        it = std["items"][key]
        furniture[key] = {"name": it["name"], "qty": n * count, "m3": it["m3"] * n * count,
                          "recycle": it.get("recycle")}
        total_m3 += it["m3"] * n * count
    loose = std.get("loose_factor", 1.6)
    vol_from_list = total_m3 * loose
    # 間取り別の相場体積（調査値）と比較し大きい方を採用
    table = (prices or {}).get("leftover_volume_m3", {})
    vol_table = table.get(layout)
    if isinstance(vol_table, dict):
        vol_table = vol_table.get("mid")
    vol_table = (vol_table or 0) * count
    extra = lo.get("extra_m3", 0.0)  # 写真で見えた屋外の残置物（ガラ・粗大ごみ等）
    vol = max(vol_from_list, vol_table) + extra
    rows = list(furniture.values())
    return {"layout": layout, "occupied_units": count, "furniture": rows,
            "volume_from_list_m3": round(vol_from_list, 1), "volume_from_table_m3": round(vol_table, 1),
            "extra_m3": extra, "volume_m3": round(vol, 1)}


def _price(prices, key):
    it = prices.get("items", {}).get(key)
    if not it:
        return None
    return it


def _num(v):
    if isinstance(v, dict):
        return v.get("mid")
    return v


def _line(cat, name, qty, unit, it, basis="", factor=1.0, src=None):
    if it is None:
        return {"cat": cat, "name": name, "qty": qty, "unit": unit, "price": None, "basis": basis,
                "low": None, "mid": None, "high": None, "src": src or [], "note": "単価未登録"}
    lo, mi, hi = it.get("low"), it.get("mid"), it.get("high")
    lo = lo if lo is not None else mi
    hi = hi if hi is not None else mi
    return {"cat": cat, "name": name, "qty": qty, "unit": unit,
            "price": {"low": lo, "mid": mi, "high": hi, "unit": it.get("unit", "")},
            "low": qty * lo * factor, "mid": qty * mi * factor, "high": qty * hi * factor,
            "basis": basis, "src": src if src is not None else it.get("src", []), "note": it.get("note", "")}


def estimate(spec):
    prices = load_data("demolition_unit_prices.json")
    if not prices:
        raise RuntimeError("data/demolition_unit_prices.json がありません")
    b = spec["building"]
    q = building_quantities(b)
    lines = []

    # 1. 建物本体
    st = b.get("structure", "wood")
    bp = dict(prices["building"].get(st) or prices["building"]["wood"])
    # 階数・規模による補正（3階建は割増、大規模は割安）
    adj = []
    sf = (prices.get("story_factor") or {}).get(f"{b.get('floors', 1)}F")
    if isinstance(sf, (int, float)) and sf != 1.0:
        adj.append((f"{b.get('floors')}階建 ×{sf}", sf))
    scf = prices.get("scale_factor") or {}
    t = q["floor_area_tsubo"]
    sk = "under_20tsubo" if t < 20 else "20_50tsubo" if t < 50 else "50_100tsubo" if t < 100 else "over_100tsubo"
    if isinstance(scf.get(sk), (int, float)) and scf[sk] != 1.0:
        adj.append((f"延床{t:.0f}坪 規模補正 ×{scf[sk]}", scf[sk]))
    for _, f in adj:
        for k in ("low", "mid", "high"):
            if bp.get(k) is not None:
                bp[k] = bp[k] * f
    # 単価の単位が 円/坪 の場合に備える
    unit_is_tsubo = "坪" in bp.get("unit", "")
    qty = q["floor_area_tsubo"] if unit_is_tsubo else q["floor_area_m2"]
    struct_name = {"wood": "木造", "light_steel": "軽量鉄骨造", "heavy_steel": "重量鉄骨造", "rc": "RC造"}.get(st, st)
    lines.append(_line("建物本体", f"{struct_name} {b.get('floors', 1)}階建 解体（上屋・基礎・分別）",
                       round(qty, 2), "坪" if unit_is_tsubo else "㎡", bp,
                       basis=f"延床 {q['floor_area_m2']:.1f}㎡（{q['floor_area_tsubo']:.1f}坪）推定。足場・養生・基礎撤去・廃材処分・簡易整地を含む" + "".join("／" + n for n, _ in adj)))
    for a in b.get("annexes", []):
        if a.get("price_key"):
            n = a.get("count", 1)
            aq = a.get("qty", n)
            lines.append(_line("建物本体", a["name"], aq, a.get("unit", "式"), _price(prices, a["price_key"]),
                               basis=a.get("basis", "写真")))
    if b.get("interior_stripping", False):
        lines.append(_line("建物本体", "内装解体（手作業分別）", round(q["floor_area_m2"], 1), "㎡",
                           _price(prices, "interior_stripping"), basis="延床"))

    # 2. 仮設・諸費
    # 市場の坪単価（building）は足場・養生、通常基礎撤去、廃材の運搬処分、簡易整地を含むので別計上しない。
    lines.append(_line("仮設", "重機回送費", 1, "式", _price(prices, "heavy_machine_transport"), basis="往復"))
    guard_days = spec.get("conditions_detail", {}).get("guard_days")
    if guard_days:
        lines.append(_line("仮設", "交通誘導員", guard_days, "人日", _price(prices, "guard_person_day"),
                           basis="前面道路の状況から推定"))

    # 3. 付帯（外構）
    for ex in spec.get("exterior", []):
        it = _price(prices, ex["key"])
        lines.append(_line("付帯工事", ex.get("label", ex["key"]), ex["qty"], ex.get("unit") or (it or {}).get("unit", "").replace("円/", ""),
                           it, basis=ex.get("basis", "")))

    # 4. 残置物
    lo = leftover_quantities(spec, prices)
    if lo["volume_m3"] > 0:
        lines.append(_line("残置物", f"残置物撤去・処分（{lo['layout']}×{lo['occupied_units']}戸＋屋外{lo['extra_m3']}㎥）",
                           lo["volume_m3"], "㎥", _price(prices, "leftover_m3"),
                           basis=f"家財リスト換算{lo['volume_from_list_m3']}㎥ / 相場表{lo['volume_from_table_m3']}㎥ の大きい方"))
    ac = spec.get("leftover", {}).get("aircon_units", 0)
    if ac:
        lines.append(_line("残置物", "エアコン撤去・フロン回収", ac, "台", _price(prices, "aircon_unit"),
                           basis="写真で確認した室外機台数"))
    rec = prices.get("items", {})
    recycle_keys = {"fridge": "recycle_fridge", "washer": "recycle_washer", "tv": "recycle_tv", "aircon": "recycle_aircon"}
    rec_counts = {}
    for f in lo["furniture"]:
        if f.get("recycle"):
            rec_counts[f["recycle"]] = rec_counts.get(f["recycle"], 0) + f["qty"]
    if ac:  # エアコンは「撤去・フロン回収」の単価にリサイクル料・運搬を含む
        rec_counts.pop("aircon", None)
    for k, n in rec_counts.items():
        if n and recycle_keys[k] in rec:
            lines.append(_line("残置物", rec[recycle_keys[k]]["name"], n, "台",
                               rec[recycle_keys[k]], basis="間取り別の想定台数"))

    # 5. 届出・手続
    if q["floor_area_m2"] >= 80:
        lines.append(_line("手続", "建設リサイクル法 届出（80㎡以上）", 1, "件", _price(prices, "recycling_notification")))
    lines.append(_line("手続", "建物滅失登記", 1, "件", _price(prices, "demolition_registration")))
    year = b.get("built_year_est")
    asb = prices.get("asbestos", {})
    if asb.get("survey"):
        lines.append(_line("手続", "アスベスト事前調査（書面・目視、必要に応じ分析）", 1, "件", asb["survey"],
                           basis="2022年4月〜 解体前の事前調査・報告が義務"))

    # 条件割増（本体・付帯に掛ける）
    factor = 1.0
    applied = []
    for cond in spec.get("conditions", []):
        cf = prices.get("condition_factor", {}).get(cond)
        if cf:
            f = cf.get("factor") or cf.get("mid") or 1.0
            factor *= f
            applied.append(f"{cf.get('name', cond)} ×{f}")
    region = spec.get("region", "default")
    rf = prices.get("region_factor", {}).get(region, prices.get("region_factor", {}).get("default", 1.0))
    rf = _num(rf) or 1.0

    def total(key):
        s = 0.0
        for ln in lines:
            if ln[key] is None:
                continue
            mult = rf
            if ln["cat"] in ("建物本体", "付帯工事"):
                mult *= factor
            if ln["cat"] == "手続":
                mult = 1.0
            s += ln[key] * mult
        return s

    sub = {k: total(k) for k in ("low", "mid", "high")}
    ov = prices["items"].get("overhead_rate", {})
    ov_rate = {k: (ov.get(k) if ov.get(k) is not None else ov.get("mid", 0)) / 100.0 for k in ("low", "mid", "high")}
    over = {k: sub[k] * ov_rate[k] for k in sub}
    tot = {k: sub[k] + over[k] for k in sub}

    # アスベスト含有時の追加（別枠）
    asb_extra = []
    if year and asb.get("suspect_by_year"):
        parts = []
        for rule in asb["suspect_by_year"]:
            if year <= rule.get("until_year", 0):
                parts += rule.get("parts", [])
        parts = list(dict.fromkeys(parts))
        if st in ("wood", "light_steel"):  # 木造・軽量鉄骨の住宅では出てこない部位を除く
            ng = ("鉄骨", "RC", "EV", "機械室", "耐火被覆", "柱・")
            parts = [x for x in parts if not any(k in x for k in ng)]
        if len(parts) > 8:
            parts = parts[:8] + [f"ほか{len(parts) - 8}部位"]
        if parts:
            wall_area = q["perimeter_m"] * q["eave_h"]
            if asb.get("level3"):
                asb_extra.append(_line("アスベスト（含有時のみ）", "レベル3建材（外壁仕上塗材・スレート等）除去 ※含有判明時",
                                       round(wall_area, 1), "㎡", asb["level3"],
                                       basis=f"外壁面積 推定 外周{q['perimeter_m']:.1f}m×軒高{q['eave_h']:.1f}m"))
            q["asbestos_suspect_parts"] = parts

    return {"quantities": q, "leftover": lo, "lines": lines, "subtotal": sub, "overhead": over,
            "overhead_rate": ov_rate, "total": tot, "region": region, "region_factor": rf,
            "condition_factor": factor, "conditions_applied": applied, "asbestos_extra": asb_extra,
            "per_tsubo_mid": tot["mid"] / q["floor_area_tsubo"] if q["floor_area_tsubo"] else None,
            "sources": prices.get("sources", [])}
