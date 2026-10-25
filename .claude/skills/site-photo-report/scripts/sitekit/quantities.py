"""建物の詳細数量（階別床面積・外壁・屋根・開口・基礎・廃材）と、読み取り値どうしの食い違いチェック。

すべて写真からの推定値。係数は data/demolition_unit_prices.json の quantity_rates（出典付き）を使う。
"""
import math

ROOF_KINDS = {
    "kawara_dobuki": "瓦（土葺き）", "kawara": "瓦（引掛け桟瓦）", "slate": "化粧スレート", "metal": "金属板",
    "shingle": "アスファルトシングル", "flat": "陸屋根（防水）", "unknown": "不明",
}
FOUNDATION_KINDS = {"nuno": "布基礎", "beta": "ベタ基礎", "dokuritsu": "独立基礎", "unknown": "不明"}


def _r(v, n=1):
    return round(v, n) if v is not None else None


def floor_plans(b):
    """階別の床（外形）。floor_plans が無ければ 1F の外形を各階に当てる（総2階とみなす）。"""
    fp = b.get("footprint", {})
    w1, d1 = fp.get("width_m", 0), fp.get("depth_m", 0)
    floors = max(1, int(b.get("floors", 1)))
    given = {int(p.get("floor", 0)): p for p in b.get("floor_plans") or [] if p.get("floor")}
    out = []
    for i in range(1, floors + 1):
        p = given.get(i) or {}
        w = p.get("w") or (w1 if i == 1 or not given else None)
        d = p.get("d") or (d1 if i == 1 or not given else None)
        area = p.get("area_m2") or ((w or 0) * (d or 0)) or None
        if area is None:  # 階の外形が分からない階は 1F と同じとみなす
            w, d, area = w1, d1, w1 * d1
        if not w or not d:  # 面積だけ分かる階は 1F と同じ縦横比で外周を出す
            k = math.sqrt(area / (w1 * d1)) if w1 * d1 else 1.0
            w, d = w1 * k, d1 * k
        out.append({"floor": i, "w": w, "d": d, "area_m2": area, "perimeter_m": 2 * (w + d),
                    "basis": p.get("basis") or ("外形寸法から" if i == 1 else "1F と同じ外形（総2階）とみなす" if not given else "")})
    return out


def _story_heights(b, n):
    """各階の外壁の高さ（その階の床〜上階の床、最上階は軒まで）。1F は GL から。"""
    fl = list(b.get("floor_levels") or [])
    eave = b.get("eave_h", 3.0 * n)
    if len(fl) < n:
        fl = [0.45 + 2.9 * i for i in range(n)]
    hs = []
    for i in range(n):
        lo = 0.0 if i == 0 else fl[i]
        hi = fl[i + 1] if i + 1 < n else eave
        hs.append(max(0.5, hi - lo))
    return hs


