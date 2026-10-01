from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from spark.core import Config, SafeError, today, target_key, unpack_state


def report(text: str):
    # Only fixed messages / counters are allowed here. Never print config or errors from Playwright.
    print(text, flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as f:
            f.write(text + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Douyin spark assistant; check is the default")
    parser.add_argument("--mode", choices=("check", "send"), default=os.getenv("SPARK_MODE", "check"))
    args = parser.parse_args()
    try:
        if args.mode == "send" and os.getenv("SPARK_ENABLED") != "true":
            raise SafeError("DISABLED")
        config = Config.parse(json.loads(os.environ.get("SPARK_CONFIG", "{}")))
        state = unpack_state(os.environ.get("DOUYIN_STATE", ""))
        day = today()
        key_secret = os.getenv("SPARK_KEY", "")
        targets = [t for t in config.targets if t.enabled]
        # Validate every payload before opening any chats.
        texts = [config.message(t, day) for t in targets]
        ledger = None
        if args.mode == "send":
            from spark.ledger import GitHubLedger
            for target in targets:
                target_key(key_secret, config, target)
            ledger = GitHubLedger(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""), day)
        from playwright.sync_api import sync_playwright
        from spark.browser import CHAT_URL, Chat, health
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=state, locale="zh-CN", timezone_id="Asia/Shanghai")
                page = context.new_page()
                page.set_default_timeout(10_000)
                page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(4500)
                health(page)
                chat = Chat(page)
                for index, (target, text) in enumerate(zip(targets, texts), 1):
                    key = target_key(key_secret, config, target) if ledger else ""
                    if ledger and ledger.contains(key):
                        report(f"对象 {index}：当天已有发送尝试记录，跳过。")
                        continue
                    chat.open(target.name)
                    if args.mode == "check":
                        report(f"对象 {index}：精确匹配和聊天输入框检查通过，未输入或发送消息。")
                        continue
                    if today() != day:
                        raise SafeError("LEDGER")  # Do not cross the local day boundary mid-run.
                    chat.prepare(target.name, text)
                    if not ledger.reserve(key):
                        continue
                    chat.send_prepared(target.name, text)
                    ledger.confirm(key)
                    report(f"对象 {index}：页面已确认新消息，无失败标志；火花状态请在抖音核对。")
                    page.wait_for_timeout(5000)
            finally:
                browser.close()
        report("检查完成（未发送）。" if args.mode == "check" else "本次发送任务结束。")
        return 0
    except SafeError as exc:
        report(f"停止 [{exc.code}]：{exc}")
        return 1
    except Exception:
        # Exceptions may embed chat contents, cookies, URLs, or selectors with names.
        report("停止 [INTERNAL]：运行异常；未输出原始异常，避免泄露私人信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
