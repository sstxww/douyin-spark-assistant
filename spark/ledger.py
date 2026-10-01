"""Durable fail-closed attempt ledger. Public state contains HMAC keys, not names."""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .core import SafeError


class GitHubLedger:
    def __init__(self, repository: str, token: str, day: date):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise SafeError("LEDGER")
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token
        self.day = day.isoformat()
        self.branch = "spark-state"
        self.sha = None
        self.data = {"version": 1, "day": self.day, "entries": {}}
        self.load()

    def api(self, method, path, body=None, missing=False):
        request = Request(self.base + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": f"Bearer {self.token}",
                                   "Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28",
                                   "Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise SafeError("LEDGER") from None
        except (URLError, OSError, ValueError):
            raise SafeError("LEDGER") from None

    def load(self):
        ref = self.api("GET", f"/git/ref/heads/{self.branch}", missing=True)
        if ref is None:
            base = self.api("GET", "/git/ref/heads/main")
            self.api("POST", "/git/refs", {"ref": f"refs/heads/{self.branch}",
                                           "sha": base["object"]["sha"]})
        file = self.api("GET", f"/contents/ledger.json?ref={self.branch}", missing=True)
        if file is None:
            if ref is not None:
                # An established ledger branch without its ledger must not reset silently.
                raise SafeError("LEDGER")
            self.flush()
            return
        try:
            self.sha = file["sha"]
            previous = json.loads(base64.b64decode(file["content"]))
            if (previous.get("version") != 1 or not isinstance(previous.get("entries"), dict)
                    or not isinstance(previous.get("day"), str)):
                raise SafeError("LEDGER")
            parsed = date.fromisoformat(previous["day"])
            for key, value in previous["entries"].items():
                if not re.fullmatch(r"[a-f0-9]{64}", key) or value not in ("reserved", "ui_confirmed"):
                    raise SafeError("LEDGER")
            if parsed > date.fromisoformat(self.day):
                raise SafeError("LEDGER")
            if previous["day"] == self.day:
                self.data = previous
        except (KeyError, TypeError, ValueError):
            raise SafeError("LEDGER") from None

    def contains(self, key: str) -> bool:
        return key in self.data["entries"]

    def reserve(self, key: str) -> bool:
        if self.contains(key):
            return False
        self.data["entries"][key] = "reserved"
        self.flush()  # CAS write happens BEFORE any click that can send.
        return True

    def confirm(self, key: str):
        self.data["entries"][key] = "ui_confirmed"
        self.flush()

    def flush(self):
        body = {"message": "chore: update private-identity daily attempt ledger",
                "branch": self.branch,
                "content": base64.b64encode(json.dumps(self.data, separators=(",", ":")).encode()).decode()}
        if self.sha:
            body["sha"] = self.sha
        result = self.api("PUT", "/contents/ledger.json", body)
        try:
            self.sha = result["content"]["sha"]
        except (KeyError, TypeError):
            raise SafeError("LEDGER") from None