def detail(b, rates):
    """建物の詳細数量。戻り値は dict（PDF・Excel・見積依頼書の参考数量に使う）。"""
    rates = rates or {}
    plans = floor_plans(b)
    n = len(plans)
    hs = _story_heights(b, n)
    faces = b.get("elevations") or []
    eave = b.get("eave_h", 3.0 * n)
    roof = b.get("roof") or {}
    ridge = max(eave, (faces[0].get("roof", {}).get("ridge_h") if faces else None) or roof.get("ridge_h") or eave)
    overhang = roof.get("overhang") or (faces[0].get("roof", {}).get("overhang") if faces else None) or 0.45
    pitch = roof.get("pitch_sun")
    kind = roof.get("kind") or "unknown"
    q = {"floors": [], "assumptions": []}

    # 階別床面積
    for p, h in zip(plans, hs):
        q["floors"].append({"floor": p["floor"], "area_m2": _r(p["area_m2"], 2), "w": _r(p["w"], 2), "d": _r(p["d"], 2),
                            "perimeter_m": _r(p["perimeter_m"], 2), "wall_h": _r(h, 2), "basis": p["basis"]})
    q["floor_area_m2"] = sum(p["area_m2"] for p in plans)

    # 外壁（階ごとの外周×階高＋妻壁の三角）−開口
    gross = sum(p["perimeter_m"] * h for p, h in zip(plans, hs))
    gable = 0.0
    if ridge > eave:
        for f in faces:
            t = (f.get("roof") or {}).get("type")
            if t in ("gable_end", "shed"):
                gable += f.get("width_m", 0) * (ridge - eave) / 2
    openings = {"window_n": 0, "window_m2": 0.0, "door_n": 0, "door_m2": 0.0}
    for f in faces:
        for e in f.get("elements", []):
            if e.get("type") in ("window", "door"):
                a = abs(e.get("w", 0) * e.get("h", 0))
                openings[e["type"] + "_n"] += 1
                openings[e["type"] + "_m2"] += a
    open_m2 = openings["window_m2"] + openings["door_m2"]
    q["wall"] = {"gross_m2": _r(gross + gable), "gable_m2": _r(gable), "openings_m2": _r(open_m2),
                 "net_m2": _r(max(0.0, gross + gable - open_m2)),
                 "basis": "階ごとの外周×階高（1Fは地盤から、最上階は軒まで）＋妻壁の三角 − 窓・ドア"}
    q["openings"] = {k: _r(v, 2) if isinstance(v, float) else v for k, v in openings.items()}
    if not faces:
        q["assumptions"].append("立面の読み取りが無いため、開口部を差し引いていません")

    # 屋根（水平投影×勾配の伸び率）。最上階の屋根＋下屋（下の階がはみ出す部分）
    top = plans[-1]
    proj_top = (top["w"] + 2 * overhang) * (top["d"] + 2 * overhang)
    lower = 0.0
    for lo_p, up_p in zip(plans, plans[1:]):
        lower += max(0.0, lo_p["area_m2"] - up_p["area_m2"])
    proj_lower = lower * 1.15 if lower > 0.5 else 0.0  # 下屋の軒の出を約15%見込む
    if kind == "flat":
        slope = 1.0
    else:
        if not pitch:
            # 軒高・最高高さと奥行から勾配を逆算（切妻・寄棟の平側を想定）。それも無ければ 4寸
            span = min(top["w"], top["d"]) / 2
            pitch = round(min(10.0, max(1.0, (ridge - eave) / span * 10)), 1) if ridge > eave and span else 4.0
            q["assumptions"].append(f"屋根勾配は高さと奥行から逆算（約{pitch:g}寸）")
        slope = math.sqrt(1 + (pitch / 10) ** 2)
    q["roof"] = {"kind": kind, "kind_label": ROOF_KINDS.get(kind, kind), "pitch_sun": pitch if kind != "flat" else 0,
                 "slope_factor": round(slope, 3), "overhang_m": overhang,
                 "projected_m2": _r(proj_top + proj_lower), "lower_projected_m2": _r(proj_lower),
                 "area_m2": _r((proj_top + proj_lower) * slope),
                 "basis": f"水平投影（軒の出{overhang:g}m込み）×勾配の伸び率{slope:.3f}" + ("＋下屋" if proj_lower else "")}

    # 基礎（外周＋内部）と コンクリート量
    fr = rates.get("foundation", {})
    ftype = b.get("foundation_type") or "unknown"
    outer = plans[0]["perimeter_m"]
    inner = outer * fr.get("inner_ratio", 0.8)
    if ftype == "beta":
        vol = plans[0]["area_m2"] * fr.get("beta_slab_t", 0.15) + (outer + inner) * fr.get("beta_wall_m3_per_m", 0.09)
    else:
        vol = (outer + inner) * fr.get("nuno_m3_per_m", 0.18)
    dens = fr.get("concrete_t_per_m3", 2.3)
    q["foundation"] = {"type": ftype, "type_label": FOUNDATION_KINDS.get(ftype, ftype), "outer_m": _r(outer),
                       "inner_m": _r(inner), "concrete_m3": _r(vol), "concrete_t": _r(vol * dens),
                       "basis": ("ベタ基礎: 底盤" if ftype == "beta" else "布基礎: ") + "断面は建告1347号の最小寸法程度の標準断面。内部の基礎は外周の"
                                + f"{fr.get('inner_ratio', 0.8):.0%}とみなす"}
    if ftype == "unknown":
        q["assumptions"].append("基礎の種類が不明のため布基礎として計算")
    if (b.get("built_year_est") or 2000) < 1971:
        q["assumptions"].append("1971年以前の建物は無筋・玉石基礎のことがあり、ガラ量は少なめに出ることがあります")

    # 廃材の発生量（木造は品目別、その他は総量）
    wr = (rates.get("waste") or {}).get(b.get("structure", "wood"))
    nobe = q["floor_area_m2"]
    waste = []
    if b.get("structure", "wood") == "wood" and wr:
        waste.append({"name": "木くず（柱・梁・下地）", "t": nobe * wr["wood_t_m2"], "basis": f"延床×{wr['wood_t_m2']} t/㎡"})
        waste.append({"name": "コンクリートガラ（基礎）", "t": vol * dens, "basis": "基礎の体積×2.3 t/㎥"})
        waste.append({"name": "石膏ボード", "t": nobe * wr["gypsum_t_m2"], "basis": f"延床×{wr['gypsum_t_m2']} t/㎡"})
        waste.append({"name": "金属くず", "t": nobe * wr["metal_t_m2"], "basis": f"延床×{wr['metal_t_m2']} t/㎡"})
        waste.append({"name": "混合廃棄物（内装材・断熱材等）", "t": nobe * wr["mixed_t_m2"], "basis": f"延床×{wr['mixed_t_m2']} t/㎡（幅が大きい）"})
        rw = (rates.get("roof_weight_t_m2") or {}).get(kind)
        if rw:
            waste.append({"name": f"屋根材（{ROOF_KINDS.get(kind, kind)}）", "t": q["roof"]["area_m2"] * rw,
                          "basis": f"屋根面積×{rw} t/㎡"})
        gw = rates.get("glass_t_m2", 0.0125)
        if openings["window_m2"]:
            waste.append({"name": "ガラス", "t": openings["window_m2"] * gw, "basis": f"窓面積×{gw} t/㎡"})
    elif wr:
        waste.append({"name": "廃材 合計（構造体込み）", "t": nobe * wr["total_t_m2"], "basis": f"延床×{wr['total_t_m2']} t/㎡"})
        if b.get("structure") != "rc":
            waste.append({"name": "うちコンクリートガラ（基礎）", "t": vol * dens, "basis": "基礎の体積×2.3 t/㎥"})
    for w in waste:
        w["t"] = _r(w["t"], 2)
    q["waste"] = waste
    q["waste_total_t"] = _r(sum(w["t"] for w in waste if not w["name"].startswith("うち")), 1)
    q["waste_src"] = rates.get("src", [])
    return q


