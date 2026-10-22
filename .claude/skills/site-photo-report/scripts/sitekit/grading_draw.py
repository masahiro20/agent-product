"""造成計画図（平面図・断面図）と現況図の描画。"""
import math

from reportlab.lib.colors import Color, black, white

from .drawing import (BLUE, CUT_COLOR, FILL_COLOR, GRAY, LIGHT, RED, View, frame, new_sheet, north_arrow,
                      pick_scale, scale_bar, text_at)
from .grading import point_in_poly, seg_len


def _extent(site, pad=4.0):
    pts = list(site["boundary"])
    if site.get("road"):
        a, b = site["road"]["edge"]
        w = site["road"].get("width_m", 4.0)
        pts += [a, b]
        # 道路の反対側の縁
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = _outward(site, a, b)
        pts += [(a[0] + nx * w, a[1] + ny * w), (b[0] + nx * w, b[1] + ny * w)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def _outward(site, a, b):
    poly = site["boundary"]
    L = seg_len(a, b)
    nx, ny = (b[1] - a[1]) / L, -(b[0] - a[0]) / L
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if (cx - mx) * nx + (cy - my) * ny > 0:
        nx, ny = -nx, -ny
    return nx, ny


def _contours(f, x0, x1, y0, y1, step, interval):
    """マーチングスクエアで等高線の線分を返す [(level, (xa,ya),(xb,yb)), ...]。"""
    nx = int((x1 - x0) / step) + 1
    ny = int((y1 - y0) / step) + 1
    g = [[f(x0 + i * step, y0 + j * step) for i in range(nx)] for j in range(ny)]
    zmin = min(min(r) for r in g)
    zmax = max(max(r) for r in g)
    segs = []
    lv = math.ceil(zmin / interval) * interval
    while lv <= zmax:
        for j in range(ny - 1):
            for i in range(nx - 1):
                corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                vals = [g[cj][ci] for ci, cj in corners]
                pts = []
                for k in range(4):
                    (ia, ja), (ib, jb) = corners[k], corners[(k + 1) % 4]
                    va, vb = vals[k], vals[(k + 1) % 4]
                    if (va - lv) * (vb - lv) < 0:
                        t = (lv - va) / (vb - va)
                        pts.append((x0 + (ia + (ib - ia) * t) * step, y0 + (ja + (jb - ja) * t) * step))
                if len(pts) == 2:
                    segs.append((lv, pts[0], pts[1]))
                elif len(pts) == 4:
                    segs.append((lv, pts[0], pts[1]))
                    segs.append((lv, pts[2], pts[3]))
        lv += interval
    return segs


def _rel(z, kbm):
    return f"{z - kbm:+.2f}"


def section_lines(site, res):
    """A-A: 道路に直交・敷地中央、B-B: 道路に平行・敷地中央。"""
    poly = site["boundary"]
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    if site.get("road"):
        a, b = site["road"]["edge"]
        L = seg_len(a, b)
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    else:
        ux, uy = 1.0, 0.0
    nx, ny = -uy, ux
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    R = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 4
    w = site.get("road", {}).get("width_m", 4.0)
    return {
        "A": ((cx - nx * (R + w), cy - ny * (R + w)), (cx + nx * (R + w), cy + ny * (R + w))),
        "B": ((cx - ux * R, cy - uy * R), (cx + ux * R, cy + uy * R)),
    }


def render_plan(c, spec, res, title="造成計画平面図（参考）", sheet_no="C-01", mode="plan"):
    """mode='plan' 造成計画平面図 / mode='existing' 現況平面図（解体範囲を含む）。"""
    site = spec["site"]
    meta = spec.get("project", {})
    new_sheet(c)
    kbm = res["road"]["center_avg"] if res.get("road") else res["fh_m"]
    notes = [
        f"高さの基準: KBM＝前面道路中心（推定 T.P.{kbm:.2f}m）を ±0.00 とした相対値。現況高は国土地理院 1mDEM＋写真推定の補正値で、±0.2〜0.5m程度の誤差を含む。",
        "敷地境界・寸法は公図／写真からの推定。確定測量・現況測量の成果で置き換えること。",
    ]
    area = frame(c, title, sheet_no, meta, notes=notes)
    ax, ay, aw, ah = area
    legend_w = 105
    x0, x1, y0, y1 = _extent(site)
    scale = pick_scale(x1 - x0, y1 - y0, aw - legend_w - 10, ah - 10)
    ox = ax + 5 + ((aw - legend_w - 10) - (x1 - x0) * 1000 / scale) / 2 - x0 * 1000 / scale
    oy = ay + 5 + ((ah - 10) - (y1 - y0) * 1000 / scale) / 2 - y0 * 1000 / scale
    v = View(c, ox, oy, scale)
    surf = res["surface"]
    pz = res["plan_z"]
    poly = [tuple(p) for p in site["boundary"]]

    # 道路
    if site.get("road"):
        a, b = site["road"]["edge"]
        w = site["road"].get("width_m", 4.0)
        nx, ny = _outward(site, a, b)
        L = seg_len(a, b)
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        ext = 3.0
        rp = [(a[0] - ux * ext, a[1] - uy * ext), (b[0] + ux * ext, b[1] + uy * ext),
              (b[0] + ux * ext + nx * w, b[1] + uy * ext + ny * w), (a[0] - ux * ext + nx * w, a[1] - uy * ext + ny * w)]
        v.polyline(rp, w=0, closed=True, fill=Color(0.93, 0.93, 0.93))
        v.line(*rp[0], *rp[1], w=0.4)
        v.line(*rp[3], *rp[2], w=0.4)
        mx, my = (a[0] + b[0]) / 2 + nx * w / 2, (a[1] + b[1]) / 2 + ny * w / 2
        v.line(a[0] - ux * ext + nx * w / 2, a[1] - uy * ext + ny * w / 2, b[0] + ux * ext + nx * w / 2,
               b[1] + uy * ext + ny * w / 2, w=0.15, color=GRAY, dash=(6, 2, 1, 2))
        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90 or ang < -90:
            ang += 180
        rd = res.get("road") or {}
        v.text(mx, my, f"{site['road'].get('name', '前面道路')}  幅員 約{w:.1f}m（推定）  KBM±0.00  縦断勾配 約{abs(rd.get('slope_pct', 0)):.1f}%",
               2.3, "c", angle=ang, dy_mm=-1.0)

    if mode == "plan":
        # 切盛の色分け
        cell = res["cell"]
        for x, y, eg, p in res["cells"]:
            d = p - eg
            if abs(d) < 0.03:
                continue
            k = min(1.0, abs(d) / 1.5)
            base = FILL_COLOR if d > 0 else CUT_COLOR
            col = Color(1 - (1 - base.red) * (0.35 + 0.65 * k), 1 - (1 - base.green) * (0.35 + 0.65 * k),
                        1 - (1 - base.blue) * (0.35 + 0.65 * k))
            v.rect(x - cell / 2, y - cell / 2, cell, cell, lw=0, fill=col)

    # 現況等高線
    zr = res["existing_diff"]
    interval = 0.25 if zr < 2 else 0.5 if zr < 5 else 1.0
    segs = _contours(surf.z, x0 + 1, x1 - 1, y0 + 1, y1 - 1, 0.5, interval)
    for lv, p, q in segs:
        major = abs((lv / (interval * 4)) - round(lv / (interval * 4))) < 1e-6
        v.line(*p, *q, w=0.3 if major else 0.15, color=Color(0.55, 0.4, 0.25), dash=None if major else (2, 1.5))
    # 等高線ラベル（主曲線のみ・間引き）
    labeled = set()
    for lv, p, q in segs:
        key = round(lv, 2)
        if key in labeled:
            continue
        major = abs((lv / (interval * 4)) - round(lv / (interval * 4))) < 1e-6
        if major or len(labeled) < 4:
            v.text(p[0], p[1], _rel(lv, kbm), 1.6, "l", color=Color(0.55, 0.4, 0.25))
            labeled.add(key)

    # 既存建物（解体）
    for bp in site.get("existing_buildings", []):
        v.polyline([tuple(q) for q in bp["polygon"]], w=0.35, closed=True, dash=(3, 1.5),
                   fill=Color(0.9, 0.9, 0.9) if mode == "existing" else None)
        if mode == "existing":
            v.hatch([tuple(q) for q in bp["polygon"]], spacing_m=0.6)
        cxp = sum(q[0] for q in bp["polygon"]) / len(bp["polygon"])
        cyp = sum(q[1] for q in bp["polygon"]) / len(bp["polygon"])
        v.text(cxp, cyp, bp.get("label", "既存建物（解体）"), 2.2, "c")

    # 外構（現況図のみ）
    if mode == "existing":
        for ex in spec.get("exterior", []):
            g = ex.get("geom")
            if not g:
                continue
            if len(g) == 1:
                v.text(g[0][0], g[0][1], "●" + ex.get("short", ex.get("label", "")), 1.8)
            else:
                v.polyline([tuple(q) for q in g], w=0.9, color=Color(0.35, 0.35, 0.35))
                v.text(g[0][0], g[0][1], ex.get("short", ex.get("label", "")), 1.7, dy_mm=1.0)

    # 敷地境界
    v.polyline(poly, w=0.7, closed=True, color=RED, dash=(8, 2, 1, 2))
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        nx, ny = _outward(site, a, b)
        L = seg_len(a, b)
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if ang > 90 or ang < -90:
            ang += 180
        v.text((a[0] + b[0]) / 2 + nx * 0.9, (a[1] + b[1]) / 2 + ny * 0.9, f"{L:.2f}m", 2.0, "c", angle=ang)
    v.text(sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly) - 1.5,
           f"敷地面積 約{res['area_m2']:.1f}㎡（{res['area_m2'] / 3.30579:.1f}坪）", 2.4, "c", dy_mm=-3)

    if mode == "plan":
        # 擁壁
        for wl in res["walls"]:
            if wl["type"] == "none":
                continue
            a, b = wl["a"], wl["b"]
            nx, ny = _outward(site, a, b)
            off = 0.15
            pa = (a[0] - nx * off, a[1] - ny * off)
            pb = (b[0] - nx * off, b[1] - ny * off)
            v.line(*pa, *pb, w=1.6, color=black)
            L = seg_len(a, b)
            n = int(L / 0.8)
            for k in range(n + 1):
                t = k / max(n, 1)
                px, py = pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t
                v.line(px, py, px - nx * 0.35, py - ny * 0.35, w=0.25)
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            if ang > 90 or ang < -90:
                ang += 180
            v.text((a[0] + b[0]) / 2 - nx * 1.0, (a[1] + b[1]) / 2 - ny * 1.0,
                   f"{wl['type_name']} H={wl['h_max']:.2f}m L={wl['length_m']:.1f}m", 2.0, "c", angle=ang, color=BLUE)
        # 排水: U字溝と桝
        if site.get("road"):
            a, b = site["road"]["edge"]
            nx, ny = _outward(site, a, b)
            off = 0.25
            v.line(a[0] - nx * off, a[1] - ny * off, b[0] - nx * off, b[1] - ny * off, w=0.3, color=BLUE)
            v.line(a[0] - nx * (off + 0.25), a[1] - ny * (off + 0.25), b[0] - nx * (off + 0.25), b[1] - ny * (off + 0.25), w=0.3, color=BLUE)
            for q in (a, b):
                v.rect(q[0] - nx * 0.6 - 0.25 + (0.5 if q is a else -0.5) * (b[0] - a[0]) / seg_len(a, b),
                       q[1] - ny * 0.6 - 0.25 + (0.5 if q is a else -0.5) * (b[1] - a[1]) / seg_len(a, b), 0.5, 0.5, lw=0.4, color=BLUE)
            # 排水方向矢印（敷地中央→道路）
            cx = sum(p[0] for p in poly) / len(poly)
            cy = sum(p[1] for p in poly) / len(poly)
            _arrow(v, (cx - nx * 0.0, cy - ny * 0.0), (cx + nx * 2.5, cy + ny * 2.5))
            v.text(cx - nx * 0.6 + 0.4, cy - ny * 0.6, f"i={res['slope_pct']:.1f}%", 2.0, color=BLUE)
        # スポットレベル（計画／現況）
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        sx = max(2.5, (max(xs) - min(xs)) / 4)
        sy = max(2.5, (max(ys) - min(ys)) / 4)
        y = min(ys) + sy / 2
        while y < max(ys):
            x = min(xs) + sx / 2
            while x < max(xs):
                if point_in_poly(x, y, poly):
                    p = pz(x, y)
                    e = surf.z(x, y)
                    v.text(x, y, "+", 2.0, "c", dy_mm=-0.7)
                    v.text(x, y, f"FH{_rel(p, kbm)}", 2.0, "l", dy_mm=0.6)
                    v.text(x, y, f"({_rel(e, kbm)})", 1.7, "l", dy_mm=-2.2, color=GRAY)
                x += sx
            y += sy
        # 断面位置
        for name, (p, q) in section_lines(site, res).items():
            v.line(*p, *q, w=0.25, color=RED, dash=(10, 2, 2, 2))
            v.text(*p, name, 3.0, "c", color=RED)
            v.text(*q, name, 3.0, "c", color=RED)
    else:
        # 現況のスポット標高
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        for x in (min(xs) + 0.8, (min(xs) + max(xs)) / 2, max(xs) - 0.8):
            for y in (min(ys) + 0.8, (min(ys) + max(ys)) / 2, max(ys) - 0.8):
                if point_in_poly(x, y, poly):
                    v.text(x, y, f"×{_rel(surf.z(x, y), kbm)}", 1.9, "l")
        for p in site["existing"].get("points", []):
            v.text(p["x"], p["y"], f"◎{_rel(p['z'], kbm)} {p.get('label', '')}", 1.8, "l", color=BLUE)

    north_arrow(c, ax + aw - legend_w - 12, ay + ah - 14, spec["site"].get("north_rot_deg", 0))
    scale_bar(c, ax + 4, ay + ah - 6, scale)
    if mode == "plan":
        _legend_plan(c, ax + aw - legend_w, ay + ah - 4, res, kbm)
    else:
        _legend_existing(c, ax + aw - legend_w, ay + ah - 4, res, kbm, spec)
    text_at(c, ax + aw / 2 - legend_w / 2, ay + ah - 4, f"{title}  S=1/{scale}", 3.4, "c")
    c.showPage()


