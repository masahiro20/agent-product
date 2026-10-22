#!/usr/bin/env python3
"""日本の公的データ（キー不要）から敷地の概況を集めるサンプル関数群。

依存: Python 標準ライブラリ + numpy + Pillow（requests 不使用、urllib のみ）

CLI:
    python public_data.py "東京都世田谷区成城6丁目" --out /tmp/x.json
    python public_data.py "東京都世田谷区成城6丁目" --out /tmp/x.json --photo /tmp/x.jpg
    python public_data.py --latlon 35.6429,139.5995 --out /tmp/x.json --skip-zoning --skip-landprice

各関数は失敗時に例外を投げず {"error": "..."} を返す。
出典表記が必要なデータは返り値に "attribution" を含める。
データ源・URL・凡例の詳細は ../references/public_data_sources.md を参照。
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import numpy as np
from PIL import Image

UA = "site-photo-report/0.1 (+public data sampler)"
CACHE_DIR = os.environ.get("SITE_DATA_CACHE", os.path.expanduser("~/.cache/site_public_data"))

ATTR_GSI = "出典：国土地理院（地理院タイル・地理院API）"
ATTR_DEM = "出典：国土地理院 標高タイル（基盤地図情報 数値標高モデル）"
ATTR_PHOTO = "出典：国土地理院 シームレス空中写真（地理院タイル）"
ATTR_HAZARD = ("出典：ハザードマップポータルサイト（国土交通省・国土地理院）。"
               "洪水・高潮・津波・内水は国土交通省各地方整備局・都道府県・市町村、"
               "土砂災害警戒区域は国土数値情報（土砂災害警戒区域）を国土地理院が加工")
ATTR_JSHIS = "出典：防災科学技術研究所 J-SHIS（地震ハザードステーション）"
ATTR_FGD = "出典：国土地理院 基盤地図情報（ベクトルタイル experimental_fgd）"
ATTR_OSM = "© OpenStreetMap contributors (ODbL)"
ATTR_TOSHI = "出典：国土交通省 都市計画決定GISデータ（参考情報。建築確認・重説には使えない）"
ATTR_KSJ_PRICE = "出典：国土数値情報（地価公示データ L01／都道府県地価調査データ L02）国土交通省"

# --------------------------------------------------------------------------- 共通

class _NotFound(Exception):
    pass


def _get(url: str, timeout: float = 30, data: bytes | None = None, retries: int = 1) -> bytes:
    """GET（data 指定時 POST）。404 は _NotFound、その他はそのまま例外。"""
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise _NotFound(url)
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        if i < retries:
            time.sleep(1.0)
    raise last  # type: ignore[misc]


def _get_json(url: str, timeout: float = 30):
    return json.loads(_get(url, timeout).decode("utf-8-sig"))


def _cached_download(url: str, name: str, timeout: float = 300) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        data = _get(url, timeout=timeout)
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    return path


def _lonlat_to_tile_px(lat: float, lon: float, z: int):
    """WebMercator のタイル座標（小数）。int() でタイル番号、小数部*256 でタイル内画素。"""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _tile_px_to_lonlat(x: float, y: float, z: int):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def _offset_latlon(lat: float, lon: float, dx_m: float, dy_m: float):
    R = 6378137.0
    return (lat + math.degrees(dy_m / R),
            lon + math.degrees(dx_m / (R * math.cos(math.radians(lat)))))


def _local_xy(lat0: float, lon0: float, lat: float, lon: float):
    R = 6378137.0
    return (math.radians(lon - lon0) * R * math.cos(math.radians(lat0)),
            math.radians(lat - lat0) * R)


def _point_in_ring(x: float, y: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_geom(lon: float, lat: float, geom) -> bool:
    if not geom:
        return False
    t = geom.get("type")
    polys = [geom["coordinates"]] if t == "Polygon" else geom["coordinates"] if t == "MultiPolygon" else []
    for poly in polys:
        if poly and _point_in_ring(lon, lat, poly[0]) and not any(_point_in_ring(lon, lat, h) for h in poly[1:]):
            return True
    return False


def _features_at(fc, lat: float, lon: float):
    return [f for f in fc.get("features", []) if _point_in_geom(lon, lat, f.get("geometry"))]


# --------------------------------------------------------------------------- 住所

def geocode(address: str):
    """住所→(lat, lon, title)。失敗時 {"error": ...}。国土地理院 住所検索API（キー不要）。"""
    try:
        url = "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(address)
        res = _get_json(url)
        if not res:
            return {"error": f"住所が見つからない: {address}"}
        f = res[0]
        lon, lat = f["geometry"]["coordinates"]
        return (float(lat), float(lon), f["properties"].get("title", ""))
    except Exception as e:  # noqa: BLE001
        return {"error": f"geocode失敗: {e}"}


_MUNI = None


def _muni_table():
    global _MUNI
    if _MUNI is None:
        js = _get("https://maps.gsi.go.jp/js/muni.js").decode("utf-8", "ignore")
        _MUNI = {}
        for code, val in re.findall(r'MUNI_ARRAY\["(\d+)"\]\s*=\s*\'([^\']*)\'', js):
            p = val.split(",")
            if len(p) >= 4:
                _MUNI[code.zfill(5)] = {"pref_code": p[0].zfill(2), "pref": p[1], "muni": p[3]}
    return _MUNI


def reverse_geocode(lat: float, lon: float) -> dict:
    """緯度経度→住所（町丁目まで）。国土地理院 逆ジオコーダ + muni.js（市区町村名）。"""
    try:
        res = _get_json(f"https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat={lat}&lon={lon}")
        r = res.get("results") or {}
        if not r:
            return {"error": "逆ジオコーダの結果なし（海上・国外など）"}
        code = str(r.get("muniCd", "")).zfill(5)
        out = {"muniCd": code, "lv01Nm": r.get("lv01Nm", "")}
        try:
            m = _muni_table().get(code)
            if m:
                out.update(m)
                out["address"] = f'{m["pref"]}{m["muni"]}{out["lv01Nm"] if out["lv01Nm"] != "－" else ""}'
        except Exception as e:  # noqa: BLE001
            out["muni_table_error"] = str(e)
        out["attribution"] = ATTR_GSI
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"reverse_geocode失敗: {e}"}


# --------------------------------------------------------------------------- 標高

# (タイルID, ズーム, 説明)。dem1a は整備域のみ、dem5a/5b/5c は整備域で異なる、dem_png(=DEM10B) は全国。
DEM_SOURCES = [
    ("dem1a_png", 17, "DEM1A（1mメッシュ・航空レーザ）"),
    ("dem5a_png", 15, "DEM5A（5mメッシュ・航空レーザ）"),
    ("dem5b_png", 15, "DEM5B（5mメッシュ・写真測量）"),
    ("dem5c_png", 15, "DEM5C（5mメッシュ・写真測量）"),
    ("dem_png", 14, "DEM10B（10mメッシュ）"),
]


def _decode_dem_png(data: bytes) -> np.ndarray:
    """標高PNGタイル → 256x256 float(m)。x=R*2^16+G*2^8+B; x<2^23: h=x*0.01, x>2^23: h=(x-2^24)*0.01, x=2^23: 無効(NaN)。"""
    a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(np.int64)
    x = (a[..., 0] << 16) + (a[..., 1] << 8) + a[..., 2]
    h = np.where(x < 2 ** 23, x, x - 2 ** 24).astype(np.float64) * 0.01
    h[x == 2 ** 23] = np.nan
    return h


def elevation_grid(lat: float, lon: float, half_size_m: float = 50, step_m: float = 2) -> dict:
    """敷地中心の (2*half)m 四方を step_m 間隔で標高取得。DEMタイルを数枚落として画素を読む。
    各点で DEM1A→DEM5A→5B→5C→DEM10B の順にフォールバック。取れない点は None。
    返り値: xs(東向きm), ys(北向きm), z[iy][ix], source(点数の内訳), stats"""
    try:
        cache: dict = {}

        def tile(tid, z, tx, ty):
            k = (tid, z, tx, ty)
            if k not in cache:
                try:
                    cache[k] = _decode_dem_png(_get(f"https://cyberjapandata.gsi.go.jp/xyz/{tid}/{z}/{tx}/{ty}.png"))
                except _NotFound:
                    cache[k] = None
            return cache[k]

        nstep = int(round(half_size_m / step_m))
        offs = [i * step_m for i in range(-nstep, nstep + 1)]
        xs, ys = offs, offs[::-1]  # ys は北が上（行0=北端）
        grid = []
        counts: dict = {}
        for dy in ys:
            row = []
            for dx in xs:
                plat, plon = _offset_latlon(lat, lon, dx, dy)
                val, src = None, None
                for tid, z, desc in DEM_SOURCES:
                    fx, fy = _lonlat_to_tile_px(plat, plon, z)
                    t = tile(tid, z, int(fx), int(fy))
                    if t is None:
                        continue
                    v = t[min(255, int((fy % 1) * 256)), min(255, int((fx % 1) * 256))]
                    if not np.isnan(v):
                        val, src = round(float(v), 2), desc
                        break
                if src:
                    counts[src] = counts.get(src, 0) + 1
                row.append(val)
            grid.append(row)
        flat = [v for r in grid for v in r if v is not None]
        if not flat:
            return {"error": "標高タイルが取得できない（範囲外・通信エラー）"}
        c = grid[nstep][nstep]
        return {
            "xs": xs, "ys": ys, "z": grid,
            "source": counts,
            "stats": {"min": min(flat), "max": max(flat), "range": round(max(flat) - min(flat), 2),
                      "center": c, "n_points": len(flat), "n_missing": sum(len(r) for r in grid) - len(flat)},
            "tiles_fetched": sum(1 for v in cache.values() if v is not None),
            "note": "画素の最近傍値。DEM1A画素≒1m、DEM5A≒5m（z15で約4.8m/px）、DEM10B≒10m。建物・植生を除いた地表面標高。",
            "attribution": ATTR_DEM,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"elevation_grid失敗: {e}"}


# --------------------------------------------------------------------------- ハザード

_DEPTH_FLOOD = {(247, 245, 169): "0.5m未満", (255, 216, 192): "0.5〜3m", (255, 183, 183): "3〜5m",
                (255, 145, 145): "5〜10m", (242, 133, 201): "10〜20m", (220, 122, 220): "20m以上",
                (248, 225, 166): "0.5〜1m", (255, 255, 179): "0.3m未満"}
_DEPTH_TSUNAMI = {(255, 255, 179): "0.3m未満", (247, 245, 169): "0.3〜0.5m", (248, 225, 166): "0.5〜1m",
                  (255, 216, 192): "1〜3m", (255, 183, 183): "3〜5m", (255, 145, 145): "5〜10m",
                  (242, 133, 201): "10〜20m", (220, 122, 220): "20m以上"}
_DEPTH_NAISUI = {(255, 255, 179): "0.1〜0.3m", (247, 245, 169): "0.1〜0.5m", (248, 225, 166): "0.5〜1m",
                 (255, 216, 192): "0.5〜3m", (255, 183, 183): "3〜5m", (255, 145, 145): "5〜10m",
                 (242, 133, 201): "10〜20m", (220, 122, 220): "20m以上"}
_KEIZOKU = {(160, 210, 255): "12時間未満", (0, 65, 255): "12時間〜1日未満", (250, 245, 0): "1日〜3日未満",
            (255, 153, 0): "3日〜1週間未満", (255, 40, 0): "1週間〜2週間未満", (180, 0, 104): "2週間以上",
            (96, 0, 96): "4週間以上"}
_DOSEKI = {(165, 0, 33): "特別警戒区域（指定済）", (183, 51, 77): "特別警戒区域（指定予定）",
           (230, 200, 50): "警戒区域（指定済）", (235, 211, 91): "警戒区域（指定予定）"}
_KYUKEI = {(250, 40, 0): "特別警戒区域（指定済）", (251, 83, 51): "特別警戒区域（指定予定）",
           (250, 230, 0): "警戒区域（指定済）", (251, 235, 51): "警戒区域（指定予定）"}
_JISUBERI = {(180, 0, 40): "特別警戒区域（指定済）", (195, 51, 83): "特別警戒区域（指定予定）",
             (255, 153, 0): "警戒区域（指定済）", (255, 173, 51): "警戒区域（指定予定）"}
_MORIDO = {(155, 255, 155): "谷埋め型", (155, 155, 255): "腹付け型", (255, 155, 155): "区分していない"}

# (key, 名称, レイヤーディレクトリ, 取得ズーム, 色→区分)
HAZARD_LAYERS = [
    ("flood_l2", "洪水浸水想定区域（想定最大規模）", "01_flood_l2_shinsuishin_data", 17, _DEPTH_FLOOD),
    ("flood_l1", "洪水浸水想定区域（計画規模）", "01_flood_l1_shinsuishin_newlegend_data", 17, _DEPTH_FLOOD),
    ("flood_keizoku", "浸水継続時間（想定最大規模）", "01_flood_l2_keizoku_data", 17, _KEIZOKU),
    ("kaoku_hanran", "家屋倒壊等氾濫想定区域（氾濫流）", "01_flood_l2_kaokutoukai_hanran_data", 17, None),
    ("kaoku_kagan", "家屋倒壊等氾濫想定区域（河岸侵食）", "01_flood_l2_kaokutoukai_kagan_data", 17, None),
    ("naisui", "雨水出水（内水）浸水想定区域", "02_naisui_data", 17, _DEPTH_NAISUI),
    ("takashio", "高潮浸水想定区域", "03_hightide_l2_shinsuishin_data", 17, _DEPTH_TSUNAMI),
    ("tsunami", "津波浸水想定", "04_tsunami_newlegend_data", 17, _DEPTH_TSUNAMI),
    ("dosha_dosekiryu", "土砂災害警戒区域（土石流）", "05_dosekiryukeikaikuiki", 17, _DOSEKI),
    ("dosha_kyukeisha", "土砂災害警戒区域（急傾斜地の崩壊）", "05_kyukeishakeikaikuiki", 17, _KYUKEI),
    ("dosha_jisuberi", "土砂災害警戒区域（地すべり）", "05_jisuberikeikaikuiki", 17, _JISUBERI),
    ("tameike", "ため池決壊による浸水想定区域", "07_tameike", 17, None),
    ("daikibo_morido", "大規模盛土造成地", "09_daikibomorido", 16, _MORIDO),
]


def _classify(rgba, table):
    r, g, b, a = rgba
    if a < 128:
        return None
    if table is None:
        return "該当"
    best, bd = None, 1e9
    for (cr, cg, cb), name in table.items():
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < bd:
            best, bd = name, d
    return best if bd <= 30 ** 2 else f"該当（凡例外の色 rgb{(r, g, b)}）"


def hazard_at(lat: float, lon: float, include_jshis: bool = True) -> dict:
    """重ねるハザードマップのラスタタイルを1枚ずつ取り、座標の画素色から区分を読む。
    タイル 404 / 透明 = 「区域外（またはその地域で未整備）」。通信失敗した層は errors に入れる。"""
    try:
        out: dict = {"layers": {}, "errors": {}}
        for key, name, layer, z, table in HAZARD_LAYERS:
            fx, fy = _lonlat_to_tile_px(lat, lon, z)
            url = f"https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{int(fx)}/{int(fy)}.png"
            try:
                im = Image.open(io.BytesIO(_get(url, timeout=20))).convert("RGBA")
                px = im.getpixel((min(255, int((fx % 1) * 256)), min(255, int((fy % 1) * 256))))
                cls = _classify(px, table)
                out["layers"][key] = {"name": name, "class": cls or "区域外", "in_area": cls is not None,
                                      "rgba": list(px)}
            except _NotFound:
                out["layers"][key] = {"name": name, "class": "区域外（タイルなし）", "in_area": False}
            except Exception as e:  # noqa: BLE001
                out["errors"][key] = str(e)
        if include_jshis:
            try:
                # attr を複数指定すると 400 になるため、attr なし（全属性）で取得して必要分を拾う
                d = _get_json("https://www.j-shis.bosai.go.jp/map/api/pshm/Y2024/AVR/TTL_MTTL/meshinfo.geojson"
                              f"?position={lon},{lat}&epsg=4326")
                p = d["features"][0]["properties"]
                out["jshis_quake_prob_30y"] = {
                    "meshcode": p.get("meshcode"),
                    "震度6弱以上_30年確率": float(p["T30_I60_PS"]) if p.get("T30_I60_PS") else None,
                    "震度5強以上_30年確率": float(p["T30_I55_PS"]) if p.get("T30_I55_PS") else None,
                    "震度5弱以上_30年確率": float(p["T30_I50_PS"]) if p.get("T30_I50_PS") else None,
                    "model": "J-SHIS 確率論的地震動予測地図 Y2024 平均ケース 全地震",
                    "attribution": ATTR_JSHIS}
            except Exception as e:  # noqa: BLE001
                out["errors"]["jshis"] = str(e)
        out["note"] = ("画素1点の判定。境界付近は周辺も確認すること。404/透明は区域外または未整備"
                       "（その地域の想定が公表されていない場合もある）。最新は各自治体のハザードマップで確認。")
        out["attribution"] = ATTR_HAZARD
        if not out["layers"] and out["errors"]:
            return {"error": "ハザードタイルを1つも取得できない", "detail": out["errors"]}
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"hazard_at失敗: {e}"}


# --------------------------------------------------------------------------- 地形分類

_LF1 = {"10101":"山地","11201":"山地","11202":"山地","11203":"山地","11204":"山地","1010101":"山地","10202":"崖･段丘崖","10204":"崖･段丘崖","2010201":"崖･段丘崖","10205":"地すべり","10206":"地すべり","10301":"台地･段丘","10302":"台地･段丘","10303":"台地･段丘","10304":"台地･段丘","10308":"台地･段丘","10314":"台地･段丘","10305":"台地･段丘","10508":"台地･段丘","2010101":"台地･段丘","10306":"台地･段丘","10307":"台地･段丘","10310":"台地･段丘","10312":"台地･段丘","10401":"山麓堆積地形","10402":"山麓堆積地形","10403":"山麓堆積地形","10404":"山麓堆積地形","10406":"山麓堆積地形","10407":"山麓堆積地形","3010101":"山麓堆積地形","10501":"扇状地","10502":"扇状地","3020101":"扇状地","10503":"自然堤防","3040101":"自然堤防","10506":"天井川","10507":"天井川","10801":"天井川","10504":"砂州・砂丘","10505":"砂州・砂丘","10512":"砂州・砂丘","3050101":"砂州・砂丘","10601":"凹地・浅い谷","2010301":"凹地・浅い谷","3030101":"氾濫平野","10701":"氾濫平野","10702":"氾濫平野","10705":"氾濫平野","10703":"後背低地･湿地","10804":"後背低地･湿地","3030201":"後背低地･湿地","10704":"旧河道","3040201":"旧河道","3040202":"旧河道","3040301":"落堀","10802":"河川敷･浜","10803":"河川敷･浜","10807":"河川敷･浜","10808":"河川敷･浜","10805":"水部","10806":"水部","10901":"水部","10903":"水部","5010201":"水部","10904":"旧水部","5010301":"旧水部"}  # noqa: E501
_LF2 = {"11001":"切土地","11003":"切土地","11009":"切土地","11011":"切土地","4010301":"切土地","11002":"農耕平坦化地","11005":"高い盛土地","4010201":"高い盛土地","11008":"干拓地","4010101":"干拓地","11004":"盛土地･埋立地","11006":"盛土地･埋立地","11007":"盛土地･埋立地","11014":"盛土地･埋立地","11010":"改変工事中"}  # noqa: E501
_TOCHIBUNRUI = {"10101":"山地・丘陵","10201":"火山斜面","10202":"火山麓扇状地","10301":"崖錐・崩壊地・地すべり地","10302":"土石流地","10303":"地形混在（集動地形）","10401":"地形混在（山地・丘陵）","20101":"段丘","20102":"台地上の浅い谷","20201":"段丘崖・段丘斜面","30101":"扇状地","30201":"谷底平野・氾濫平野","30202":"海岸平野・三角州・砂州間低地","30203":"地形混在（低地の一般面）","30301":"自然堤防","30302":"砂丘","30303":"砂州･浜堤","30304":"地形混在（低地の微高地）","30401":"後背湿地","30402":"旧河道","30501":"河原･河川敷","30502":"干潟","30503":"浜・磯・隠顕岩・岩礁","30601":"天井川","30701":"地形混在（低地）","40101":"切土地","40102":"盛土地","40103":"埋立地","40104":"干拓地","40105":"地形混在（人工改変地）","50101":"水部","60101":"崖","70101":"地形混在"}  # noqa: E501

LANDFORM_LAYERS = [
    # key, 名称, URLテンプレート, ズーム候補, コード表
    ("natural", "地形分類（自然地形）", "https://cyberjapandata.gsi.go.jp/xyz/experimental_landformclassification1/{z}/{x}/{y}.geojson", (16, 15, 14), _LF1),
    ("artificial", "地形分類（人工地形）", "https://cyberjapandata.gsi.go.jp/xyz/experimental_landformclassification2/{z}/{x}/{y}.geojson", (16, 15, 14), _LF2),
    ("tochibunrui_50000", "土地分類基本調査（地形分類 1/5万）", "https://disaportal.gsi.go.jp/data/vector/tochibunrui_kihon_20210303/{z}/{x}/{y}.geojson", (15,), _TOCHIBUNRUI),
]


def landform_at(lat: float, lon: float) -> dict:
    """地理院の地形分類ベクトルタイル（GeoJSON）で座標を含むポリゴンのコードを引く + J-SHIS 表層地盤。"""
    try:
        out: dict = {"errors": {}}
        for key, name, tmpl, zooms, table in LANDFORM_LAYERS:
            for z in zooms:
                fx, fy = _lonlat_to_tile_px(lat, lon, z)
                try:
                    fc = _get_json(tmpl.format(z=z, x=int(fx), y=int(fy)))
                except _NotFound:
                    continue
                except Exception as e:  # noqa: BLE001
                    out["errors"][key] = str(e)
                    break
                hits = _features_at(fc, lat, lon)
                if hits:
                    code = str(hits[0]["properties"].get("code"))
                    out[key] = {"name": name, "code": code, "class": table.get(code, "不明コード"), "zoom": z}
                else:
                    out[key] = {"name": name, "class": "該当ポリゴンなし（未整備 or 対象外）", "zoom": z}
                break
            else:
                out.setdefault(key, {"name": name, "class": "タイルなし（未整備）"})
        try:
            d = _get_json("https://www.j-shis.bosai.go.jp/map/api/sstrct/V3/meshinfo.geojson"
                          f"?position={lon},{lat}&epsg=4326")
            p = d["features"][0]["properties"]
            out["jshis_surface"] = {"微地形区分": p.get("JNAME"), "AVS30_m_s": float(p["AVS"]) if p.get("AVS") else None,
                                    "地盤増幅率": float(p["ARV"]) if p.get("ARV") else None, "meshcode": p.get("meshcode"),
                                    "note": "250mメッシュ代表値", "attribution": ATTR_JSHIS}
        except Exception as e:  # noqa: BLE001
            out["errors"]["jshis_surface"] = str(e)
        if not any(k in out for k in ("natural", "artificial", "tochibunrui_50000", "jshis_surface")):
            return {"error": "地形分類を取得できない", "detail": out["errors"]}
        out["note"] = "地形分類は縮尺1/2.5万〜1/5万相当の概略。人工地形（盛土等）は整備地域のみ。"
        out["attribution"] = ATTR_GSI + "（地形分類）／" + ATTR_JSHIS
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"landform_at失敗: {e}"}


# --------------------------------------------------------------------------- 航空写真

def aerial_photo(lat: float, lon: float, zoom: int = 19, size_px: int = 768, out_path: str = "aerial.jpg") -> dict:
    """シームレス空中写真のタイルを結合し、敷地中心で size_px 四方に切り出して保存。
    seamlessphoto は z18 が最大（z19/20 は 404）。zoom>18 を指定した場合は z18 を拡大して同じ縮尺にする。"""
    try:
        fetch_z = zoom
        tmpl = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
        while fetch_z >= 14:
            fx, fy = _lonlat_to_tile_px(lat, lon, fetch_z)
            try:
                _get(tmpl.format(z=fetch_z, x=int(fx), y=int(fy)), timeout=20)
                break
            except _NotFound:
                fetch_z -= 1
        else:
            return {"error": "空中写真タイルが取得できない"}
        scale = 2 ** (zoom - fetch_z)
        need = size_px / scale  # fetch_z での必要ピクセル幅
        cx, cy = (v * 256 for v in _lonlat_to_tile_px(lat, lon, fetch_z))
        x0, y0, x1, y1 = cx - need / 2, cy - need / 2, cx + need / 2, cy + need / 2
        tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
        mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (255, 255, 255))
        missing = 0
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                try:
                    t = Image.open(io.BytesIO(_get(tmpl.format(z=fetch_z, x=tx, y=ty), timeout=20))).convert("RGB")
                    mosaic.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
                except _NotFound:
                    missing += 1
        crop = mosaic.crop((round(x0 - tx0 * 256), round(y0 - ty0 * 256),
                            round(x0 - tx0 * 256 + need), round(y0 - ty0 * 256 + need)))
        if crop.size != (size_px, size_px):
            crop = crop.resize((size_px, size_px), Image.LANCZOS)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        crop.save(out_path, quality=92)
        mpp = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
        return {"path": os.path.abspath(out_path), "zoom_requested": zoom, "zoom_fetched": fetch_z,
                "upscaled": scale > 1, "size_px": size_px, "m_per_px": round(mpp, 4),
                "extent_m": round(mpp * size_px, 1), "tiles": (tx1 - tx0 + 1) * (ty1 - ty0 + 1),
                "missing_tiles": missing, "center": [lat, lon],
                "note": "撮影年は地域で異なる（地理院地図で確認）。オルソ画像だが建物の倒れ込みあり。",
                "attribution": ATTR_PHOTO}
    except Exception as e:  # noqa: BLE001
        return {"error": f"aerial_photo失敗: {e}"}


# --------------------------------------------------------------------------- 建物・道路

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def _ring_area_m2(lat0, lon0, ring):
    pts = [_local_xy(lat0, lon0, la, lo) for la, lo in ring]
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def _fgd_buildings(lat: float, lon: float, radius_m: float) -> dict:
    """フォールバック: 地理院ベクトルタイル experimental_fgd（z18 GeoJSON）の建築物外周線 BldL / 道路縁 RdEdg。
    タイル境界で切れた線は fid ごとに端点連結して閉じたものを建物ポリゴンとする。"""
    z = 18
    fx, fy = _lonlat_to_tile_px(lat, lon, z)
    span = int(math.ceil(radius_m / (156543.03392 * math.cos(math.radians(lat)) / 2 ** z * 256))) + 0
    segs: dict = {}
    roads = []
    for tx in range(int(fx) - span, int(fx) + span + 1):
        for ty in range(int(fy) - span, int(fy) + span + 1):
            try:
                fc = _get_json(f"https://cyberjapandata.gsi.go.jp/xyz/experimental_fgd/{z}/{tx}/{ty}.geojson")
            except _NotFound:
                continue
            for f in fc.get("features", []):
                p, g = f["properties"], f["geometry"]
                if g["type"] != "LineString":
                    continue
                if p.get("class") == "BldL":
                    segs.setdefault(p.get("fid"), []).append([(c[1], c[0]) for c in g["coordinates"]])
                elif p.get("class") == "RdEdg":
                    roads.append({"type": p.get("type"), "line": [[c[1], c[0]] for c in g["coordinates"]]})
    buildings = []
    for fid, parts in segs.items():
        chain = parts.pop(0)
        changed = True
        while parts and changed:
            changed = False
            for i, s in enumerate(parts):
                if _close(chain[-1], s[0]):
                    chain += s[1:]
                elif _close(chain[-1], s[-1]):
                    chain += s[::-1][1:]
                elif _close(chain[0], s[-1]):
                    chain = s[:-1] + chain
                elif _close(chain[0], s[0]):
                    chain = s[::-1][:-1] + chain
                else:
                    continue
                parts.pop(i)
                changed = True
                break
        closed = _close(chain[0], chain[-1]) and len(chain) >= 4
        cx = sum(p[0] for p in chain) / len(chain)
        cy = sum(p[1] for p in chain) / len(chain)
        dist = math.hypot(*_local_xy(lat, lon, cx, cy))
        if dist > radius_m + 30:
            continue
        b = {"id": fid, "polygon": [list(p) for p in chain], "closed": closed,
             "centroid_dist_m": round(dist, 1)}
        if closed:
            b["area_m2"] = round(_ring_area_m2(lat, lon, chain), 1)
            b["contains_point"] = _point_in_ring(lon, lat, [(q[1], q[0]) for q in chain])
        buildings.append(b)
    buildings.sort(key=lambda b: b["centroid_dist_m"])
    roads = [r for r in roads if any(math.hypot(*_local_xy(lat, lon, a, o)) <= radius_m for a, o in r["line"])]
    return {"source": "GSI experimental_fgd (基盤地図情報)", "buildings": buildings, "roads": roads,
            "attribution": ATTR_FGD}


def _close(a, b, tol=1e-7):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def nearby_buildings_osm(lat: float, lon: float, radius_m: float = 40, fallback_gsi: bool = True,
                         timeout: float = 15) -> dict:
    """周辺の建物ポリゴン・道路を取得。OSM Overpass を順に試し、全滅なら地理院 基盤地図情報にフォールバック。
    返り値: {"source", "buildings":[{"polygon":[[lat,lon],...], "area_m2", ...}], "roads":[...], "attribution"}"""
    q = (f'[out:json][timeout:{int(timeout)}];(way["building"](around:{radius_m},{lat},{lon});'
         f'way["highway"](around:{radius_m},{lat},{lon}););out geom tags;')
    errs = {}
    for ep in OVERPASS_ENDPOINTS:
        try:
            d = json.loads(_get(ep, timeout=timeout + 5, data=urllib.parse.urlencode({"data": q}).encode(), retries=0))
            buildings, roads = [], []
            for e in d.get("elements", []):
                geom = [[g["lat"], g["lon"]] for g in e.get("geometry", [])]
                tags = e.get("tags", {})
                if "building" in tags and len(geom) >= 4:
                    buildings.append({"id": e["id"], "polygon": geom, "tags": tags, "closed": geom[0] == geom[-1],
                                      "area_m2": round(_ring_area_m2(lat, lon, geom), 1),
                                      "contains_point": _point_in_ring(lon, lat, [(p[1], p[0]) for p in geom])})
                elif "highway" in tags:
                    roads.append({"id": e["id"], "highway": tags.get("highway"), "name": tags.get("name"),
                                  "width": tags.get("width"), "line": geom})
            return {"source": f"OSM Overpass ({ep})", "buildings": buildings, "roads": roads,
                    "attribution": ATTR_OSM}
        except Exception as e:  # noqa: BLE001
            errs[ep] = str(e)[:200]
    if fallback_gsi:
        try:
            r = _fgd_buildings(lat, lon, radius_m)
            r["overpass_errors"] = errs
            return r
        except Exception as e:  # noqa: BLE001
            errs["gsi_fgd"] = str(e)
    return {"error": "Overpass／地理院とも取得失敗", "detail": errs}


# --------------------------------------------------------------------------- 用途地域（キー不要・要DL）

_TOSHI_PAGE = "https://www.mlit.go.jp/toshi/tosiko/toshi_tosiko_tk_000182.html"
# 都市計画決定GISデータのファイル種別（GeoJSON ファイル名の接尾辞）
_TOSHI_LAYERS = {"youto": "用途地域", "bouka": "防火・準防火地域", "koudoti": "高度地区", "senbiki": "区域区分（線引き）",
                 "tokei": "都市計画区域", "chikukei": "地区計画", "fuuchichiku": "風致地区", "koudori": "高度利用地区",
                 "tkbt": "特別用途地区", "tochiku": "土地区画整理事業", "ryokukachiiki": "緑化地域",
                 "tokuteibou": "特定防災街区整備地区", "tokuryoku": "特別緑地保全地区"}


def _zipname(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp932")
    except Exception:  # noqa: BLE001
        return info.filename


def zoning_at(lat: float, lon: float) -> dict:
    """国交省「都市計画決定GISデータ」（都道府県別 GeoJSON zip、キー不要、数十MB）を初回DL・キャッシュし、
    座標を含む用途地域（建ぺい率BCR・容積率FAR）・防火地域・高度地区などを返す。"""
    try:
        rg = reverse_geocode(lat, lon)
        if "error" in rg:
            return rg
        pref, muni = rg.get("pref"), rg["muniCd"]
        html = _get(_TOSHI_PAGE).decode("utf-8", "ignore")
        link = None
        for row in re.findall(r"<tr.*?</tr>", html, re.S):
            txt = re.sub(r"<[^>]+>", " ", row).split()
            links = re.findall(r'href="([^"]+\.zip)"', row)
            if txt and txt[0] == pref and len(links) >= 3:
                link = urllib.parse.urljoin(_TOSHI_PAGE, links[2])  # 列順: shp, CityGML, GeoJSON
                break
        if not link:
            return {"error": f"都市計画決定GISデータのDLリンクが見つからない: {pref}"}
        path = _cached_download(link, "toshi_" + os.path.basename(link))
        z = zipfile.ZipFile(path)
        names = {(_zipname(i)): i for i in z.infolist() if not i.is_dir() and _zipname(i).endswith(".geojson")}
        # 市区町村コードのファイルを優先。政令市など合わない場合は同種ファイルを全部見る
        cands = [n for n in names if os.path.basename(n).startswith(muni + "_")]
        if not cands:
            cands = list(names)
        out: dict = {"muniCd": muni, "pref": pref, "source_zip": link}
        for n in cands:
            base = os.path.basename(n)[:-8]
            kind = base.split("_", 1)[1] if "_" in base else base
            if kind not in _TOSHI_LAYERS:
                continue
            raw = z.read(names[n])
            try:
                fc = json.loads(raw.decode("utf-8-sig"))
            except UnicodeDecodeError:
                fc = json.loads(raw.decode("cp932"))
            hits = _features_at(fc, lat, lon)
            if hits:
                out.setdefault(kind, [])
                for h in hits:
                    p = {k: v for k, v in h["properties"].items() if v not in (None, "")}
                    p["_layer"] = _TOSHI_LAYERS[kind]
                    out[kind].append(p)
        y = (out.get("youto") or [{}])[0]
        out["summary"] = {"用途地域": y.get("YoutoName"), "建ぺい率%": y.get("BCR"), "容積率%": y.get("FAR"),
                          "防火": [b.get("AreaType") for b in out.get("bouka", [])] or ["指定なし（データ上）"],
                          "高度地区": [k.get("DistType") for k in out.get("koudoti", [])] or None}
        out["note"] = ("参考情報（概ねの位置）。境界付近・最新の変更は自治体の都市計画図で必ず確認。"
                       "高度地区の種別（第1種等）や角地緩和は含まれないことがある。")
        out["attribution"] = ATTR_TOSHI
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"zoning_at失敗: {e}"}


# --------------------------------------------------------------------------- 地価（キー不要・要DL）

_ZONE_RE = re.compile(r"^(1低専|2低専|1中専|2中専|1住居|2住居|準住居|田園住|近商|商業|準工|工業|工専|_|調区|.*地域)$")


def land_price_nearby(lat: float, lon: float, n: int = 5, year: int | None = None) -> dict:
    """国土数値情報 地価公示(L01)・都道府県地価調査(L02) の都道府県別 zip（GeoJSON入り、数MB）から近い地点を返す。"""
    try:
        rg = reverse_geocode(lat, lon)
        if "error" in rg:
            return rg
        pc = rg.get("pref_code") or rg["muniCd"][:2]
        cur = year or time.localtime().tm_year
        out: dict = {"pref_code": pc}
        spec = {"L01": ("地価公示", {"year": "L01_007", "price": "L01_008", "change": "L01_009", "addr": "L01_025",
                                   "area": "L01_027", "use": "L01_028", "surround": "L01_047", "station": "L01_048",
                                   "station_m": "L01_050", "zone": "L01_051", "fire": "L01_052", "bcr": "L01_057",
                                   "far": "L01_058"}),
                # L02 は令和8年(L02-26)版で属性が1つ増え、043以降が1つずれた。古い版は _L02_OLD を使う
                "L02": ("都道府県地価調査", {"year": "L02_005", "price": "L02_006", "change": "L02_007",
                                     "addr": "L02_022", "area": "L02_024", "use": "L02_025", "surround": "L02_044",
                                     "station": "L02_045", "station_m": "L02_046", "zone": "L02_047",
                                     "fire": "L02_048", "bcr": "L02_051", "far": "L02_052"})}
        _L02_OLD = {"surround": "L02_043", "station": "L02_044", "station_m": "L02_045", "zone": "L02_046",
                    "fire": "L02_047", "bcr": "L02_050", "far": "L02_051"}
        for code, (label, f) in spec.items():
            fc = None
            for y in range(cur, cur - 4, -1):
                yy = f"{y % 100:02d}"
                url = f"https://nlftp.mlit.go.jp/ksj/gml/data/{code}/{code}-{yy}/{code}-{yy}_{pc}_GML.zip"
                try:
                    path = _cached_download(url, f"{code}-{yy}_{pc}_GML.zip", timeout=120)
                except _NotFound:
                    continue
                zz = zipfile.ZipFile(path)
                gj = [i for i in zz.infolist() if i.filename.endswith(".geojson")]
                if gj:
                    fc = json.loads(zz.read(gj[0]).decode("utf-8-sig"))
                    out[code + "_dataset"] = f"{code}-{yy}"
                    if code == "L02" and int(yy) <= 25:
                        f = {**f, **_L02_OLD}
                    break
            if fc is None:
                out[code] = {"error": f"{label} データ取得失敗"}
                continue
            pts = []
            for ft in fc["features"]:
                lo, la = ft["geometry"]["coordinates"][:2]
                d = math.hypot(*_local_xy(lat, lon, la, lo))
                pts.append((d, ft["properties"]))
            pts.sort(key=lambda t: t[0])
            out[code] = [{"label": label, "dist_m": round(d, 0), **{k: p.get(v) for k, v in f.items()},
                          "price_unit": "円/m2"} for d, p in pts[:n]]
            if out[code] and not _ZONE_RE.match(str(out[code][0].get("zone"))):
                out[code + "_warning"] = "属性番号の対応がずれている可能性（データ定義書で確認）"
        out["note"] = "標準地・基準地の価格（円/m2）。実取引価格（不動産取引価格情報）は不動産情報ライブラリAPI（要キー）。"
        out["attribution"] = ATTR_KSJ_PRICE
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"land_price_nearby失敗: {e}"}


# --------------------------------------------------------------------------- CLI

def _main(argv=None):
    ap = argparse.ArgumentParser(description="住所から公的データ（キー不要）を集めて JSON 出力")
    ap.add_argument("address", nargs="?", help="住所（例: 東京都世田谷区成城6丁目）")
    ap.add_argument("--latlon", help="住所の代わりに 'lat,lon'")
    ap.add_argument("--out", default="site_public_data.json")
    ap.add_argument("--photo", help="航空写真の保存先（省略時 --out と同じ場所に *_aerial.jpg）")
    ap.add_argument("--half", type=float, default=50, help="標高グリッドの半幅 m")
    ap.add_argument("--step", type=float, default=2, help="標高グリッド間隔 m")
    ap.add_argument("--radius", type=float, default=40, help="建物取得半径 m")
    ap.add_argument("--skip-zoning", action="store_true", help="用途地域（数十MBのDL）を省略")
    ap.add_argument("--skip-landprice", action="store_true", help="地価（数MBのDL）を省略")
    a = ap.parse_args(argv)

    res: dict = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if a.latlon:
        lat, lon = (float(v) for v in a.latlon.split(","))
        res["geocode"] = {"lat": lat, "lon": lon, "title": None}
    elif a.address:
        g = geocode(a.address)
        if isinstance(g, dict):
            res["geocode"] = g
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 1
        lat, lon, title = g
        res["geocode"] = {"query": a.address, "lat": lat, "lon": lon, "title": title, "attribution": ATTR_GSI}
    else:
        ap.error("address か --latlon が必要")

    steps = [
        ("reverse_geocode", lambda: reverse_geocode(lat, lon)),
        ("elevation_grid", lambda: elevation_grid(lat, lon, a.half, a.step)),
        ("hazard", lambda: hazard_at(lat, lon)),
        ("landform", lambda: landform_at(lat, lon)),
        ("aerial_photo", lambda: aerial_photo(lat, lon, 19, 768,
                                              a.photo or os.path.splitext(a.out)[0] + "_aerial.jpg")),
        ("buildings", lambda: nearby_buildings_osm(lat, lon, a.radius)),
    ]
    if not a.skip_zoning:
        steps.append(("zoning", lambda: zoning_at(lat, lon)))
    if not a.skip_landprice:
        steps.append(("land_price", lambda: land_price_nearby(lat, lon)))
    for name, fn in steps:
        t = time.time()
        res[name] = fn()
        st = "ERR" if isinstance(res[name], dict) and "error" in res[name] else "ok"
        print(f"[{st}] {name} {time.time() - t:.1f}s", file=sys.stderr)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"saved: {os.path.abspath(a.out)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
