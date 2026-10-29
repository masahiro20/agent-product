"""MCP サーバー（Streamable HTTP・状態なし・JSON 応答）。claude.ai のカスタムコネクタから使う。

道具（tools）:
  find_drive_folders       ドライブの写真フォルダを名前で探す
  create_site_report       ドライブのフォルダの写真＋住所 → 読み取り・概算・案件の保存・資料のリンク
  list_cases / get_case    保存した案件
  update_case              延床・階数などを直して概算を作り直す
  make_quote_request       業者向け見積依頼書（PDF・Excel）のリンク
"""
import base64
import concurrent.futures as cf
import json
import traceback

from . import drive, links, service, store

STRUCT = {"wood": "木造", "light_steel": "軽量鉄骨造", "heavy_steel": "重量鉄骨造", "rc": "RC造"}
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "ホームランディック社内の『現地写真レポート』です。Google ドライブの写真フォルダと住所から、"
    "建物の寸法・延床・解体の数量と概算・造成の概算を読み取り、PDF・Excel・業者向け見積依頼書を作ります。"
    "結果は推定値（延床で ±10〜20% 程度）なので、回答では『推定』『概算』と明記し、要確認の項目も伝えてください。"
    "写真は建物の4面＋斜め45°があると精度が上がります。")


def _num_schema(desc):
    return {"type": "number", "description": desc}


TOOLS = [
    {"name": "find_drive_folders",
     "description": "Google ドライブで、名前に指定の文字を含むフォルダを探す（写真フォルダの特定用）。",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "フォルダ名の一部"}},
                     "required": ["name"]}},
    {"name": "create_site_report",
     "description": ("Google ドライブのフォルダにある現地写真（最大12枚）と住所から、建物の読み取り・解体と造成の概算を行い、"
                     "案件として保存して、PDF・Excel・見積依頼書のダウンロードリンクを返す。2〜4分かかる。"),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string", "description": "ドライブのフォルダの URL、ID、またはフォルダ名"},
         "address": {"type": "string", "description": "物件の住所（番地まで。地番でも可）"},
         "project_name": {"type": "string", "description": "物件名（資料の表紙に入る）"},
         "notes": {"type": "string", "description": "分かっていること（築年・構造・戸数・浄化槽など）"},
         "include_grading": {"type": "boolean", "description": "造成の計画・概算も出すか（既定 true）"}},
         "required": ["folder", "address"]}},
    {"name": "list_cases",
     "description": "保存した案件の一覧（新しい順）。住所や物件名の一部で絞り込める。",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "get_case",
     "description": "保存した案件の要約（延床・数量・概算・要確認事項）と資料のダウンロードリンク。",
     "inputSchema": {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]}},
    {"name": "update_case",
     "description": "案件の読み取り値を直して概算を作り直す（登記の延床が分かった、階数が違う等）。指定した項目だけ変える。",
     "inputSchema": {"type": "object", "properties": {
         "case_id": {"type": "string"},
         "floors": {"type": "integer", "description": "階数"},
         "floor_area_1f_m2": _num_schema("1階の床面積（㎡）"), "floor_area_2f_m2": _num_schema("2階の床面積（㎡）"),
         "frontage_m": _num_schema("建物の幅（道路側, m）"), "depth_m": _num_schema("建物の奥行（m）"),
         "eave_h": _num_schema("軒高（m）"), "built_year_est": {"type": "integer", "description": "築年"},
         "structure": {"type": "string", "enum": ["wood", "light_steel", "heavy_steel", "rc"]},
         "units_count": {"type": "integer"}, "occupied_units": {"type": "integer", "description": "家財が残る戸数"},
         "region": {"type": "string", "description": "単価の地域キー（例 aichi_other, nagoya）"}},
         "required": ["case_id"]}},
    {"name": "make_quote_request",
     "description": "業者向けの見積依頼書（金額欄が空欄の数量表・写真・図面）のダウンロードリンクを作る。",
     "inputSchema": {"type": "object", "properties": {
         "case_id": {"type": "string"}, "kind": {"type": "string", "enum": ["demolition", "grading"]},
         "due": {"type": "string", "description": "回答期限（例 2026年11月10日）"},
         "contact": {"type": "string", "description": "依頼元の担当者・連絡先"}},
         "required": ["case_id", "kind"]}},
]


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _man(v):
    return f"{v / 10000:,.0f}万円" if v else "-"


def case_text(case, base):
    s = case.get("summary") or {}
    b = (case.get("reading") or {}).get("building") or {}
    lines = [f"■ 案件 {case['id']}　{case.get('title') or ''}　{case.get('address') or ''}"]
    if s.get("floor_area_m2"):
        lines.append(f"建物（推定）: {STRUCT.get(b.get('structure'), b.get('structure', ''))} {b.get('floors', '')}階建・延床 約{s['floor_area_m2']}㎡（{s.get('floor_area_tsubo')}坪）・"
                     f"推定築年 {b.get('built_year_est', '')}年頃")
    d = s.get("demolition_total")
    if d:
        lines.append(f"解体の概算（税別）: 約{_man(d['mid'])}（幅 {_man(d['low'])}〜{_man(d['high'])}）"
                     + (f"／アスベスト含有時の追加 約{_man(s['asbestos_extra'][0]['mid'])}（別枠）" if s.get("asbestos_extra") else ""))
    g = s.get("grading_total")
    if g:
        lines.append(f"造成の概算（税別）: 約{_man(g['mid'])}（幅 {_man(g['low'])}〜{_man(g['high'])}）")
    checks = [c["msg"] for c in s.get("quantity_checks", []) if c.get("level") == "warn"]
    if checks:
        lines.append("要確認: " + "／".join(checks))
    nc = (case.get("reading") or {}).get("next_checks") or []
    if nc:
        lines.append("次に確認すること: " + "／".join(nc[:5]))
    lines.append("資料（7日間有効のリンク）:")
    for fmt, label in (("pdf", "調査レポート PDF"), ("xlsx", "概算見積 Excel"), ("dxf", "図面 DXF")):
        lines.append(f"- {label}: {links.file_url(base, case['id'], fmt)}")
    lines.append(f"画面で開いて直す: {base}/?case={case['id']}")
    return "\n".join(lines)


