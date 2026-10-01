"""GitHub runner for browser-managed accounts. Never prints names or message text."""
from __future__ import annotations
import os
import sys
from run import report
from spark.core import SafeError, target_key, today
from spark.web_config import cloud_accounts


def main() -> int:
    mode = os.getenv("SPARK_MODE", "check")
    try:
        if mode not in ("check", "send"):
            raise SafeError("CONFIG")
        if mode == "send" and os.getenv("SPARK_WEB_ENABLED") != "true":
            raise SafeError("DISABLED")
        manifest, accounts = cloud_accounts(os.environ, os.getenv("SPARK_ACCOUNT", "all"))
        day = today()
        # Prepare all messages before opening a browser or writing a ledger.
        plans = [(slot, cfg, state, [(t, cfg.message(t, day)) for t in cfg.targets if t.enabled])
                 for slot, cfg, state in accounts]
        ledger = None
        if mode == "send":
            from spark.ledger import GitHubLedger
            ledger = GitHubLedger(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""), day)
        from playwright.sync_api import sync_playwright
        from spark.browser import CHAT_URL, Chat, wait_chat_ready
        errors = 0
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for number, (slot, cfg, state, targets) in enumerate(plans, 1):
                    context = None
                    try:
                        context = browser.new_context(storage_state=state, locale="zh-CN", timezone_id="Asia/Shanghai")
                        page = context.new_page()
                        page.set_default_timeout(10_000)
                        page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
                        wait_chat_ready(page)
                        chat = Chat(page)
                        for index, (target, text) in enumerate(targets, 1):
                            key = target_key(manifest["key"], cfg, target)
                            if ledger and ledger.contains(key):
                                report(f"账号 {number} / 对象 {index}：今日已尝试，跳过，未重复发送。")
                                continue
                            report(f"账号 {number} / 对象 {index}：开始核对，尚未触发发送。")
                            chat.open(target.name)
                            if mode == "check":
                                report(f"账号 {number} / 对象 {index}：对象与输入框检查通过；未发送。")
                                continue
                            if today() != day:
                                raise SafeError("LEDGER")
                            chat.prepare(target.name, text)
                            report(f"账号 {number} / 对象 {index}：发送前校验通过。")
                            if not ledger.reserve(key):
                                continue
                            chat.send_prepared(target.name, text)
                            ledger.confirm(key)
                            report(f"账号 {number} / 对象 {index}：页面确认新消息；火花请自行核对。")
                            page.wait_for_timeout(5000)
                    except SafeError as exc:
                        errors += 1
                        report(f"账号 {number} 已停止 [{exc.code}]：{exc}")
                        if exc.code == "LEDGER":
                            raise
                    except Exception:
                        errors += 1
                        report(f"账号 {number} 已停止 [INTERNAL]：异常详情已隐藏。")
                    finally:
                        if context:
                            context.close()
            finally:
                browser.close()
        if errors:
            report("本次有账号未通过；不会自动重试不确定的发送。")
            return 1
        report("全部选中账号检查通过（未发送）。" if mode == "check" else "本次计划执行结束；包含跳过项时不代表每位好友都收到新消息。")
        return 0
    except SafeError as exc:
        report(f"停止 [{exc.code}]：{exc}")
        return 1
    except Exception:
        report("停止 [INTERNAL]：异常详情已隐藏，防止泄露凭据。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
