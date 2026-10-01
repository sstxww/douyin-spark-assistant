#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
python3 -m virtualenv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-web.txt
# Browser binaries/system libraries are already in the version-matched image.
.venv/bin/python -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()'
