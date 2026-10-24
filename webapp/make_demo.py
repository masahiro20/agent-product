"""「サンプルで試す」用のデモ素材を作る（開発用。出力は public/demo/ にコミットする）。

  python -m webapp.make_demo <読み取り結果JSON（{"reading": ...} 形式）>

建物の外観イメージを立面図の定義から描き（実在の写真は使わない）、読み取り箇所の枠も
その座標から計算して、public/demo/photo*.jpg と public/demo/sample.json を出力する。
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from . import convert
from .engine import elevation
from .engine import report  # noqa: F401  (フォントパスの解決のため)
from .engine import load_data  # noqa: F401

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "public", "demo")
FONT = os.path.join(ROOT, "fonts", "ipag.ttf")
W, H = 1400, 1050

DEMO = {
    "address": "愛知県小牧市城山2丁目",
    "project_name": "【サンプル】木造2階建てアパート 解体・造成",
    "notes": "サンプル物件です。木造2階建て・1K×8戸のアパート。入居者はほぼ退去済み。",
}


class PilView:
    """elevation.draw_face をそのまま画像に描くための View 互換クラス。"""

    def __init__(self, draw, ox, oy, k):
        self.d, self.ox, self.oy, self.k = draw, ox, oy, k
        self.c = None
        self.scale = 1
        self.font = ImageFont.truetype(FONT, 18)

    def P(self, x, z):
        return (self.ox + x * self.k, self.oy - z * self.k)

    p = P

    def len_mm(self, m):
        return m * self.k

    def _col(self, color, default=(60, 60, 60)):
        if color is None:
            return default
        try:
            return tuple(int(v * 255) for v in (color.red, color.green, color.blue))
        except AttributeError:
            return default

    def line(self, x0, y0, x1, y1, w=0.25, color=None, dash=None):
        self.d.line([self.P(x0, y0), self.P(x1, y1)], fill=self._col(color), width=max(1, int(w * 4)))

    def polyline(self, pts, w=0.25, color=None, closed=False, fill=None, dash=None):
        q = [self.P(*p) for p in pts]
        if fill is not None and closed:
            self.d.polygon(q, fill=self._col(fill, (240, 240, 240)))
        if w > 0:
            self.d.line(q + ([q[0]] if closed else []), fill=self._col(color), width=max(1, int(w * 4)))

    def rect(self, x, y, w, h, lw=0.25, color=None, fill=None, dash=None):
        self.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], w=lw, color=color, closed=True, fill=fill)

    def ellipse(self, cx, cy, rx, ry, w=0.25, color=None, dash=None):
        x0, y0 = self.P(cx - rx, cy + ry)
        x1, y1 = self.P(cx + rx, cy - ry)
        self.d.ellipse([x0, y0, x1, y1], fill=(120, 150, 100), outline=(90, 120, 80))

    def text(self, *a, **k):
        pass

    def hatch(self, *a, **k):
        pass

    def dim_h(self, *a, **k):
        pass

    def dim_v(self, *a, **k):
        pass

    def level_mark(self, *a, **k):
        pass


def render_face(face, path):
    x0, x1, z0, z1 = elevation.face_extent(face)
    k = min((W - 160) / (x1 - x0), (H - 220) / (z1 - z0))
    ox = (W - (x1 - x0) * k) / 2 - x0 * k
    oy = H - 120
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(int(oy)):  # 空のグラデーション
        t = y / oy
        d.line([(0, y), (W, y)], fill=(int(150 + 80 * t), int(190 + 50 * t), int(235 + 15 * t)))
    d.rectangle([0, oy, W, H], fill=(150, 145, 135))
    v = PilView(d, ox, oy, k)
    elevation.draw_face(v, face)
    f = ImageFont.truetype(FONT, 26)
    d.rectangle([20, 20, 560, 64], fill=(255, 255, 255))
    d.text((32, 26), "サンプル画像（実際は現地写真を使います）", font=f, fill=(170, 60, 60))
    im.save(path, quality=88)
    return v


def _bbox(v, x0, z0, x1, z1):
    (px0, py0), (px1, py1) = v.P(x0, z1), v.P(x1, z0)
    return [round(max(0, min(px0, px1) / W - .01), 3), round(max(0, min(py0, py1) / H - .01), 3),
            round(min(1, max(px0, px1) / W + .01), 3), round(min(1, max(py0, py1) / H + .01), 3)]


def marks_for(face_r, v):
    out = []
    seen = set()
    for e in face_r["elements"]:
        t = e["type"]
        if t in seen or t not in ("window", "door", "stair", "stair_front", "railing", "block_wall", "tree", "box"):
            continue
        seen.add(t)
        x, z, w, h = e["x"], e["z"], e["w"], e["h"]
        if t == "block_wall":
            h = 0.2 * (e.get("courses") or 1)
        if t == "tree":
            x, w = x - (w or h * .6) / 2, (w or h * .6)
        x0, x1 = min(x, x + w), max(x, x + w)
        z0, z1 = min(z, z + h), max(z, z + h)
        label = {"window": "窓", "door": "玄関ドア", "stair": "鉄骨外階段", "stair_front": "外階段",
                 "railing": "手すり", "block_wall": "ブロック塀", "tree": "樹木", "box": "室外機"}[t]
        if e.get("label"):
            label = e["label"]
        basis = {"window": "アルミサッシの標準寸法を寸法の基準に使用", "door": "ドア高さ≒2.0mを基準",
                 "railing": "手すり高さ≒1.1m", "block_wall": "ブロック1段0.2m", "stair": "蹴上げ≒0.2m×段数"}.get(t, "")
        out.append({"x0": 0, "y0": 0, "x1": 0, "y1": 0, "label": label, "basis": basis})
        out[-1].update(dict(zip(("x0", "y0", "x1", "y1"), _bbox(v, x0, z0, x1, z1))))
        if len(out) >= 6:
            break
    return out


def main(src):
    reading = json.load(open(src, encoding="utf-8"))["reading"]
    b = reading["building"]
    order = [1, 2, 0, 3]  # 道路側（南）→ 東 → 北 → 西
    names = ["南面（道路側・居室）", "東面（外階段）", "北面（共用廊下・玄関）", "西面（側面通路）"]
    faces = [b["faces"][i] for i in order]
    for f, n in zip(faces, names):
        f["name"] = n.replace("面", "立面図", 1)
    b["faces"] = faces
    os.makedirs(OUT, exist_ok=True)
    photos = []
    for i, f in enumerate(faces, 1):
        face_spec = {"name": f["name"], "width_m": f["width_m"], "eave_h": b["eave_h"], "floors": b["floor_levels"],
                     "roof": {"type": f["roof_type"], "ridge_h": b["ridge_h"], "overhang": b["roof_overhang_m"]},
                     "elements": [convert._el(e) for e in f["elements"]]}
        v = render_face(face_spec, os.path.join(OUT, f"photo{i}.jpg"))
        photos.append({"photo_index": i, "caption": names[i - 1], "marks": marks_for(f, v)})
    reading["photos"] = photos
    reading["project_name"] = DEMO["project_name"]
    reading["summary"] = [s for s in reading.get("summary", []) if "デモ" not in s and "X" not in s] + [
        "【サンプル】この物件と画像は操作確認用の架空のものです。"]
    json.dump({**DEMO, "photos": [f"/demo/photo{i}.jpg" for i in range(1, 5)], "reading": reading},
              open(os.path.join(OUT, "sample.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ok", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
