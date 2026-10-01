"""Local-only UI entry point; never run as an internet-facing service."""
from __future__ import annotations
import asyncio
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8767
URL = f"http://127.0.0.1:{PORT}"


def ready() -> bool:
    try:
        with urllib.request.urlopen(URL + "/health", timeout=1) as response:
            data = json.load(response)
        return data.get("application") == "spark-assistant" and data.get("local") is True
    except Exception:
        return False


def open_when_ready():
    for _ in range(60):
        if ready():
            webbrowser.open(URL)
            return
        time.sleep(0.25)


def main():
    if os.getenv("CODESPACE_NAME") or os.getenv("CODESPACES") == "true":
        print("Local mode must run on your own computer, not Codespaces.")
        return 1
    if ready():
        webbrowser.open(URL)
        return 0
    # Never stop or replace an unrelated local service using this port.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            print("Port 8767 is occupied. Close the previous Spark local panel and retry.")
            return 1
    from webui.server import create_app
    from spark.web_config import new_account
    import uvicorn
    root = Path(__file__).resolve().parent / ".local" / "web-local"
    app = create_app(root, hosts={f"127.0.0.1:{PORT}", f"localhost:{PORT}"}, local=True)
    # No recipients and no send permissions are selected automatically.
    if not app.state.workspace.data["accounts"]:
        data = app.state.workspace.data.copy()
        data["accounts"] = [new_account("a1", "我的账号")]
        app.state.workspace.save(data)
    threading.Thread(target=open_when_ready, daemon=True).start()
    print("Spark local panel: " + URL + "  (close this window to stop)")
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT,
                            access_log=False, log_level="critical", loop="asyncio")
    # Explicit asyncio.run keeps the Windows Proactor loop needed by Playwright.
    asyncio.run(uvicorn.Server(config).serve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        # Do not print browser call logs, session data, or local credential values.
        print("Startup failed. Re-run start-local.bat; private details were not printed.")
        raise SystemExit(1)
