"""Private, versioned multi-account configuration shared by UI and Actions."""
from __future__ import annotations

import base64
import copy
import gzip
import io
import json
import re
import secrets
from pathlib import Path
from typing import Any

from .core import Config, SafeError, save_private, to_cron, validate_state
from .schedule import daily_times

SLOTS = ("a1", "a2", "a3")
MAX_TARGETS = 10  # Total enabled recipients, not ten per account.
MAX_RAW = 3_000_000


def pack(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > MAX_RAW:
        raise SafeError("CONFIG")
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    if len(encoded) > 47_000:
        raise SafeError("CAPACITY")
    return encoded


def unpack(value: str) -> dict:
    try:
        if not isinstance(value, str) or len(value) > 48_000:
            raise SafeError("CONFIG")
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value, validate=True))) as f:
            raw = f.read(MAX_RAW + 1)
        if len(raw) > MAX_RAW:
            raise SafeError("CONFIG")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise SafeError("CONFIG")
        return result
    except (ValueError, OSError, EOFError, TypeError):
        raise SafeError("CONFIG") from None


def new_workspace() -> dict:
    return {"version": 2, "time": "20:17", "accounts": [], "templates": [],
            "key": secrets.token_hex(32), "revision": "", "deployed_head": "",
            "repository": "", "published": False}


def new_account(slot: str, label: str) -> dict:
    if slot not in SLOTS or not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
        raise SafeError("CONFIG")
    return {"slot": slot, "label": label.strip(), "enabled": True,
            "state": None, "saved_at": "", "contacts": [],
            "config": {"version": 1, "account_id": secrets.token_hex(16), "time": "20:17",
                       "mode": "cycle", "messages": ["今天也来和你打个招呼 🔥"], "targets": []}}


def validate_workspace(raw: Any, deploy: bool = False) -> dict:
    try:
        value = copy.deepcopy(raw)
        if not isinstance(value, dict) or value.get("version") != 2:
            raise SafeError("CONFIG")
        if not re.fullmatch(r"[a-f0-9]{64}", value["key"]):
            raise SafeError("CONFIG")
        to_cron(value["time"])
        accounts = value["accounts"]
        if not isinstance(accounts, list) or len(accounts) > len(SLOTS):
            raise SafeError("CONFIG")
        seen, ids, active_count, targets_count = set(), set(), 0, 0
        for row in accounts:
            slot = row["slot"]
            if slot not in SLOTS or slot in seen or type(row["enabled"]) is not bool:
                raise SafeError("CONFIG")
            if not isinstance(row["label"], str) or not 1 <= len(row["label"].strip()) <= 40:
                raise SafeError("CONFIG")
            seen.add(slot)
            cfg = row["config"]
            if cfg["account_id"] in ids:
                raise SafeError("CONFIG")
            ids.add(cfg["account_id"])
            cfg["time"] = value["time"]
            # Drafts may temporarily have no active recipient. Validate everything else.
            probe = copy.deepcopy(cfg)
            if not probe.get("targets"):
                probe["targets"] = [{"name": "预览对象", "enabled": True}]
            elif not any(t.get("enabled", True) for t in probe["targets"]):
                probe["targets"][0]["enabled"] = True
            Config.parse(probe)
            if row.get("state") is not None:
                validate_state(row["state"])
            if deploy and row["enabled"]:
                parsed = Config.parse(cfg)
                validate_state(row.get("state"))
                targets_count += sum(t.enabled for t in parsed.targets)
                active_count += 1
        if deploy and (active_count == 0 or not 1 <= targets_count <= MAX_TARGETS):
            raise SafeError("CONFIG")
        templates = value.get("templates", [])
        if not isinstance(templates, list) or len(templates) > 20:
            raise SafeError("CONFIG")
        template_ids = set()
        for t in templates:
            if (not isinstance(t.get("id"), str) or not re.fullmatch(r"[a-f0-9]{16}", t["id"])
                    or t["id"] in template_ids or not isinstance(t.get("title"), str)
                    or not 1 <= len(t["title"].strip()) <= 40):
                raise SafeError("CONFIG")
            template_ids.add(t["id"])
            probe = new_account("a1", "校验")["config"]
            probe.update(mode=t["mode"], messages=t["messages"], targets=[{"name": "校验"}])
            Config.parse(probe)
        return value
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SafeError("CONFIG") from None


