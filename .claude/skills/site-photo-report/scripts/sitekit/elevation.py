"""立面図の描画。

face 定義（site.json の building.elevations[]）:
{
  "name": "南立面図（共用廊下側）",
  "width_m": 14.56,              # 外壁の幅（GLでの左右端）
  "eave_h": 5.75,                # 軒高（GL→軒桁上端の目安）
  "floors": [0.0, 2.9],          # 各階 FL（GL基準）
  "gl_offset": 0.0,              # 左端からの地盤の上下（傾斜地は ground 推奨）
  "ground": [[-2,0],[16,0]],     # 任意: 地盤線（x, z）
  "roof": {"type": "gable_side|gable_end|shed|flat|hip_side",
           "ridge_h": 7.4, "overhang": 0.45, "label": "カラー鉄板 切妻 4寸"},
  "elements": [ ... ]            # 下記 type
}
element type:
  window   {x, z, w, h, label?, grille?: bool}       引違い窓
  door     {x, z, w, h, label?}
  railing  {x, z, w, h, label?, bar: 0.12}          手すり（縦格子）
  slab     {x, z, w, h}                              廊下・バルコニー床
  post     {x, z, h, w?}                             柱
  pipe     {x, z0, z1}                               雨樋たて
  stair    {x0, z0, x1, z1, rail_h?: 0.9, label?}    外階段（側面）
  stair_front {x, z0, w, z1}                         外階段（正面・段の見え）
  box      {x, z, w, h, label?}                      室外機・メーター等
  block_wall {x, w, courses, z?}                     ブロック塀（1段0.2m）
  fence    {x, w, h, z?, label?}
  tree     {x, h, w?}
  band     {z, h?}                                   胴差し・幕板
  canopy   {x, z, w, h?}                             庇
  label    {x, z, text}
"""
from reportlab.lib.colors import Color, black

from .drawing import GRAY, LIGHT, View, frame, new_sheet, pick_scale, scale_bar, text_at

WALL_FILL = Color(0.97, 0.97, 0.97)


def face_extent(face):
    w = face["width_m"]
    roof = face.get("roof", {})
    ov = roof.get("overhang", 0.4)
    top = max(roof.get("ridge_h", face["eave_h"]), face["eave_h"])
    xs = [-ov, w + ov]
    for e in face.get("elements", []):
        if "x" in e:
            xs += [e["x"], e["x"] + e.get("w", 0)]
        if "x0" in e:
            xs += [e["x0"], e["x1"]]
    for g in face.get("ground", []):
        xs.append(g[0])
    return min(xs), max(xs), -0.6, top + 0.3


def draw_face(v: View, face):
    w = face["width_m"]
    eave = face["eave_h"]
    roof = face.get("roof", {"type": "gable_side"})
    ov = roof.get("overhang", 0.4)
    ridge = roof.get("ridge_h", eave)
    rtype = roof.get("type", "gable_side")
    x_min, x_max, _, _ = face_extent(face)

    # 外壁
    if rtype == "gable_end":
        wall = [(0, 0), (w, 0), (w, eave), (w / 2, ridge - 0.25), (0, eave)]
    else:
        wall = [(0, 0), (w, 0), (w, eave), (0, eave)]
    v.polyline(wall, w=0.5, closed=True, fill=WALL_FILL)

    # 屋根
    if rtype == "gable_end":
        th = 0.2
        v.polyline([(-ov, eave - ov * (ridge - eave) / (w / 2)), (w / 2, ridge), (w + ov, eave - ov * (ridge - eave) / (w / 2))], w=0.6)
        v.polyline([(-ov, eave - ov * (ridge - eave) / (w / 2) - th), (w / 2, ridge - th), (w + ov, eave - ov * (ridge - eave) / (w / 2) - th)], w=0.3)
        v.line(-ov, eave - ov * (ridge - eave) / (w / 2), -ov, eave - ov * (ridge - eave) / (w / 2) - th, w=0.3)
        v.line(w + ov, eave - ov * (ridge - eave) / (w / 2), w + ov, eave - ov * (ridge - eave) / (w / 2) - th, w=0.3)
    elif rtype in ("gable_side", "hip_side"):
        inset = (ridge - eave) * 1.2 if rtype == "hip_side" else 0
        v.polyline([(-ov, eave), (w + ov, eave), (w + ov - inset, ridge), (-ov + inset, ridge)], w=0.6, closed=True,
                   fill=Color(0.9, 0.9, 0.9))
        # 屋根材の縦筋（瓦棒・段葺きの見え）
        n = int((w + 2 * ov) / 0.45)
        for i in range(1, n):
            x = -ov + (w + 2 * ov) * i / n
            if -ov + inset <= x <= w + ov - inset:
                v.line(x, eave, x, ridge, w=0.08, color=GRAY)
        v.line(-ov, eave - 0.18, w + ov, eave - 0.18, w=0.3)
    elif rtype == "shed":
        v.polyline([(-ov, eave), (w + ov, ridge), (w + ov, ridge + 0.15), (-ov, eave + 0.15)], w=0.5, closed=True)
    elif rtype == "flat":
        v.rect(-0.05, eave, w + 0.1, 0.4, lw=0.5)

    # 地盤線
    ground = face.get("ground") or [[x_min - 0.5, 0], [x_max + 0.5, 0]]
    v.polyline([tuple(g) for g in ground], w=0.8)
    for i in range(len(ground) - 1):
        (gx0, gz0), (gx1, gz1) = ground[i], ground[i + 1]
        n = max(1, int(abs(gx1 - gx0) / 0.6))
        for k in range(n):
            x = gx0 + (gx1 - gx0) * k / n
            z = gz0 + (gz1 - gz0) * k / n
            v.line(x, z, x - 0.25, z - 0.25, w=0.1, color=GRAY)

    for e in face.get("elements", []):
        _draw_element(v, e)

    for fl in face.get("floors", [])[1:]:
        v.line(0, fl, w, fl, w=0.12, color=GRAY, dash=(4, 2))


