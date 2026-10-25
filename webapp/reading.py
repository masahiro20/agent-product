"""現地写真 → 読み取り結果（構造化JSON）。Claude に写真と航空写真を見せ、寸法・数量・高低差を推定させる。

出力は「読み取り結果（reading）」という平たい形にし、図面・見積用の site.json への変換は convert.py が行う。
"""
import json
import os

import anthropic

from .engine import load_data

MODEL = os.environ.get("SITE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("SITE_EFFORT", "medium")

ELEMENT_TYPES = ["window", "door", "railing", "slab", "post", "pipe", "stair", "stair_front",
                 "box", "block_wall", "fence", "tree", "canopy", "vent", "meter", "heater"]
WALL_PATTERNS = ["mortar", "siding_h", "siding_v", "board", "panel", "tile", "alc"]
FINISH_KEYS = ["屋根", "外壁", "軒天", "破風・鼻隠し", "雨樋", "サッシ", "基礎", "バルコニー・廊下", "外階段"]
ROOF_TYPES = ["gable_side", "gable_end", "hip_side", "shed", "flat"]
STRUCTURES = ["wood", "light_steel", "heavy_steel", "rc"]
LAYOUTS = ["1R", "1K", "1DK", "2DK", "3LDK", "house_4LDK"]
SIDES = ["N", "E", "S", "W", "unknown"]
ROOF_MATERIALS = ["kawara_dobuki", "kawara", "slate", "metal", "shingle", "flat", "unknown"]
FOUNDATIONS = ["nuno", "beta", "dokuritsu", "unknown"]

# 建物本体・手続きなど、外構として選ばせない単価キー
_NOT_EXTERIOR = {"interior_stripping", "scaffold_m2", "heavy_machine_transport", "guard_person_day", "road_use_permit",
                 "neighbor_greeting", "leftover_m3", "waste_disposal_mixed_m3", "recycling_notification",
                 "asbestos_report", "demolition_registration", "overhead_rate", "aircon_unit",
                 "grading_m2"}  # 整地は建物本体の単価に含む（二重計上を防ぐ）


def exterior_catalog():
    items = load_data("demolition_unit_prices.json")["items"]
    return {k: {"name": v.get("name", k), "unit": v.get("unit", "").replace("円/", "")}
            for k, v in items.items()
            if k not in _NOT_EXTERIOR and not k.startswith(("waste_", "recycle_", "appliance_"))}


def condition_catalog():
    cf = load_data("demolition_unit_prices.json").get("condition_factor", {})
    return {k: v.get("name", k) for k, v in cf.items() if isinstance(v, dict)}


# 出力の形（構造化出力のスキーマは大きすぎて API が受け付けないため、形はプロンプトで示し、受け取った後に normalize で点検・補完する）
TEMPLATE = """{
  "project_name": "物件名の案",
  "building": {
    "exists": true, "structure": "wood|light_steel|heavy_steel|rc", "use": "用途", "floors": 2, "built_year_est": 1980,
    "frontage_m": 14.5, "depth_m": 4.6, "eave_h": 5.8, "ridge_h": 6.7, "roof_overhang_m": 0.45, "roof_label": "切妻 4寸 カラー鉄板",
    "floor_levels": [0.45, 3.2],
    "floor_plans": [{"floor": 1, "w": 14.5, "d": 4.6, "area_m2": 66.7, "basis": "1Fの外形。L字・下屋・外廊下の扱いを書く"}, {"floor": 2, "w": 14.5, "d": 4.6, "area_m2": 66.7, "basis": "総2階"}],
    "roof_pitch_sun": 4, "roof_material": "kawara_dobuki|kawara|slate|metal|shingle|flat|unknown", "foundation_type": "nuno|beta|dokuritsu|unknown",
    "units_count": 8, "unit_layout": "1R|1K|1DK|2DK|3LDK|house_4LDK", "unit_area_m2": 16.6,
    "occupied_units": 0, "aircon_units": 4, "outdoor_leftover_m3": 1.0,
    "annexes": [{"name": "鉄骨外階段", "price_key": "steel_stair|carport|storage_shed|none", "qty": 1, "unit": "基", "basis": "写真2"}],
    "measure_basis": [{"item": "桁行", "value": "約14.5m", "basis": "根拠", "confidence": "高|中|低"}],
    "finishes": {"屋根": "カラー鉄板 瓦棒葺き", "外壁": "モルタル吹付", "軒天": "ケイカル板（推定）", "破風・鼻隠し": "鉄板巻き",
                 "雨樋": "塩ビ 半丸", "サッシ": "アルミ 単板ガラス", "基礎": "布基礎（推定）", "バルコニー・廊下": "RC床＋鉄骨手すり", "外階段": "鉄骨"},
    "faces": [{"name": "南立面図（道路側）", "width_m": 14.5, "roof_type": "gable_side|gable_end|hip_side|shed|flat",
               "wall_pattern": "mortar|siding_h|siding_v|board|panel|tile|alc",
               "elements": [{"type": "window|door|railing|slab|post|pipe|stair|stair_front|box|block_wall|fence|tree|canopy|vent|meter|heater",
                             "x": 1.0, "z": 0.45, "w": 1.69, "h": 1.8, "label": "", "courses": 0, "grille": false}]}]
  },
  "exterior": [{"key": "単価キー", "label": "CB塀 南側 H≈0.8 L≈15m", "qty": 12.0, "unit": "㎡", "basis": "写真3：4段", "x0": 0, "y0": 0, "x1": 0, "y1": 0}],
  "site": {
    "frontage_m": 19.5, "depth_m": 12.5, "road_side": "N|E|S|W|unknown", "road_width_m": 4.0, "road_name": "市道",
    "building_offset_left_m": 1.2, "building_setback_m": 3.0,
    "extra_footprints": [{"label": "外階段", "x": 15.8, "y": 3.0, "w": 1.0, "d": 3.0}],
    "level_points": [{"label": "敷地左手前", "x": 0.5, "y": 0.5, "dz_from_road_center_m": 0.4, "basis": "CB2段"}],
    "access": {"road_width_m": 4.0, "machine": "0.25㎥級（ミニ）まで進入可|0.45㎥級まで進入可|重機進入不可（手壊し）", "truck": "4t車可|2t車まで|軽トラックのみ",
               "neighbor_gap_m": 0.8, "carry_distance_m": 0, "notes": "電線・電柱、隣家の窓、通学路など搬出・近隣で気をつけること"}
  },
  "conditions": ["施工条件のキー"],
  "photos": [{"photo_index": 1, "caption": "南面（道路側）", "marks": [{"x0": 0.1, "y0": 0.3, "x1": 0.3, "y1": 0.5, "label": "掃出し窓 W≈1.69m", "basis": "寸法の基準"}]}],
  "summary": ["表紙に載せる要点"],
  "next_checks": ["次に確認すること"]
}"""


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default=0):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _pick(v, allowed, default):
    return v if v in allowed else default