def _photos_from_drive(token, folder):
    fid = drive.folder_id_from(folder)
    if not fid:
        found = drive.find_folders(token, folder)
        if len(found) != 1:
            names = "、".join(f"{f['name']}（{f['id']}）" for f in found) or "見つかりません"
            raise ValueError(f"フォルダ「{folder}」を1つに絞れませんでした: {names}。URL か ID で指定してください。")
        fid = found[0]["id"]
    files = drive.list_images(token, fid)
    if not files:
        raise ValueError("フォルダに写真（JPEG・PNG・HEIC）がありません。")
    files = files[:service.MAX_PHOTOS]

    def one(f):
        return {"name": f["name"], "data": base64.b64encode(service.shrink_jpeg(drive.download(token, f["id"]))).decode()}

    with cf.ThreadPoolExecutor(6) as ex:
        photos = list(ex.map(one, files))
    return photos, drive.folder_name(token, fid)


def call_tool(name, args, user, base):
    if name == "find_drive_folders":
        found = drive.find_folders(user["google_token"](), args["name"], limit=10)
        return _text("\n".join(f"- {f['name']}（ID: {f['id']}、更新 {f.get('modifiedTime', '')[:10]}）" for f in found) or "見つかりませんでした。")
    if name == "create_site_report":
        photos, folder_name = _photos_from_drive(user["google_token"](), args["folder"])
        address = args["address"].strip()
        reading, land, usage = service.analyze(photos, address, args.get("notes", ""))
        options = {"address": address, "project_name": args.get("project_name") or folder_name,
                   "region": service.region_from_address(address), "include_demolition": True,
                   "include_grading": args.get("include_grading", True),
                   "purpose": "解体概算・造成計画" if args.get("include_grading", True) else "解体概算"}
        summary = service.build(reading, land, [], options, "summary")
        case = service.save_new_case(reading, land, photos, options, summary, source=f"mcp:{user['email']}", usage=usage)
        return _text(f"写真 {len(photos)}枚（フォルダ「{folder_name}」）を読み取りました。\n" + case_text(case, base))
    if name == "list_cases":
        q = (args.get("query") or "").strip()
        rows = [r for r in store.list_cases() if not q or q in (r.get("title") or "") + (r.get("address") or "")]
        rows = rows[: int(args.get("limit") or 20)]
        return _text("\n".join(f"- {r['id']}　{r.get('title') or ''}　{r.get('address') or ''}　延床 {r.get('floor_area_m2') or '-'}㎡　"
                               f"解体 {_man(r.get('demolition_mid'))}　（{(r.get('updated_at') or '')[:10]}）" for r in rows) or "案件はまだありません。")
    if name == "get_case":
        return _text(case_text(store.load_case(args["case_id"]), base))
    if name == "update_case":
        case = store.load_case(args["case_id"])
        b = case["reading"]["building"]
        for k in ("floors", "frontage_m", "depth_m", "eave_h", "built_year_est", "structure", "units_count", "occupied_units"):
            if args.get(k) is not None:
                b[k] = args[k]
        plans = {p["floor"]: p for p in b.get("floor_plans") or []}
        for fno, key in ((1, "floor_area_1f_m2"), (2, "floor_area_2f_m2")):
            if args.get(key):
                plans[fno] = {"floor": fno, "w": None, "d": None, "area_m2": float(args[key]), "basis": "利用者の指定"}
        b["floor_plans"] = [plans[k] for k in sorted(plans)]
        if args.get("region"):
            case["options"]["region"] = args["region"]
        case = service.summarize_case(case)
        return _text("直した値で作り直しました。\n" + case_text(case, base))
    if name == "make_quote_request":
        case = store.load_case(args["case_id"])
        kind = args["kind"]
        label = "解体" if kind == "demolition" else "造成"
        p = {"kind": kind, "due": args.get("due", ""), "contact": args.get("contact", "")}
        return _text(f"{label}の見積依頼書を作りました（7日間有効）。\n"
                     f"- 依頼書 PDF: {links.file_url(base, case['id'], 'rfq_pdf', **p)}\n"
                     f"- 数量表 Excel（業者さんの記入用）: {links.file_url(base, case['id'], 'rfq_xlsx', **p)}")
    raise KeyError(name)


def handle(msg, user, base):
    """JSON-RPC 1件を処理。通知なら None。"""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        v = params.get("protocolVersion")
        return ok({"protocolVersion": v if v in PROTOCOLS else PROTOCOLS[1], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "genchi-photo-report", "title": "現地写真レポート", "version": "1.0.0"},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"不明な道具: {name}"}}
        try:
            return ok(call_tool(name, params.get("arguments") or {}, user, base))
        except KeyError as e:
            return ok({**_text(f"案件が見つかりません: {e}"), "isError": True})
        except Exception as e:  # noqa: BLE001  道具のエラーは結果として返す（AI が言い直せるように）
            traceback.print_exc()
            return ok({**_text(f"エラー: {e}"), "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"未対応のメソッド: {method}"}}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)