def _arrow(v, p, q):
    v.line(*p, *q, w=0.5, color=BLUE)
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    L = 0.5
    for s in (1, -1):
        v.line(*q, q[0] - L * math.cos(ang + s * 0.4), q[1] - L * math.sin(ang + s * 0.4), w=0.5, color=BLUE)


def _legend_plan(c, x, ytop, res, kbm):
    y = ytop
    text_at(c, x, y - 4, "凡例", 3.0)
    y -= 9
    items = [("fill", "盛土（濃いほど厚い）"), ("cut", "切土（濃いほど深い）"), ("wall", "擁壁・土留め"),
             ("bnd", "敷地境界（推定）"), ("cont", f"現況等高線（{0.25 if res['existing_diff'] < 2 else 0.5}m間隔）"),
             ("drain", "U字溝・雨水桝・排水方向")]
    for k, label in items:
        if k in ("fill", "cut"):
            c.saveState()
            c.setFillColor(FILL_COLOR if k == "fill" else CUT_COLOR)
            c.rect(x * 2.8346, (y - 1) * 2.8346, 8 * 2.8346, 3 * 2.8346, stroke=0, fill=1)
            c.restoreState()
        else:
            c.saveState()
            c.setLineWidth({"wall": 1.6, "bnd": 0.7, "cont": 0.2, "drain": 0.4}[k])
            c.setStrokeColor({"wall": black, "bnd": RED, "cont": Color(0.55, 0.4, 0.25), "drain": BLUE}[k])
            if k == "bnd":
                c.setDash(8, 2)
            c.line(x * 2.8346, (y + 0.5) * 2.8346, (x + 8) * 2.8346, (y + 0.5) * 2.8346)
            c.restoreState()
        text_at(c, x + 10, y - 0.3, label, 2.2)
        y -= 5
    text_at(c, x, y - 1, "FH+0.00：計画高（KBM基準）", 2.1)
    text_at(c, x, y - 4.5, "(+0.00)：現況高（DEM＋写真補正、推定）", 2.1, color=GRAY)
    y -= 12
    # 土量表
    text_at(c, x, y, "土量集計（メッシュ法 0.5m）", 2.8)
    y -= 5
    b = res["balance"]
    rows = [("敷地面積", f"{res['area_m2']:.1f} ㎡"),
            ("計画高 FH", f"KBM{_rel(res['fh_m'], kbm)}（{res['fh_basis']}）"),
            ("現況高低差", f"{res['existing_diff']:.2f} m"),
            ("切土（地山）", f"{res['cut_m3']:.1f} ㎥"),
            ("盛土（締固め後）", f"{res['fill_m3']:.1f} ㎥"),
            ("流用土", f"{b['reuse_m3']:.1f} ㎥"),
            ("購入土（地山換算）", f"{b['purchase_m3']:.1f} ㎥"),
            ("残土（ほぐし）", f"{b['disposal_loose_m3']:.1f} ㎥"),
            ("土量変化率", f"L={res['soil']['L']} C={res['soil']['C']}"),
            ("最大盛土厚／切土深", f"{res['max_fill_m']:.2f} m ／ {res['max_cut_m']:.2f} m")]
    c.saveState()
    c.setLineWidth(0.2)
    for i, (k, val) in enumerate(rows):
        yy = y - i * 4.6
        c.rect(x * 2.8346, (yy - 1.4) * 2.8346, 100 * 2.8346, 4.6 * 2.8346)
        text_at(c, x + 1.5, yy, k, 2.1)
        text_at(c, x + 36, yy, val, 2.1)
    c.restoreState()
    y -= len(rows) * 4.6 + 4
    alts = res.get("alternatives") or []
    if len(alts) > 1:
        text_at(c, x, y, "計画高の比較（KBM基準・概算は標準値）", 2.6)
        y -= 4.6
        c.saveState()
        c.setLineWidth(0.2)
        for a in alts:
            c.rect(x * 2.8346, (y - 1.4) * 2.8346, 100 * 2.8346, 7.6 * 2.8346)
            text_at(c, x + 1.2, y + 3.0, a["label"][:28], 1.9)
            note = "道路より低い・排水注意" if a["below_road"] else ""
            text_at(c, x + 1.2, y - 0.2,
                    f"FH{_rel(a['fh_m'], kbm)} 切{a['cut_m3']:.0f}/盛{a['fill_m3']:.0f}m³ 擁壁{a['wall_m']:.0f}m(最大H{a['wall_hmax']:.1f}) "
                    f"約{a['total_mid'] / 10000:,.0f}万円 {note}", 1.85)
            y -= 7.6
        c.restoreState()
        y -= 3
    text_at(c, x, y, "法規チェック（区域指定・自治体基準は要確認）", 2.6)
    y -= 4.5
    for f in res["flags"]:
        for line in _wrap(f, 46):
            text_at(c, x + 1, y, line, 2.0, color=RED if "可能性" in f or "対象" in f else black)
            y -= 3.4
        y -= 0.8


