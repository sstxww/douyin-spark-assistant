"""Two daily occurrences, with legacy-safe keys and immutable run timestamps."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

from .core import Config, SafeError, TZ, Target, target_key, to_cron


def daily_times(anchor: str) -> tuple[str, str]:
    """The existing time remains one of two slots, exactly 12 hours apart."""
    to_cron(anchor)
    hour, minute = map(int, anchor.split(":"))
    first = hour % 12
    return f"{first:02d}:{minute:02d}", f"{first + 12:02d}:{minute:02d}"


def now_local() -> datetime:
    return datetime.now(TZ)


def run_created_at(env: dict[str, str]) -> datetime:
    """Use ORIGINAL creation time, not the start time of a delayed/re-run job.

    Metadata only. No tokens or responses are logged or put into artifacts.
    A workflow needs actions:read in addition to its ledger contents permission.
    """
    if env.get("GITHUB_ACTIONS") != "true":
        return now_local()
    repo, run_id, token = (env.get(k, "") for k in
                           ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_TOKEN"))
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or not re.fullmatch(r"[0-9]+", run_id) or not token):
        raise SafeError("GITHUB")
    request = Request(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}",
                      headers={"Authorization": f"Bearer {token}",
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urlopen(request, timeout=25) as response:
            data = json.loads(response.read(524289))
        if str(data["id"]) != run_id:
            raise SafeError("GITHUB")
        created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise SafeError("GITHUB")
        return created.astimezone(TZ)
    except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SafeError("GITHUB") from None


@dataclass(frozen=True)
class Occurrence:
    day: date
    index: int
    start: datetime
    end: datetime

    def active(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise SafeError("CONFIG")
        return self.start <= now < self.end


def occurrence(anchor: str, created: datetime, event: str = "workflow_dispatch",
               cron: str = "") -> Occurrence:
    """Bind to one slot once; do not borrow tomorrow's or the other slot's quota.

    Manual sends before the first schedule count toward the day's FIRST slot.
    Scheduled sends never run early, after the next slot, or on the next day.
    """
    if created.tzinfo is None:
        raise SafeError("CONFIG")
    created = created.astimezone(TZ)
    day = created.date()
    times = daily_times(anchor)
    midnight = datetime.combine(day, time(), TZ)
    boundaries = [datetime.combine(day, time.fromisoformat(value), TZ) for value in times]
    tomorrow = midnight + timedelta(days=1)
    if event == "schedule":
        matches = [i for i, value in enumerate(times) if to_cron(value) == cron]
        if len(matches) != 1:
            raise SafeError("CONFIG")
        index = matches[0]
        start = boundaries[index]
    elif event in ("", "workflow_dispatch"):
        index = 0 if created < boundaries[1] else 1
        start = midnight if index == 0 else boundaries[1]
    else:
        raise SafeError("CONFIG")
    return Occurrence(day, index + 1, start, boundaries[1] if index == 0 else tomorrow)


def occurrence_key(secret: str, config: Config, target: Target, index: int) -> str:
    base = target_key(secret, config, target)
    if index == 1:
        # Existing v1 daily attempts consume the FIRST slot. Never wipe the ledger
        # or reset account IDs: today's earlier test must not become a third send.
        return base
    if index == 2:
        return hmac.new(bytes.fromhex(secret),
                        f"spark-twice-daily/v1/second\0{base}".encode(),
                        hashlib.sha256).hexdigest()
    raise SafeError("CONFIG")
