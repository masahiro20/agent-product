"""造成計画の計算（現況地盤面・計画高・土量・擁壁・法規チェック・概算）。

座標系: 敷地ローカル（m）。原点は spec.site.origin（任意の点、通常は敷地の左下角）、
x=東 / y=北 方向を図の右 / 上とする（rotation_deg で図の回転を指定可能）。
高さはすべて T.P.（東京湾平均海面）基準 m。図では KBM（道路中心）からの相対値も併記する。

site 定義（site.json の site）:
{
  "boundary": [[0,0],[15,0],[15,20],[0,20]],        # 敷地境界（反時計回り推奨）
  "road": {"edge": [[0,0],[15,0]], "width_m": 4.0, "name": "市道", "side": "S"},
  "existing": {
     "source": "dem|points|dem+points",
     "dem": {"xs":[..], "ys":[..], "z":[[..]]},       # terrain.py が作る（ローカル座標）
     "points": [{"x":..,"y":..,"z":.., "label":"ブロック天端", "basis":"写真3 CB6段"}]
  },
  "neighbors": [{"edge":[[15,0],[15,20]], "level_offset_m": 0.0}],  # 任意: 隣地地盤（現況地盤との差）
  "plan": {
     "fh_mode": "road_plus|balance|fixed", "road_plus_m": 0.3, "fh_m": null,
     "terraces": [],                                  # 任意: 段々造成 [{"polygon":[...],"fh_m":..}]
     "slab_slope_pct": 1.0
  },
  "soil": "default|sandy|clay|gravel"
}
"""
import math

from .common import load_data

CELL = 0.5  # 土量メッシュ (m)


# ---------- 幾何 ----------

def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xi:
                inside = not inside
    return inside


def poly_area(poly):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def seg_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def same_seg(s, a, b, tol=0.05):
    (p, q) = s
    return (seg_len(p, a) < tol and seg_len(q, b) < tol) or (seg_len(p, b) < tol and seg_len(q, a) < tol)


# ---------- 現況地盤面 ----------

class Surface:
    """DEM（格子）＋ 実測/写真推定の点 を合成した現況地盤面。

    点がある場合は DEM との差（残差）を IDW で面的に補正する。
    """

    def __init__(self, existing):
        self.dem = existing.get("dem")
        self.points = existing.get("points", [])
        self._resid = []
        if self.dem:
            for p in self.points:
                d = self._dem_at(p["x"], p["y"])
                if d is not None:
                    self._resid.append((p["x"], p["y"], p["z"] - d))

    def _dem_at(self, x, y):
        d = self.dem
        xs, ys, z = d["xs"], d["ys"], d["z"]
        if not (xs[0] <= x <= xs[-1] and ys[0] <= y <= ys[-1]):
            x = min(max(x, xs[0]), xs[-1])
            y = min(max(y, ys[0]), ys[-1])
        i = _bisect(xs, x)
        j = _bisect(ys, y)
        x0, x1 = xs[i], xs[i + 1]
        y0, y1 = ys[j], ys[j + 1]
        tx = (x - x0) / (x1 - x0) if x1 != x0 else 0
        ty = (y - y0) / (y1 - y0) if y1 != y0 else 0
        v00, v10, v01, v11 = z[j][i], z[j][i + 1], z[j + 1][i], z[j + 1][i + 1]
        vals = [v for v in (v00, v10, v01, v11) if v is not None]
        if not vals:
            return None
        v00 = v00 if v00 is not None else sum(vals) / len(vals)
        v10 = v10 if v10 is not None else sum(vals) / len(vals)
        v01 = v01 if v01 is not None else sum(vals) / len(vals)
        v11 = v11 if v11 is not None else sum(vals) / len(vals)
        return (v00 * (1 - tx) * (1 - ty) + v10 * tx * (1 - ty) + v01 * (1 - tx) * ty + v11 * tx * ty)

    def _idw(self, x, y, pts, power=2.0):
        num = den = 0.0
        for px, py, pz in pts:
            d = math.hypot(x - px, y - py)
            if d < 1e-6:
                return pz
            w = 1.0 / d ** power
            num += w * pz
            den += w
        return num / den if den else 0.0

    def z(self, x, y):
        if self.dem:
            base = self._dem_at(x, y)
            if base is None:
                base = 0.0
            if self._resid:
                base += self._idw(x, y, self._resid)
            return base
        if self.points:
            return self._idw(x, y, [(p["x"], p["y"], p["z"]) for p in self.points])
        raise ValueError("現況地盤のデータ（DEM または 点）がありません")