def _draw_element(v: View, e):
    t = e["type"]
    if t == "window":
        x, z, w, h = e["x"], e["z"], e["w"], e["h"]
        v.rect(x, z, w, h, lw=0.4, fill=Color(0.88, 0.93, 0.98))
        v.rect(x + 0.04, z + 0.04, w - 0.08, h - 0.08, lw=0.15)
        v.line(x + w / 2, z + 0.04, x + w / 2, z + h - 0.04, w=0.25)
        if e.get("grille"):
            n = max(3, int(w / 0.12))
            for i in range(1, n):
                v.line(x + w * i / n, z - 0.05, x + w * i / n, z + h * 0.45, w=0.12)
            v.line(x, z + h * 0.45, x + w, z + h * 0.45, w=0.2)
        if e.get("label"):
            lab = f"W{w*1000:.0f}×H{h*1000:.0f}" if e["label"] == "auto" else e["label"]
            v.text(x + w / 2, z - 0.05, lab, 1.8, "c", dy_mm=-2.4)
    elif t == "door":
        x, z, w, h = e["x"], e["z"], e["w"], e["h"]
        v.rect(x, z, w, h, lw=0.4, fill=Color(0.92, 0.92, 0.92))
        v.rect(x + 0.05, z + 0.05, w - 0.1, h - 0.05, lw=0.12)
        v.line(x + w - 0.12, z + h * 0.45, x + w - 0.12, z + h * 0.55, w=0.4)
        if e.get("label"):
            v.text(x + w / 2, z + h + 0.05, e["label"], 1.8, "c", dy_mm=0.6)
    elif t == "railing":
        x, z, w, h = e["x"], e["z"], e["w"], e["h"]
        bar = e.get("bar", 0.12)
        v.line(x, z + h, x + w, z + h, w=0.45)
        v.line(x, z + 0.08, x + w, z + 0.08, w=0.2)
        n = max(1, int(w / bar))
        for i in range(n + 1):
            xx = x + w * i / n
            v.line(xx, z + 0.08, xx, z + h, w=0.1)
    elif t == "slab":
        v.rect(e["x"], e["z"], e["w"], e.get("h", 0.15), lw=0.35, fill=LIGHT)
    elif t == "post":
        pw = e.get("w", 0.1)
        v.rect(e["x"] - pw / 2, e["z"], pw, e["h"], lw=0.3, fill=Color(1, 1, 1))
    elif t == "pipe":
        v.line(e["x"], e["z0"], e["x"], e["z1"], w=0.5)
        v.line(e["x"] - 0.05, e["z1"], e["x"] + 0.05, e["z1"], w=0.3)
    elif t == "stair":
        x0, z0, x1, z1 = e["x0"], e["z0"], e["x1"], e["z1"]
        rh = e.get("rail_h", 0.9)
        v.polyline([(x0, z0), (x1, z1), (x1, z1 - 0.25), (x0 + 0.3, z0)], w=0.4, closed=True, fill=LIGHT)
        v.line(x0, z0 + rh, x1, z1 + rh, w=0.4)
        n = max(2, int(abs(x1 - x0) / 0.5))
        for i in range(n + 1):
            xx = x0 + (x1 - x0) * i / n
            zz = z0 + (z1 - z0) * i / n
            v.line(xx, zz, xx, zz + rh, w=0.12)
        steps = int(abs(z1 - z0) / 0.2)
        for i in range(1, steps):
            xx = x0 + (x1 - x0) * i / steps
            zz = z0 + (z1 - z0) * i / steps
            v.line(xx, zz, xx, zz - 0.05, w=0.2)
        if e.get("label"):
            v.text((x0 + x1) / 2, (z0 + z1) / 2 + rh + 0.3, e["label"], 1.8, "c")
    elif t == "stair_front":
        x, w = e["x"], e["w"]
        z0, z1 = e["z0"], e["z1"]
        v.line(x, z0, x, z1 + 0.9, w=0.35)
        v.line(x + w, z0, x + w, z1 + 0.9, w=0.35)
        steps = int((z1 - z0) / 0.2)
        for i in range(steps + 1):
            zz = z0 + (z1 - z0) * i / steps
            v.line(x, zz, x + w, zz, w=0.15)
    elif t == "box":
        v.rect(e["x"], e["z"], e["w"], e["h"], lw=0.3, fill=Color(0.95, 0.95, 0.95))
        if e.get("label"):
            v.text(e["x"] + e["w"] / 2, e["z"] + e["h"], e["label"], 1.6, "c", dy_mm=0.5)
    elif t == "block_wall":
        z = e.get("z", 0.0)
        x, w, n = e["x"], e["w"], e["courses"]
        h = 0.2 * n
        v.rect(x, z, w, h, lw=0.4, fill=Color(0.88, 0.88, 0.86))
        for i in range(1, n):
            v.line(x, z + 0.2 * i, x + w, z + 0.2 * i, w=0.1, color=GRAY)
        for i in range(n):
            off = 0 if i % 2 == 0 else 0.195
            xx = x + off
            while xx < x + w:
                v.line(xx, z + 0.2 * i, xx, z + 0.2 * (i + 1), w=0.08, color=GRAY)
                xx += 0.39
        if e.get("label", True):
            v.text(x + w / 2, z + h, e.get("label") or f"CB塀 {n}段 H≈{h:.1f}m", 1.7, "c", dy_mm=0.6)
    elif t == "fence":
        z = e.get("z", 0.0)
        x, w, h = e["x"], e["w"], e["h"]
        v.line(x, z + h, x + w, z + h, w=0.35)
        v.line(x, z + 0.1, x + w, z + 0.1, w=0.2)
        n = max(1, int(w / 0.15))
        for i in range(n + 1):
            v.line(x + w * i / n, z, x + w * i / n, z + h, w=0.1)
        if e.get("label"):
            v.text(x + w / 2, z + h, e["label"], 1.7, "c", dy_mm=0.6)
    elif t == "tree":
        x, h = e["x"], e["h"]
        cw = e.get("w", h * 0.6)
        v.line(x, 0, x, h * 0.45, w=0.6)
        v.ellipse(x, h * 0.65, cw / 2, h * 0.35, dash=(1, 1))
        v.text(x, h, e.get("label", f"樹木 H≈{h:.0f}m"), 1.7, "c", dy_mm=0.6)
    elif t == "band":
        x0 = e.get("x", 0)
        v.rect(x0, e["z"], e.get("w", 0), e.get("h", 0.12), lw=0.25) if e.get("w") else None
    elif t == "canopy":
        v.rect(e["x"], e["z"], e["w"], e.get("h", 0.1), lw=0.35, fill=LIGHT)
    elif t == "label":
        v.text(e["x"], e["z"], e["text"], e.get("size", 1.8), e.get("anchor", "l"))


