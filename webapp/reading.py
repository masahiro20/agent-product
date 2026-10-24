"""現地写真 → 読み取り結果（構造化JSON）。Claude に写真と航空写真を見せ、寸法・数量・高低差を推定させる。

出力は「読み取り結果（reading）」という平たい形にし、図面・見積用の site.json への変換は convert.py が行う。
"""
import os

import anthropic

from .engine import load_data

MODEL = os.environ.get("SITE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("SITE_EFFORT", "medium")

ELEMENT_TYPES = ["window", "door", "railing", "slab", "post", "pipe", "stair", "stair_front",
                 "box", "block_wall", "fence", "tree", "canopy"]
ROOF_TYPES = ["gable_side", "gable_end", "hip_side", "shed", "flat"]
STRUCTURES = ["wood", "light_steel", "heavy_steel", "rc"]
LAYOUTS = ["1R", "1K", "1DK", "2DK", "3LDK", "house_4LDK"]
SIDES = ["N", "E", "S", "W", "unknown"]

# 建物本体・手続きなど、外構として選ばせない単価キー
_NOT_EXTERIOR = {"interior_stripping", "scaffold_m2", "heavy_machine_transport", "guard_person_day", "road_use_permit",
                 "neighbor_greeting", "leftover_m3", "waste_disposal_mixed_m3", "recycling_notification",
                 "asbestos_report", "demolition_registration", "overhead_rate", "aircon_unit"}


def exterior_catalog():
    items = load_data("demolition_unit_prices.json")["items"]
    return {k: {"name": v.get("name", k), "unit": v.get("unit", "").replace("円/", "")}
            for k, v in items.items()
            if k not in _NOT_EXTERIOR and not k.startswith(("waste_", "recycle_", "appliance_"))}


def condition_catalog():
    cf = load_data("demolition_unit_prices.json").get("condition_factor", {})
    return {k: v.get("name", k) for k, v in cf.items() if isinstance(v, dict)}


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


S, N, I, B = {"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}


def _enum(vals):
    return {"type": "string", "enum": vals}


def schema():
    element = _obj({"type": _enum(ELEMENT_TYPES), "x": N, "z": N, "w": N, "h": N, "label": S,
                    "courses": I, "grille": B})
    face = _obj({"name": S, "width_m": N, "roof_type": _enum(ROOF_TYPES), "elements": {"type": "array", "items": element}})
    basis = _obj({"item": S, "value": S, "basis": S})
    rect = _obj({"label": S, "x": N, "y": N, "w": N, "d": N})
    annex = _obj({"name": S, "price_key": _enum(["steel_stair", "carport", "storage_shed", "none"]), "qty": N, "unit": S,
                  "basis": S})
    exterior = _obj({"key": _enum(sorted(exterior_catalog())), "label": S, "qty": N, "unit": S, "basis": S,
                     "x0": N, "y0": N, "x1": N, "y1": N})
    mark = _obj({"x0": N, "y0": N, "x1": N, "y1": N, "label": S, "basis": S})
    photo = _obj({"photo_index": I, "caption": S, "marks": {"type": "array", "items": mark}})
    level = _obj({"label": S, "x": N, "y": N, "dz_from_road_center_m": N, "basis": S})
    building = _obj({
        "exists": B, "structure": _enum(STRUCTURES), "use": S, "floors": I, "built_year_est": I,
        "frontage_m": N, "depth_m": N, "eave_h": N, "ridge_h": N, "roof_overhang_m": N, "roof_label": S,
        "floor_levels": {"type": "array", "items": N},
        "units_count": I, "unit_layout": _enum(LAYOUTS), "unit_area_m2": N,
        "occupied_units": I, "aircon_units": I, "outdoor_leftover_m3": N,
        "annexes": {"type": "array", "items": annex},
        "measure_basis": {"type": "array", "items": basis},
        "faces": {"type": "array", "items": face},
    })
    site = _obj({
        "frontage_m": N, "depth_m": N, "road_side": _enum(SIDES), "road_width_m": N, "road_name": S,
        "building_offset_left_m": N, "building_setback_m": N,
        "extra_footprints": {"type": "array", "items": rect},
        "level_points": {"type": "array", "items": level},
    })
    return _obj({
        "project_name": S,
        "building": building,
        "exterior": {"type": "array", "items": exterior},
        "site": site,
        "conditions": {"type": "array", "items": _enum(sorted(condition_catalog()))},
        "photos": {"type": "array", "items": photo},
        "summary": {"type": "array", "items": S},
        "next_checks": {"type": "array", "items": S},
    })


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

# 外構・付帯（exterior）
- key は単価表のキーから選ぶ。数量の単位はその単価に合わせる（ブロック塀は見付面積㎡＝長さ×段数×0.2m、フェンスは m、樹木は本、竹は㎡ など）。伐採した高木・中木には抜根（tree_stump）も別行で入れる。
- 建物と一体の外廊下は本体に含める。鉄骨外階段は building.annexes に steel_stair で入れる。

# 写真の読み取り箇所（photos）
- 写真ごとに（photo_index は「写真1」なら 1 の、1 から数える番号）、寸法や数量の根拠にした箇所を最大7つ、画像に対する比率（0〜1、左上原点）の矩形で示す。

# 文章
- summary は表紙に載せる要点3〜6行（構造・規模・築年、費用が振れる要因、施工条件、残置物、高低差）。
- next_checks は精度を上げるために次に確認すること（アスベスト調査、浄化槽・井戸・地中埋設物、境界、隣地との離れ、入居状況など）。
- すべて日本語。数値は推定であり断定しない書き方にする。"""


def read_site(photos_b64, address, notes, land_info, aerial_b64=None):
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
             "上の写真から、指定のJSON形式で読み取り結果を出してください。"]
    content.append({"type": "text", "text": "\n".join(lines)})

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema()}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("AIが読み取りを辞退しました。写真を変えて再度お試しください。")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("読み取り結果が長すぎて途中で切れました。写真の枚数を減らして再度お試しください。")
    import json
    text = next(b.text for b in msg.content if b.type == "text")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens, "model": msg.model}
    return json.loads(text), usage