def _bisect(arr, v):
    lo, hi = 0, len(arr) - 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if arr[mid] <= v:
            lo = mid
        else:
            hi = mid - 1
    return max(0, min(lo, len(arr) - 2))


# ---------- 計画 ----------

def sample_edge(surf, a, b, step=0.5):
    n = max(2, int(seg_len(a, b) / step) + 1)
    return [surf.z(a[0] + (b[0] - a[0]) * i / (n - 1), a[1] + (b[1] - a[1]) * i / (n - 1)) for i in range(n)]


def mesh(poly, cell=CELL):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cells = []
    y = min(ys) + cell / 2
    while y < max(ys):
        x = min(xs) + cell / 2
        while x < max(xs):
            if point_in_poly(x, y, poly):
                cells.append((x, y))
            x += cell
        y += cell
    return cells


def road_level(site, surf):
    road = site.get("road")
    if not road:
        return None
    a, b = road["edge"]
    # 道路境界から道路側に 半幅 寄った線＝道路中心
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    nx, ny = dy / L, -dx / L  # 右手法線
    cx, cy = sum(p[0] for p in site["boundary"]) / len(site["boundary"]), sum(p[1] for p in site["boundary"]) / len(site["boundary"])
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if (cx - mx) * nx + (cy - my) * ny > 0:  # 法線が敷地側を向いていたら反転
        nx, ny = -nx, -ny
    hw = road.get("width_m", 4.0) / 2
    ca = (a[0] + nx * hw, a[1] + ny * hw)
    cb = (b[0] + nx * hw, b[1] + ny * hw)
    edge_z = sample_edge(surf, a, b)
    center_z = sample_edge(surf, ca, cb)
    return {"edge_min": min(edge_z), "edge_max": max(edge_z), "edge_avg": sum(edge_z) / len(edge_z),
            "center_avg": sum(center_z) / len(center_z), "center_line": [ca, cb],
            "slope_pct": (edge_z[-1] - edge_z[0]) / seg_len(a, b) * 100, "normal": (nx, ny)}


def decide_fh(site, surf, cells, rl, fh_override=None):
    if fh_override is not None:
        return fh_override
    plan = site.get("plan", {})
    mode = plan.get("fh_mode", "optimize")
    zs = [surf.z(x, y) for x, y in cells]
    if mode == "fixed" and plan.get("fh_m") is not None:
        return plan["fh_m"], "指定値"
    if mode == "balance" or rl is None:
        # 切盛バランス（締固め後）: 切土×C ≒ 盛土 となる高さ
        soil = load_soil(site)
        lo, hi = min(zs) - 1, max(zs) + 1
        for _ in range(60):
            mid = (lo + hi) / 2
            cut = sum(max(0, z - mid) for z in zs)
            fill = sum(max(0, mid - z) for z in zs)
            if cut * soil["C"] > fill:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2, 2), "切盛バランス"
    if mode == "optimize":  # 初期値（optimize_fh が上書きする）
        mean = sum(zs) / len(zs)
        return round(max(rl["edge_max"] + 0.15, mean), 2), "初期値"
    plus = plan.get("road_plus_m", 0.3)
    return round(rl["edge_max"] + plus, 2), f"道路境界の最高点 +{plus:.2f}m"


def load_soil(site):
    gp = load_data("grading_unit_prices.json") or {}
    table = gp.get("soil_change_rate", {})
    s = table.get(site.get("soil", "default")) or table.get("default") or {"L": 1.2, "C": 0.9}
    return {"L": s.get("L", 1.2), "C": s.get("C", 0.9)}


