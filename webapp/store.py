"""案件の保存（Vercel Blob の非公開ストア）。

置き方:
  cases/index.json            一覧（id・物件名・住所・日付・概算・延床）
  cases/<id>/case.json        読み取り結果・公開データ・オプション・概算の要約・実績
  cases/<id>/photo<n>.jpg     現地写真（縮小済み）
資料（PDF・Excel・DXF）は保存せず、ダウンロードのたびに case.json から作り直す。
"""
import datetime
import json
import os
import secrets

from vercel.blob import sync as blob

ACCESS = "private"
INDEX = "cases/index.json"


def enabled():
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def _now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def new_id():
    return datetime.datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3)


def _put_json(path, data):
    blob.put_blob(path, json.dumps(data, ensure_ascii=False).encode(), access=ACCESS,
                  content_type="application/json", allow_overwrite=True)


def _get_json(path, default=None):
    try:
        return json.loads(blob.get_blob(path, access=ACCESS).body)
    except blob.BlobNotFoundError:
        return default


def _check_id(case_id):
    if not case_id or any(c not in "0123456789abcdef-" for c in case_id):
        raise ValueError("案件IDが正しくありません")


def list_cases():
    return sorted(_get_json(INDEX, []), key=lambda r: r.get("updated_at", ""), reverse=True)


def _brief(case):
    s = case.get("summary") or {}
    demo = s.get("demolition_total") or {}
    grad = s.get("grading_total") or {}
    return {"id": case["id"], "title": case.get("title") or "", "address": case.get("address") or "",
            "created_at": case.get("created_at"), "updated_at": case.get("updated_at"),
            "floor_area_m2": s.get("floor_area_m2"), "demolition_mid": demo.get("mid"), "grading_mid": grad.get("mid"),
            "photos": case.get("photo_count", 0), "source": case.get("source", "web"),
            "has_actual": bool(case.get("actuals"))}


def save_case(case):
    """作成・更新。case["id"] が無ければ採番する。戻り値は保存した case。"""
    case = dict(case)
    if not case.get("id"):
        case["id"] = new_id()
        case["created_at"] = _now()
    _check_id(case["id"])
    case["updated_at"] = _now()
    _put_json(f"cases/{case['id']}/case.json", case)
    idx = [r for r in _get_json(INDEX, []) if r.get("id") != case["id"]]
    idx.append(_brief(case))
    _put_json(INDEX, idx)
    return case


def load_case(case_id):
    _check_id(case_id)
    c = _get_json(f"cases/{case_id}/case.json")
    if c is None:
        raise KeyError(case_id)
    return c


def save_photo(case_id, no, data):
    _check_id(case_id)
    blob.put_blob(f"cases/{case_id}/photo{int(no)}.jpg", data, access=ACCESS, content_type="image/jpeg",
                  allow_overwrite=True)


def load_photo(case_id, no):
    _check_id(case_id)
    return blob.get_blob(f"cases/{case_id}/photo{int(no)}.jpg", access=ACCESS).body


def delete_case(case_id):
    _check_id(case_id)
    paths = [b.pathname for b in blob.query_blobs(prefix=f"cases/{case_id}/")]
    if paths:
        blob.delete_blob(paths)
    _put_json(INDEX, [r for r in _get_json(INDEX, []) if r.get("id") != case_id])
