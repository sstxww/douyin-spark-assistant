"""GitHub runner with per-target results; no names or message text in public logs."""
from __future__ import annotations
import json
import os
import sys
from run import report
from spark.core import SafeError, today
from spark.schedule import now_local, run_created_at, occurrence, occurrence_key
from spark.web_config import cloud_accounts


def outcome(account: str, target: int, state: str, code: str = ""):
    report("SPARK_RESULT " + json.dumps({"v": 1, "account": account, "target": target,
                                          "state": state, "code": code}, separators=(",", ":")))


def main() -> int:
    mode = os.getenv("SPARK_MODE", "check")
    try:
        if mode not in ("check", "send"):
            raise SafeError("CONFIG")
        if mode == "send" and os.getenv("SPARK_WEB_ENABLED") != "true":
            raise SafeError("DISABLED")
        manifest, accounts = cloud_accounts(os.environ, os.getenv("SPARK_ACCOUNT", "all"))
        event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        period = None
        created = run_created_at(os.environ)
        if mode == "send":
            period = occurrence(manifest["time"], created, event, os.getenv("SPARK_SCHEDULE", ""))
            if not period.active(now_local()):
                report("本次运行对应的发送时段已结束或尚未开始；跳过，不补发。")
                return 0
            day = period.day
            report(f"本次为 UTC+8 {day.isoformat()} 第 {period.index} 时段；每个对象每时段最多一次。")
        else:
            day = today()
        plans = [(slot, cfg, state, [(t, cfg.message(t, day)) for t in cfg.targets if t.enabled])
                 for slot, cfg, state in accounts]
        ledger = None
        if mode == "send":
            from spark.ledger import GitHubLedger
            ledger = GitHubLedger(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""), day)
        errors = 0
        todo = []
        # Repeated dispatches resolve from the ledger before any Douyin access.
        # A reserved/uncertain entry is NOT a successful delivery.
        for number, (slot, cfg, state, targets) in enumerate(plans, 1):
            for index, (target, text) in enumerate(targets, 1):
                key = occurrence_key(manifest["key"], cfg, target, period.index if period else 1)
                previous = ledger.data["entries"].get(key) if ledger else None
                if previous == "ui_confirmed":
                    report(f"账号 {number} / 对象 {index}：本时段已确认，跳过，未重复发送。")
                    outcome(slot, index, "already_confirmed")
                elif previous == "reserved":
                    errors += 1
                    report(f"账号 {number} / 对象 {index}：[UNCERTAIN] 先前尝试结果不确定；不重发，需核对。")
                    outcome(slot, index, "uncertain", "UNCERTAIN")
                else:
                    todo.append((number, slot, cfg, state, index, target, text, key))
        if not todo:
            report("所有对象本时段均有页面确认，无需发送。" if not errors else "有未确认记录，不能按全部成功处理。")
            return 1 if errors else 0
        from playwright.sync_api import sync_playwright
        from spark.browser import CHAT_URL, Chat, wait_chat_ready
        blocked_accounts = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for number, slot, cfg, state, index, target, text, key in todo:
                    if slot in blocked_accounts:
                        errors += 1
                        outcome(slot, index, "needs_attention", blocked_accounts[slot])
                        continue
                    context = None
                    reserved = False
                    try:
                        # A fresh context per target avoids carrying another target's
                        # failed draft or half-mounted chat into the next operation.
                        context = browser.new_context(storage_state=state, locale="zh-CN", timezone_id="Asia/Shanghai")
                        page = context.new_page()
                        page.set_default_timeout(10_000)
                        page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
                        wait_chat_ready(page)
                        chat = Chat(page)
                        report(f"账号 {number} / 对象 {index}：开始核对，尚未触发发送。")
                        chat.open(target.name)
                        if mode == "check":
                            report(f"账号 {number} / 对象 {index}：对象与输入框检查通过；未发送。")
                            outcome(slot, index, "checked")
                            continue
                        if not period.active(now_local()):
                            raise SafeError("LEDGER")
                        chat.prepare(target.name, text)
                        report(f"账号 {number} / 对象 {index}：发送前校验通过。")
                        if not ledger.reserve(key):
                            # Another writer / race must never turn a reservation
                            # into proof of delivery.
                            errors += 1
                            outcome(slot, index, "uncertain", "UNCERTAIN")
                            continue
                        reserved = True
                        if not period.active(now_local()):
                            raise SafeError("LEDGER")
                        chat.send_prepared(target.name, text)
                        ledger.confirm(key)
                        report(f"账号 {number} / 对象 {index}：页面确认新消息；火花请自行核对。")
                        outcome(slot, index, "ui_confirmed")
                        page.wait_for_timeout(5000)
                    except SafeError as exc:
                        errors += 1
                        report(f"账号 {number} / 对象 {index} 已停止 [{exc.code}]：{exc}")
                        classification = "uncertain" if reserved else (
                            "retryable_before_send" if exc.code in ("LOADING", "GITHUB", "INTERNAL") else "needs_attention")
                        outcome(slot, index, classification, exc.code)
                        if exc.code in ("AUTH", "RISK"):
                            blocked_accounts[slot] = exc.code
                        if exc.code == "LEDGER":
                            raise
                    except Exception:
                        errors += 1
                        report(f"账号 {number} / 对象 {index} 已停止 [INTERNAL]：异常详情已隐藏。")
                        outcome(slot, index, "uncertain" if reserved else "retryable_before_send", "INTERNAL")
                    finally:
                        if context:
                            try:
                                context.close()
                            except Exception:
                                pass
            finally:
                browser.close()
        if errors:
            report("本次存在未完成或未确认对象；只有明确未触发发送的临时故障可由补漏助手有限重试。")
            return 1
        report("全部选中账号检查通过（未发送）。" if mode == "check" else "本次计划全部完成；页面确认不等于对方已读或火花结果。")
        return 0
    except SafeError as exc:
        report(f"停止 [{exc.code}]：{exc}")
        return 1
    except Exception:
        report("停止 [INTERNAL]：异常详情已隐藏，防止泄露凭据。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