def draw_face_dims(v: View, face):
    w = face["width_m"]
    eave = face["eave_h"]
    roof = face.get("roof", {})
    ridge = roof.get("ridge_h", eave)
    x_min, x_max, _, _ = face_extent(face)
    v.dim_h(0, w, 0, off_mm=-9)
    # 開口の位置寸法（窓・ドア）を下段に
    xs = sorted({round(e["x"], 3) for e in face.get("elements", []) if e["type"] in ("window", "door")} |
                {round(e["x"] + e["w"], 3) for e in face.get("elements", []) if e["type"] in ("window", "door")})
    xs = [x for x in xs if 0 <= x <= w]
    chain = [0.0] + xs + [w]
    chain = sorted(set(chain))
    if 2 < len(chain) <= 24:
        for a, b in zip(chain[:-1], chain[1:]):
            if v.len_mm(b - a) >= 5.5:
                v.dim_h(a, b, 0, off_mm=-5, size=1.7)
    # 高さ寸法（右側）
    xr = max(w, x_max)
    levels = [0.0] + list(face.get("floors", [])[1:]) + [eave]
    if ridge > eave + 0.05:
        levels.append(ridge)
    levels = sorted(set(levels))
    for a, b in zip(levels[:-1], levels[1:]):
        v.dim_v(a, b, xr, off_mm=6)
    v.dim_v(0, levels[-1], xr, off_mm=12)
    # レベル表記（左側）
    xl = min(0, x_min)
    names = {0.0: "GL±0"}
    fls = face.get("floors", [])
    if fls and fls[0] > 0.05:
        names[fls[0]] = "1FL"
        levels = sorted(set(levels + [fls[0]]))
    for i, fl in enumerate(face.get("floors", [])[1:], start=2):
        names[fl] = f"{i}FL"
    names[eave] = "軒高"
    if ridge > eave + 0.05:
        names[ridge] = "最高高さ"
    for z, n in names.items():
        v.line(xl - 0.6, z, xl - 0.1, z, w=0.15)
        v.level_mark(xl - 0.6, z, f"{n} {z*1000:+,.0f}" if z else n, 1.8, right=False)
    if roof.get("label"):
        v.text(w / 2, max(ridge, eave), roof["label"], 1.8, "c", dy_mm=1.5)


