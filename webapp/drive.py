"""Google ドライブのフォルダから写真を取る（利用者の Google アカウントのアクセストークンで読む）。"""
import json
import re
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/drive/v3"
IMAGE_TYPES = ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp")


def _get(url, token, raw=False, timeout=60):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data)


def folder_id_from(text):
    """フォルダの URL か ID を受け取って ID を返す。名前なら None（呼び出し側で検索）。"""
    text = (text or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", text) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", text):
        return text
    return None


def find_folders(token, name, limit=5):
    q = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name contains '{name.replace(chr(39), ' ')}'"
    url = f"{API}/files?" + urllib.parse.urlencode({"q": q, "pageSize": limit, "orderBy": "modifiedTime desc",
                                                    "fields": "files(id,name,modifiedTime)",
                                                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    return _get(url, token).get("files", [])


def folder_name(token, folder_id):
    return _get(f"{API}/files/{folder_id}?fields=name&supportsAllDrives=true", token).get("name", "")


def list_images(token, folder_id, limit=50):
    q = f"'{folder_id}' in parents and trashed=false and mimeType contains 'image/'"
    url = f"{API}/files?" + urllib.parse.urlencode({"q": q, "pageSize": limit, "orderBy": "name",
                                                    "fields": "files(id,name,mimeType,size)",
                                                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    return [f for f in _get(url, token).get("files", []) if f.get("mimeType") in IMAGE_TYPES]


def download(token, file_id):
    return _get(f"{API}/files/{file_id}?alt=media&supportsAllDrives=true", token, raw=True, timeout=90)