def normalize(r):
    """AI の出力を点検し、欠けた項目を既定値で補い、型をそろえる（変換・作図が落ちないように）。"""
    r = r if isinstance(r, dict) else {}
    b = r.get("building") or {}
    out_b = {
        "exists": bool(b.get("exists", True)),
        "structure": _pick(b.get("structure"), STRUCTURES, "wood"),
        "use": str(b.get("use") or ""),
        "floors": max(1, _int(b.get("floors"), 2)),
        "built_year_est": _int(b.get("built_year_est"), 1985) or 1985,
        "frontage_m": max(1.0, _num(b.get("frontage_m"), 9.1)),
        "depth_m": max(1.0, _num(b.get("depth_m"), 7.3)),
        "eave_h": max(2.0, _num(b.get("eave_h"), 5.8)),
        "roof_overhang_m": _num(b.get("roof_overhang_m"), 0.45),
        "roof_label": str(b.get("roof_label") or ""),
        "units_count": max(1, _int(b.get("units_count"), 1)),
        "unit_layout": _pick(b.get("unit_layout"), LAYOUTS, "house_4LDK"),
        "unit_area_m2": _num(b.get("unit_area_m2"), 0) or None,
        "occupied_units": max(0, _int(b.get("occupied_units"), 0)),
        "aircon_units": max(0, _int(b.get("aircon_units"), 0)),
        "outdoor_leftover_m3": max(0.0, _num(b.get("outdoor_leftover_m3"), 0)),
    }
    out_b["ridge_h"] = max(out_b["eave_h"], _num(b.get("ridge_h"), out_b["eave_h"] + 1.0))
    fl = [_num(v) for v in (b.get("floor_levels") or []) if v is not None]
    out_b["floor_levels"] = fl or [0.45] + [0.45 + 2.8 * i for i in range(1, out_b["floors"])]
    out_b["annexes"] = [{"name": str(a.get("name") or "付属物"),
                         "price_key": _pick(a.get("price_key"), ["steel_stair", "carport", "storage_shed", "none"], "none"),
                         "qty": _num(a.get("qty"), 1) or 1, "unit": str(a.get("unit") or "基"), "basis": str(a.get("basis") or "")}
                        for a in (b.get("annexes") or []) if isinstance(a, dict)]
    out_b["measure_basis"] = [{"item": str(m.get("item", "")), "value": str(m.get("value", "")), "basis": str(m.get("basis", "")),
                               "confidence": _pick(m.get("confidence"), ["高", "中", "低"], "")}
                              for m in (b.get("measure_basis") or []) if isinstance(m, dict)]
    pitch = _num(b.get("roof_pitch_sun"), 0)
    out_b["roof_pitch_sun"] = round(min(12.0, pitch), 1) if pitch > 0 else None
    out_b["roof_material"] = _pick(b.get("roof_material"), ROOF_MATERIALS, "unknown")
    out_b["foundation_type"] = _pick(b.get("foundation_type"), FOUNDATIONS, "unknown")
    plans = {}
    for p in b.get("floor_plans") or []:
        fno = _int(p.get("floor"), 0) if isinstance(p, dict) else 0
        if 1 <= fno <= out_b["floors"] and fno not in plans:
            plans[fno] = {"floor": fno, "w": _num(p.get("w"), 0) or None, "d": _num(p.get("d"), 0) or None,
                          "area_m2": _num(p.get("area_m2"), 0) or None, "basis": str(p.get("basis") or "")}
    out_b["floor_plans"] = [plans[k] for k in sorted(plans)]
    faces = []
    for f in b.get("faces") or []:
        if not isinstance(f, dict):
            continue
        els = []
        for e in f.get("elements") or []:
            if not isinstance(e, dict) or e.get("type") not in ELEMENT_TYPES:
                continue
            els.append({"type": e["type"], "x": _num(e.get("x")), "z": _num(e.get("z")), "w": _num(e.get("w")), "h": _num(e.get("h")),
                        "label": str(e.get("label") or ""), "courses": _int(e.get("courses"), 0), "grille": bool(e.get("grille"))})
        faces.append({"name": str(f.get("name") or f"立面図{len(faces) + 1}"),
                      "width_m": max(1.0, _num(f.get("width_m"), out_b["frontage_m"])),
                      "roof_type": _pick(f.get("roof_type"), ROOF_TYPES, "gable_side"),
                      "wall_pattern": _pick(f.get("wall_pattern"), WALL_PATTERNS, "mortar"), "elements": els})
    out_b["faces"] = faces
    fin = b.get("finishes") if isinstance(b.get("finishes"), dict) else {}
    out_b["finishes"] = {k: str(fin.get(k)) for k in FINISH_KEYS if fin.get(k)}
    # 敷地座標の x は道路沿い。道路側の立面（1面目）の幅が建物の奥行に近ければ、幅と奥行が入れ替わっているので直す
    # （立面の幅は外廊下などを含むことがあるので、面積には AI が出した外壁の寸法をそのまま使う）
    if faces:
        f0 = faces[0]["width_m"]
        if abs(f0 - out_b["depth_m"]) < abs(f0 - out_b["frontage_m"]):
            out_b["frontage_m"], out_b["depth_m"] = out_b["depth_m"], out_b["frontage_m"]
            for p in out_b["floor_plans"]:
                p["w"], p["d"] = p["d"], p["w"]
    cat = exterior_catalog()
    ext = []
    for e in r.get("exterior") or []:
        if not isinstance(e, dict) or e.get("key") not in cat or _num(e.get("qty")) <= 0:
            continue
        ext.append({"key": e["key"], "label": str(e.get("label") or cat[e["key"]]["name"]), "qty": _num(e.get("qty")),
                    "unit": str(e.get("unit") or cat[e["key"]]["unit"]), "basis": str(e.get("basis") or ""),
                    **{k: _num(e.get(k)) for k in ("x0", "y0", "x1", "y1")}})
    s = r.get("site") or {}
    site = {
        "frontage_m": max(3.0, _num(s.get("frontage_m"), out_b["frontage_m"] + 4)),
        "depth_m": max(3.0, _num(s.get("depth_m"), out_b["depth_m"] + 6)),
        "road_side": _pick(s.get("road_side"), SIDES, "unknown"),
        "road_width_m": max(1.8, _num(s.get("road_width_m"), 4.0)),
        "road_name": str(s.get("road_name") or "前面道路"),
        "building_offset_left_m": max(0.0, _num(s.get("building_offset_left_m"), 1.0)),
        "building_setback_m": max(0.0, _num(s.get("building_setback_m"), 1.5)),
        "extra_footprints": [{"label": str(x.get("label") or ""), **{k: _num(x.get(k)) for k in ("x", "y", "w", "d")}}
                             for x in (s.get("extra_footprints") or []) if isinstance(x, dict) and _num(x.get("w")) > 0 and _num(x.get("d")) > 0],
        "level_points": [{"label": str(p.get("label") or ""), "x": _num(p.get("x")), "y": _num(p.get("y")),
                          "dz_from_road_center_m": _num(p.get("dz_from_road_center_m")), "basis": str(p.get("basis") or "")}
                         for p in (s.get("level_points") or []) if isinstance(p, dict)],
    }
    acc = s.get("access") if isinstance(s.get("access"), dict) else {}
    site["access"] = {"road_width_m": _num(acc.get("road_width_m"), site["road_width_m"]) or site["road_width_m"],
                      "machine": str(acc.get("machine") or ""), "truck": str(acc.get("truck") or ""),
                      "neighbor_gap_m": _num(acc.get("neighbor_gap_m"), 0) or None,
                      "carry_distance_m": _num(acc.get("carry_distance_m"), 0) or None, "notes": str(acc.get("notes") or "")}
    # 建物が敷地からはみ出していたら敷地を広げる（読み取りの食い違い対策）
    need_f = site["building_offset_left_m"] + out_b["frontage_m"] + 0.5
    need_d = site["building_setback_m"] + out_b["depth_m"] + 0.5
    if out_b["exists"] and site["frontage_m"] < need_f:
        site["frontage_m"] = round(need_f, 2)
    if out_b["exists"] and site["depth_m"] < need_d:
        site["depth_m"] = round(need_d, 2)
    conds = [c for c in (r.get("conditions") or []) if c in condition_catalog()]
    photos = []
    for ph in r.get("photos") or []:
        if not isinstance(ph, dict):
            continue
        marks = []
        for m in ph.get("marks") or []:
            if not isinstance(m, dict):
                continue
            x0, y0, x1, y1 = (min(1.0, max(0.0, _num(m.get(k)))) for k in ("x0", "y0", "x1", "y1"))
            if x1 > x0 and y1 > y0:
                marks.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "label": str(m.get("label") or ""), "basis": str(m.get("basis") or "")})
        photos.append({"photo_index": _int(ph.get("photo_index"), len(photos) + 1), "caption": str(ph.get("caption") or ""), "marks": marks})
    return {"project_name": str(r.get("project_name") or ""), "building": out_b, "exterior": ext, "site": site,
            "conditions": conds, "photos": photos,
            "summary": [str(x) for x in (r.get("summary") or [])][:8],
            "next_checks": [str(x) for x in (r.get("next_checks") or [])][:12]}


