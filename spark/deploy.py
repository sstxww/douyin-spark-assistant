from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from .core import Config, SafeError, pack_state, to_cron
from .schedule import daily_times


def gh(args: list[str], data: str | None = None) -> str:
    if not shutil.which("gh"):
        raise SafeError("GITHUB")
    try:
        result = subprocess.run(["gh", *args], input=data, text=True, encoding="utf-8",
                                capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SafeError("GITHUB") from None
    if result.returncode:
        raise SafeError("GITHUB")
    return result.stdout.strip()


def repository_check(repository: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SafeError("CONFIG")
    login = gh(["api", "user", "--jq", ".login"])
    if login.casefold() != repository.split("/")[0].casefold():
        raise SafeError("GITHUB")
    branch = gh(["api", f"repos/{repository}", "--jq", ".default_branch"])
    if branch != "main":
        raise SafeError("GITHUB")


def set_enabled(repository: str, enabled: bool):
    repository_check(repository)
    if enabled:
        gh(["variable", "set", "SPARK_WEB_ENABLED", "--repo", repository, "--body", "false"])
    gh(["variable", "set", "SPARK_ENABLED", "--repo", repository,
        "--body", "true" if enabled else "false"])


def schedule_text(source: str, when: str) -> str:
    secondary = "# managed-spark-morning"
    if secondary in source:
        first, second = daily_times(when)
        source, count = re.subn(r"^    - cron: '[^']+' # managed-spark-morning$",
                               lambda _: "    - cron: '" + to_cron(first) + "' " + secondary,
                               source, flags=re.MULTILINE)
        if count != 1:
            raise SafeError("GITHUB")
        when = second
    replacement = "    - cron: '" + to_cron(when) + "' # managed-spark-schedule"
    updated, count = re.subn(r"^    - cron: '[^']+' # managed-spark-schedule$",
                             lambda _: replacement, source, flags=re.MULTILINE)
    if count != 1:
        raise SafeError("GITHUB")
    return updated


def upload(repository: str, raw: dict, state: dict, key: str):
    config = Config.parse(raw)
    compressed = pack_state(state)
    repository_check(repository)
    # Changing a configuration always pauses real sends before any secrets change.
    set_enabled(repository, False)
    for name, value in {"SPARK_CONFIG": json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
                        "DOUYIN_STATE": compressed, "SPARK_KEY": key}.items():
        if len(value.encode()) > 47_000:
            raise SafeError("CONFIG")
        gh(["secret", "set", name, "--repo", repository], data=value)
    endpoint = f"repos/{repository}/contents/.github/workflows/spark.yml"
    file = json.loads(gh(["api", endpoint + "?ref=main"]))
    original = base64.b64decode(file["content"]).decode("utf-8")
    updated = schedule_text(original, config.time)
    if updated != original:
        payload = {"message": "chore: update daily schedule (UTC+8)", "branch": "main",
                   "sha": file["sha"], "content": base64.b64encode(updated.encode()).decode()}
        gh(["api", endpoint, "--method", "PUT", "--input", "-"], data=json.dumps(payload))
    # The workflow may have been disabled after prolonged inactivity.
    gh(["workflow", "enable", "spark.yml", "--repo", repository])


def check_run(repository: str):
    repository_check(repository)
    gh(["workflow", "run", "spark.yml", "--repo", repository, "--ref", "main", "-f", "mode=check"])