def wall_type(h, gp):
    """擁壁・土留めの種類を高さから選ぶ。"""
    rules = (gp or {}).get("wall_selection") or [
        {"max_h": 0.3, "type": "none", "name": "不要（縁石・見切り程度）"},
        {"max_h": 0.6, "type": "cb", "name": "CB土留め（化粧ブロック2〜3段）"},
        {"max_h": 5.0, "type": "l_rc", "name": "L型RC擁壁"},
        {"max_h": 99, "type": "special", "name": "個別設計擁壁（高さ5m超）"},
    ]
    for r in rules:
        if h <= r["max_h"]:
            return r
    return rules[-1]


def plan_site(spec, fh_override=None):
    site = spec["site"]
    gp = load_data("grading_unit_prices.json") or {}
    surf = Surface(site["existing"])
    poly = [tuple(p) for p in site["boundary"]]
    area = poly_area(poly)
    cells = mesh(poly)
    rl = road_level(site, surf)
    fh, fh_basis = decide_fh(site, surf, cells, rl, fh_override)
    slope = site.get("plan", {}).get("slab_slope_pct", 1.0) / 100.0

    # 計画面: 道路側に向けて排水勾配（道路から離れるほど高く）
    def plan_z(x, y):
        if rl is None:
            return fh
        a, _ = site["road"]["edge"]
        nx, ny = rl["normal"]
        dist = abs((x - a[0]) * nx + (y - a[1]) * ny)
        return fh + dist * slope

    soil = load_soil(site)
    cut = fill = 0.0
    cell_data = []
    ca = CELL * CELL
    for x, y in cells:
        eg = surf.z(x, y)
        pz = plan_z(x, y)
        d = pz - eg
        if d > 0:
            fill += d * ca
        else:
            cut += -d * ca
        cell_data.append((x, y, eg, pz))

    # 境界ごとの段差と擁壁
    walls = []
    road_edge = site.get("road", {}).get("edge")
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        L = seg_len(a, b)
        is_road = road_edge is not None and same_seg((tuple(road_edge[0]), tuple(road_edge[1])), a, b)
        # 境界の外側 0.5m の地盤（隣地・道路）
        dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        nx, ny = dy, -dx
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if (cx - mx) * nx + (cy - my) * ny > 0:
            nx, ny = -nx, -ny
        n = max(2, int(L / 0.5) + 1)
        diffs = []
        for k in range(n):
            t = k / (n - 1)
            px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            outside = surf.z(px + nx * 0.5, py + ny * 0.5)
            for nb in site.get("neighbors", []):
                if same_seg((tuple(nb["edge"][0]), tuple(nb["edge"][1])), a, b):
                    outside += nb.get("level_offset_m", 0.0)
            inside = plan_z(px - nx * 0.05, py - ny * 0.05)
            diffs.append(inside - outside)
        hmax = max(abs(d) for d in diffs)
        havg = sum(abs(d) for d in diffs) / len(diffs)
        kind = "盛土側（敷地が高い）" if sum(diffs) > 0 else "切土側（敷地が低い）"
        wt = wall_type(hmax, gp)
        if is_road and max(diffs) <= 0.6 and min(diffs) >= -0.05:
            wt = {"type": "none", "name": "不要（道路と擦り付け・土間）"}
        walls.append({"index": i, "a": a, "b": b, "length_m": round(L, 2), "is_road": is_road,
                      "h_max": round(hmax, 2), "h_avg": round(havg, 2), "side": kind,
                      "type": wt["type"], "type_name": wt["name"], "diffs": [round(d, 2) for d in diffs]})

    # 法規チェック（区域指定の有無は別途確認）
    flags = []
    reg = gp.get("regulation", {})
    max_fill = max((pz - eg) for _, _, eg, pz in cell_data) if cell_data else 0
    max_cut = max((eg - pz) for _, _, eg, pz in cell_data) if cell_data else 0
    cliff_fill = max([w["h_max"] for w in walls if "盛土" in w["side"] and w["type"] != "none"] or [0])
    cliff_cut = max([w["h_max"] for w in walls if "切土" in w["side"] and w["type"] != "none"] or [0])
    if cliff_fill > 1.0:
        flags.append(f"盛土で高さ{cliff_fill:.1f}m（>1m）の崖・擁壁が生じる → 盛土規制法の許可対象の可能性")
    if cliff_cut > 2.0:
        flags.append(f"切土で高さ{cliff_cut:.1f}m（>2m）の崖・擁壁が生じる → 盛土規制法の許可対象の可能性")
    if max_fill > 2.0:
        flags.append(f"崖を生じない盛土でも高さ{max_fill:.1f}m（>2m） → 許可対象の可能性")
    if area > 500 and (fill > 0 or cut > 0):
        flags.append(f"造成面積 {area:.0f}㎡（>500㎡） → 盛土規制法の許可対象の可能性")
    if max(cliff_fill, cliff_cut) > 2.0:
        flags.append("高さ2m超の崖・擁壁 → がけ条例（自治体）の対象。擁壁は確認申請（工作物）が必要")
    dev = reg.get("development_permit_area_m2", {})
    if area >= 500:
        flags.append("敷地 500㎡以上：区画形質の変更があれば開発許可の要否を確認（市街化区域1,000㎡／三大都市圏の一部500㎡〜）")
    permit_possible = bool(flags)
    if not flags:
        flags.append("規模からは盛土規制法・開発許可の対象になりにくい（区域指定と自治体基準は要確認）")

    eg_vals = [c[2] for c in cell_data]
    result = {
        "area_m2": round(area, 2),
        "fh_m": fh, "fh_basis": fh_basis, "slope_pct": slope * 100,
        "existing_min": round(min(eg_vals), 2), "existing_max": round(max(eg_vals), 2),
        "existing_diff": round(max(eg_vals) - min(eg_vals), 2),
        "road": rl and {k: (round(v, 2) if isinstance(v, float) else v) for k, v in rl.items() if k != "normal"},
        "cut_m3": round(cut, 1), "fill_m3": round(fill, 1),
        "soil": soil, "walls": walls, "flags": flags, "permit_possible": permit_possible,
        "max_fill_m": round(max_fill, 2), "max_cut_m": round(max_cut, 2),
        "cells": cell_data, "cell": CELL,
    }
    # 土量バランス
    usable = cut * soil["C"]  # 切土を締め固めると何㎥の盛土になるか
    if usable >= fill:
        surplus_bank = (usable - fill) / soil["C"]
        result["balance"] = {"reuse_m3": round(fill, 1), "purchase_m3": 0.0,
                             "disposal_bank_m3": round(surplus_bank, 1),
                             "disposal_loose_m3": round(surplus_bank * soil["L"], 1)}
    else:
        result["balance"] = {"reuse_m3": round(usable, 1), "purchase_m3": round((fill - usable) / soil["C"], 1),
                             "disposal_bank_m3": 0.0, "disposal_loose_m3": 0.0}
    result["surface"] = surf
    result["plan_z"] = plan_z
    return result