def _legend_existing(c, x, ytop, res, kbm, spec):
    y = ytop - 4
    text_at(c, x, y, "現況の読み取り", 3.0)
    y -= 6
    rows = [f"敷地面積 約{res['area_m2']:.1f}㎡（推定）",
            f"現況高低差（敷地内） {res['existing_diff']:.2f}m",
            f"敷地内 最低 {_rel(res['existing_min'], kbm)} ／ 最高 {_rel(res['existing_max'], kbm)}"]
    if res.get("road"):
        rows.append(f"道路境界 {_rel(res['road']['edge_min'], kbm)}〜{_rel(res['road']['edge_max'], kbm)}")
    for p in spec["site"]["existing"].get("points", []):
        rows.append(f"◎{p.get('label', '')}: {p.get('basis', '')}")
    for r in rows:
        for line in _wrap(r, 46):
            text_at(c, x, y, line, 2.1)
            y -= 3.6
    y -= 3
    text_at(c, x, y, "斜線：解体する既存建物 ／ 太線：解体する外構", 2.1)


def _wrap(s, n):
    out = []
    while len(s) > n:
        out.append(s[:n])
        s = s[n:]
    out.append(s)
    return out


def render_sections(c, spec, res, sheet_no="C-02"):
    """A-A（道路直交）・B-B（道路平行）断面。高低差が小さいときは縦方向を強調（縦倍率を表記）。"""
    site = spec["site"]
    meta = spec.get("project", {})
    new_sheet(c)
    kbm = res["road"]["center_avg"] if res.get("road") else res["fh_m"]
    area = frame(c, "造成計画断面図（参考）", sheet_no, meta,
                 notes=["断面の現況線は推定（1mDEM＋写真補正）。擁壁の形状は標準的なL型擁壁の模式。構造は大臣認定品または構造計算による。"])
    ax, ay, aw, ah = area
    lines = section_lines(site, res)
    surf = res["surface"]
    pz = res["plan_z"]
    poly = [tuple(p) for p in site["boundary"]]
    profiles = {}
    zmin, zmax, smax = 1e9, -1e9, 0
    for name, (p, q) in lines.items():
        L = seg_len(p, q)
        n = int(L / 0.25) + 1
        pts = []
        for k in range(n):
            t = k / (n - 1)
            x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            e = surf.z(x, y) - kbm
            inside = point_in_poly(x, y, poly)
            pp = pz(x, y) - kbm if inside else None
            pts.append((t * L, e, pp))
            zmin = min(zmin, e, pp if pp is not None else e)
            zmax = max(zmax, e, pp if pp is not None else e)
        profiles[name] = (pts, L)
        smax = max(smax, L)
    each_h = (ah - 10) / 2
    scale = pick_scale(smax + 6, 4.0, aw - 50, each_h - 20)
    k = 1000 / scale
    relief = max(zmax - zmin, 0.1) + 1.6  # 擁壁の根入れ・余白
    ex = 1
    for cand in (1, 2, 3, 5, 10):
        if relief * cand * k <= each_h - 22:
            ex = cand
        if relief * cand * k >= 35:
            break
    for idx, (name, (pts, L)) in enumerate(profiles.items()):
        band_top = ay + ah - 4 - each_h * idx
        base_y = band_top - each_h + 12
        ox = ax + 30 + ((aw - 50) - L * k) / 2
        oy = base_y - (zmin - 1.0) * ex * k
        v = View(c, ox, oy, scale)
        Z = lambda z: z * ex  # noqa: E731
        for (s0, e0, p0), (s1, e1, p1) in zip(pts, pts[1:]):
            if p0 is None or p1 is None:
                continue
            col = FILL_COLOR if (p0 + p1) / 2 > (e0 + e1) / 2 else CUT_COLOR
            v.polyline([(s0, Z(e0)), (s1, Z(e1)), (s1, Z(p1)), (s0, Z(p0))], w=0, closed=True, fill=col)
        v.polyline([(s, Z(e)) for s, e, _ in pts], w=0.35, dash=(3, 1.5), color=Color(0.45, 0.3, 0.2))
        seg = []
        for s, _, p in pts + [(None, None, None)]:
            if p is None:
                if len(seg) > 1:
                    v.polyline(seg, w=0.9)
                seg = []
            else:
                seg.append((s, Z(p)))
        for (s0, e0, p0), (s1, e1, p1) in zip(pts, pts[1:]):
            if (p0 is None) == (p1 is None):
                continue
            s = s1 if p0 is None else s0
            inside_z = p1 if p0 is None else p0
            outside_z = e0 if p0 is None else e1
            top, bot = max(inside_z, outside_z), min(inside_z, outside_z)
            v.line(s, Z(top) + 0.6 * ex, s, Z(bot) - 0.3 * ex, w=0.15, color=RED, dash=(4, 1.5))
            v.text(s, Z(top) + 0.6 * ex, "境界", 1.8, "c", color=RED, dy_mm=0.5)
            hdiff = top - bot
            if hdiff > 0.3:
                high_dir = 1 if (inside_z > outside_z) == (p0 is None) else -1
                foot = 0.5 + hdiff * 0.55
                v.polyline([(s, Z(top)), (s, Z(bot) - 0.4 * ex), (s + high_dir * foot, Z(bot) - 0.4 * ex),
                            (s + high_dir * foot, Z(bot) - 0.1 * ex), (s + high_dir * 0.2, Z(bot) - 0.1 * ex),
                            (s + high_dir * 0.2, Z(top))], w=0.5, closed=True, fill=LIGHT)
                v.dim_v(Z(bot), Z(top), s, off_mm=-7 * high_dir, label=f"H={hdiff:.2f}")
            elif hdiff > 0.05:
                v.text(s, Z(top), f"段差{hdiff:.2f}", 1.7, "c", dy_mm=3.0)
        v.line(-1, 0, L + 1, 0, w=0.15, color=GRAY, dash=(1, 1.5))
        v.text(-1.2, 0, "KBM±0", 1.9, "r", dy_mm=-0.6)
        inside = [(s, p) for s, _, p in pts if p is not None]
        if inside:
            sm, pm = inside[len(inside) // 2]
            v.level_mark(sm, Z(pm), f"FH{pm:+.2f}", 2.1)
            em = [e for s, e, _ in pts if abs(s - sm) < 0.13][0]
            v.text(sm, Z(em), f"現況{em:+.2f}", 1.8, "c", dy_mm=-3.2, color=GRAY)
        for kk in range(0, int(L) + 1, 5):
            v.line(kk, Z(zmin - 1.0), kk, Z(zmin - 1.0) + 0.6, w=0.2)
            v.text(kk, Z(zmin - 1.0), f"{kk}m", 1.6, "c", dy_mm=-2.6)
        ttl = f"{name}-{name}断面  H=1/{scale}" + (f"  V=1/{scale // ex if scale % ex == 0 else round(scale / ex)}（縦{ex}倍強調）" if ex > 1 else "")
        text_at(c, ax + 6, band_top - 5, ttl, 3.2)
    text_at(c, ax + aw - 2, ay + ah - 2, "実線：計画地盤 ／ 破線：現況地盤（推定）／ 緑：盛土 ／ 黄：切土 ／ 高さはKBM基準", 2.2, "r")
    c.showPage()
