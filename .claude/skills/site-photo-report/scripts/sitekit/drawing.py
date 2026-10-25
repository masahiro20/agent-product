"""図面用の描画プリミティブ（A3図枠・表題欄・寸法線・縮尺）。

座標系: モデルはメートル、用紙はミリ。View が両者を変換する。
"""
import math

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A3, landscape

from .common import FONT, MM, ensure_font

SHEET_W, SHEET_H = 420.0, 297.0  # A3横 (mm)
MARGIN = 10.0
TITLE_H = 32.0
STD_SCALES = [20, 30, 50, 100, 150, 200, 250, 300, 400, 500, 600, 1000]

GRAY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.85, 0.85, 0.85)
RED = Color(0.8, 0.1, 0.1)
BLUE = Color(0.1, 0.3, 0.75)
CUT_COLOR = Color(0.93, 0.78, 0.45)   # 切土（黄土色）
FILL_COLOR = Color(0.55, 0.78, 0.55)  # 盛土（緑）


def pick_scale(model_w_m, model_h_m, avail_w_mm, avail_h_mm):
    for s in STD_SCALES:
        if model_w_m * 1000 / s <= avail_w_mm and model_h_m * 1000 / s <= avail_h_mm:
            return s
    return STD_SCALES[-1]


class View:
    """モデル座標(m) → 用紙座標(mm)。ox, oy はモデル原点の用紙位置。"""

    def __init__(self, c, ox_mm, oy_mm, scale):
        self.c = c
        self.ox = ox_mm
        self.oy = oy_mm
        self.scale = scale

    def p(self, x, y):
        return ((self.ox + x * 1000 / self.scale) * MM, (self.oy + y * 1000 / self.scale) * MM)

    def len_mm(self, m):
        return m * 1000 / self.scale

    # --- 基本図形 ---
    def line(self, x0, y0, x1, y1, w=0.25, color=black, dash=None):
        c = self.c
        c.saveState()
        c.setLineWidth(w)
        c.setStrokeColor(color)
        if dash:
            c.setDash(list(dash))
        c.line(*self.p(x0, y0), *self.p(x1, y1))
        c.restoreState()

    def polyline(self, pts, w=0.25, color=black, closed=False, fill=None, dash=None):
        if len(pts) < 2:
            return
        c = self.c
        c.saveState()
        c.setLineWidth(w)
        c.setStrokeColor(color)
        if dash:
            c.setDash(list(dash))
        path = c.beginPath()
        path.moveTo(*self.p(*pts[0]))
        for q in pts[1:]:
            path.lineTo(*self.p(*q))
        if closed:
            path.close()
        if fill is not None:
            c.setFillColor(fill)
        c.drawPath(path, stroke=1 if w > 0 else 0, fill=1 if fill is not None else 0)
        c.restoreState()

    def rect(self, x, y, w, h, lw=0.25, color=black, fill=None, dash=None):
        self.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], w=lw, color=color,
                      closed=True, fill=fill, dash=dash)

    def ellipse(self, cx, cy, rx, ry, w=0.25, color=black, dash=None):
        c = self.c
        c.saveState()
        c.setLineWidth(w)
        c.setStrokeColor(color)
        if dash:
            c.setDash(list(dash))
        px, py = self.p(cx, cy)
        c.ellipse(px - self.len_mm(rx) * MM, py - self.len_mm(ry) * MM, px + self.len_mm(rx) * MM, py + self.len_mm(ry) * MM)
        c.restoreState()

    def text(self, x, y, s, size=2.5, anchor="l", color=black, angle=0, dy_mm=0.0):
        """size は文字高さ(mm)。"""
        c = self.c
        px, py = self.p(x, y)
        text_at(c, px / MM, py / MM + dy_mm, s, size, anchor, color, angle)

    def clip_lines(self, poly, segs, w=0.1, color=None):
        """多角形の内側だけに線分を描く（外壁の仕上げ模様など）。"""
        c = self.c
        c.saveState()
        path = c.beginPath()
        path.moveTo(*self.p(*poly[0]))
        for q in poly[1:]:
            path.lineTo(*self.p(*q))
        path.close()
        c.clipPath(path, stroke=0, fill=0)
        c.setLineWidth(w)
        c.setStrokeColor(color or Color(0.62, 0.62, 0.62))
        for (x0, y0), (x1, y1) in segs:
            c.line(*self.p(x0, y0), *self.p(x1, y1))
        c.restoreState()

    def hatch(self, poly, spacing_m=0.2, angle_deg=45, w=0.12, color=GRAY):
        """多角形内をハッチング（単純な走査線＋クリップ）。"""
        c = self.c
        c.saveState()
        path = c.beginPath()
        path.moveTo(*self.p(*poly[0]))
        for q in poly[1:]:
            path.lineTo(*self.p(*q))
        path.close()
        c.clipPath(path, stroke=0, fill=0)
        xs = [q[0] for q in poly]
        ys = [q[1] for q in poly]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2 + spacing_m
        a = math.radians(angle_deg)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        c.setLineWidth(w)
        c.setStrokeColor(color)
        k = -r
        while k <= r:
            x0, y0 = cx + nx * k - dx * r, cy + ny * k - dy * r
            x1, y1 = cx + nx * k + dx * r, cy + ny * k + dy * r
            c.line(*self.p(x0, y0), *self.p(x1, y1))
            k += spacing_m
        c.restoreState()

    # --- 寸法線 ---
    def dim_h(self, x0, x1, y, off_mm=6.0, label=None, size=2.3):
        """水平寸法。y はモデルでの測点高さ、off_mm だけ用紙上で上下にずらす（負で下）。"""
        c = self.c
        _, py = self.p(0, y)
        py_line = py + off_mm * MM
        px0, _ = self.p(x0, y)
        px1, _ = self.p(x1, y)
        c.saveState()
        c.setLineWidth(0.15)
        c.setStrokeColor(GRAY)
        sgn = 1 if off_mm >= 0 else -1
        c.line(px0, py + sgn * 1 * MM, px0, py_line + sgn * 1.5 * MM)
        c.line(px1, py + sgn * 1 * MM, px1, py_line + sgn * 1.5 * MM)
        c.setStrokeColor(black)
        c.line(px0, py_line, px1, py_line)
        for px in (px0, px1):
            c.line(px - 0.8 * MM, py_line - 0.8 * MM, px + 0.8 * MM, py_line + 0.8 * MM)
        c.restoreState()
        s = label if label is not None else f"{(x1 - x0) * 1000:,.0f}"
        text_at(c, (px0 + px1) / 2 / MM, py_line / MM + 0.8, s, size, "c")

    def dim_v(self, y0, y1, x, off_mm=6.0, label=None, size=2.3):
        c = self.c
        px, _ = self.p(x, 0)
        px_line = px + off_mm * MM
        _, py0 = self.p(x, y0)
        _, py1 = self.p(x, y1)
        c.saveState()
        c.setLineWidth(0.15)
        c.setStrokeColor(GRAY)
        sgn = 1 if off_mm >= 0 else -1
        c.line(px + sgn * 1 * MM, py0, px_line + sgn * 1.5 * MM, py0)
        c.line(px + sgn * 1 * MM, py1, px_line + sgn * 1.5 * MM, py1)
        c.setStrokeColor(black)
        c.line(px_line, py0, px_line, py1)
        for py in (py0, py1):
            c.line(px_line - 0.8 * MM, py - 0.8 * MM, px_line + 0.8 * MM, py + 0.8 * MM)
        c.restoreState()
        s = label if label is not None else f"{(y1 - y0) * 1000:,.0f}"
        text_at(c, px_line / MM - 0.8, (py0 + py1) / 2 / MM, s, size, "c", angle=90)

    def level_mark(self, x, y, label, size=2.3, right=True):
        """▽ レベル記号＋ラベル（立面・断面用）。"""
        c = self.c
        px, py = self.p(x, y)
        c.saveState()
        c.setLineWidth(0.2)
        t = 1.4 * MM
        path = c.beginPath()
        path.moveTo(px, py)
        path.lineTo(px - t * 0.6, py + t)
        path.lineTo(px + t * 0.6, py + t)
        path.close()
        c.drawPath(path, stroke=1, fill=0)
        c.restoreState()
        text_at(c, px / MM + (1.5 if right else -1.5), py / MM + 1.6, label, size, "l" if right else "r")