def render_elevations(c, spec, sheet_prefix="A"):
    """立面図を 1シート2面ずつ（大きい建物は1面）描く。シート数を返す。"""
    faces = spec["building"].get("elevations", [])
    meta = spec.get("project", {})
    sheets = 0
    i = 0
    while i < len(faces):
        group = faces[i:i + 2]
        new_sheet(c)
        notes = [
            "寸法は現地写真に写した基準物（メジャー・ブロック・ドア等の標準寸法）からの推定値。±5〜10%程度の誤差を含む。",
            "写真で見えない部分（裏面・屋根上・基礎）は一般的な仕様で補完している。",
        ]
        area = frame(c, "立面図（参考）", f"{sheet_prefix}-{sheets + 1:02d}", meta, notes=notes)
        ax, ay, aw, ah = area
        ext = [face_extent(f) for f in group]
        ws = [e[1] - e[0] + 6.0 for e in ext]   # 左右の寸法・レベル表記ぶん
        hs = [e[3] - e[2] + 1.6 for e in ext]
        # 横並び と 縦積み のうち大きい縮尺を採用
        s_side = pick_scale(sum(ws), max(hs), aw - 10, ah - 22)
        s_stack = pick_scale(max(ws), sum(hs), aw - 10, ah - 16 * len(group))
        stack = s_stack < s_side and len(group) > 1
        scale = s_stack if stack else s_side
        k = 1000 / scale
        if stack:
            total_h = sum(hs) * k + 14 * len(group)
            y = ay + (ah - total_h) / 2 + total_h
            for f, (x0, x1, z0, z1), wd, ht in zip(group, ext, ws, hs):
                y -= ht * k + 14
                left = ax + (aw - wd * k) / 2 + 3.0 * k
                v = View(c, left - x0 * k, y + 12 + 1.2 * k, scale)
                draw_face(v, f)
                draw_face_dims(v, f)
                text_at(c, left + (x1 - x0) * k / 2, y + 3, f"{f['name']}  S=1/{scale}", 3.2, "c")
        else:
            total_w = sum(ws) * k
            left = ax + (aw - total_w) / 2
            base = ay + (ah - max(hs) * k - 14) / 2
            for f, (x0, x1, z0, z1), wd in zip(group, ext, ws):
                ox = left + 3.0 * k - x0 * k
                v = View(c, ox, base + 12 + 1.2 * k, scale)
                draw_face(v, f)
                draw_face_dims(v, f)
                text_at(c, left + wd * k / 2, base + 3, f"{f['name']}  S=1/{scale}", 3.2, "c")
                left += wd * k
        scale_bar(c, ax + 2, ay + ah - 6, scale)
        c.showPage()
        sheets += 1
        i += len(group)
    return sheets
