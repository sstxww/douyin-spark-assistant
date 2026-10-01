"""Private Codespaces control panel. No public hosting, remote shell or cookie API."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from spark.core import SafeError, TZ
from spark.web_config import SLOTS, Workspace, new_account, public_view
from .backup import decrypt, encrypt
from .cloud import GitHubCloud, detect_repository
from .login import LoginBrowser, account_hint

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "static"


def allowed_hosts() -> set[str]:
    hosts = {"127.0.0.1:8765", "localhost:8765"}
    name = os.getenv("CODESPACE_NAME", "")
    domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    if name:
        hosts.add(f"{name}-8765.{domain}")
    return hosts


def create_app(root: Path | None = None, repository: str | None = None, hosts: set | None = None, *, local: bool = False) -> FastAPI:
    private = root or Path(os.getenv("SPARK_WEB_HOME", str(ROOT / ".local" / ("web-local" if local else "web"))))
    workspace = Workspace(private)
    cloud = GitHubCloud(private, repository or detect_repository(), local_cli=local)
    browser = LoginBrowser(local=local)
    csrf = secrets.token_urlsafe(32)
    permitted = hosts if hosts is not None else allowed_hosts()
    lock = asyncio.Lock()

    async def expire_preview():
        while True:
            await asyncio.sleep(30)
            async with browser.lock:
                if browser.page and time.monotonic() >= browser.expires:
                    await browser.close()

    @asynccontextmanager
    async def lifespan(app):
        reaper = asyncio.create_task(expire_preview())
        yield
        reaper.cancel()
        await asyncio.gather(reaper, return_exceptions=True)
        await cloud.close()
        async with browser.lock:
            await browser.close()

    app = FastAPI(title="火花小助手", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # Exposed only to local tests; never serialized into API responses.
    app.state.workspace, app.state.cloud, app.state.browser = workspace, cloud, browser

    @app.middleware("http")
    async def security(request: Request, call_next):
        host = request.headers.get("host", "")
        status = None
        if host not in permitted:
            status = 403
        elif request.headers.get("sec-fetch-site") == "cross-site" and request.url.path != "/":
            status = 403
        if request.url.path.startswith("/api/") and request.url.path != "/api/bootstrap":
            if not secrets.compare_digest(request.headers.get("x-spark-csrf", ""), csrf):
                status = 403
        if request.method not in ("GET", "HEAD"):
            origin = urlsplit(request.headers.get("origin", ""))
            if origin.netloc not in permitted or origin.scheme not in ("http", "https"):
                status = 403
            if origin.netloc.endswith(".github.dev") and origin.scheme != "https":
                status = 403
        try:
            length = int(request.headers.get("content-length", "0"))
            if length < 0 or length > 4_500_000:
                status = 413
        except ValueError:
            status = 400
        if status:
            response = JSONResponse({"ok": False, "error": "访问被拒绝，请从本人私有页面重新打开。"}, status_code=status)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse({"ok": False, "code": "INTERNAL", "error": "操作失败，详情未公开；请刷新后检查状态。"}, status_code=500)
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(SafeError)
    async def safe_error(request, exc):
        return JSONResponse({"ok": False, "code": exc.code, "error": str(exc)}, status_code=400)

    async def body(request):
        raw = await request.body()
        if len(raw) > 4_500_000:
            raise SafeError("CONFIG")
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise SafeError("CONFIG")
            return result
        except (ValueError, TypeError):
            raise SafeError("CONFIG") from None

    def view():
        return {"ok": True, "workspace": public_view(workspace.data), "repository": cloud.repository,
                "runtime": {"local": local, "session_reuse": local}}

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{name}")
    async def assets(name: str):
        if name not in ("app.js", "style.css"):
            return Response(status_code=404)
        return FileResponse(STATIC / name)

    @app.get("/health")
    async def health():
        return {"ok": True, "application": "spark-assistant", "local": local}

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {"csrf": csrf}

    @app.get("/api/state")
    async def state():
        return view()

    @app.get("/api/cloud")
    async def cloud_state():
        try:
            result = await asyncio.to_thread(cloud.status)
            return {"ok": True, **result, "auth": cloud.auth}
        except SafeError:
            return {"ok": True, "connected": False, "auth": cloud.auth, "runs": [], "enabled": None}

    @app.post("/api/github/login")
    async def github_login(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("CONFIG")
        return {"ok": True, "auth": await cloud.start_auth()}

    @app.post("/api/account/add")
    async def account_add(request: Request):
        data = await body(request)
        async with lock:
            ws = copy.deepcopy(workspace.data)
            used = {a["slot"] for a in ws["accounts"]}
            slot = next((s for s in SLOTS if s not in used), None)
            if slot is None:
                raise SafeError("CONFIG")
            ws["accounts"].append(new_account(slot, data.get("label", "")))
            workspace.save(ws)
        return view()

    @app.post("/api/account/remove")
    async def account_remove(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("CONFIG")
        async with lock:
            workspace.account(data.get("slot"))
            ws = copy.deepcopy(workspace.data)
            ws["accounts"] = [a for a in ws["accounts"] if a["slot"] != data["slot"]]
            workspace.save(ws)
            async with browser.lock:
                if browser.slot == data["slot"]:
                    await browser.close()
        return view()

    @app.post("/api/settings")
    async def settings(request: Request):
        data = await body(request)
        async with lock:
            ws = copy.deepcopy(workspace.data)
            rows = data.get("accounts")
            if (not isinstance(rows, list) or len(rows) != len(ws["accounts"])
                    or {a.get("slot") for a in rows} != {a["slot"] for a in ws["accounts"]}):
                raise SafeError("CONFIG")
            ws["time"] = data.get("time")
            for saved in ws["accounts"]:
                row = next(r for r in rows if r["slot"] == saved["slot"])
                saved["label"], saved["enabled"] = row.get("label"), row.get("enabled")
                # Account ids, login states and the deduplication key are never client-editable.
                saved["config"].update(mode=row.get("config", {}).get("mode"),
                    messages=row.get("config", {}).get("messages"), targets=row.get("config", {}).get("targets"))
            workspace.save(ws)
        return view()

    @app.post("/api/template/save")
    async def template_save(request: Request):
        data = await body(request)
        async with lock:
            ws = copy.deepcopy(workspace.data)
            ws["templates"].append({"id": secrets.token_hex(8), "title": data.get("title"),
                                    "mode": data.get("mode"), "messages": data.get("messages")})
            workspace.save(ws)
        return view()

    @app.post("/api/template/remove")
    async def template_remove(request: Request):
        data = await body(request)
        async with lock:
            ws = copy.deepcopy(workspace.data)
            ws["templates"] = [t for t in ws["templates"] if t["id"] != data.get("id")]
            workspace.save(ws)
        return view()

    @app.post("/api/login/start")
    async def login_start(request: Request):
        data = await body(request)
        async with lock:
            workspace.account(data.get("slot"))
            async with browser.lock:
                if local:
                    saved = copy.deepcopy(workspace.account(data["slot"]).get("state"))
                    await browser.start(data["slot"], state=saved)
                else:
                    await browser.start(data["slot"])
        return {"ok": True, "slot": data["slot"]}

    @app.get("/api/login/frame")
    async def login_frame():
        async with browser.lock:
            image = await browser.frame()
        return Response(image, media_type="image/jpeg")

    @app.post("/api/login/click")
    async def login_click(request: Request):
        data = await body(request)
        if type(data.get("x")) not in (float, int) or type(data.get("y")) not in (float, int):
            raise SafeError("CONFIG")
        async with browser.lock:
            await browser.click(data["x"], data["y"])
        return {"ok": True}

    @app.post("/api/login/finish")
    async def login_finish(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("LOGIN")
        async with lock:
            async with browser.lock:
                state, contacts = await browser.finish(data.get("slot"))
                hint = account_hint(state)
                ws = copy.deepcopy(workspace.data)
                for other in ws["accounts"]:
                    if other["slot"] != data["slot"] and other.get("state") and hint and account_hint(other["state"]) == hint:
                        raise SafeError("DUPLICATE")
                row = next(a for a in ws["accounts"] if a["slot"] == data["slot"])
                row.update(state=state, contacts=contacts, saved_at=datetime.now(TZ).isoformat(timespec="minutes"))
                workspace.save(ws)
                await browser.close()
        return view()

    @app.post("/api/login/close")
    async def login_close():
        async with browser.lock:
            await browser.close()
        return {"ok": True}

    @app.post("/api/publish")
    async def publish():
        async with lock:
            snapshot = copy.deepcopy(workspace.data)
            revision, head = await asyncio.to_thread(cloud.publish, snapshot)
            snapshot.update(revision=revision, deployed_head=head, published=True, repository=cloud.repository)
            workspace.save(snapshot, changed=False)
        return view()

    @app.post("/api/run")
    async def run(request: Request):
        data = await body(request)
        if data.get("mode") == "send" and data.get("confirmed") is not True:
            raise SafeError("CONFIG")
        async with lock:
            await asyncio.to_thread(cloud.dispatch, copy.deepcopy(workspace.data), data.get("mode"), data.get("account", "all"))
        return {"ok": True}

    @app.post("/api/enable")
    async def enable(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("CONFIG")
        async with lock:
            await asyncio.to_thread(cloud.enable, copy.deepcopy(workspace.data))
        return {"ok": True}

    @app.post("/api/pause")
    async def pause():
        async with lock:
            await asyncio.to_thread(cloud.pause)
        return {"ok": True}

    @app.post("/api/cancel")
    async def cancel(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("CONFIG")
        async with lock:
            await asyncio.to_thread(cloud.cancel)
        return {"ok": True}

    @app.post("/api/backup/export")
    async def export_backup(request: Request):
        data = await body(request)
        async with lock:
            result = await asyncio.to_thread(encrypt, copy.deepcopy(workspace.data), data.get("password"))
        return {"ok": True, "backup": result}

    @app.post("/api/backup/import")
    async def import_backup(request: Request):
        data = await body(request)
        if data.get("confirmed") is not True:
            raise SafeError("BACKUP")
        async with lock:
            ws = await asyncio.to_thread(decrypt, data.get("backup"), data.get("password"))
            workspace.save(ws)
        return view()

    return app


def main():
    import uvicorn
    # Default 127.0.0.1; Codespaces' private forwarder supplies HTTPS/authentication.
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
