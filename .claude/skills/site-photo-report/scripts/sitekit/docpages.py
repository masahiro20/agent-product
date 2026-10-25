"""報告書・見積書のページ（A4縦）。図面（A3横）は elevation / grading_draw が描く。

読みやすさの方針:
- 本文 9.5pt 前後・表 8.5〜9pt。1ページに詰め込まず、表は区分ごとに小計を入れる
- 金額は「標準」を主役にし、幅（安め〜高め）は総括と合計行だけに出す
- 根拠は項目名の下に小さく添える（別列にしない）。出典は巻末に、使った単価のものだけ載せる
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle


class KeepTogether(Flowable):
    """見出しと表など、ページをまたがせたくないまとまり（入らなければ丸ごと次のページへ）。"""

    def __init__(self, items, gap_mm=1.5):
        super().__init__()
        self.items, self.gap = items, gap_mm * MM
        self._sizes = []

    def wrap(self, aw, ah):
        self._sizes = [it.wrap(aw, 10 ** 6) for it in self.items]
        self.width = aw
        self.height = sum(h for _, h in self._sizes) + self.gap * (len(self.items) - 1)
        return aw, self.height

    def split(self, aw, ah):
        return []

    def draw(self):
        y = self.height
        for it, (_, h) in zip(self.items, self._sizes):
            y -= h
            it.drawOn(self.canv, 0, y)
            y -= self.gap

from .common import FONT, MM, ensure_font, yen
from .drawing import jp

INK = colors.HexColor("#333333")
SUB = colors.HexColor("#7a7f85")
LINE = colors.HexColor("#cdd6dd")
SOFT = colors.HexColor("#f3f5f6")
ACCENT = colors.HexColor("#8c9baa")
GOLD = colors.HexColor("#a18c4c")
GOLD_SOFT = colors.HexColor("#f6f1e4")
RED = colors.HexColor("#a94442")

PW, PH = A4[0] / MM, A4[1] / MM  # 210 x 297 mm
ML, MR, MT, MB = 18.0, 18.0, 24.0, 20.0
CW = PW - ML - MR  # 本文幅 174mm

COMPANY = os.environ.get("COMPANY_NAME", "")


def man(v):
    return "-" if v is None else f"{v / 10000:,.0f}万円"


def st():
    ensure_font()
    registerFontFamily(FONT, normal=FONT, bold=FONT, italic=FONT, boldItalic=FONT)
    base = dict(fontName=FONT, textColor=INK)
    return {
        "body": ParagraphStyle("body", fontSize=9.5, leading=15, **base),
        "small": ParagraphStyle("small", fontSize=8, leading=11.5, textColor=SUB, fontName=FONT),
        "cell": ParagraphStyle("cell", fontSize=8.8, leading=12, **base),
        "cell_sub": ParagraphStyle("cell_sub", fontSize=7.3, leading=9.5, textColor=SUB, fontName=FONT),
        "cell_r": ParagraphStyle("cell_r", fontSize=8.8, leading=12, alignment=2, **base),
        "h2": ParagraphStyle("h2", fontSize=12, leading=18, spaceBefore=4, spaceAfter=4, **base),
        "bullet": ParagraphStyle("bullet", fontSize=9.5, leading=15, leftIndent=10, firstLineIndent=-10, **base),
    }


def P(text, style):
    return Paragraph(jp(text).replace("\n", "<br/>"), style)


# ---------- ページの枠 ----------

class Doc:
    """ページ番号・ヘッダー・フッターを管理する。2回描いて総ページ数を入れる。"""

    def __init__(self, c, spec, total=None, header="現地写真 調査レポート"):
        self.c, self.spec, self.total, self.header = c, spec, total, header
        self.page = 0
        # 図面側（elevation / grading_draw）も c.showPage() でページを閉じるので、そこでページ番号を入れる
        self._show = c.showPage
        c.showPage = self._show_page

    def _show_page(self):
        self.page += 1
        if self.c._pagesize[0] / MM > 300:  # A3 横の図面
            t = f"{self.page} / {self.total}" if self.total else f"{self.page}"
            self.text(420 / 2, 4.2, t, 7.5, SUB, "c")
        else:
            self.footer()
        self._show()

    def a4(self, title_en=None, title_ja=None):
        c = self.c
        c.setPageSize(A4)
        p = self.spec.get("project", {})
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(ML * MM, (PH - 14) * MM, (PW - MR) * MM, (PH - 14) * MM)
        self.text(ML, PH - 11.5, f"{self.header}｜{p.get('name', '')}"[:48], 7.5, SUB)
        self.text(PW - MR, PH - 11.5, COMPANY or p.get("author", ""), 7.5, SUB, "r")
        y = PH - MT
        if title_ja:
            if title_en:
                self.text(ML, y - 1, title_en, 7.5, ACCENT, spacing=2)
                y -= 5
            self.text(ML, y - 6, title_ja, 16, INK)
            c.setStrokeColor(GOLD)
            c.setLineWidth(1.2)
            c.line(ML * MM, (y - 10) * MM, (ML + 14) * MM, (y - 10) * MM)
            y -= 16
        return y

    def footer(self):
        t = f"{self.page} / {self.total}" if self.total else f"{self.page}"
        self.text(PW / 2, 9, t, 8, SUB, "c")
        self.text(ML, 9, "参考資料：現地写真・公開データからの推定値を含みます", 7, SUB)
        self.text(PW - MR, 9, self.spec.get("project", {}).get("date", ""), 7, SUB, "r")

    def text(self, x, y, s, size, color=INK, anchor="l", spacing=0):
        c = self.c
        ensure_font()
        c.saveState()
        c.setFont(FONT, size)
        c.setFillColor(color)
        s = jp(s)
        if spacing:
            to = c.beginText()
            to.setTextOrigin(x * MM, y * MM)
            to.setFont(FONT, size)
            to.setCharSpace(spacing)
            to.textLine(s)
            c.drawText(to)
        elif anchor == "r":
            c.drawRightString(x * MM, y * MM, s)
        elif anchor == "c":
            c.drawCentredString(x * MM, y * MM, s)
        else:
            c.drawString(x * MM, y * MM, s)
        c.restoreState()

    def flow(self, flows, title_en, title_ja, y=None):
        """flowable を A4 に流し込む。はみ出したら次ページ（見出しは「（続き）」）。"""
        y = self.a4(title_en, title_ja) if y is None else y
        queue = list(flows)
        while queue:
            f = queue.pop(0)
            if f == "PAGEBREAK":
                self.c.showPage()
                y = self.a4(title_en, (title_ja + "（続き）") if title_ja else None)
                continue
            avail = y - MB
            w, h = f.wrapOn(self.c, CW * MM, avail * MM)
            if h / MM <= avail:
                f.drawOn(self.c, ML * MM, (y * MM) - h)
                y -= h / MM + 3
                continue
            if isinstance(f, KeepTogether) and h / MM < PH - MT - MB - 30:
                # まとめて次のページへ
                queue.insert(0, f)
                self.c.showPage()
                y = self.a4(title_en, (title_ja + "（続き）") if title_ja else None)
                continue
            parts = f.split(CW * MM, avail * MM) if avail > 25 else []
            if parts and "Break" in parts[0].__class__.__name__:  # KeepTogether が「次ページへ」と返した
                queue = parts[1:] + queue
                parts = []
                self.c.showPage()
                y = self.a4(title_en, (title_ja + "（続き）") if title_ja else None)
                continue
            if parts and len(parts) > 1:
                w, h = parts[0].wrapOn(self.c, CW * MM, avail * MM)
                parts[0].drawOn(self.c, ML * MM, (y * MM) - h)
                queue = parts[1:] + queue
            else:
                queue.insert(0, f)
            self.c.showPage()
            y = self.a4(title_en, (title_ja + "（続き）") if title_ja else None)
        self.c.showPage()


# ---------- 表 ----------

def table(rows, widths, header=True, styles=(), repeat=1):
    t = Table(rows, colWidths=[w * MM for w in widths], repeatRows=repeat if header else 0)
    base = [("FONT", (0, 0), (-1, -1), FONT, 8.8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE)]
    if header:
        base += [("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONT", (0, 0), (-1, 0), FONT, 8.3)]
    t.setStyle(TableStyle(base + list(styles)))
    return t


def hcell(s):
    return Paragraph(jp(s), ParagraphStyle("h", fontName=FONT, fontSize=8.3, leading=11, textColor=colors.white))


def name_cell(name, sub=None, S=None):
    S = S or st()
    if sub:
        return [P(name, S["cell"]), P(sub, S["cell_sub"])]
    return P(name, S["cell"])


def qty_s(q):
    if q is None:
        return ""
    if isinstance(q, float) and not q.is_integer():
        return f"{q:,.1f}"
    return f"{int(q):,}"


# ---------- 各ページ ----------

def cover(doc, spec, demo, grad, gest):
    S = st()
    c = doc.c
    doc.a4()
    p = spec.get("project", {})
    y = PH - 34
    if COMPANY:
        doc.text(ML, y, COMPANY, 9, SUB, spacing=3)
    y -= 16
    doc.text(ML, y, "現地写真 調査レポート", 24)
    y -= 9
    doc.text(ML, y, p.get("purpose", "解体概算・造成計画"), 11, ACCENT, spacing=1)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.4)
    c.line(ML * MM, (y - 5) * MM, (ML + 18) * MM, (y - 5) * MM)
    y -= 18
    rows = [("物件名", p.get("name", "")), ("所在地", p.get("address", "")), ("作成日", p.get("date", "")),
            ("作成", p.get("author", ""))]
    for k, v in rows:
        doc.text(ML, y, k, 8.5, SUB)
        doc.text(ML + 18, y, v[:46], 10.5)
        y -= 7
    y -= 6

    # 概算の大きな数字
    boxes = []
    if demo:
        boxes.append(("解体工事", demo["total"], f"延床 約{demo['quantities']['floor_area_m2']:.0f}㎡（{demo['quantities']['floor_area_tsubo']:.1f}坪）"))
    if gest:
        boxes.append(("造成工事", gest["total"], f"敷地 約{grad['area_m2']:.0f}㎡"))
    if demo and gest:
        boxes.append(("合計", {k: demo["total"][k] + gest["total"][k] for k in ("low", "mid", "high")}, "解体＋造成"))
    if boxes:
        n = len(boxes)
        gap = 4
        bw = (CW - gap * (n - 1)) / n
        bh = 34
        for i, (label, t, note) in enumerate(boxes):
            x = ML + i * (bw + gap)
            total = label == "合計"
            c.setFillColor(INK if total else SOFT)
            c.rect(x * MM, (y - bh) * MM, bw * MM, bh * MM, stroke=0, fill=1)
            fc = colors.white if total else INK
            doc.text(x + bw / 2, y - 8, label, 10, fc, "c")
            doc.text(x + bw / 2, y - 19, f"{t['mid'] / 10000:,.0f}", 22, colors.HexColor("#e9dcb4") if total else GOLD, "c")
            doc.text(x + bw / 2 + 15, y - 19, "万円", 9, fc, "l")
            doc.text(x + bw / 2, y - 25.5, f"幅 {t['low'] / 10000:,.0f}〜{t['high'] / 10000:,.0f}万円（税別）", 7.5,
                     colors.HexColor("#cccccc") if total else SUB, "c")
            doc.text(x + bw / 2, y - 30.5, note, 7.5, colors.HexColor("#cccccc") if total else SUB, "c")
        y -= bh + 4
        if demo and demo["asbestos_extra"]:
            a = demo["asbestos_extra"][0]
            doc.text(ML, y - 3, f"※ アスベスト含有が判明した場合は、別途 約{a['mid'] / 10000:,.0f}万円（{a['low'] / 10000:,.0f}〜{a['high'] / 10000:,.0f}万円）が加わります。", 8, RED)
            y -= 6
    y -= 6

    # 要点と航空写真
    aer = spec.get("terrain", {}).get("aerial_photo")
    text_w = CW
    if aer and os.path.exists(aer):
        side = 62
        c.drawImage(ImageReader(aer), (PW - MR - side) * MM, (y - side) * MM, side * MM, side * MM, preserveAspectRatio=True)
        doc.text(PW - MR - side, y - side - 4, "航空写真（国土地理院）・中心＝住所の代表点", 6.8, SUB)
        text_w = CW - side - 6
    doc.text(ML, y - 2, "この物件の要点", 11)
    y -= 7
    for s in spec.get("summary", [])[:7]:
        para = P("・" + s, S["bullet"])
        w, h = para.wrapOn(c, text_w * MM, 60 * MM)
        para.drawOn(c, ML * MM, y * MM - h)
        y -= h / MM + 1.2

    # 精度の注意（ページ下部）
    box_y = MB + 6
    c.setFillColor(SOFT)
    c.rect(ML * MM, box_y * MM, CW * MM, 22 * MM, stroke=0, fill=1)
    doc.text(ML + 4, box_y + 16, "この資料について", 9)
    para = P("現地写真と公開データ（国土地理院の標高・航空写真、国交省の都市計画データ等）からの推定で作成した参考資料です。"
             "寸法・数量は±10〜20%、高さは±0.2〜0.5m程度の誤差を含みます。正式な見積・設計には、現地調査・測量・地盤調査・アスベスト事前調査が必要です。",
             S["small"])
    para.wrapOn(c, (CW - 8) * MM, 20 * MM)
    para.drawOn(c, (ML + 4) * MM, (box_y + 3) * MM)
    c.showPage()


def summary_page(doc, spec, demo, grad, gest):
    S = st()
    c = doc.c
    y = doc.a4("ESTIMATE", "概算見積書（総括）")
    tot = {"low": 0, "mid": 0, "high": 0}
    for e in (demo, gest):
        if e:
            for k in tot:
                tot[k] += e["total"][k]
    # 金額ボックス
    c.setFillColor(GOLD_SOFT)
    c.rect(ML * MM, (y - 24) * MM, CW * MM, 24 * MM, stroke=0, fill=1)
    doc.text(ML + 6, y - 9, "概算金額（税別）", 10)
    doc.text(ML + 6, y - 19, f"{yen(tot['mid'])} 円", 20, INK)
    doc.text(PW - MR - 6, y - 9, "金額の幅（安め〜高め）", 8, SUB, "r")
    doc.text(PW - MR - 6, y - 17, f"{yen(tot['low'])} 〜 {yen(tot['high'])} 円", 11, INK, "r")
    y -= 32

    rows = [[hcell("工事区分"), hcell("概算（標準）"), hcell("幅（安め〜高め）"), hcell("主な内容")]]
    if demo:
        q = demo["quantities"]
        rows.append([P("解体工事", S["cell"]), P(yen(demo["total"]["mid"]) + " 円", S["cell_r"]),
                     P(f"{man(demo['total']['low'])}〜{man(demo['total']['high'])}", S["cell_r"]),
                     P(f"建物本体 延床約{q['floor_area_m2']:.0f}㎡、付帯・外構、残置物、届出 ／ 坪単価 約{(demo['per_tsubo_mid'] or 0) / 10000:.1f}万円", S["cell_sub"])])
    if gest:
        rows.append([P("造成工事", S["cell"]), P(yen(gest["total"]["mid"]) + " 円", S["cell_r"]),
                     P(f"{man(gest['total']['low'])}〜{man(gest['total']['high'])}", S["cell_r"]),
                     P(f"土工（切土{grad['cut_m3']:.0f}㎥・盛土{grad['fill_m3']:.0f}㎥）、擁壁・土留め、排水、測量・地盤調査", S["cell_sub"])])
    rows.append([P("合計（税別）", S["cell"]), P(yen(tot["mid"]) + " 円", S["cell_r"]),
                 P(f"{man(tot['low'])}〜{man(tot['high'])}", S["cell_r"]), ""])
    t = table(rows, [28, 34, 36, 76], styles=[("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), SOFT),
                                              ("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 0.8, INK)])
    flows = [t, Spacer(1, 6 * MM), P("見積の条件", S["h2"])]
    conds = []
    if demo:
        conds.append(f"単価は公開相場（巻末の出典）の標準値。地域係数 ×{demo['region_factor']}"
                     + (f"、施工条件の割増 {'／'.join(demo['conditions_applied'])}" if demo["conditions_applied"] else "") + "。")
        conds.append(f"解体の諸経費は直接工事費の {demo['overhead_rate']['mid'] * 100:.0f}%（幅 {demo['overhead_rate']['low'] * 100:.0f}〜{demo['overhead_rate']['high'] * 100:.0f}%）。")
        conds.append("建物本体の単価には、足場・養生、通常の基礎撤去、廃材の運搬処分、簡易整地を含みます。")
    if gest:
        conds.append(f"造成の諸経費は {gest['overhead_rate']['mid'] * 100:.0f}%。計画地盤は「{grad['fh_basis']}」で設定。")
    for s in conds:
        flows.append(P("・" + s, S["bullet"]))
    flows += [Spacer(1, 3 * MM), P("含まれないもの（別途）", S["h2"])]
    excl = []
    if demo and demo["asbestos_extra"]:
        a = demo["asbestos_extra"][0]
        excl.append(f"アスベスト除去（事前調査で含有が判明した場合）：約{man(a['mid'])}（{man(a['low'])}〜{man(a['high'])}）")
    excl += ["地中埋設物（古い基礎・浄化槽・ガラ等）の撤去", "境界確定測量、建物の設計・確認申請費", "消費税"]
    for s in excl:
        flows.append(P("・" + s, S["bullet"]))
    flows += [Spacer(1, 4 * MM), P("内訳は次ページ以降（解体工事内訳書・造成工事内訳書）。単価を自社単価に置き換える場合は同梱の Excel を使ってください。", S["small"])]
    doc.flow(flows, "ESTIMATE", "概算見積書（総括）", y=y)


def detail_page(doc, est, title_ja, extra=None, notes=None):
    """内訳書：区分ごとに見出し行と小計。金額は標準値。"""
    S = st()
    rows = [[hcell("名称・根拠"), hcell("数量"), hcell("単位"), hcell("単価"), hcell("金額")]]
    styles = []
    cats = []
    for ln in est["lines"]:
        if ln["cat"] not in cats:
            cats.append(ln["cat"])
    for cat in cats:
        lines = [ln for ln in est["lines"] if ln["cat"] == cat]
        rows.append([P(cat, S["cell"]), "", "", "", ""])
        styles += [("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), SOFT), ("SPAN", (0, len(rows) - 1), (-1, len(rows) - 1))]
        sub = 0.0
        for ln in lines:
            price = (ln.get("price") or {}).get("mid")
            rows.append([name_cell(ln["name"], ln.get("basis") or None, S), P(qty_s(ln["qty"]), S["cell_r"]),
                         P(ln["unit"], S["cell"]), P(yen(price), S["cell_r"]), P(yen(ln["mid"]), S["cell_r"])])
            sub += ln["mid"] or 0
        rows.append(["", P(f"{cat} 小計", ParagraphStyle("st", parent=S["cell_sub"], alignment=2)), "", "", P(yen(sub), S["cell_r"])])
        r = len(rows) - 1
        styles += [("SPAN", (1, r), (3, r)), ("LINEABOVE", (1, r), (4, r), 0.5, SUB)]
    sub, over, tot = est["subtotal"], est["overhead"], est["total"]
    raw = sum((ln["mid"] or 0) for ln in est["lines"])
    adj = sub["mid"] - raw
    foot = [("直接工事費 計", raw)]
    if abs(adj) >= 1:
        foot.append(("地域係数・施工条件の割増", adj))
    foot += [(f"諸経費（{est['overhead_rate']['mid'] * 100:.0f}%）", over["mid"]), ("合計（税別）", tot["mid"])]
    for k, (label, v) in enumerate(foot):
        rows.append(["", P(label, ParagraphStyle("ft", parent=S["cell"], alignment=2)), "", "", P(yen(v), S["cell_r"])])
        r = len(rows) - 1
        styles.append(("SPAN", (1, r), (3, r)))
        if k == 0:
            styles.append(("LINEABOVE", (0, r), (-1, r), 0.8, INK))
        if label.startswith("合計"):
            styles += [("BACKGROUND", (1, r), (4, r), GOLD_SOFT), ("LINEABOVE", (1, r), (4, r), 0.8, INK)]
    t = table(rows, [96, 16, 12, 22, 28], styles=styles)
    flows = [t, Spacer(1, 3 * MM),
             P(f"金額の幅（安め〜高め）：{yen(tot['low'])} 〜 {yen(tot['high'])} 円（税別）。単価は公開相場の標準値（出典は巻末）。", S["small"])]
    if extra:
        flows += [Spacer(1, 4 * MM), P("別途（合計に含めない）", S["h2"])]
        for ln in extra:
            flows.append(P(f"・{ln['name']}：数量 {qty_s(ln['qty'])}{ln['unit']} × 単価 {yen((ln.get('price') or {}).get('mid'))} 円 ＝ 約{yen(ln['mid'])} 円"
                           f"（{yen(ln['low'])}〜{yen(ln['high'])}）。{ln.get('basis', '')}", S["bullet"]))
    for n in notes or []:
        flows.append(n)
    doc.flow(flows, "BREAKDOWN", title_ja)


def grading_notes(grad):
    S = st()
    kbm = grad["road"]["center_avg"] if grad.get("road") else grad["fh_m"]
    out = [Spacer(1, 5 * MM)]
    head = P("計画地盤の高さの比較", S["h2"])
    rows = [[hcell("案"), hcell("計画高"), hcell("切土／盛土"), hcell("擁壁"), hcell("概算")]]
    for i, a in enumerate(grad.get("alternatives", [])):
        label = a["label"].replace("採用案：", "【採用】")
        if a["below_road"]:
            label += "（道路より低い：排水対策が前提）"
        rows.append([P(label, S["cell"]), P(f"{a['fh_m'] - kbm:+.2f} m", S["cell_r"]),
                     P(f"{a['cut_m3']:.0f}／{a['fill_m3']:.0f} ㎥", S["cell_r"]), P(f"{a['wall_m']:.0f} m", S["cell_r"]),
                     P(man(a["total_mid"]), S["cell_r"])])
    if len(rows) > 1:
        out.append(KeepTogether([head, table(rows, [82, 20, 28, 18, 26], styles=[("BACKGROUND", (0, 1), (-1, 1), GOLD_SOFT)]),
                                 P("計画高は前面道路中心（KBM）を±0とした高さ。", S["small"])]))
    out += [Spacer(1, 4 * MM), P("法規チェック（区域指定・自治体基準は要確認）", S["h2"])]
    for f in grad["flags"]:
        out.append(P("・" + f, S["bullet"]))
    return out


def quantities_page(doc, spec, demo):
    S = st()
    b = spec["building"]
    q = demo["quantities"]
    flows = [P("建物の推定寸法と根拠", S["h2"])]
    rows = [[hcell("項目"), hcell("推定値"), hcell("根拠（写真・基準物）")]]
    for r in b.get("measure_basis", []):
        rows.append([P(r["item"], S["cell"]), P(r["value"], S["cell"]), P(r.get("basis", ""), S["cell_sub"])])
    if len(rows) > 1:
        flows.append(table(rows, [34, 40, 100]))
    flows += [Spacer(1, 5 * MM), P("解体数量", S["h2"])]
    rows = [[hcell("項目"), hcell("数量"), hcell("算出")],
            [P("建築面積", S["cell"]), P(f"{q['building_area_m2']:.1f} ㎡", S["cell_r"]), P("外形寸法から", S["cell_sub"])],
            [P("延床面積", S["cell"]), P(f"{q['floor_area_m2']:.1f} ㎡（{q['floor_area_tsubo']:.1f}坪）", S["cell_r"]), P(f"{b.get('floors')}階建", S["cell_sub"])],
            [P("外周長", S["cell"]), P(f"{q['perimeter_m']:.1f} m", S["cell_r"]), ""],
            [P("足場架面積（参考）", S["cell"]), P(f"{q['scaffold_m2']:.0f} ㎡", S["cell_r"]), P("(外周+8m)×(軒高+1m)。本体単価に含む", S["cell_sub"])]]
    if q.get("units_count"):
        chk = q.get("units_area_check_m2")
        rows.append([P("戸数・間取り", S["cell"]), P(f"{q['units_count']}戸（{q.get('units_layout', '')}）", S["cell_r"]),
                     P(f"専有合計 約{chk:.0f}㎡（延床との差は共用部・壁）" if chk else "", S["cell_sub"])])
    for a in q.get("annexes", []):
        if a["area_m2"]:
            rows.append([P(a["name"], S["cell"]), P(f"{a['area_m2']:.1f} ㎡", S["cell_r"]), P(a.get("kind", ""), S["cell_sub"])])
    flows.append(table(rows, [44, 46, 84]))
    if q.get("asbestos_suspect_parts"):
        flows += [Spacer(1, 3 * MM), P(f"アスベスト含有の可能性がある部位（推定築年 {b.get('built_year_est')}年頃）", S["h2"]),
                  P("、".join(q["asbestos_suspect_parts"]), S["body"])]
    lo = demo["leftover"]
    if lo["furniture"]:
        lo_head = [P(f"残置物（家財）の推定　{lo['layout']} × {lo['occupied_units']}戸", S["h2"]),
                  P(f"積込み体積 約{lo['volume_m3']}㎥（家財の数量から {lo['volume_from_list_m3']}㎥、間取り別の相場から {lo['volume_from_table_m3']}㎥ の大きい方＋屋外 {lo['extra_m3']}㎥）", S["small"])]
        items = lo["furniture"]
        half = (len(items) + 1) // 2
        rows = [[hcell("品目"), hcell("数量"), hcell("㎥"), hcell("品目"), hcell("数量"), hcell("㎥")]]
        for i in range(half):
            r = []
            for f in (items[i], items[i + half] if i + half < len(items) else None):
                r += [P(f["name"], S["cell"]), P(f"{f['qty']:g}", S["cell_r"]), P(f"{f['m3']:.1f}", S["cell_r"])] if f else ["", "", ""]
            rows.append(r)
        flows.append(KeepTogether(lo_head + [table(rows, [52, 14, 14, 52, 14, 14], styles=[("LINEAFTER", (2, 0), (2, -1), 0.6, LINE)])]))
    doc.flow(flows, "QUANTITY", "建物と数量の根拠")


def land_page(doc, spec, grad):
    S = st()
    rows = [[hcell("項目"), hcell("内容"), hcell("確実性")]]
    tone = {"確定": colors.HexColor("#4f7a5a"), "要確認": colors.HexColor("#b26a00"), "推測": SUB}
    styles = []
    items = list(spec.get("land_info", []))
    if grad:
        r = grad.get("road") or {}
        items.append({"item": "敷地内の高低差", "value": f"{grad['existing_diff']:.2f}m（T.P.{grad['existing_min']:.2f}〜{grad['existing_max']:.2f}）",
                      "confidence": "推測", "source": "国土地理院の標高＋写真から補正"})
        if r:
            items.append({"item": "前面道路", "value": f"道路中心 T.P.{r['center_avg']:.2f}m、縦断勾配 約{abs(r['slope_pct']):.1f}%",
                          "confidence": "推測", "source": "国土地理院の標高"})
    for it in items:
        conf = it.get("confidence", "推測")
        rows.append([P(it["item"], S["cell"]), [P(it["value"], S["cell"]), P(it.get("source", ""), S["cell_sub"])],
                     P(conf, ParagraphStyle("c", fontName=FONT, fontSize=8.3, textColor=tone.get(conf, SUB), alignment=1))])
    flows = [table(rows, [44, 112, 18], styles=styles),
             Spacer(1, 3 * MM),
             P("確実性　確定＝公的資料で確認できたもの／要確認＝窓口・現地・原本で確かめるまで決まらないもの／推測＝地図の代表点・写真・一般的な傾向からの見立て", S["small"])]
    if spec.get("market_notes"):
        flows += [Spacer(1, 4 * MM), P("相場・土地勘メモ", S["h2"])] + [P("・" + s, S["bullet"]) for s in spec["market_notes"]]
    doc.flow(flows, "SITE", "土地の概況")


def photo_pages(doc, spec, base_dir, annotate):
    S = st()
    photos = spec.get("photos", [])
    c = doc.c
    for i in range(0, len(photos), 2):
        y = doc.a4("PHOTOS", "写真台帳（読み取り箇所）" if i == 0 else "写真台帳（続き）")
        for ph in photos[i:i + 2]:
            path = ph["path"] if os.path.isabs(ph["path"]) else os.path.join(base_dir, ph["path"])
            doc.text(ML, y - 4, f"写真{ph.get('no', '')}　{ph.get('caption', '')}", 10.5)
            y -= 7
            if not os.path.exists(path):
                y -= 10
                continue
            img, (iw, ih) = annotate(path, ph.get("marks"))
            box_w, box_h = 104, 78
            k = min(box_w / iw, box_h / ih)
            dw, dh = iw * k, ih * k
            c.drawImage(img, ML * MM, (y - dh) * MM, dw * MM, dh * MM)
            ty = y
            for j, m in enumerate(ph.get("marks", [])[:7]):
                para = Paragraph(jp(f"<font color='#a94442'>{j + 1}</font>　{m['label']}"
                                    + (f"<br/><font size='7' color='#7a7f85'>{m['basis']}</font>" if m.get("basis") else "")),
                                 ParagraphStyle("m", fontName=FONT, fontSize=8.5, leading=11, textColor=INK))
                w, h = para.wrapOn(c, (CW - dw - 6) * MM, 30 * MM)
                para.drawOn(c, (ML + dw + 6) * MM, ty * MM - h)
                ty -= h / MM + 2
            y -= max(dh, y - ty) + 10
        c.showPage()


def notes_page(doc, spec, demo, gest):
    S = st()
    flows = [P("次に確認すること（見積・設計の精度を上げるため）", S["h2"])]
    for s in spec.get("next_checks", []):
        flows.append(P("□ " + s, S["bullet"]))
    used = set()
    for est in (demo, gest):
        if est:
            for ln in est["lines"] + (est.get("asbestos_extra") or []):
                used.update(ln.get("src") or [])
    rows = [[hcell("ID"), hcell("出典"), hcell("URL")]]
    seen = set()
    for est in (demo, gest):
        if not est:
            continue
        for s in est.get("sources", []):
            if s["id"] in used and s["id"] not in seen:
                seen.add(s["id"])
                rows.append([P(s["id"], S["cell_sub"]), P(s.get("title", ""), S["cell_sub"]), P(s.get("url", ""), S["cell_sub"])])
    flows += [Spacer(1, 5 * MM), P("単価の出典（この見積で使ったもの）", S["h2"])]
    if len(rows) > 1:
        flows.append(table(rows, [12, 70, 92]))
    attrs = spec.get("data_attribution", [])
    if attrs:
        flows += [Spacer(1, 4 * MM), P("公開データの出典", S["h2"]), P("、".join(attrs) + "。", S["small"])]
    doc.flow(flows, "NOTES", "確認事項と出典")
