"""Ephemeral, manually operated Douyin login preview. No cookie extraction API."""
from __future__ import annotations
import asyncio
import hashlib
import time
from urllib.parse import urlsplit
from spark.core import SafeError, validate_state
from spark.browser import CHAT_URL, CONVERSATION_NAMES, SEARCH


def douyin_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and (parsed.hostname == "douyin.com" or
                                         (parsed.hostname or "").endswith(".douyin.com"))


def account_hint(state: dict) -> str:
    # A conservative duplicate hint, NOT proof of identity. Cookie formats may change.
    cookies = {c["name"]: c["value"] for c in state.get("cookies", [])
               if (c.get("domain", "").lstrip(".") == "douyin.com")}
    value = cookies.get("uid_tt") or cookies.get("uid_tt_ss")
    return hashlib.sha256(value.encode()).hexdigest() if value else ""


class LoginBrowser:
    def __init__(self):
        self.pw = self.browser = self.context = self.page = None
        self.slot = None
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        self.pw = self.browser = self.context = self.page = None
        self.slot = None
        self.expires = 0

    async def start(self, slot: str):
        await self.close()
        from playwright.async_api import async_playwright
        try:
            self.pw = await async_playwright().start()
            self.browser = await self.pw.chromium.launch(headless=True)
            # Clean isolated context: accounts never share cookies.
            self.context = await self.browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai",
                                                        viewport={"width": 1280, "height": 800})
            self.page = await self.context.new_page()
            self.page.on("popup", lambda page: asyncio.create_task(page.close()))
            self.page.set_default_timeout(10_000)
            self.slot, self.expires = slot, time.monotonic() + 900
            await self.page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
            await self.page.wait_for_timeout(2000)
        except Exception:
            await self.close()
            raise SafeError("LOGIN") from None

    async def guard(self):
        if not self.page or time.monotonic() >= self.expires:
            await self.close()
            raise SafeError("LOGIN")
        if not douyin_url(self.page.url):
            raise SafeError("LOGIN")

    async def frame(self) -> bytes:
        await self.guard()
        return await self.page.screenshot(type="jpeg", quality=75, full_page=False)

    async def click(self, x: float, y: float):
        await self.guard()
        if not (0 <= x < 1280 and 0 <= y < 800):
            raise SafeError("CONFIG")
        await self.page.mouse.click(x, y)
        await self.page.wait_for_timeout(400)

    async def finish(self, expected_slot: str) -> tuple[dict, list[str]]:
        await self.guard()
        if self.slot != expected_slot:
            raise SafeError("LOGIN")
        for text in ("安全验证", "完成验证", "验证身份", "操作频繁"):
            if await self.page.get_by_text(text, exact=True).is_visible():
                raise SafeError("RISK")
        for text in ("扫码登录", "验证码登录", "登录后即可发送消息"):
            nodes = self.page.get_by_text(text, exact=True)
            for i in range(await nodes.count()):
                if await nodes.nth(i).is_visible():
                    raise SafeError("LOGIN")
        state = await self.context.storage_state(indexed_db=True)
        validate_state(state)
        # Visitor cookies alone do NOT count as an authenticated session.
        logged = any(c.get("name") in ("sessionid", "sessionid_ss") and c.get("value")
                     and c.get("domain", "").lstrip(".") == "douyin.com" for c in state["cookies"])
        search = self.page.locator(SEARCH)
        search_visible = any([await search.nth(i).is_visible() for i in range(await search.count())])
        if not logged or not search_visible:
            raise SafeError("LOGIN")
        names = []
        nodes = self.page.locator(CONVERSATION_NAMES)
        for i in range(min(await nodes.count(), 500)):
            item = nodes.nth(i)
            if await item.is_visible():
                value = (await item.inner_text()).strip()
                if 1 <= len(value) <= 80:
                    names.append(value)
        return state, sorted(n for n in set(names) if names.count(n) == 1)
