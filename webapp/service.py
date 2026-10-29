"""画面（/api）と MCP の両方から使う処理: 写真の読み取り、概算の要約、資料の作成、案件の保存。"""
import base64
import concurrent.futures as cf
import io
import os
import shutil
import tempfile

from PIL import Image, ImageOps

try:  # iPhone の HEIC 写真（ドライブに入っていることが多い）を開けるようにする
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

from . import convert, land, reading, store
from .engine import report

FORMATS = {"summary": (), "pdf": ("pdf",), "xlsx": ("xlsx",), "dxf": ("dxf",), "rfq_pdf": ("rfq_pdf",), "rfq_xlsx": ("rfq_xlsx",)}
MEDIA = {"pdf": "application/pdf", "rfq_pdf": "application/pdf", "dxf": "application/dxf"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_PHOTOS = 12


def shrink_jpeg(data, long_side=1568, quality=85):
    """写真を読み取り用に縮小（画面側の縮小と同じ長辺 1568px）。HEIC 等で開けなければ ValueError。"""
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"画像を開けませんでした（{e}）") from e
    k = long_side / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def analyze(photos, address, notes="", effort=None):
    """photos: [{"name", "data"(base64 JPEG)}]。住所の公開データと写真の読み取りをまとめて行う。"""
    lnd = None
    if address:
        try:
            lnd = land.fetch_land(address)
        except Exception as e:  # noqa: BLE001  公開データが取れなくても写真だけで読む
            lnd = {"address": address, "land_info": [], "warnings": [f"公開データの取得に失敗: {e}"], "outlines": []}
    r, usage = reading.read_site(photos, address, notes, (lnd or {}).get("land_info"), (lnd or {}).get("aerial_b64"),
                                 effort=effort, outlines=[{k: v for k, v in o.items() if k != "poly_m"}
                                                          for o in (lnd or {}).get("outlines") or []])
    return r, lnd, usage


def build(reading_, land_, photos, options, fmt="summary"):
    """fmt=summary は概算の要約 dict、それ以外は (bytes, media_type)。"""
    if fmt not in FORMATS:
        raise ValueError(f"不明な形式です: {fmt}")
    job = tempfile.mkdtemp(prefix="job_", dir="/tmp")
    try:
        opts = options or {}
        spec = convert.to_spec(reading_, land_, photos, opts, job)
        summary = report.build(spec, os.path.join(job, "out"), job, formats=FORMATS[fmt], rfq_opts=opts.get("rfq"))
        if fmt == "summary":
            return {k: v for k, v in summary.items() if k not in ("pdf", "xlsx", "dxf", "rfq_pdf", "rfq_xlsx")}
        path = summary.get(fmt)
        if not path or not os.path.exists(path):
            raise RuntimeError(f"{fmt} を作れませんでした")
        with open(path, "rb") as f:
            return f.read(), MEDIA.get(fmt, XLSX)
    finally:
        shutil.rmtree(job, ignore_errors=True)


# ---------------------------------------------------------------- 案件

def case_photos(case):
    """保存した写真を読み取り・資料用の形（base64）で返す。"""
    out = []
    for i, name in enumerate(case.get("photo_names") or [], 1):
        out.append({"name": name, "data": base64.b64encode(store.load_photo(case["id"], i)).decode()})
    return out


def save_new_case(reading_, land_, photos, options, summary=None, source="web", usage=None):
    """読み取りが終わった案件を保存する。写真は並行して書き込む。"""
    opts = dict(options or {})
    case = store.save_case({
        "title": opts.get("project_name") or reading_.get("project_name") or "",
        "address": opts.get("address") or (land_ or {}).get("address") or "",
        "reading": reading_, "land": land_, "options": opts, "summary": summary,
        "photo_names": [p.get("name") or f"写真{i}" for i, p in enumerate(photos, 1)], "photo_count": len(photos),
        "source": source, "usage": usage,
    })
    with cf.ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda ip: store.save_photo(case["id"], ip[0], base64.b64decode(ip[1]["data"])), enumerate(photos, 1)))
    return case


def summarize_case(case):
    """保存した案件の概算を作り直して保存し直す（読み取り結果を直したとき）。"""
    case["summary"] = build(case["reading"], case.get("land"), [], case.get("options"), "summary")
    return store.save_case(case)


# 住所 → 単価の地域キー（画面の app.js の REGION_RULES と同じ）
_REGION_RULES = [(r"東京都[^市町村郡]{1,4}区", "tokyo23"), (r"東京都", "tokyo_tama"), (r"神奈川", "kanagawa"), (r"埼玉", "saitama"),
                 (r"千葉", "chiba"), (r"名古屋市", "nagoya"), (r"愛知", "aichi_other"), (r"大阪", "osaka"), (r"福岡", "fukuoka"),
                 (r"新潟", "niigata"), (r"北海道", "hokkaido")]


def region_from_address(address):
    import re
    for pat, key in _REGION_RULES:
        if re.search(pat, address or ""):
            return key
    return "default"
