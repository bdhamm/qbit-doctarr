import json
import http.cookiejar
import shutil
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.error import HTTPError
from .config import QUARANTINE_PATH

_opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
_sessions = {}


class QBittorrentAPI:
    def __init__(self, config: dict):
        q = config["qbit"]
        self.base = q["url"].rstrip("/")
        auth_method = q.get("auth_method", "password")
        self.headers = {}
        self.username = ""
        self.password = ""
        
        if auth_method == "apikey":
            api_key = q.get("api_key", "").strip()
            if api_key: self.headers["Authorization"] = f"Bearer {api_key}"
        else:
            self.username = q.get("username", "").strip()
            self.password = q.get("password", "").strip()
            if self.username and self.password:
                if not _sessions.get(self.base):
                    self._login()
        self.opener = _opener

    def _login(self):
        req = Request(self.base + "/api/v2/auth/login", data=urlencode({"username": self.username, "password": self.password}).encode(), method="POST")
        with _opener.open(req, timeout=10) as resp:
            if resp.read().decode("utf-8", "replace").strip() != "Ok.": 
                raise Exception("qBittorrent login failed.")
        _sessions[self.base] = True

    def get_torrents(self) -> list[dict]:
        req = Request(self.base + "/api/v2/torrents/info", headers=self.headers)
        try:
            with self.opener.open(req, timeout=10) as resp: 
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 403 and self.username:
                self._login()
                with self.opener.open(req, timeout=10) as resp: 
                    return json.loads(resp.read())
            raise Exception(f"API unreachable: {e}")
        except Exception as e: 
            raise Exception(f"API unreachable: {e}")

    def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        req = Request(f"{self.base}/api/v2/torrents/files?hash={torrent_hash}", headers=self.headers)
        try:
            with self.opener.open(req, timeout=10) as resp: 
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 403 and self.username:
                self._login()
                with self.opener.open(req, timeout=10) as resp: 
                    return json.loads(resp.read())
            raise Exception(f"Failed to get files for {torrent_hash}: {e}")
        except Exception as e: 
            raise Exception(f"Failed to get files for {torrent_hash}: {e}")

    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int):
        if not file_ids: return
        url = self.base + "/api/v2/torrents/filePrio"
        data = urlencode({"hash": torrent_hash, "id": "|".join(map(str, file_ids)), "priority": priority}).encode()
        req = Request(url, data=data, method="POST", headers=self.headers)
        try:
            with self.opener.open(req, timeout=10) as resp:
                if resp.status != 200: raise Exception(f"HTTP {resp.status}")
        except HTTPError as e:
            if e.code == 403 and self.username:
                self._login()
                with self.opener.open(req, timeout=10) as resp:
                    if resp.status != 200: raise Exception(f"HTTP {resp.status}")
            else:
                raise Exception(f"Failed to set file priority for {torrent_hash}: {e}")
        except Exception as e: 
            raise Exception(f"Failed to set file priority for {torrent_hash}: {e}")

    def delete_torrent(self, torrent_hash: str):
        url = self.base + "/api/v2/torrents/delete"
        data = urlencode({"hashes": torrent_hash, "deleteFiles": "true"}).encode()
        req = Request(url, data=data, method="POST", headers=self.headers)
        try:
            with self.opener.open(req, timeout=10) as resp:
                if resp.status != 200: raise Exception(f"HTTP {resp.status}")
        except HTTPError as e:
            if e.code == 403 and self.username:
                self._login()
                with self.opener.open(req, timeout=10) as resp:
                    if resp.status != 200: raise Exception(f"HTTP {resp.status}")
            else:
                raise Exception(f"Direct qBit delete failed: {e}")
        except Exception as e: 
            raise Exception(f"Direct qBit delete failed: {e}")

    def stop_torrent(self, torrent_hash: str):
        url = self.base + "/api/v2/torrents/stop"
        data = urlencode({"hashes": torrent_hash}).encode()
        req = Request(url, data=data, method="POST", headers=self.headers)
        try:
            with self.opener.open(req, timeout=10) as resp:
                if resp.status != 200: raise Exception(f"HTTP {resp.status}")
        except HTTPError as e:
            if e.code == 403 and self.username:
                self._login()
                with self.opener.open(req, timeout=10) as resp:
                    if resp.status != 200: raise Exception(f"HTTP {resp.status}")
            else:
                raise Exception(f"Direct qBit stop failed: {e}")
        except Exception as e: 
            raise Exception(f"Direct qBit stop failed: {e}")


def move_to_quarantine(source: Path):
    quarantine_dir = Path(QUARANTINE_PATH)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / source.name
    counter = 1
    while dest.exists():
        dest = quarantine_dir / f"{source.stem}.{counter}{source.suffix}"
        counter += 1
    shutil.move(str(source), str(dest))