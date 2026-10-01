from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TZ = timezone(timedelta(hours=8), "UTC+8")
LOCAL = Path(__file__).resolve().parents[1] / ".local"
ERRORS = {
    "CONFIG": "配置不完整或格式不正确，请重新保存配置。",
    "AUTH": "登录已失效或未登录，请重新扫码登录并上传。",
    "RISK": "页面要求验证或限制操作；已停止，请本人在抖音中处理。",
    "TARGET": "没有找到唯一、精确匹配的好友；请为好友设置唯一备注。",
    "HEADER": "无法确认当前聊天对象，已停止，未发送。",
    "EDITOR": "输入框或发送按钮不唯一、不可用，或已有草稿；已停止。",
    "UNCERTAIN": "已尝试发送，但页面结果不确定；当天不再自动重试，请手动核对。",
    "REJECTED": "页面提示发送失败；当天不再自动重试，请手动核对。",
    "LEDGER": "去重记录不可用或写入失败；为避免重复，已停止发送。",
    "GITHUB": "GitHub 操作失败，请检查 gh 登录、仓库权限或网络。",
    "DISABLED": "自动发送尚未开启。",
    "RESTORE": "仓库已有网页配置，请打开原 Codespace 或导入加密备份；不会覆盖原有去重密钥。",
    "CAPACITY": "账号数据超过 GitHub 单个 Secret 容量，未上传；请重新登录减少状态数据。",
    "STALE": "云端配置版本不一致或已更新，请重新发布并检查。",
    "BUSY": "仍有任务运行或排队；已暂停新发送，请在 Actions 取消或等任务结束后重试。",
    "CHECK": "请先对当前已发布版本执行全部账号的只检查，确认通过后再开启。",
    "BACKUP": "加密备份无效或密码不正确，未导入任何数据。",
    "LOGIN": "尚未确认登录成功，请在私有预览中完成扫码并核对账号。",
    "DUPLICATE": "检测到相同账号的登录标识；请在原账号卡片重新登录，不要重复添加。",
    "INTERNAL": "运行遇到异常，已停止；请检查网络、依赖和网页版本。",
}


class SafeError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "INTERNAL"
        super().__init__(ERRORS[self.code])


def today() -> date:
    return datetime.now(TZ).date()


def to_cron(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise SafeError("CONFIG")
    hour, minute = map(int, value.split(":"))
    return f"{minute} {(hour - 8) % 24} * * *"


def _texts(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise SafeError("CONFIG")
    if any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in value):
        raise SafeError("CONFIG")
    return [x.strip() for x in value]


@dataclass(frozen=True)
class Target:
    name: str
    enabled: bool
    messages: list[str] | None


@dataclass(frozen=True)
class Config:
    account_id: str
    time: str
    mode: str
    messages: list[str]
    targets: list[Target]

    @classmethod
    def parse(cls, raw: Any) -> "Config":
        try:
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise SafeError("CONFIG")
            account = raw["account_id"]
            if not isinstance(account, str) or not re.fullmatch(r"[a-f0-9]{32}", account):
                raise SafeError("CONFIG")
            when = raw["time"]
            to_cron(when)
            mode = raw.get("mode", "cycle")
            if mode not in ("fixed", "cycle", "random"):
                raise SafeError("CONFIG")
            messages = _texts(raw["messages"])
            rows = raw["targets"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
                raise SafeError("CONFIG")
            targets = []
            seen = set()
            for row in rows:
                name = row["name"]
                enabled = row.get("enabled", True)
                if (not isinstance(name, str) or not name.strip() or len(name) > 80
                        or type(enabled) is not bool):
                    raise SafeError("CONFIG")
                name = name.strip()
                if name in seen or any(ord(c) < 32 for c in name):
                    raise SafeError("CONFIG")
                seen.add(name)
                custom = row.get("messages")
                targets.append(Target(name, enabled, _texts(custom) if custom else None))
            if not any(t.enabled for t in targets):
                raise SafeError("CONFIG")
            return cls(account, when, mode, messages, targets)
        except (KeyError, TypeError, ValueError) as exc:
            raise SafeError("CONFIG") from exc

    def message(self, target: Target, day: date) -> str:
        choices = target.messages or self.messages
        if self.mode == "fixed":
            index = 0
        elif self.mode == "cycle":
            index = day.toordinal() % len(choices)
        else:
            # Stable within one day: a rerun cannot change the selected message.
            digest = hashlib.sha256(f"{day}|{target.name}".encode()).digest()
            index = int.from_bytes(digest[:8], "big") % len(choices)
        result = choices[index]
        for key, value in {"name": target.name, "date": day.isoformat(),
                           "weekday": "星期" + "一二三四五六日"[day.weekday()]}.items():
            result = result.replace("{" + key + "}", value)
        if not result.strip() or len(result) > 500:
            raise SafeError("CONFIG")
        return result


def target_key(secret: str, config: Config, target: Target) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", secret):
        raise SafeError("CONFIG")
    return hmac.new(bytes.fromhex(secret),
                    f"{config.account_id}\0{target.name}".encode(), hashlib.sha256).hexdigest()


def pack_state(state: dict) -> str:
    validate_state(state)
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > 2_000_000:
        raise SafeError("AUTH")
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    if len(encoded) > 47_000:
        raise SafeError("AUTH")
    return encoded


def unpack_state(value: str) -> dict:
    try:
        if len(value) > 48_000:
            raise SafeError("AUTH")
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value, validate=True))) as f:
            raw = f.read(2_000_001)
        if len(raw) > 2_000_000:
            raise SafeError("AUTH")
        state = json.loads(raw)
        validate_state(state)
        return state
    except (ValueError, OSError, EOFError, KeyError, TypeError) as exc:
        raise SafeError("AUTH") from exc


def validate_state(state: dict) -> None:
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise SafeError("AUTH")
    if any(not isinstance(c, dict) for c in state["cookies"]):
        raise SafeError("AUTH")
    if not any(c.get("name") and c.get("value") and
               (c.get("domain", "").lstrip(".") == "douyin.com" or
                c.get("domain", "").endswith(".douyin.com")) for c in state["cookies"]):
        raise SafeError("AUTH")


def save_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        f.write(content)
    temp.replace(path)