# ---------- 概算 ----------

def _it(gp, key):
    return gp.get("items", {}).get(key)


def _wall_price(gp, h):
    table = gp.get("retaining_wall_l_type_per_m") or []
    if not table:
        return None
    table = sorted(table, key=lambda r: r["height_m"])
    if h <= table[0]["height_m"]:
        r = table[0]
        return {k: r[k] for k in ("low", "mid", "high")}
    for r0, r1 in zip(table, table[1:]):
        if r0["height_m"] <= h <= r1["height_m"]:
            t = (h - r0["height_m"]) / (r1["height_m"] - r0["height_m"])
            return {k: r0[k] + (r1[k] - r0[k]) * t for k in ("low", "mid", "high")}
    r = table[-1]
    k = h / r["height_m"]
    return {kk: r[kk] * k * k for kk in ("low", "mid", "high")}


def estimate(spec, res):
    gp = load_data("grading_unit_prices.json")
    if not gp:
        raise RuntimeError("data/grading_unit_prices.json がありません")
    lines = []

    def add(cat, name, qty, unit, price, basis="", src=None):
        if price is None or qty <= 0:
            if qty > 0:
                lines.append({"cat": cat, "name": name, "qty": qty, "unit": unit, "price": None,
                              "low": None, "mid": None, "high": None, "basis": basis, "src": [], "note": "単価未登録"})
            return
        lo = price.get("low") if price.get("low") is not None else price.get("mid")
        hi = price.get("high") if price.get("high") is not None else price.get("mid")
        mi = price.get("mid")
        lines.append({"cat": cat, "name": name, "qty": round(qty, 1), "unit": unit,
                      "price": {"low": lo, "mid": mi, "high": hi},
                      "low": qty * lo, "mid": qty * mi, "high": qty * hi, "basis": basis,
                      "src": src if src is not None else price.get("src", []), "note": price.get("note", "")})

    area = res["area_m2"]
    bal = res["balance"]
    opts = spec.get("site", {}).get("plan", {})
    # 解体と同時に見積る場合、樹木の伐採・抜根と整地は解体側に計上済み
    if opts.get("clearing", not spec.get("building")):
        add("準備工", "伐採・除根・表土処理", area, "㎡", _it(gp, "clearing_m2"), "敷地全体")
    add("土工", "切土（掘削）", res["cut_m3"], "㎥", _it(gp, "cut_m3"), "メッシュ法 0.5m格子（地山）")
    add("土工", "盛土（流用土・敷均し）", bal["reuse_m3"], "㎥", _it(gp, "fill_reuse_m3"), "切土の流用（締固め後）")
    add("土工", "盛土（購入土）", bal["purchase_m3"], "㎥", _it(gp, "fill_purchased_m3"), "不足分（地山換算）")
    add("土工", "残土処分（運搬含む）", bal["disposal_loose_m3"], "㎥", _it(gp, "soil_disposal_m3"),
        f"余剰 地山{bal['disposal_bank_m3']}㎥×L={res['soil']['L']}（ほぐし）")
    add("土工", "整地・転圧", area, "㎡", _it(gp, "compaction_m2"), "敷地全体")
    for w in res["walls"]:
        if w["type"] == "none":
            continue
        name = f"{w['type_name']} H≈{w['h_max']:.2f}m（境界{w['index'] + 1}）"
        if w["type"] == "cb":
            add("擁壁・土留め", name, w["length_m"], "m", _it(gp, "cb_retaining_m"), f"L={w['length_m']}m")
        elif w["type"] in ("l_rc", "special"):
            p = _wall_price(gp, w["h_max"])
            add("擁壁・土留め", name, w["length_m"], "m", p and {**p, "src": [s for r in gp.get("retaining_wall_l_type_per_m", []) for s in r.get("src", [])][:3]},
                f"L={w['length_m']}m、高さは境界上の最大値で計上（安全側）")
    ex = spec.get("site", {}).get("existing_walls", [])
    for e in ex:
        if e.get("remove"):
            add("擁壁・土留め", f"既存擁壁撤去（{e.get('label', '')}）", e.get("area_m2", 0), "㎡", _it(gp, "existing_wall_removal_m2"),
                e.get("basis", "写真"))
    # 排水
    perim_drain = opts.get("u_ditch_m")
    if perim_drain is None:
        perim_drain = sum(w["length_m"] for w in res["walls"] if w["is_road"])
    add("排水", "U字溝（道路境界沿い）", perim_drain, "m", _it(gp, "u_ditch_m"), "道路境界の延長")
    add("排水", "雨水桝・浸透桝", opts.get("basins", 2), "箇所", _it(gp, "catch_basin"), "最低2箇所想定")
    # 調査・設計
    add("調査・設計", "現況測量", 1, "式", _it(gp, "survey_current"), "造成計画の前提として必須")
    if res.get("permit_possible"):
        add("調査・設計", "造成設計・許可申請", 1, "式", _it(gp, "design_and_permit"), "許可対象の可能性あり")
    add("調査・設計", "地盤調査（SWS）", opts.get("sws_points", 1), "件", _it(gp, "soil_test_sws"), "建築前")

    rft = gp.get("region_factor", {})
    region = spec.get("region", "default")
    region = rft.get("alias", {}).get(region, region)  # 解体側の地域キーも受け付ける
    rf = rft.get(region, rft.get("default", 1.0))
    if isinstance(rf, dict):
        rf = rf.get("mid", 1.0)
    sub = {}
    for k in ("low", "mid", "high"):
        sub[k] = sum((ln[k] or 0) * (1.0 if ln["cat"] == "調査・設計" else rf) for ln in lines)
    ov = gp.get("items", {}).get("overhead_rate", {})
    rate = {k: (ov.get(k) if ov.get(k) is not None else ov.get("mid", 0)) / 100.0 for k in ("low", "mid", "high")}
    over = {k: sub[k] * rate[k] for k in sub}
    tot = {k: sub[k] + over[k] for k in sub}
    return {"lines": lines, "subtotal": sub, "overhead": over, "overhead_rate": rate, "total": tot,
            "region_factor": rf, "sources": gp.get("sources", [])}