GLYPH_FIX = {"㎥": "m³"}


def jp(s):
    """フォントに無い字形を置き換える。"""
    s = str(s)
    for k, v in GLYPH_FIX.items():
        s = s.replace(k, v)
    return s


def text_at(c, x_mm, y_mm, s, size=2.5, anchor="l", color=black, angle=0):
    ensure_font()
    s = jp(s)
    fs = size / 0.7 * MM / MM * 2.8346  # 文字高さ(mm) → フォントサイズ(pt) 概算
    c.saveState()
    c.setFont(FONT, fs)
    c.setFillColor(color)
    c.translate(x_mm * MM, y_mm * MM)
    if angle:
        c.rotate(angle)
    if anchor == "c":
        c.drawCentredString(0, 0, s)
    elif anchor == "r":
        c.drawRightString(0, 0, s)
    else:
        c.drawString(0, 0, s)
    c.restoreState()


def text_width_mm(s, size):
    ensure_font()
    s = jp(s)
    from reportlab.pdfbase.pdfmetrics import stringWidth
    fs = size / 0.7 * 2.8346
    return stringWidth(s, FONT, fs) / MM


def new_sheet(c):
    c.setPageSize(landscape(A3))


def frame(c, title, sheet_no, meta, scale_label="", notes=None):
    """図枠と表題欄。meta: project dict。図面の作図可能領域 (x, y, w, h) mm を返す。"""
    ensure_font()
    c.setLineWidth(0.6)
    c.rect(MARGIN * MM, MARGIN * MM, (SHEET_W - 2 * MARGIN) * MM, (SHEET_H - 2 * MARGIN) * MM)
    # 表題欄（右下）
    tw = 200.0
    tx = SHEET_W - MARGIN - tw
    ty = MARGIN
    c.setLineWidth(0.35)
    c.rect(tx * MM, ty * MM, tw * MM, TITLE_H * MM)
    cols = [tx, tx + 30, tx + 120, tx + 150]
    for x in cols[1:]:
        c.line(x * MM, ty * MM, x * MM, (ty + TITLE_H) * MM)
    for k in range(1, 4):
        c.line(tx * MM, (ty + TITLE_H * k / 4) * MM, (tx + tw) * MM, (ty + TITLE_H * k / 4) * MM)
    rows = [
        ("物件名", meta.get("name", ""), "図面番号", sheet_no),
        ("所在地", meta.get("address", ""), "縮尺", scale_label),
        ("図面名", title, "作成日", meta.get("date", "")),
        ("作成", meta.get("author", "現地写真AI推定"), "用紙", "A3"),
    ]
    for i, (k1, v1, k2, v2) in enumerate(rows):
        yy = ty + TITLE_H - TITLE_H / 4 * (i + 1) + 2.6
        text_at(c, tx + 2, yy, k1, 2.4)
        text_at(c, tx + 32, yy, _clip(v1, 34), 2.8 if i == 2 else 2.5)
        text_at(c, tx + 122, yy, k2, 2.4)
        text_at(c, tx + 152, yy, str(v2), 2.5)
    # 参考値スタンプ
    stamp = "参考図（現地写真・公開データからの推定。寸法・高さは参考値／実測・測量で要確認）"
    c.saveState()
    c.setFillColor(RED)
    c.setStrokeColor(RED)
    c.setLineWidth(0.4)
    w = text_width_mm(stamp, 2.6) + 4
    c.rect((MARGIN + 3) * MM, (MARGIN + 3) * MM, w * MM, 6 * MM, stroke=1, fill=0)
    c.restoreState()
    text_at(c, MARGIN + 5, MARGIN + 4.9, stamp, 2.6, color=RED)
    if notes:
        y = MARGIN + 12
        for n in reversed(notes):
            text_at(c, MARGIN + 4, y, n, 2.2, color=GRAY)
            y += 3.4
        top_notes = y
    else:
        top_notes = MARGIN + 12
    # 作図領域
    x0 = MARGIN + 6
    y0 = max(MARGIN + TITLE_H + 4, top_notes + 2)
    return (x0, y0, SHEET_W - MARGIN - 6 - x0, SHEET_H - MARGIN - 8 - y0)