def public_view(workspace: dict) -> dict:
    """Only this projection is allowed in regular browser responses. No credentials."""
    return {"version": 2, "time": workspace["time"], "daily_times": list(daily_times(workspace["time"])), "templates": workspace["templates"],
            "repository": workspace.get("repository", ""),
            "published": workspace.get("published", False),
            "accounts": [{"slot": a["slot"], "label": a["label"], "enabled": a["enabled"],
                          "logged_in": a.get("state") is not None,
                          "saved_at": a.get("saved_at", ""), "contacts": a.get("contacts", []),
                          "config": a["config"]} for a in workspace["accounts"]]}


def cloud_secrets(workspace: dict, revision: str) -> dict[str, str]:
    ws = validate_workspace(workspace, deploy=True)
    if not re.fullmatch(r"[a-f0-9]{16}", revision):
        raise SafeError("CONFIG")
    accounts = [a for a in ws["accounts"] if a["enabled"]]
    result = {}
    for row in accounts:
        result[f"SPARK_WEB_{row['slot'].upper()}"] = pack(
            {"version": 2, "revision": revision, "config": row["config"], "state": row["state"]})
    result["SPARK_WEB_MANIFEST"] = pack(
        {"version": 2, "revision": revision, "time": ws["time"],
         "accounts": [a["slot"] for a in accounts], "key": ws["key"]})
    return result


def cloud_accounts(env: dict, selection: str = "all") -> tuple[dict, list[tuple[str, Config, dict]]]:
    """Validate the complete deployment before allowing even its first side effect."""
    try:
        manifest = unpack(env.get("SPARK_WEB_MANIFEST", ""))
        if manifest.get("version") != 2 or not re.fullmatch(r"[a-f0-9]{16}", manifest["revision"]):
            raise SafeError("CONFIG")
        revision = env.get("SPARK_REVISION", "current")
        if revision not in ("current", manifest["revision"]):
            raise SafeError("STALE")
        if not re.fullmatch(r"[a-f0-9]{64}", manifest["key"]):
            raise SafeError("CONFIG")
        slots = manifest["accounts"]
        if (not isinstance(slots, list) or not slots or len(slots) > 3
                or len(set(slots)) != len(slots) or any(s not in SLOTS for s in slots)):
            raise SafeError("CONFIG")
        if selection != "all" and selection not in slots:
            raise SafeError("CONFIG")
        to_cron(manifest["time"])
        accounts, ids, count = [], set(), 0
        for slot in slots:
            row = unpack(env.get(f"SPARK_WEB_{slot.upper()}", ""))
            if row.get("version") != 2 or row.get("revision") != manifest["revision"]:
                raise SafeError("STALE")
            cfg = Config.parse(row["config"])
            validate_state(row["state"])
            if cfg.account_id in ids or cfg.time != manifest["time"]:
                raise SafeError("CONFIG")
            ids.add(cfg.account_id)
            count += sum(t.enabled for t in cfg.targets)
            if selection == "all" or slot == selection:
                accounts.append((slot, cfg, row["state"]))
        if count > MAX_TARGETS:
            raise SafeError("CONFIG")
        return manifest, accounts
    except (KeyError, ValueError, TypeError):
        raise SafeError("CONFIG") from None


class Workspace:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.path = root / "workspace.json"
        self.data = validate_workspace(json.loads(self.path.read_text("utf-8"))) if self.path.exists() else new_workspace()

    def save(self, data: dict, changed: bool = True):
        self.data = validate_workspace(data)
        if changed:
            self.data["published"] = False
        save_private(self.path, json.dumps(self.data, ensure_ascii=False))

    def account(self, slot: str) -> dict:
        for row in self.data["accounts"]:
            if row["slot"] == slot:
                return row
        raise SafeError("CONFIG")
