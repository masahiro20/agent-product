"""地図の建物外形（国土地理院 基盤地図情報）を住所の周りから拾い、航空写真に番号付きで描く。

AI は写真の建物がどの番号かを答え、1F の外形はこの外形を優先して読む（目分量より誤差が小さい）。
"""
import base64
import io
import math

from PIL import Image, ImageDraw, ImageFont

from .engine import public_data

RADIUS_M = 35.0
MAX_OUTLINES = 8
# 基盤地図情報の建物外形は航空写真の屋根から描かれ、軒の出・ポーチ・カーポートを含む。
# SUUMO の中古戸建てで1階床面積（登記・壁芯）が分かる5件では 1階床面積 ÷ 外形面積 = 0.68〜0.78（平均0.72）だった
FLOOR_RATIO = 0.72
FLOOR_RATIO_RANGE = (0.66, 0.80)
WALL_INSET_M = 0.6  # 外接長方形から壁の外形へ、片側あたりの縮め幅の目安


def _min_rect(pts):
    """最小面積の外接長方形 → (長辺, 短辺, 長辺の向き deg)。凸包の辺の向きを総当たり。"""
    best = None
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        a = math.atan2(y1 - y0, x1 - x0)
        c, s = math.cos(-a), math.sin(-a)
        xs = [x * c - y * s for x, y in pts]
        ys = [x * s + y * c for x, y in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if best is None or w * h < best[0]:
            best = (w * h, w, h, math.degrees(a))
    _, w, h, ang = best
    if h > w:
        w, h, ang = h, w, ang + 90
    return w, h, (ang + 180) % 180


def outlines(lat, lon, radius_m=RADIUS_M):
    """住所の代表点の周りの建物外形。[{no, area_m2, long_m, short_m, angle_deg, dist_m, contains_point, poly_m}]"""
    r = public_data._fgd_buildings(lat, lon, radius_m)
    out = []
    for b in r.get("buildings", []):
        if not b.get("closed") or not 15 <= (b.get("area_m2") or 0) <= 3000:
            continue
        poly = [public_data._local_xy(lat, lon, la, lo) for la, lo in b["polygon"]]
        if poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) < 3:
            continue
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        lw, sw, ang = _min_rect(poly)
        if sw < 2.5:  # 塀・通路・細長い庇は住宅の候補から外す
            continue
        out.append({"area_m2": b["area_m2"], "floor_est_m2": round(b["area_m2"] * FLOOR_RATIO, 1),
                    "wall_long_m": round(max(lw - 2 * WALL_INSET_M, 1), 2), "wall_short_m": round(max(sw - 2 * WALL_INSET_M, 1), 2),
                    "long_m": round(lw, 2), "short_m": round(sw, 2), "angle_deg": round(ang),
                    "dist_m": round(math.hypot(cx, cy), 1), "contains_point": bool(b.get("contains_point")),
                    "poly_m": [[round(x, 2), round(y, 2)] for x, y in poly]})
    # 代表点を含む建物を先頭に、あとは近い順
    out.sort(key=lambda o: (not o["contains_point"], o["dist_m"]))
    out = out[:MAX_OUTLINES]
    for i, o in enumerate(out, 1):
        o["no"] = i
    return {"outlines": out, "source": r.get("source"), "attribution": r.get("attribution")}


def draw_on_aerial(aerial_b64, lat, outs, zoom=19):
    """航空写真（中心＝代表点、北が上）に外形と番号を描いた JPEG の base64。"""
    im = Image.open(io.BytesIO(base64.b64decode(aerial_b64))).convert("RGB")
    mpp = 156543.03392 * math.cos(math.radians(lat)) / 2 ** zoom
    # 中央の約半分（≒95m四方）に寄せて拡大する（敷地と外形の番号を見やすく）
    W, H = im.size
    im = im.crop((W // 4, H // 4, W - W // 4, H - H // 4)).resize((W, H), Image.LANCZOS)
    mpp /= 2
    cx, cy = im.width / 2, im.height / 2
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:
        font = ImageFont.load_default()
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], outline=(0, 160, 255), width=3)  # 番号より先に描き、番号を隠さない
    for o in outs:
        pts = [(cx + x / mpp, cy - y / mpp) for x, y in o["poly_m"]]
        d.line(pts + [pts[0]], fill=(255, 215, 0), width=3)
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        d.rectangle([mx - 14, my - 14, mx + 14, my + 14], fill=(210, 40, 40))
        d.text((mx, my), str(o["no"]), fill=(255, 255, 255), font=font, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def describe(outs):
    """AI に渡す外形の一覧（文章）。"""
    if not outs:
        return "地図の建物外形: なし（取得できなかった）"
    lines = ["地図の建物外形（国土地理院 基盤地図情報。航空写真に黄線と赤い番号で描いた。青丸＝住所の代表点。代表点は数m〜数十mずれることがある）。",
             f"注意: この外形は屋根の外周（軒の出・玄関ポーチ・カーポート・下屋を含む）で、1階の床面積より大きい。実測との比較では 1階床面積 ≒ 外形面積×{FLOOR_RATIO}"
             f"（{FLOOR_RATIO_RANGE[0]}〜{FLOOR_RATIO_RANGE[1]}）、壁の外形 ≒ 外接長方形の各辺から {2 * WALL_INSET_M:.1f}m 前後短い。外形の面積をそのまま1階にしないこと:"]
    for o in outs:
        lines.append(f"  No.{o['no']}: 外形 約{o['area_m2']:.0f}㎡（1階床の目安 約{o['floor_est_m2']:.0f}㎡）、外接長方形 {o['long_m']:.1f}m×{o['short_m']:.1f}m"
                     f"（壁の外形の目安 {o['wall_long_m']:.1f}m×{o['wall_short_m']:.1f}m、長辺の向き 東から{o['angle_deg']}°）、"
                     f"代表点から{o['dist_m']:.0f}m" + ("、代表点を含む" if o["contains_point"] else ""))
    return "\n".join(lines)