def _clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def north_arrow(c, x_mm, y_mm, rot_deg=0.0, r=6.0):
    """方位記号。rot_deg: 図の上方向に対する真北の角度（時計回り正）。"""
    c.saveState()
    c.translate(x_mm * MM, y_mm * MM)
    c.rotate(rot_deg)  # 図の上方向が北から時計回りに rot_deg → 北は上から反時計回りに rot_deg
    c.setLineWidth(0.3)
    c.circle(0, 0, r * MM)
    p = c.beginPath()
    p.moveTo(0, r * MM)
    p.lineTo(-r * 0.35 * MM, -r * 0.6 * MM)
    p.lineTo(0, -r * 0.25 * MM)
    p.close()
    c.setFillColor(black)
    c.drawPath(p, stroke=1, fill=1)
    p = c.beginPath()
    p.moveTo(0, r * MM)
    p.lineTo(r * 0.35 * MM, -r * 0.6 * MM)
    p.lineTo(0, -r * 0.25 * MM)
    p.close()
    c.setFillColor(white)
    c.drawPath(p, stroke=1, fill=1)
    c.restoreState()
    text_at(c, x_mm, y_mm + r + 1.5, "N", 3.0, "c")


def scale_bar(c, x_mm, y_mm, scale, length_m=None):
    if length_m is None:
        for L in (1, 2, 5, 10, 20, 50):
            if L * 1000 / scale >= 25:
                length_m = L
                break
        else:
            length_m = 50
    w = length_m * 1000 / scale
    c.saveState()
    c.setLineWidth(0.3)
    for i in range(4):
        c.setFillColor(black if i % 2 == 0 else white)
        c.rect((x_mm + w / 4 * i) * MM, y_mm * MM, w / 4 * MM, 1.5 * MM, stroke=1, fill=1)
    c.restoreState()
    text_at(c, x_mm, y_mm + 2.5, "0", 2.2, "c")
    text_at(c, x_mm + w, y_mm + 2.5, f"{length_m}m", 2.2, "c")
    text_at(c, x_mm + w + 3, y_mm + 0.2, f"S=1/{scale}", 2.2)
