"""案件の保存（Vercel Blob の非公開ストア）。

置き方:
  cases/_idx/<id>__<要約>       一覧用の目印（中身は空。ファイル名に一覧の要約を base64 で入れる）
  cases/<id>/case-<時刻>.json   読み取り結果・公開データ・オプション・概算の要約・実績（保存のたびに新しい版を作る）
  cases/<id>/photo<n>.jpg       現地写真（縮小済み）
Blob の読み出しはキャッシュされるため、同じ名前の上書きはすぐ反映されない。そこで上書きはせず、
新しい名前で書いて古い版を消し、一覧はファイル名の一覧（キャッシュされない）から作る。
資料（PDF・Excel・DXF）は保存せず、ダウンロードのたびに作り直す。
"""
import base64
import datetime
import json
import os
import secrets
import time

from vercel.blob import sync as blob

ACCESS = "private"
IDX = "cases/_idx/"


def enabled():
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def _now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def new_id():
    return datetime.datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3)


def _check_id(case_id):
    if not case_id or any(c not in "0123456789abcdef-" for c in case_id):
        raise ValueError("案件IDが正しくありません")


def _paths(prefix):
    return [b.pathname for b in blob.query_blobs(prefix=prefix)]


def _brief(case):
    s = case.get("summary") or {}
    return {"id": case["id"], "title": (case.get("title") or "")[:40], "address": (case.get("address") or "")[:60],
            "created_at": case.get("created_at"), "updated_at": case.get("updated_at"),
            "floor_area_m2": s.get("floor_area_m2"), "demolition_mid": (s.get("demolition_total") or {}).get("mid"),
            "grading_mid": (s.get("grading_total") or {}).get("mid"), "photos": case.get("photo_count", 0),
            "source": (case.get("source") or "web")[:40], "has_actual": bool(case.get("actuals"))}


def _encode_brief(b):
    return base64.urlsafe_b64encode(json.dumps(b, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_brief(name):
    raw = name.split("__", 1)[1]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def list_cases():
    out = []
    for p in _paths(IDX):
        try:
            out.append(_decode_brief(p[len(IDX):]))
        except Exception:  # noqa: BLE001  壊れた目印は飛ばす
            continue
    return sorted(out, key=lambda r: r.get("updated_at") or "", reverse=True)


def save_case(case):
    """作成・更新。case["id"] が無ければ採番する。戻り値は保存した case。"""
    case = dict(case)
    if not case.get("id"):
        case["id"] = new_id()
        case["created_at"] = _now()
    _check_id(case["id"])
    case["updated_at"] = _now()
    old = _paths(f"cases/{case['id']}/case-") + _paths(f"{IDX}{case['id']}__")
    ver = f"cases/{case['id']}/case-{int(time.time() * 1000)}.json"
    blob.put_blob(ver, json.dumps(case, ensure_ascii=False).encode(), access=ACCESS, content_type="application/json")
    marker = f"{IDX}{case['id']}__{_encode_brief(_brief(case))}"
    blob.put_blob(marker, b"", access=ACCESS, content_type="text/plain", allow_overwrite=True)
    old = [p for p in old if p not in (ver, marker)]
    if old:
        blob.delete_blob(old)
    return case


def load_case(case_id):
    _check_id(case_id)
    vers = sorted(_paths(f"cases/{case_id}/case-"))
    if not vers:
        raise KeyError(case_id)
    return json.loads(blob.get_blob(vers[-1], access=ACCESS).body)


def save_photo(case_id, no, data):
    _check_id(case_id)
    blob.put_blob(f"cases/{case_id}/photo{int(no)}.jpg", data, access=ACCESS, content_type="image/jpeg",
                  allow_overwrite=True)


def load_photo(case_id, no):
    _check_id(case_id)
    return blob.get_blob(f"cases/{case_id}/photo{int(no)}.jpg", access=ACCESS).body


def delete_case(case_id):
    _check_id(case_id)
    paths = _paths(f"cases/{case_id}/") + _paths(f"{IDX}{case_id}__")
    if paths:
        blob.delete_blob(paths)