def plan_and_estimate(spec):
    """計画高を決めて土量・擁壁・概算を出す。fh_mode=optimize なら概算（標準）が最小の計画高を探す。

    探索範囲: 道路境界の最高点+0.1m（雨水を道路側に流す最低限）〜 現況の最高点+0.3m、0.05m刻み。
    """
    mode = spec["site"].get("plan", {}).get("fh_mode", "optimize")
    res = plan_site(spec)
    if mode != "optimize" or not res.get("road"):
        return res, estimate(spec, res)
    lo = res["road"]["edge_max"] + 0.1
    hi = max(res["existing_max"] + 0.3, lo + 0.1)
    best = None
    tried = []
    k = 0
    while lo + k * 0.05 <= hi + 1e-9:
        fh = round(lo + k * 0.05, 2)
        r = plan_site(spec, (fh, ""))
        e = estimate(spec, r)
        tried.append((fh, e["total"]["mid"]))
        if best is None or e["total"]["mid"] < best[2]["total"]["mid"]:
            best = (fh, r, e)
        k += 1
    fh, r, e = best
    r["fh_basis"] = f"道路より高く保つ条件で概算最小（道路境界最高点+{fh - res['road']['edge_max']:.2f}m）"
    r["fh_search"] = tried
    r["alternatives"] = alternatives(spec, r, e)
    return r, e


