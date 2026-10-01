"""GitHub operations. OAuth stays in this private Codespace, never in Actions."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

from spark.core import SafeError
from spark.deploy import schedule_text
from spark.web_config import cloud_secrets

ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
WORKFLOW = "spark-web.yml"


def detect_repository() -> str:
    value = os.getenv("GITHUB_REPOSITORY", "")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        return value
    try:
        remote = subprocess.run(["git", "config", "--get", "remote.origin.url"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", remote)
        if match:
            return match[1]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "sstxww/douyin-spark-assistant"


class GitHubCloud:
    def __init__(self, root: Path, repository: str, local_cli: bool = False):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise SafeError("CONFIG")
        if local_cli and (os.getenv("CODESPACE_NAME") or os.getenv("CODESPACES") == "true"):
            raise SafeError("CONFIG")
        self.local_cli = local_cli
        self.repository = repository
        self.base = f"repos/{repository}"
        self.auth_root = root / "github-auth"
        self.auth_root.mkdir(parents=True, exist_ok=True)
        self.auth_root.chmod(0o700)
        self.env = os.environ.copy()
        # Codespaces' built-in token cannot reliably manage Actions Secrets.
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_PROMPT_DISABLED"):
            self.env.pop(name, None)
        # Explicit local mode uses the already authorized CLI/keyring, without
        # reading, printing, copying, or uploading its token. Cloud stays isolated.
        if not local_cli:
            self.env["GH_CONFIG_DIR"] = str(self.auth_root)
        self.env.update(GH_HOST="github.com", BROWSER="true", GH_BROWSER="true",
                        GH_COLOR_LABELS="0", NO_COLOR="1", LC_ALL="C.UTF-8")
        self.auth = {"status": "idle", "code": "", "url": "https://github.com/login/device"}
        self.auth_task = None
        self.process = None

    def gh(self, args: list[str], data: str | None = None) -> str:
        try:
            result = subprocess.run(["gh", *args], input=data, capture_output=True, text=True,
                                    encoding="utf-8", env=self.env, timeout=90)
            if result.returncode:
                raise SafeError("GITHUB")
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            raise SafeError("GITHUB") from None

    def api(self, path: str, method="GET", body=None):
        args = ["api", path, "--method", method]
        if body is not None:
            args += ["--input", "-"]
        text = self.gh(args, json.dumps(body, ensure_ascii=False) if body is not None else None)
        return json.loads(text) if text else None

    def identity(self):
        user = self.api("user")
        if user["login"].casefold() != self.repository.split("/")[0].casefold():
            raise SafeError("GITHUB")
        repo = self.api(self.base)
        if repo.get("default_branch") != "main" or not repo.get("permissions", {}).get("admin"):
            raise SafeError("GITHUB")
        return user["login"]

    def variables(self) -> dict:
        rows = self.api(f"{self.base}/actions/variables?per_page=100")
        return {v["name"]: v["value"] for v in rows.get("variables", [])}

    def variable(self, name: str, value: str):
        self.gh(["variable", "set", name, "--repo", self.repository, "--body", value])

    def runs(self, workflow=WORKFLOW):
        return self.api(f"{self.base}/actions/workflows/{workflow}/runs?per_page=30")["workflow_runs"]

    def status(self):
        login = self.identity()
        variables = self.variables()
        runs = self.runs()
        return {"connected": True, "login": login,
                "enabled": variables.get("SPARK_WEB_ENABLED") == "true",
                "runs": [{"status": r["status"], "conclusion": r["conclusion"], "url": r["html_url"],
                          "created_at": r["created_at"], "title": r["display_title"]} for r in runs[:8]]}

    def pause(self):
        self.identity()
        self.variable("SPARK_WEB_ENABLED", "false")
        self.variable("SPARK_ENABLED", "false")

    def cancel(self):
        self.pause()
        for workflow in (WORKFLOW, "spark.yml"):
            for row in self.runs(workflow):
                if row["status"] in ACTIVE:
                    self.api(f"{self.base}/actions/runs/{row['id']}/cancel", "POST")

    def installation(self, workspace: dict, variables: dict):
        fingerprint = hashlib.sha256(bytes.fromhex(workspace["key"])).hexdigest()
        previous = variables.get("SPARK_WEB_INSTALLATION")
        if previous and previous != fingerprint:
            raise SafeError("RESTORE")
        return fingerprint

    def publish(self, workspace: dict) -> tuple[str, str]:
        revision = secrets.token_hex(8)
        payloads = cloud_secrets(workspace, revision)  # All validations first.
        self.identity()
        variables = self.variables()
        fingerprint = self.installation(workspace, variables)
        self.pause()
        # Never replace credentials underneath an already queued/running job.
        for workflow in (WORKFLOW, "spark.yml"):
            if any(r["status"] in ACTIVE for r in self.runs(workflow)):
                raise SafeError("BUSY")
        # Manifest is written LAST so a partial publication cannot mix generations.
        for name, value in payloads.items():
            self.gh(["secret", "set", name, "--repo", self.repository], value)
        endpoint = f"{self.base}/contents/.github/workflows/{WORKFLOW}"
        source = self.api(endpoint + "?ref=main")
        before = base64.b64decode(source["content"]).decode()
        after = schedule_text(before, workspace["time"])
        if after != before:
            self.api(endpoint, "PUT", {"branch": "main", "sha": source["sha"],
                     "message": "chore: update browser-managed schedule (UTC+8)",
                     "content": base64.b64encode(after.encode()).decode()})
        self.gh(["workflow", "enable", WORKFLOW, "--repo", self.repository])
        self.variable("SPARK_WEB_INSTALLATION", fingerprint)
        self.variable("SPARK_WEB_REVISION", revision)
        head = self.api(f"{self.base}/git/ref/heads/main")["object"]["sha"]
        return revision, head

    def current(self, workspace: dict):
        self.identity()
        variables = self.variables()
        self.installation(workspace, variables)
        if (not workspace.get("published") or workspace.get("repository") != self.repository
                or variables.get("SPARK_WEB_REVISION") != workspace.get("revision")):
            raise SafeError("STALE")
        return variables

    def dispatch(self, workspace: dict, mode: str, account="all"):
        if mode not in ("check", "send") or account not in ("all", "a1", "a2", "a3"):
            raise SafeError("CONFIG")
        variables = self.current(workspace)
        if mode == "send" and variables.get("SPARK_WEB_ENABLED") != "true":
            raise SafeError("DISABLED")
        self.api(f"{self.base}/actions/workflows/{WORKFLOW}/dispatches", "POST",
                 {"ref": "main", "inputs": {"mode": mode, "account": account,
                                              "revision": workspace["revision"]}})

    def enable(self, workspace: dict):
        self.current(workspace)
        head = self.api(f"{self.base}/git/ref/heads/main")["object"]["sha"]
        expected = f"check · all · {workspace['revision']}"
        checked = any(r.get("display_title") == expected and r.get("conclusion") == "success"
                      and r.get("status") == "completed" and r.get("event") == "workflow_dispatch"
                      and r.get("head_sha") == head for r in self.runs())
        if not checked:
            raise SafeError("CHECK")
        self.variable("SPARK_WEB_ENABLED", "true")

    async def start_auth(self):
        if self.auth_task and not self.auth_task.done():
            return self.auth
        self.auth = {"status": "starting", "code": "", "url": "https://github.com/login/device"}
        self.auth_task = asyncio.create_task(self._authenticate())
        return self.auth

    async def _authenticate(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                "gh", "auth", "login", "--hostname", "github.com", "--git-protocol", "https",
                "--web", "--scopes", "repo,workflow", env=self.env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT)
            self.process.stdin.write(b"\n")
            await self.process.stdin.drain()
            self.process.stdin.close()
            async with asyncio.timeout(900):
                text = ""
                while True:
                    chunk = await self.process.stdout.read(512)
                    if not chunk:
                        break
                    text = (text + chunk.decode("utf-8", "replace"))[-8192:]
                    code = re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", text)
                    if code:
                        self.auth.update(status="waiting", code=code[0])
                returncode = await self.process.wait()
            if returncode:
                raise SafeError("GITHUB")
            await asyncio.to_thread(self.identity)
            self.auth.update(status="connected", code="")
        except (Exception, asyncio.CancelledError):
            self.auth.update(status="failed", code="")
        finally:
            if self.process and self.process.returncode is None:
                self.process.kill()
                await self.process.wait()

    async def close(self):
        if self.auth_task and not self.auth_task.done():
            self.auth_task.cancel()
            await asyncio.gather(self.auth_task, return_exceptions=True)