def checks(b, q):
    """読み取り値どうしの食い違い・ありえない値を拾う。[{level: warn|info, msg}]"""
    out = []
    fp = b.get("footprint", {})
    w, d = fp.get("width_m", 0), fp.get("depth_m", 0)
    floors = max(1, int(b.get("floors", 1)))
    eave = b.get("eave_h", 0)
    faces = b.get("elevations") or []
    for i, f in enumerate(faces[:4]):
        ref = w if i % 2 == 0 else d
        fw = f.get("width_m", 0)
        if ref and fw and abs(fw - ref) / ref > 0.15:
            out.append({"level": "warn", "msg": f"{f.get('name', f'{i + 1}面目')}の幅 {fw:.1f}m が建物の{'間口' if i % 2 == 0 else '奥行'} "
                                                f"{ref:.1f}m と {abs(fw - ref):.1f}m 違います（外廊下・下屋を含むなら問題なし）"})
    rng = {1: (2.4, 4.5), 2: (5.0, 7.2), 3: (7.8, 10.5)}.get(floors)
    if rng and eave and not rng[0] <= eave <= rng[1]:
        out.append({"level": "warn", "msg": f"軒高 {eave:.1f}m は{floors}階建てとしては{'低め' if eave < rng[0] else '高め'}です（目安 {rng[0]}〜{rng[1]}m）"})
    fl = q.get("floors") or []
    for lo_p, up_p in zip(fl, fl[1:]):
        if up_p["area_m2"] > lo_p["area_m2"] * 1.1:
            out.append({"level": "warn", "msg": f"{up_p['floor']}階の床面積が{lo_p['floor']}階より大きくなっています（オーバーハング以外は要確認）"})
    units = b.get("units") or {}
    if units.get("count", 1) > 1 and units.get("area_each_m2"):
        need = units["count"] * units["area_each_m2"]
        nobe = q.get("floor_area_m2", 0)
        if nobe and not 0.85 <= nobe / need <= 1.6:
            out.append({"level": "warn", "msg": f"戸数×専有面積（{need:.0f}㎡）と延床（{nobe:.0f}㎡）が合いません。戸数か外形寸法を確認してください"})
    if w and d and max(w, d) / min(w, d) > 4:
        out.append({"level": "info", "msg": f"建物の縦横比が {max(w, d) / min(w, d):.1f} と細長です。間口と奥行の読み違いがないか確認してください"})
    mo = b.get("map_outline")
    if mo and fl:
        a1 = fl[0]["area_m2"]
        if abs(a1 - mo["area_m2"]) / mo["area_m2"] > 0.15:
            out.append({"level": "warn", "msg": f"1階の床面積 {a1:.0f}㎡ が地図の建物外形 No.{mo['no']}（約{mo['area_m2']:.0f}㎡）と "
                                                f"{(a1 - mo['area_m2']) / mo['area_m2']:+.0%} 違います（下屋・カーポートの扱いを確認）"})
    if not faces:
        out.append({"level": "info", "msg": "立面の読み取りが無いため、窓・ドアの面積を差し引いていません"})
    elif len(faces) < 4:
        out.append({"level": "info", "msg": f"立面が{len(faces)}面しかありません。写っていない面は外周から推定しています"})
    return out