def _extract_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("JSON が見つかりません")
    return json.loads(t[i:j + 1])


SYSTEM = """あなたは解体工事と宅地造成の積算に慣れた建築士です。現地写真（と航空写真）から、解体業者・造成業者がそのまま概算に使える数量と寸法を読み取ります。

# 読み取りの原則
- 寸法は必ず写真に写った基準物からの比例で出す。優先順位: メジャー・スタッフ > ブロック（1段0.2m、1枚0.39m）> 玄関ドア高2.0m > 手すり1.1m > アルミ掃出し窓の幅1.69m・高さ1.8〜2.0m > 腰窓の高さ1.1m前後 > 外階段1段0.18〜0.2m。根拠を measure_basis と写真の marks の basis に短く書く。
- 間取りと戸数は、玄関ドア・メーター・室外機・郵便受けの数、間口（1Kなら1戸≒3.64m）から推定する。
- 写真に写らない部分（裏面・屋根上・基礎）は、一般的な仕様で補完してよいが、補完したことを basis に書く。
- 推定築年は仕様（外壁材・サッシ・外階段・屋根材）から。2006年以前ならアスベストの事前調査が必要なことを next_checks に入れる。
- 迷った数値は安全側（数量は多め、高低差は大きめ）に寄せない。最もありそうな値を入れ、不確かさは next_checks に書く。

# 座標の約束（重要）
- 敷地ローカル座標: 前面道路側に立って敷地を見たとき、x＝道路に沿って左→右、y＝道路から奥へ。原点は敷地の左手前の角（道路境界上）。単位m。
- site.frontage_m＝間口（道路に接する長さ）、depth_m＝奥行。敷地形状が分からなければ写真と航空写真から長方形で近似する。
- building_offset_left_m／building_setback_m は建物外壁の左端と道路側の外壁までの距離。extra_footprints は外廊下・外階段・カーポートなど本体以外の平面（同じ座標系、x,y＝左手前の角、w＝x方向、d＝y方向）。
- building.frontage_m は建物の x 方向の外壁長、depth_m は y 方向の外壁長。
- road_side は前面道路が敷地のどの方位にあるか（航空写真は北が上）。判断できなければ unknown。
- level_points は高低差の読み取り点。dz_from_road_center_m は前面道路の中心（敷地間口の中央）を0とした高さ。道路中心自体（x=間口/2, y=-道路幅/2, dz=0）は入れなくてよい。ブロックの段数・階段の段数・メジャーなどで読み、basis に根拠を書く。敷地の4隅付近と、段差のある境界の外側（隣地）を入れる。
- exterior の x0,y0,x1,y1 は外構の位置（線分。点状のものは x0=x1,y0=y1）。不明なら全部0。

# 立面図（faces）
- 4面（道路側・右・奥・左の順を基本）を、それぞれ正面から見た座標で出す: x＝その面の左端の外壁を0として右へ、z＝地盤面(GL)を0として上へ。width_m はその面の外壁の幅。
- elements の使い方: window/door（x,z＝左下、w,h）、railing（手すり。z＝床、h＝高さ）、slab（廊下・バルコニー床、h≈0.15〜0.2）、post（柱。x＝中心、h）、pipe（たて樋。x、z＝下端、h＝長さ）、stair（側面から見た外階段。x,z＝下端、w,h＝上端までのx・z差。下りが右なら w は負）、stair_front（正面から見た外階段。x,w、z＝下端、h＝昇る高さ）、box（室外機・メーター等）、block_wall（x,w、courses＝段数、z＝基礎天端。h は0）、fence（x,w,h、z＝下端）、tree（x＝幹、h＝樹高、w＝枝張り）、canopy（庇。x,z,w、h≈0.1）。
- courses と grille は該当しない要素では 0／false。label は空文字なら表示しない。窓は数が多いので、ラベルは各面の代表1か所だけ（例「掃出し窓 W1690×H1800」）。
- 屋根: 平側の面は gable_side、妻側の面は gable_end（切妻の場合）。building.ridge_h は最高高さ、eave_h は軒高。floor_levels は各階の床高 [1FL, 2FL, ...]（GL基準）。

# 数量の精度（解体業者が積算に使う。特に丁寧に）
- 延床面積は「外形×階数」で済ませない。floor_plans に階ごとの外形（w＝x方向、d＝y方向、area_m2）を出す。部分2階・下屋・L字・オーバーハング・吹抜けは、立面写真の屋根の段差・窓の並び・航空写真の屋根形状から読み、basis に書く。外廊下・バルコニーは床面積に含めない（外廊下が屋内扱いのアパートは含めて basis に明記）。
- 1Fの外形（building.frontage_m × depth_m）は、航空写真の屋根の大きさ（軒の出を差し引く）と、立面写真の基準物からの寸法の両方で確かめ、食い違えば measure_basis に両方の値を書く。
- 寸法は尺モジュール（0.91m）・メーターモジュール（1.0m）のどちらかに乗ることが多い。柱間・窓の割付から判断して丸める。
- 写っていない奥行（側面・裏面）は、「4間」「10m」のような決め打ちで埋めない（誤差の最大の原因）。次の手がかりを全部当てて、いちばん整合する値にする:
  (1) 妻面（三角の破風が見える面）が写っていれば、その幅がそのまま奥行（平側が道路なら）または間口になる。
  (2) 屋根の幾何: 切妻・寄棟は 棟までの立上り ≒ (妻側の幅÷2)×(勾配÷10)。平側の写真で軒高と棟高が読めて勾配が分かれば、妻側の幅 ≒ 2×(棟高−軒高)÷(勾配÷10)。
  (3) 斜めから写った側面の窓・戸・換気口・たて樋の数と間隔（部屋1つ＝おおむね2〜3間の外壁、窓1〜2か所）。
  (4) 側面が見えない場合でも、窓の数・掃出し窓の数・2階の窓の数から部屋数（間取り）を見立て、間取りから延床の目安と照合する（目安: 3DK〜3LDK 70〜95㎡、4LDK 95〜120㎡、5LDK以上 120〜150㎡、古い平屋の和風住宅で座敷・続き間があれば 120〜170㎡）。
  使った手がかりと、外形から出した延床と間取りの目安が食い違うときの判断を measure_basis の「延床面積」の basis に書く。
- 部分2階の2Fは、2Fの外壁が写っている面の幅と、1F屋根（下屋）の出から読む。2Fの奥行が見えないときは 1F の奥行から下屋の出（片側 0.9〜1.8m）を差し引く。一般に2Fは1Fの 45〜80%。
- roof_pitch_sun は屋根の勾配（寸。4寸＝4/10）。妻側の写真の屋根の傾きから読む。roof_material は屋根材（土葺きの瓦は古い和瓦で棟が高いもの、slate＝化粧スレート、metal＝鋼板・瓦棒）。
- foundation_type は写真に写る基礎の立上りと築年から（1981年以前は布基礎が多い。分からなければ unknown）。
- measure_basis の confidence は、基準物で直接測れた＝高、他の寸法からの比例や一般的な割付＝中、写らない部分の補完＝低。延床・間口・奥行・軒高・戸数は必ず入れる。

- 敷地（site.frontage_m×depth_m）は広く取りすぎない（実測より大きく読む傾向がある）。写真に写る塀・境界ブロック・隣家の外壁から読み、写らない側は建物の外壁から境界まで 0.6〜1.0m 程度とする。庭・駐車場は写っている広さだけ足す。郊外の分譲地は 150〜250㎡ が多い。

# 外部仕上げ・設備（細かく）
- building.finishes に、屋根・外壁・軒天・破風・雨樋・サッシ・基礎・バルコニー/廊下・外階段の材料を、写真から分かる範囲で書く（推定は「（推定）」を付ける）。解体の分別とアスベストの判断に使う。
- 各面の wall_pattern に外壁の張り方（mortar=モルタル・吹付、siding_h=横張りサイディング、siding_v=縦張り、board=板張り、panel=パネル、tile=タイル、alc=ALC）。
- 立面の elements には、窓・ドアだけでなく、換気口（vent）、電気・ガスメーター（meter）、給湯器（heater）、室外機（box）、たて樋（pipe）、庇（canopy）、面格子付き窓（window の grille=true）も見える範囲で入れる。各面で窓・ドアの位置と大きさは写真の比率から丁寧に割り付ける。

# 搬出・施工条件（site.access）
- 前面道路の幅、入れそうな重機の大きさ、トラックの大きさ、隣家との最も近い離れ、車両から建物までの搬出距離、電線・電柱・通学路など近隣で気をつけることを書く（解体業者への見積依頼にそのまま載せる）。

# 外構・付帯（exterior）
- key は単価表のキーから選ぶ。数量の単位はその単価に合わせる（ブロック塀は見付面積㎡＝長さ×段数×0.2m、フェンスは m、樹木は本、竹は㎡ など）。伐採した高木・中木には抜根（tree_stump）も別行で入れる。
- 建物と一体の外廊下は本体に含める。鉄骨外階段は building.annexes に steel_stair で入れる。

# 写真の読み取り箇所（photos）
- 写真ごとに（photo_index は「写真1」なら 1 の、1 から数える番号）、寸法や数量の根拠にした箇所を最大7つ、画像に対する比率（0〜1、左上原点）の矩形で示す。

# 文章
- summary は表紙に載せる要点3〜6行（構造・規模・築年、費用が振れる要因、施工条件、残置物、高低差）。
- next_checks は精度を上げるために次に確認すること（アスベスト調査、浄化槽・井戸・地中埋設物、境界、隣地との離れ、入居状況など）。
- すべて日本語。数値は推定であり断定しない書き方にする。"""


