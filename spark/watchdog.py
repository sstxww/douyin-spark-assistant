"""Independent local dispatcher. No Douyin cookies, no send/ledger-write API.

A Windows task calls one tick every five minutes. Existing GitHub CLI credentials
are used in-place. Only the already-published plan can run. The cloud runner owns
all message sends and its durable per-slot reservations remain authoritative.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .core import Config, SafeError, TZ, save_private, to_cron
from .schedule import daily_times, occurrence, occurrence_key

WORKFLOW = "spark-web.yml"
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
BLOCKERS = {"AUTH", "RISK", "TARGET", "HEADER", "EDITOR", "CONFIG", "STALE", "DISABLED"}
MAX_DISPATCHES = 6
BACKOFF_MINUTES = (5, 10, 20, 30, 60, 60)
SCHEMA = 1


def _iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SafeError("CONFIG")
    return parsed.astimezone(TZ)


def build_plan(workspace: dict) -> dict:
    """Projection only: no account names, messages, cookies or HMAC secret."""
    if not workspace.get("published"):
        raise SafeError("STALE")
    rows = []
    for account in workspace["accounts"]:
        if not account["enabled"]:
            continue
        cfg = Config.parse(account["config"])
        rows.append({"account": account["slot"], "keys": {
            str(index): [occurrence_key(workspace["key"], cfg, target, index)
                         for target in cfg.targets if target.enabled]
            for index in (1, 2)}})
    result = {"version": SCHEMA, "repository": workspace["repository"],
              "revision": workspace["revision"], "time": workspace["time"],
              "installation": hashlib.sha256(bytes.fromhex(workspace["key"])).hexdigest(),
              "accounts": rows}
    return validate_plan(result)


def validate_plan(plan: dict) -> dict:
    try:
        if plan.get("version") != SCHEMA:
            raise SafeError("CONFIG")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", plan["repository"]):
            raise SafeError("CONFIG")
        if not re.fullmatch(r"[a-f0-9]{16}", plan["revision"]):
            raise SafeError("CONFIG")
        if not re.fullmatch(r"[a-f0-9]{64}", plan["installation"]):
            raise SafeError("CONFIG")
        to_cron(plan["time"])
        accounts = plan["accounts"]
        if not isinstance(accounts, list) or not 1 <= len(accounts) <= 3:
            raise SafeError("CONFIG")
        slots, all_keys = set(), set()
        for row in accounts:
            slot = row["account"]
            if slot not in ("a1", "a2", "a3") or slot in slots:
                raise SafeError("CONFIG")
            slots.add(slot)
            if set(row["keys"]) != {"1", "2"}:
                raise SafeError("CONFIG")
            if len(row["keys"]["1"]) != len(row["keys"]["2"]):
                raise SafeError("CONFIG")
            for keys in row["keys"].values():
                if not isinstance(keys, list) or not 1 <= len(keys) <= 10:
                    raise SafeError("CONFIG")
                for key in keys:
                    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key) or key in all_keys:
                        raise SafeError("CONFIG")
                    all_keys.add(key)
        if len(all_keys) > 20:
            raise SafeError("CONFIG")
        return plan
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SafeError("CONFIG") from None


def export_plan(root: Path, workspace: dict):
    # Replacing this projection NEVER replaces the real attempt ledger or budget.
    save_private(root / "watchdog-plan.json", json.dumps(build_plan(workspace)))


def due_period(anchor: str, now: datetime):
    if now.tzinfo is None:
        raise SafeError("CONFIG")
    now = now.astimezone(TZ)
    first, second = daily_times(anchor)
    first_at = datetime.combine(now.date(), time.fromisoformat(first), TZ)
    second_at = datetime.combine(now.date(), time.fromisoformat(second), TZ)
    if now < first_at:
        return None
    slot_time = first if now < second_at else second
    return occurrence(anchor, now, "schedule", to_cron(slot_time))


def ledger_entries(value: dict, day: date) -> dict:
    """Validate without initializing, overwriting or cleaning the cloud ledger."""
    try:
        if value.get("version") != 1 or not isinstance(value.get("entries"), dict):
            raise SafeError("LEDGER")
        previous = date.fromisoformat(value["day"])
        if previous > day:
            raise SafeError("LEDGER")
        for key, state in value["entries"].items():
            if not re.fullmatch(r"[a-f0-9]{64}", key) or state not in ("reserved", "ui_confirmed"):
                raise SafeError("LEDGER")
        return value["entries"] if previous == day else {}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SafeError("LEDGER") from None


class GitHubClient:
    def __init__(self, repository: str, gh_path: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise SafeError("CONFIG")
        self.repository = repository
        self.base = f"repos/{repository}"
        self.gh_path = gh_path or shutil.which("gh")
        if not self.gh_path:
            raise SafeError("GITHUB")
        self.env = os.environ.copy()
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            self.env.pop(key, None)
        self.env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", NO_COLOR="1",
                        GH_PAGER="cat", GH_BROWSER="true", BROWSER="true")

    def command(self, args: list[str], data=None):
        try:
            return subprocess.run([self.gh_path, *args], input=data, text=True,
                                  encoding="utf-8", errors="replace", capture_output=True,
                                  env=self.env, timeout=40,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise SafeError("GITHUB") from None

    def api(self, path: str, method="GET", body=None, missing=False):
        if path != "user" and not path.startswith(self.base + "/"):
            raise SafeError("CONFIG")
        args = ["api", path, "--method", method, "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if body is not None:
            args += ["--input", "-"]
        result = self.command(args, json.dumps(body) if body is not None else None)
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else None
        except ValueError:
            raise SafeError("GITHUB") from None
        if result.returncode:
            if missing and isinstance(data, dict) and str(data.get("status")) == "404":
                return None
            raise SafeError("GITHUB")
        return data

    def ledger(self, day: date):
        file = self.api(self.base + "/contents/ledger.json?ref=spark-state", missing=True)
        if file is None:
            ref = self.api(self.base + "/git/ref/heads/spark-state", missing=True)
            if ref is not None:
                raise SafeError("LEDGER")
            return {}  # First ever send initializes it, not this read-only helper.
        try:
            raw = base64.b64decode(file["content"])
            if len(raw) > 200_000:
                raise SafeError("LEDGER")
            return ledger_entries(json.loads(raw), day)
        except (KeyError, ValueError, TypeError):
            raise SafeError("LEDGER") from None

    def blocking_codes(self, run_id: int) -> set[str]:
        result = self.command(["run", "view", str(int(run_id)), "--repo", self.repository, "--log"])
        if result.returncode:
            raise SafeError("GITHUB")
        # Raw logs are never returned, stored, or shown. Only these fixed codes.
        return set(re.findall(r"\[(AUTH|RISK|TARGET|HEADER|EDITOR|CONFIG|STALE|DISABLED)\]", result.stdout))


def load_budget(path: Path) -> dict:
    if not path.exists():
        return {"version": SCHEMA, "slots": {}}
    try:
        raw = json.loads(path.read_text("utf-8"))
        if raw.get("version") != SCHEMA or not isinstance(raw.get("slots"), dict):
            raise SafeError("CONFIG")
        if len(raw["slots"]) > 64:
            raise SafeError("CONFIG")
        for key, attempts in raw["slots"].items():
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}:[12]", key) or not isinstance(attempts, list):
                raise SafeError("CONFIG")
            if len(attempts) > MAX_DISPATCHES:
                raise SafeError("CONFIG")
            for stamp in attempts:
                _iso(stamp)
        return raw
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SafeError("CONFIG") from None


def tick(plan: dict, client, budget: dict, persist, now: datetime, *, dry_run=False) -> dict:
    """One bounded evaluation. It may dispatch ONE job; it never sends a message."""
    plan = validate_plan(plan)
    if now.tzinfo is None:
        raise SafeError("CONFIG")
    now = now.astimezone(TZ)
    period = due_period(plan["time"], now)
    result = {"version": SCHEMA, "checked_at": now.isoformat(timespec="seconds"),
              "repository": plan["repository"], "revision": plan["revision"],
              "times": list(daily_times(plan["time"])), "status": "not_due", "dispatches": 0,
              "confirmed": 0, "uncertain": 0, "missing": 0, "dry_run": dry_run}
    if period is None:
        return result
    result.update(day=period.day.isoformat(), slot=period.index)
    base = client.base
    values = client.api(base + "/actions/variables?per_page=100")
    values = {v["name"]: v["value"] for v in values["variables"]}
    if values.get("SPARK_WEB_ENABLED") != "true":
        return {**result, "status": "paused"}
    if (values.get("SPARK_WEB_REVISION") != plan["revision"] or
            values.get("SPARK_WEB_INSTALLATION") != plan["installation"]):
        return {**result, "status": "plan_stale"}
    entries = client.ledger(period.day)
    keys = [key for row in plan["accounts"] for key in row["keys"][str(period.index)]]
    counts = {state: sum(entries.get(k) == state for k in keys)
              for state in ("ui_confirmed", "reserved", None)}
    result.update(confirmed=counts["ui_confirmed"], uncertain=counts["reserved"], missing=counts[None])
    if not counts[None]:
        return {**result, "status": "needs_attention" if counts["reserved"] else "confirmed"}
    # Do not create a job too close to the next slot / midnight.
    if now >= period.end - timedelta(minutes=10):
        return {**result, "status": "window_ending"}
    # Check both workflows: the legacy one shares the cloud execution lock.
    runs = client.api(base + f"/actions/workflows/{WORKFLOW}/runs?per_page=50")["workflow_runs"]
    legacy = client.api(base + "/actions/workflows/spark.yml/runs?per_page=10")["workflow_runs"]
    if any(r["status"] in ACTIVE for r in runs + legacy):
        return {**result, "status": "job_active"}
    head = client.api(base + "/git/ref/heads/main")["object"]["sha"]
    expected = "check · all · " + plan["revision"]
    checked = any(r.get("display_title") == expected and r.get("head_sha") == head
                  and r.get("status") == "completed" and r.get("conclusion") == "success"
                  and r.get("event") == "workflow_dispatch" for r in runs)
    proof = {"head": head, "revision": plan["revision"]}
    if not checked and budget.get("verified") != proof:
        return {**result, "status": "check_required"}
    if checked and budget.get("verified") != proof and not dry_run:
        budget["verified"] = proof
        persist(budget)
    # A known login/identity/draft problem must not be hammered with retries.
    completed = [r for r in runs if r.get("status") == "completed"
                 and r.get("conclusion") in ("failure", "timed_out")
                 and r.get("head_sha") == head
                 and str(r.get("display_title", "")).startswith("send · ")
                 and str(r.get("display_title", "")).endswith(plan["revision"])
                 and period.start <= _iso(r["created_at"]) <= now]
    if completed:
        latest = max(completed, key=lambda r: _iso(r["created_at"]))
        codes = client.blocking_codes(latest["id"])
        if codes:
            return {**result, "status": "needs_attention", "codes": sorted(codes)}
    key = f"{period.day.isoformat()}:{period.index}"
    attempts = budget["slots"].get(key, [])
    result["dispatches"] = len(attempts)
    if len(attempts) >= MAX_DISPATCHES:
        return {**result, "status": "retry_exhausted"}
    if attempts and now < _iso(attempts[-1]) + timedelta(minutes=BACKOFF_MINUTES[len(attempts)-1]):
        return {**result, "status": "backoff"}
    if dry_run:
        return {**result, "status": "would_dispatch"}
    # Re-read enable/version immediately before any external write.
    values = client.api(base + "/actions/variables?per_page=100")
    values = {v["name"]: v["value"] for v in values["variables"]}
    if values.get("SPARK_WEB_ENABLED") != "true":
        return {**result, "status": "paused"}
    if (values.get("SPARK_WEB_REVISION") != plan["revision"] or
            values.get("SPARK_WEB_INSTALLATION") != plan["installation"]):
        return {**result, "status": "plan_stale"}
    # Count the attempt BEFORE dispatch: even a lost HTTP response cannot create
    # an unbounded retry loop. This budget is separate from actual send records.
    attempts = [*attempts, now.isoformat(timespec="seconds")]
    budget["slots"][key] = attempts
    budget["slots"] = {k: v for k, v in budget["slots"].items()
                       if k[:10] >= (period.day - timedelta(days=14)).isoformat()}
    persist(budget)
    response = client.api(base + f"/actions/workflows/{WORKFLOW}/dispatches", "POST",
                          {"ref": "main", "inputs": {"mode": "send", "account": "all",
                                                        "revision": plan["revision"]}})
    result.update(status="dispatched", dispatches=len(attempts))
    if isinstance(response, dict) and isinstance(response.get("workflow_run_id"), int):
        result["run_id"] = response["workflow_run_id"]
    return result


@contextmanager
def single_instance(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "watchdog.lock"
    with path.open("a+b") as file:
        if file.tell() == 0:
            file.write(b"0"); file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Spark independent local dispatcher")
    parser.add_argument("--home", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".local" / "web-local")
    parser.add_argument("--gh-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-plan", action="store_true")
    args = parser.parse_args(argv)
    if os.getenv("CODESPACE_NAME") or os.getenv("GITHUB_ACTIONS") == "true":
        return 2  # This path must be INDEPENDENT of GitHub's scheduled runner.
    result = {"version": SCHEMA, "checked_at": datetime.now(TZ).isoformat(timespec="seconds"),
              "status": "error", "code": "INTERNAL"}
    try:
        with single_instance(args.home) as acquired:
            if not acquired:
                return 0
            if args.export_plan:
                from .web_config import validate_workspace
                ws = validate_workspace(json.loads((args.home / "workspace.json").read_text("utf-8")), deploy=True)
                export_plan(args.home, ws)
                if sys.stdout: print("Published-plan projection refreshed; credentials not exported.")
                return 0
            plan = validate_plan(json.loads((args.home / "watchdog-plan.json").read_text("utf-8")))
            client = GitHubClient(plan["repository"], args.gh_path)
            budget_file = args.home / "watchdog-budget.json"
            budget = load_budget(budget_file)
            result = tick(plan, client, budget,
                          lambda data: save_private(budget_file, json.dumps(data)),
                          datetime.now(TZ), dry_run=args.dry_run)
    except SafeError as exc:
        result["code"] = exc.code
    except Exception:
        pass  # Do not echo subprocess output, local files or exception details.
    try:
        save_private(args.home / "watchdog-status.json", json.dumps(result, ensure_ascii=False))
    except Exception:
        return 1
    if sys.stdout:
        print(json.dumps(result, ensure_ascii=True))
    return 1 if result["status"] in {"error", "needs_attention", "plan_stale", "check_required", "retry_exhausted", "window_ending"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