def summary_rows(q):
    """資料用の行 [(項目, 数量, 算出)]。q は demolition.building_quantities の戻り値。"""
    d = q.get("detail") or {}
    rows = [("延床面積", f"{q['floor_area_m2']:.1f}㎡（{q['floor_area_tsubo']:.1f}坪）",
             "／".join(f"{f['floor']}階 {f['area_m2']:.1f}㎡" for f in d.get("floors", [])))]
    if d.get("wall"):
        w, op = d["wall"], d["openings"]
        rows.append(("外壁面積（窓・ドアを除く）", f"{w['net_m2']:.1f}㎡",
                     f"外周×階高 {w['gross_m2'] - w['gable_m2']:.1f}㎡＋妻壁 {w['gable_m2']:.1f}㎡−開口 {w['openings_m2']:.1f}㎡"))
        rows.append(("窓・ドア", f"窓{op['window_n']}か所 {op['window_m2']:.1f}㎡／ドア{op['door_n']}か所", "立面図の合計"))
    if d.get("roof"):
        rf = d["roof"]
        rows.append(("屋根面積", f"{rf['area_m2']:.1f}㎡（{rf['kind_label']}）",
                     f"水平投影 {rf['projected_m2']:.1f}㎡×伸び率{rf['slope_factor']}" + (f"（{rf['pitch_sun']:g}寸）" if rf.get("pitch_sun") else "")))
    if d.get("foundation"):
        fd = d["foundation"]
        rows.append(("基礎", f"約{fd['outer_m'] + fd['inner_m']:.0f}m／コンクリート約{fd['concrete_m3']:.1f}㎥",
                     f"{fd['type_label'] if fd['type'] != 'unknown' else '布基礎とみなす'}。外周{fd['outer_m']:.1f}m＋内部{fd['inner_m']:.1f}m（推定）"))
    if d.get("waste"):
        rows.append(("廃材の発生量（見込み）", f"約{d['waste_total_t']:.1f}t",
                     "、".join(f"{x['name'].split('（')[0]} {x['t']:.1f}t" for x in d["waste"] if not x["name"].startswith("うち"))))
    return rows
