"""一式資料（PDF・Excel・DXF）の組み立て。"""
import datetime
import io
import os

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from . import demolition, elevation, grading, grading_draw
from .common import FONT, MM, ensure_font, font_path, man_yen, yen
from .drawing import MARGIN, SHEET_H, SHEET_W, frame, jp, new_sheet, text_at

CONF = {"確定": colors.HexColor("#1b7f3b"), "要確認": colors.HexColor("#b26a00"), "推測": colors.HexColor("#555555")}


def P(text, style):
    return Paragraph(jp(text), style)


def _styles():
    ensure_font()
    return {
        "h": ParagraphStyle("h", fontName=FONT, fontSize=15, leading=20),
        "b": ParagraphStyle("b", fontName=FONT, fontSize=10.5, leading=15),
        "L": ParagraphStyle("L", fontName=FONT, fontSize=12.5, leading=19),
        "s": ParagraphStyle("s", fontName=FONT, fontSize=8, leading=11),
        "t": ParagraphStyle("t", fontName=FONT, fontSize=8.5, leading=11),
    }


def _table(data, col_w, header=True, font_size=8.5, zebra=True, align_right_cols=()):
    st = _styles()
    ps = ParagraphStyle("c", parent=st["t"], fontSize=font_size, leading=font_size * 1.3)
    rows = [[Paragraph(jp(x), ps) if not isinstance(x, Paragraph) else x for x in r] for r in data]
    t = Table(rows, colWidths=[w * MM for w in col_w], repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), FONT, font_size), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf2")))
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f7f7f7")))
    for col in align_right_cols:
        style.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _draw_flow(c, flow, x_mm, y_top_mm, w_mm, h_mm):
    """flowable を上詰めで描く。収まらない分は分割して残りを返す。"""
    w, h = flow.wrapOn(c, w_mm * MM, h_mm * MM)
    if h <= h_mm * MM:
        flow.drawOn(c, x_mm * MM, y_top_mm * MM - h)
        return None, h / MM
    parts = flow.split(w_mm * MM, h_mm * MM)
    if not parts:
        flow.drawOn(c, x_mm * MM, y_top_mm * MM - h)
        return None, h / MM
    first = parts[0]
    w, h = first.wrapOn(c, w_mm * MM, h_mm * MM)
    first.drawOn(c, x_mm * MM, y_top_mm * MM - h)
    return (parts[1] if len(parts) > 1 else None), h / MM


def _page_with_flows(c, spec, title, sheet_no, flows, notes=None):
    """flowable を A3 図枠のページに流し込む（複数ページ可）。"""
    queue = list(flows)
    n = 0
    while queue:
        new_sheet(c)
        ax, ay, aw, ah = frame(c, title, f"{sheet_no}-{n + 1}" if n else sheet_no, spec.get("project", {}), notes=notes)
        ytop = ay + ah
        col_w = aw
        while queue and ytop - ay > 15:
            f = queue[0]
            if f == "COLBREAK":
                queue.pop(0)
                break
            rest, used = _draw_flow(c, f, ax, ytop, col_w, ytop - ay)
            queue.pop(0)
            if rest is not None:
                queue.insert(0, rest)
                break
            ytop -= used + 4
        c.showPage()
        n += 1
    return n


# ---------- 写真 ----------