def read_site(photos_b64, address, notes, land_info, aerial_b64=None, effort=None):
    """photos_b64: [{"name":..., "data": base64 JPEG}]. 戻り値: (reading dict, usage dict)"""
    content = []
    for i, p in enumerate(photos_b64, 1):
        content.append({"type": "text", "text": f"写真{i}（{p.get('name', '')}）"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": p["data"]}})
    if aerial_b64:
        content.append({"type": "text", "text": "航空写真（国土地理院、北が上、中心＝住所の代表点。敷地とずれていることがある。約0.5m/画素）"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": aerial_b64}})
    cat = exterior_catalog()
    lines = [f"住所: {address or '（未入力）'}",
             f"担当者メモ: {notes or '（なし）'}",
             "公開データからの土地情報: " + ("; ".join(f"{x['item']}={x['value']}" for x in (land_info or [])[:12]) or "（なし）"),
             "外構・付帯の単価キー: " + "、".join(f"{k}（{v['name']}／{v['unit']}）" for k, v in cat.items()),
             "施工条件のキー: " + "、".join(f"{k}（{v}）" for k, v in condition_catalog().items()),
             "上の写真から、次の形の JSON で読み取り結果を出してください。値の例は形を示すためのもので、写真から読み取った値に置き換えること。"
             "「a|b|c」は選択肢（どれか1つ）。説明文やコードブロック（```）は付けず、JSON だけを出力すること。",
             TEMPLATE]
    content.append({"type": "text", "text": "\n".join(lines)})

    client = anthropic.Anthropic()
    effort = effort if effort in ("low", "medium", "high") else EFFORT
    msg = _call(client, [{"role": "user", "content": content}], effort)
    text = "".join(b.text for b in msg.content if b.type == "text")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens, "model": msg.model}
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # JSON が崩れていたら1回だけ直させる
        fix = _call(client, [{"role": "user", "content": content}, {"role": "assistant", "content": text},
                             {"role": "user", "content": "出力が JSON として読めませんでした。同じ内容を、正しい JSON だけで出し直してください。"}], effort)
        data = _extract_json("".join(b.text for b in fix.content if b.type == "text"))
    return normalize(data), usage


def _call(client, messages, effort=EFFORT):
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        messages=messages,
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("AIが読み取りを辞退しました。写真を変えて再度お試しください。")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("読み取り結果が長すぎて途中で切れました。写真の枚数を減らして再度お試しください。")
    return msg