def _summ(label, r, e):
    return {"label": label, "fh_m": r["fh_m"], "cut_m3": r["cut_m3"], "fill_m3": r["fill_m3"],
            "wall_m": round(sum(w["length_m"] for w in r["walls"] if w["type"] != "none"), 1),
            "wall_hmax": max([w["h_max"] for w in r["walls"] if w["type"] != "none"] or [0]),
            "permit": r.get("permit_possible", False), "total_mid": e["total"]["mid"],
            "below_road": bool(r.get("road")) and r["fh_m"] < r["road"]["edge_max"]}


def alternatives(spec, chosen, chosen_est):
    """計画高の代替案（切盛バランス・現況平均）と比較する。"""
    out = [_summ("採用案：" + chosen["fh_basis"], chosen, chosen_est)]
    soil = chosen["soil"]
    zs = [c[2] for c in chosen["cells"]]
    lo, hi = min(zs) - 1, max(zs) + 1
    for _ in range(50):
        mid = (lo + hi) / 2
        cut = sum(max(0, z - mid) for z in zs)
        fill = sum(max(0, mid - z) for z in zs)
        lo, hi = (mid, hi) if cut * soil["C"] > fill else (lo, mid)
    cands = [("切盛バランス（残土・購入土を最小）", round((lo + hi) / 2, 2)),
             ("現況平均の高さ", round(sum(zs) / len(zs), 2))]
    for label, fh in cands:
        if abs(fh - chosen["fh_m"]) < 0.05:
            continue
        r = plan_site(spec, (fh, label))
        out.append(_summ(label, r, estimate(spec, r)))
    return out