def annotate_photo(path, marks, max_px=1400):
    """marks: [{"bbox":[x0,y0,x1,y1] (0-1), "label":"..."}] を描いた画像を返す。"""
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_px, max_px))
    d = ImageDraw.Draw(im)
    fs = max(14, im.width // 45)
    font = ImageFont.truetype(font_path(), fs)
    for i, m in enumerate(marks or []):
        x0, y0, x1, y1 = m["bbox"]
        box = (x0 * im.width, y0 * im.height, x1 * im.width, y1 * im.height)
        col = (220, 30, 30) if m.get("color", "red") == "red" else (30, 90, 210)
        d.rectangle(box, outline=col, width=max(2, im.width // 300))
        label = f"{i + 1}. {m['label']}"
        tw = d.textlength(label, font=font)
        ty = box[1] - fs - 6 if box[1] > fs + 6 else box[3] + 2
        d.rectangle((box[0], ty, box[0] + tw + 8, ty + fs + 4), fill=col)
        d.text((box[0] + 4, ty + 1), label, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    buf.seek(0)
    return ImageReader(buf), im.size


def photo_pages(c, spec, base_dir):
    photos = spec.get("photos", [])
    if not photos:
        return
    per = 4
    for p0 in range(0, len(photos), per):
        new_sheet(c)
        ax, ay, aw, ah = frame(c, "写真台帳（読み取り箇所）", f"P-{p0 // per + 1:02d}", spec.get("project", {}))
        cells = [(ax, ay + ah / 2, aw / 2 - 3, ah / 2 - 2), (ax + aw / 2 + 3, ay + ah / 2, aw / 2 - 3, ah / 2 - 2),
                 (ax, ay, aw / 2 - 3, ah / 2 - 4), (ax + aw / 2 + 3, ay, aw / 2 - 3, ah / 2 - 4)]
        for ph, (x, y, w, h) in zip(photos[p0:p0 + per], cells):
            path = ph["path"] if os.path.isabs(ph["path"]) else os.path.join(base_dir, ph["path"])
            if not os.path.exists(path):
                text_at(c, x + 2, y + h / 2, f"写真が見つかりません: {ph['path']}", 2.5)
                continue
            img, (iw, ih) = annotate_photo(path, ph.get("marks"))
            cap_h = 4 + 3.3 * min(4, len(ph.get("marks", [])))
            bw, bh = w * 0.6, h - 8
            k = min(bw / iw, bh / ih)
            dw, dh = iw * k, ih * k
            c.drawImage(img, x * MM, (y + h - dh - 6) * MM, dw * MM, dh * MM)
            text_at(c, x, y + h - 4, f"写真{ph.get('no', '')} {ph.get('caption', '')}", 2.8)
            ty = y + h - 10
            for i, m in enumerate(ph.get("marks", [])):
                for line in _wrap(f"{i + 1}. {m['label']}" + (f" — {m['basis']}" if m.get("basis") else ""), 34):
                    text_at(c, x + dw + 3, ty, line, 2.2)
                    ty -= 3.3
        c.showPage()


def _wrap(s, n):
    out = []
    while len(s) > n:
        out.append(s[:n])
        s = s[n:]
    out.append(s)
    return out


# ---------- 各ページ ----------

def cover_page(c, spec, demo, grad, gest):
    st = _styles()
    new_sheet(c)
    p = spec.get("project", {})
    ax, ay, aw, ah = frame(c, "現地写真 調査レポート（表紙・総括）", "00", p)
    text_at(c, ax + 4, ay + ah - 12, p.get("name", "現地写真 調査レポート"), 8)
    text_at(c, ax + 4, ay + ah - 22, f"所在地：{p.get('address', '')}", 4)
    text_at(c, ax + 4, ay + ah - 29, f"作成日：{p.get('date', '')}　　依頼内容：{p.get('purpose', '解体概算・造成計画')}", 3.4)
    # 航空写真
    aer = spec.get("terrain", {}).get("aerial_photo")
    if aer and os.path.exists(aer):
        c.drawImage(aer, (ax + aw - 120) * MM, (ay + ah - 128) * MM, 118 * MM, 118 * MM, preserveAspectRatio=True)
        text_at(c, ax + aw - 120, ay + ah - 132, "航空写真（国土地理院 シームレス空中写真）", 2.3)
    rows = [["項目", "概算（標準）", "幅（安め〜高め）", "メモ"]]
    if demo:
        q = demo["quantities"]
        rows.append(["解体工事", man_yen(demo["total"]["mid"]), f"{man_yen(demo['total']['low'])} 〜 {man_yen(demo['total']['high'])}",
                     f"延床 約{q['floor_area_m2']:.0f}㎡（{q['floor_area_tsubo']:.1f}坪）／坪単価 約{demo['per_tsubo_mid'] / 10000:.1f}万円（諸経費込み）"])
        if demo["asbestos_extra"]:
            a = demo["asbestos_extra"][0]
            rows.append(["（アスベスト含有時の追加）", man_yen(a["mid"]), f"{man_yen(a['low'])} 〜 {man_yen(a['high'])}", "事前調査で含有が判明した場合のみ"])
    if gest:
        rows.append(["造成工事", man_yen(gest["total"]["mid"]), f"{man_yen(gest['total']['low'])} 〜 {man_yen(gest['total']['high'])}",
                     f"切土{grad['cut_m3']:.0f}㎥／盛土{grad['fill_m3']:.0f}㎥／擁壁 {sum(w['length_m'] for w in grad['walls'] if w['type'] != 'none'):.1f}m"])
    for a in (grad or {}).get("alternatives", [])[1:]:
        rows.append([f"（造成 別案）{a['label']}", man_yen(a["total_mid"]), "",
                     f"FH {a['fh_m'] - (grad['road']['center_avg'] if grad.get('road') else 0):+.2f}m／擁壁{a['wall_m']:.0f}m" + ("／道路より低い（排水・浸水注意）" if a["below_road"] else "")])
    if demo and gest:
        rows.append(["合計", man_yen(demo["total"]["mid"] + gest["total"]["mid"]),
                     f"{man_yen(demo['total']['low'] + gest['total']['low'])} 〜 {man_yen(demo['total']['high'] + gest['total']['high'])}", "税別"])
    t = _table(rows, [58, 36, 60, 100], align_right_cols=(1,), font_size=10.5)
    _, used = _draw_flow(c, t, ax + 4, ay + ah - 38, 262, 90)
    y = ay + ah - 38 - used - 8
    flows = [P("<b>この敷地の要点</b>", st["L"])]
    for s in spec.get("summary", []):
        flows.append(P("・" + s, st["L"]))
    flows.append(P("<b>精度について</b>", st["b"]))
    flows.append(P("本資料は現地写真と公開データ（国土地理院の標高・航空写真等）からの推定で作成した参考資料です。"
                           "寸法・数量は±10〜20%、標高は±0.2〜0.5m程度の誤差を含みます。見積は公開相場の単価幅（安め／標準／高め）による概算で、"
                           "正式見積・設計には現地調査・測量・地盤調査・アスベスト事前調査が必要です。", st["s"]))
    yy = y
    for f in flows:
        _, used = _draw_flow(c, f, ax + 4, yy, 265, yy - ay)
        yy -= used + 1.5
    c.showPage()


def site_info_page(c, spec, grad):
    st = _styles()
    info = spec.get("land_info", [])
    rows = [["項目", "内容", "確実性", "出典・根拠"]]
    for it in info:
        conf = it.get("confidence", "推測")
        rows.append([it["item"], it["value"], f"<font color='{CONF.get(conf, colors.black).hexval()}'>{conf}</font>"
                     if conf in CONF else conf, it.get("source", "")])
    if grad:
        r = grad.get("road") or {}
        rows.append(["敷地内の高低差", f"{grad['existing_diff']:.2f}m（最低 T.P.{grad['existing_min']:.2f} ／ 最高 T.P.{grad['existing_max']:.2f}）",
                     "推測", "国土地理院 1mDEM＋写真補正"])
        if r:
            rows.append(["前面道路", f"道路中心 T.P.{r['center_avg']:.2f}m、縦断勾配 約{abs(r['slope_pct']):.1f}%", "推測", "国土地理院 1mDEM"])
    flows = [_table(rows, [50, 190, 22, 120])]
    if spec.get("market_notes"):
        flows.append(P("<b>相場・土地勘メモ</b>", st["b"]))
        for s in spec["market_notes"]:
            flows.append(P("・" + s, st["b"]))
    _page_with_flows(c, spec, "土地の概況（公開データ）", "01", flows,
                     notes=["確実性：確定＝公的資料・条文で確認／要確認＝窓口・現地・原本で確かめるまで未確定／推測＝地図・写真・一般傾向からの見立て"])


def building_page(c, spec, demo):
    st = _styles()
    b = spec["building"]
    q = demo["quantities"]
    rows = [["項目", "推定値", "根拠（写真・基準物）"]]
    for r in b.get("measure_basis", []):
        rows.append([r["item"], r["value"], r.get("basis", "")])
    flows = [P("<b>建物の推定寸法と根拠</b>", st["b"]), _table(rows, [55, 60, 265])]
    rows2 = [["数量項目", "数量", "算出"],
             ["建築面積", f"{q['building_area_m2']:.1f} ㎡", "外形寸法から"],
             ["延床面積", f"{q['floor_area_m2']:.1f} ㎡（{q['floor_area_tsubo']:.1f}坪）", f"{b.get('floors')}階建"],
             ["外周長", f"{q['perimeter_m']:.1f} m", ""],
             ["足場架面積", f"{q['scaffold_m2']:.1f} ㎡", "(外周+8m)×(軒高+1m)"]]
    if q.get("units_count"):
        chk = q.get("units_area_check_m2")
        rows2.append(["戸数・間取り", f"{q['units_count']}戸（{q.get('units_layout', '')}）",
                      f"専有合計 約{chk:.0f}㎡（延床との差＝共用部・壁芯差）" if chk else ""])
    for a in q.get("annexes", []):
        rows2.append([a["name"], f"{a['area_m2']:.1f} ㎡", a.get("kind", "")])
    if q.get("asbestos_suspect_parts"):
        rows2.append(["アスベスト含有の可能性がある部位", "、".join(q["asbestos_suspect_parts"]), f"推定築年 {b.get('built_year_est')}年頃"])
    flows += [P("<b>解体数量（建物）</b>", st["b"]), _table(rows2, [55, 80, 245])]
    lo = demo["leftover"]
    if lo["furniture"]:
        rows3 = [["品目", "想定数量", "体積(㎥)", "家電リサイクル"]]
        for f in lo["furniture"]:
            rows3.append([f["name"], f"{f['qty']:g}", f"{f['m3']:.2f}", f.get("recycle") or ""])
        flows += [P(f"<b>残置物（家財）の推定</b>　{lo['layout']} × {lo['occupied_units']}戸、"
                            f"積込み体積 約{lo['volume_m3']}㎥（家財リスト換算 {lo['volume_from_list_m3']}㎥ ／ 相場表 {lo['volume_from_table_m3']}㎥ ／ 屋外 {lo['extra_m3']}㎥）", st["b"]),
                  _table(rows3, [80, 30, 30, 40], align_right_cols=(1, 2))]
    _page_with_flows(c, spec, "建物・数量の推定", "02", flows)


def estimate_page(c, spec, est, title, sheet_no, extra_lines=None, conditions=None):
    st = _styles()
    rows = [["区分", "項目", "数量", "単位", "単価（標準）", "金額（標準）", "安め", "高め", "算出根拠", "出典"]]
    for ln in est["lines"] + (extra_lines or []):
        p = ln.get("price") or {}
        rows.append([ln["cat"], ln["name"], f"{ln['qty']:,.1f}" if isinstance(ln["qty"], float) else f"{ln['qty']:,}",
                     ln["unit"], yen(p.get("mid")), yen(ln["mid"]), yen(ln["low"]), yen(ln["high"]),
                     ln.get("basis", ""), ",".join(ln.get("src", []))])
    flows = [_table(rows, [24, 82, 18, 12, 24, 28, 24, 24, 110, 22], align_right_cols=(2, 4, 5, 6, 7), font_size=7.8)]
    sub, over, tot = est["subtotal"], est["overhead"], est["total"]
    sm = [["", "安め", "標準", "高め"],
          ["小計（地域係数・条件割増 反映後）", yen(sub["low"]), yen(sub["mid"]), yen(sub["high"])],
          [f"諸経費（{est['overhead_rate']['low'] * 100:.0f}〜{est['overhead_rate']['high'] * 100:.0f}%）", yen(over["low"]), yen(over["mid"]), yen(over["high"])],
          ["合計（税別）", yen(tot["low"]), yen(tot["mid"]), yen(tot["high"])]]
    flows.append(_table(sm, [80, 40, 40, 40], align_right_cols=(1, 2, 3)))
    memo = [f"地域係数 ×{est.get('region_factor', 1.0)}"]
    if conditions:
        memo += conditions
    flows.append(P("適用：" + "／".join(memo) + "。単価の出典は巻末「出典一覧」。単価を自社単価に差し替える場合は同梱の Excel を使用。", st["s"]))
    if extra_lines:
        flows.append(P("※「アスベスト（含有時のみ）」の行は合計に含めていません。", st["s"]))
    _page_with_flows(c, spec, title, sheet_no, flows)


def notes_page(c, spec, demo, gest):
    st = _styles()
    flows = [P("<b>次に確認すること（見積・設計の精度を上げるため）</b>", st["b"])]
    for s in spec.get("next_checks", []):
        flows.append(P("□ " + s, st["b"]))
    flows.append(P("<b>出典一覧（単価・データ）</b>", st["b"]))
    rows = [["ID", "出典", "URL", "確認日"]]
    seen = set()
    for est in (demo, gest):
        if not est:
            continue
        for s in est.get("sources", []):
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            rows.append([s["id"], s.get("title", ""), s.get("url", ""), s.get("accessed", "")])
    for s in spec.get("data_attribution", []):
        rows.append(["-", s, "", ""])
    flows.append(_table(rows, [12, 120, 200, 22], font_size=7.2))
    _page_with_flows(c, spec, "確認事項・出典", "99", flows)


# ---------- Excel ----------

def write_xlsx(path, spec, demo, gest):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    first = True
    for est, name in ((demo, "解体概算"), (gest, "造成概算")):
        if not est:
            continue
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name
        ws.append([f"{spec.get('project', {}).get('name', '')}　{name}（参考・税別）"])
        ws.append(["単価列（F〜H）を自社単価に書き換えると金額が再計算されます。地域係数・条件割増は J列の係数に反映済み。"])
        hdr = ["区分", "項目", "数量", "単位", "根拠", "単価 安め", "単価 標準", "単価 高め", "金額 標準", "係数", "出典"]
        ws.append(hdr)
        for cell in ws[3]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E8ECF2")
        rf = est.get("region_factor", 1.0)
        cf = est.get("condition_factor", 1.0)
        start = 4
        for ln in est["lines"]:
            p = ln.get("price") or {}
            k = 1.0 if ln["cat"] in ("手続", "調査・設計") else rf * (cf if ln["cat"] in ("建物本体", "付帯工事") else 1.0)
            r = ws.max_row + 1
            ws.append([ln["cat"], ln["name"], ln["qty"], ln["unit"], ln.get("basis", ""), p.get("low"), p.get("mid"), p.get("high"),
                       f"=C{r}*G{r}*J{r}", round(k, 3), ",".join(ln.get("src", []))])
        end = ws.max_row
        ws.append([])
        r = ws.max_row + 1
        ws.append(["", "小計", "", "", "", "", "", "", f"=SUM(I{start}:I{end})"])
        ov = est["overhead_rate"]["mid"]
        ws.append(["", f"諸経費（{ov * 100:.0f}%）", "", "", "", "", "", "", f"=I{r}*{ov}"])
        ws.append(["", "合計（税別）", "", "", "", "", "", "", f"=I{r}+I{r + 1}"])
        for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
            for cell in row[5:9]:
                cell.number_format = "#,##0"
        widths = [12, 46, 9, 6, 50, 11, 11, 11, 13, 7, 12]
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"].alignment = Alignment(wrap_text=False)
    if demo and demo["leftover"]["furniture"]:
        ws = wb.create_sheet("残置物推定")
        ws.append(["品目", "想定数量", "体積(㎥)", "家電リサイクル"])
        for f in demo["leftover"]["furniture"]:
            ws.append([f["name"], f["qty"], round(f["m3"], 2), f.get("recycle") or ""])
    wb.save(path)


# ---------- DXF ----------

class DxfView:
    """elevation.draw_face 等をそのまま DXF に出すための View 互換クラス（単位 mm）。"""

    def __init__(self, msp, ox=0.0, oy=0.0, layer="0"):
        self.msp = msp
        self.ox, self.oy = ox, oy
        self.layer = layer
        self.scale = 1
        self.c = None

    def P(self, x, y):
        return (self.ox + x * 1000, self.oy + y * 1000)

    def line(self, x0, y0, x1, y1, w=0.25, color=None, dash=None):
        self.msp.add_line(self.P(x0, y0), self.P(x1, y1), dxfattribs={"layer": self.layer})

    def polyline(self, pts, w=0.25, color=None, closed=False, fill=None, dash=None):
        if len(pts) >= 2:
            self.msp.add_lwpolyline([self.P(*p) for p in pts], close=closed, dxfattribs={"layer": self.layer})

    def rect(self, x, y, w, h, lw=0.25, color=None, fill=None, dash=None):
        self.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], closed=True)

    def text(self, x, y, s, size=2.5, anchor="l", color=None, angle=0, dy_mm=0.0):
        t = self.msp.add_text(s, height=size * 40, rotation=angle, dxfattribs={"layer": "TEXT", "style": "JP"})
        t.set_placement(self.P(x, y))

    def hatch(self, *a, **k):
        pass

    def ellipse(self, cx, cy, rx, ry, w=0.25, color=None, dash=None):
        if rx >= ry:
            self.msp.add_ellipse(self.P(cx, cy), major_axis=(rx * 1000, 0), ratio=ry / rx, dxfattribs={"layer": self.layer})
        else:
            self.msp.add_ellipse(self.P(cx, cy), major_axis=(0, ry * 1000), ratio=rx / ry, dxfattribs={"layer": self.layer})

    def len_mm(self, m):
        return m * 1000

    def p(self, x, y):
        return self.P(x, y)

    def dim_h(self, x0, x1, y, off_mm=6.0, label=None, size=2.3):
        d = self.msp.add_linear_dim(base=(self.ox + x0 * 1000, self.oy + y * 1000 + off_mm * 100),
                                    p1=self.P(x0, y), p2=self.P(x1, y), dimstyle="EZDXF",
                                    override={"dimtxt": 150, "dimasz": 80}, dxfattribs={"layer": "DIM"})
        d.render()

    def dim_v(self, y0, y1, x, off_mm=6.0, label=None, size=2.3):
        d = self.msp.add_linear_dim(base=(self.ox + x * 1000 + off_mm * 100, self.oy + y0 * 1000),
                                    p1=self.P(x, y0), p2=self.P(x, y1), angle=90, dimstyle="EZDXF",
                                    override={"dimtxt": 150, "dimasz": 80}, dxfattribs={"layer": "DIM"})
        d.render()

    def level_mark(self, x, y, label, size=2.3, right=True):
        self.text(x, y, "▽" + label, size)


def write_dxf(path, spec, grad):
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.styles.add("JP", font="msgothic.ttc")
    for name in ("ELEV", "SITE", "WALL", "CONTOUR", "TEXT", "DIM", "LEVEL"):
        if name not in doc.layers:
            doc.layers.add(name)
    msp = doc.modelspace()
    # 立面図（横に並べる）
    ox = 0.0
    for f in spec.get("building", {}).get("elevations", []):
        v = DxfView(msp, ox, 0, "ELEV")
        elevation.draw_face(v, f)
        elevation.draw_face_dims(v, f)
        v.text(0, -1.5, f["name"], 3)
        x0, x1, _, _ = elevation.face_extent(f)
        ox += (x1 - x0 + 8) * 1000
    # 造成計画平面
    if grad:
        site = spec["site"]
        base_y = -40000
        v = DxfView(msp, 0, base_y, "SITE")
        v.polyline([tuple(p) for p in site["boundary"]], closed=True)
        kbm = grad["road"]["center_avg"] if grad.get("road") else grad["fh_m"]
        vw = DxfView(msp, 0, base_y, "WALL")
        for w in grad["walls"]:
            if w["type"] != "none":
                vw.line(*w["a"], *w["b"])
                vw.text((w["a"][0] + w["b"][0]) / 2, (w["a"][1] + w["b"][1]) / 2, f"{w['type_name']} H={w['h_max']:.2f}", 2)
        vc = DxfView(msp, 0, base_y, "CONTOUR")
        xs = [p[0] for p in site["boundary"]]
        ys = [p[1] for p in site["boundary"]]
        segs = grading_draw._contours(grad["surface"].z, min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3, 0.5,
                                      0.25 if grad["existing_diff"] < 2 else 0.5)
        for lv, p, q in segs:
            vc.line(*p, *q)
        vl = DxfView(msp, 0, base_y, "LEVEL")
        step = 3.0
        y = min(ys) + 1
        while y < max(ys):
            x = min(xs) + 1
            while x < max(xs):
                if grading.point_in_poly(x, y, site["boundary"]):
                    vl.text(x, y, f"FH{grad['plan_z'](x, y) - kbm:+.2f} ({grad['surface'].z(x, y) - kbm:+.2f})", 1.6)
                x += step
            y += step
    doc.saveas(path)


# ---------- メイン ----------

def build(spec, out_dir, base_dir):
    os.makedirs(out_dir, exist_ok=True)
    spec.setdefault("project", {}).setdefault("date", datetime.date.today().isoformat())
    demo = demolition.estimate(spec) if spec.get("building") else None
    grad = gest = None
    if spec.get("site"):
        grad, gest = grading.plan_and_estimate(spec)
    stem = spec.get("project", {}).get("slug", "site_report")
    pdf_path = os.path.join(out_dir, f"{stem}.pdf")
    c = rl_canvas.Canvas(pdf_path, pagesize=landscape(A3))
    c.setTitle(spec.get("project", {}).get("name", "現地写真 調査レポート"))
    cover_page(c, spec, demo, grad, gest)
    site_info_page(c, spec, grad)
    photo_pages(c, spec, base_dir)
    if demo:
        building_page(c, spec, demo)
        elevation.render_elevations(c, spec)
    if grad:
        grading_draw.render_plan(c, spec, grad, title="現況平面図・解体範囲図（参考）", sheet_no="B-01", mode="existing")
    if demo:
        estimate_page(c, spec, demo, "解体工事 概算見積（参考）", "D-01", extra_lines=demo["asbestos_extra"],
                      conditions=demo["conditions_applied"])
    if grad:
        grading_draw.render_plan(c, spec, grad)
        grading_draw.render_sections(c, spec, grad)
        estimate_page(c, spec, gest, "造成工事 概算見積（参考）", "E-01")
    notes_page(c, spec, demo, gest)
    c.save()
    xlsx_path = os.path.join(out_dir, f"{stem}_見積.xlsx")
    write_xlsx(xlsx_path, spec, demo, gest)
    dxf_path = os.path.join(out_dir, f"{stem}_図面.dxf")
    try:
        write_dxf(dxf_path, spec, grad)
    except Exception as e:  # DXF は補助出力なので失敗してもレポートは出す
        dxf_path = f"(DXF出力失敗: {e})"
    summary = {"pdf": pdf_path, "xlsx": xlsx_path, "dxf": dxf_path}
    if demo:
        summary["demolition_total"] = {k: round(v) for k, v in demo["total"].items()}
        summary["floor_area_m2"] = round(demo["quantities"]["floor_area_m2"], 1)
        summary["floor_area_tsubo"] = round(demo["quantities"]["floor_area_tsubo"], 1)
        summary["per_tsubo_mid"] = round(demo["per_tsubo_mid"] or 0)
        summary["asbestos_extra"] = [{k: (round(v) if isinstance(v, float) else v) for k, v in a.items() if k in ("name", "low", "mid", "high")}
                                     for a in demo["asbestos_extra"]]
        summary["demolition_lines"] = [{"cat": l["cat"], "name": l["name"], "qty": l["qty"], "unit": l["unit"],
                                        "mid": round(l["mid"]) if l["mid"] is not None else None} for l in demo["lines"]]
    if grad:
        summary["grading_total"] = {k: round(v) for k, v in gest["total"].items()}
        summary["grading"] = {k: grad[k] for k in ("area_m2", "fh_m", "fh_basis", "cut_m3", "fill_m3", "existing_diff", "flags")}
        kbm = grad["road"]["center_avg"] if grad.get("road") else 0.0
        summary["kbm_tp"] = round(kbm, 2)
        summary["alternatives"] = [{**a, "fh_rel": round(a["fh_m"] - kbm, 2), "total_mid": round(a["total_mid"])}
                                   for a in grad.get("alternatives", [])]
        summary["grading_lines"] = [{"cat": l["cat"], "name": l["name"], "qty": l["qty"], "unit": l["unit"],
                                     "mid": round(l["mid"]) if l["mid"] is not None else None} for l in gest["lines"]]
        summary["walls"] = [{k: w[k] for k in ("index", "length_m", "h_max", "type_name", "side")} for w in grad["walls"]]
    return summary
