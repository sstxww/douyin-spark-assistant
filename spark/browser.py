from __future__ import annotations

import time
import uuid
from .core import SafeError

CHAT_URL = "https://www.douyin.com/chat"
# Compatibility strings from public DOM research; see docs/COMPATIBILITY.md.
SEARCH = 'input[placeholder*="搜索"], input[aria-label*="搜索"]'
SEARCH_ROWS = '[class*="SearchPanelitembox"], [class*="SearchPanelitem-box"], [class*="SearchPanelitem_box"]'
SEARCH_NAMES = '[class*="SearchPanelitemtitle"], [class*="SearchPanelitemTitle"], [class*="SearchPanelitem_name"], [class*="SearchPanelitemname"]'
CONVERSATIONS = '[data-e2e="conversation-item"], .conversationConversationItemwrapper'
CONVERSATION_NAMES = '[class*="conversationConversationItemtitle"], [class*="ConversationItemTitle"], [class*="conversation-item-title"]'
HEADERS = '[class*="RightPanelHeadertitle"], [class*="RightPanelHeaderTitle"], [class*="RightPanelHeader_title"], [class*="RightPanelHeader-title"], [class*="chatHeadertitle"], [class*="chatHeaderTitle"], [class*="chatHeader_title"], [class*="chatHeader-title"], [class*="ChatHeaderTitle"], [class*="ChatHeader_title"], [class*="ChatHeader-title"]'
HEADER_CONTAINERS = '[class*="RightPanelHeader"], [class*="chatHeader"], [class*="ChatHeader"]'
HEADER_FALLBACK_NAMES = '[class*="nickname"], [class*="Nickname"], [class*="name"], [class*="Name"]'
EDITORS = '.DraftEditor-root [contenteditable="true"], [class*="messageEditor"] [contenteditable="true"], [contenteditable="true"][aria-label*="消息"], textarea[placeholder*="消息"]'
SEND = '[class*="messageMsgInputpublishBtn"], .e2e-send-msg-bt, button[aria-label="发送"], [role="button"][aria-label="发送"]'
OUTGOING = '[class*="messageMessageBoxmessageBox"]:has([class*="messageMessageBoxisFromMe"])'
CONTENT = '[data-e2e="msg-item-content"], [class*="messageMessageBoxcontentBox"]'
FAIL = '[class*="SendStatusretry"], [class*="sendFailed"], [class*="SendFailed"], [aria-label*="重试"], [title*="重试"]'
PENDING = '.semi-spin, [class*="im-saas-message-spin"], [data-icon="spin"]'


def visible(locator):
    return [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]


def unique(locator, code="EDITOR"):
    items = visible(locator)
    if len(items) != 1:
        raise SafeError(code)
    return items[0]


def composer_text(editor):
    """Read text without treating Editor Kit's boundary caret as a draft.

    Only the observed editor-kit/ace-line shape gets this normalization.
    Never delete internal zero-width characters or emoji joiners, and never
    treat images, mentions or other non-text attachments as an empty draft.
    """
    if editor.evaluate("e => e.tagName") == "TEXTAREA":
        return editor.input_value()
    if editor.locator('img, video, audio, canvas, iframe, [contenteditable="false"]').count():
        raise SafeError("EDITOR")
    value = editor.inner_text()
    is_editor_kit = editor.evaluate(
        "e => e.classList.contains('editor-kit-container') && "
        "e.classList.contains('messageEditorinputArea') && !!e.querySelector('.ace-line')")
    if is_editor_kit:
        return value.strip(" \t\r\n\u200b\ufeff")
    return value


def health(page):
    for text in ("安全验证", "完成验证", "验证身份", "操作频繁"):
        if visible(page.get_by_text(text, exact=True)):
            raise SafeError("RISK")
    for text in ("扫码登录", "验证码登录", "登录后即可发送消息"):
        if visible(page.get_by_text(text, exact=True)):
            raise SafeError("AUTH")


def wait_chat_ready(page, timeout: float = 40.0):
    """Wait for the existing chat list to hydrate, not a fixed startup sleep.

    This helper never types or clicks and always honors login/risk screens.
    An empty/unloaded account fails closed instead of guessing a recipient.
    """
    deadline = time.monotonic() + timeout
    while True:
        health(page)
        searches = visible(page.locator(SEARCH))
        if len(searches) > 1:
            raise SafeError("TARGET")
        rows = visible(page.locator(CONVERSATIONS))
        hydrated = any(any(n.inner_text().strip()
                          for n in visible(row.locator(CONVERSATION_NAMES)))
                       for row in rows)
        if len(searches) == 1 and hydrated:
            return
        if time.monotonic() >= deadline:
            raise SafeError("LOADING")
        page.wait_for_timeout(250)


def imported_contacts(page) -> list[str]:
    """Only the currently loaded conversation titles, not a full friend export."""
    health(page)
    names = [n.inner_text().strip() for n in visible(page.locator(CONVERSATION_NAMES))]
    return sorted({n for n in names if n and names.count(n) == 1})


class Chat:
    def __init__(self, page):
        self.page = page

    def open(self, name: str):
        health(self.page)
        # Prefer a unique already-loaded conversation. This is both more stable
        # and safer than choosing among multiple global-search categories.
        conversations = []
        for row in visible(self.page.locator(CONVERSATIONS)):
            if any(n.inner_text().strip() == name
                   for n in visible(row.locator(CONVERSATION_NAMES))):
                conversations.append(row)
        if len(conversations) > 1:
            raise SafeError("TARGET")
        if len(conversations) == 1:
            candidates = conversations
        else:
            search = unique(self.page.locator(SEARCH), "TARGET")
            search.fill(name)
            self.page.wait_for_timeout(1400)
            health(self.page)
            candidates = []
            for row in visible(self.page.locator(SEARCH_ROWS)):
                matches = [n for n in visible(row.locator(SEARCH_NAMES))
                           if n.inner_text().strip() == name]
                if matches:
                    buttons = visible(row.locator('[class*="SearchPanelitemchat_btn"]'))
                    if len(buttons) != 1:
                        raise SafeError("TARGET")
                    candidates.append(buttons[0])
        if len(candidates) != 1:
            raise SafeError("TARGET")
        candidates[0].click(timeout=10_000)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                self.confirm(name)
                return
            except SafeError as exc:
                if exc.code != "HEADER":
                    raise
                self.page.wait_for_timeout(250)
        raise SafeError("HEADER")

    def confirm(self, name: str):
        health(self.page)
        # Douyin changes hashed/header class variants frequently. Keep identity
        # verification strict on TEXT, but allow the exact title to live under a
        # visible header container instead of requiring one historical class.
        matched = any(h.inner_text().strip() == name for h in visible(self.page.locator(HEADERS)))
        if not matched:
            for container in visible(self.page.locator(HEADER_CONTAINERS)):
                if any(n.inner_text().strip() == name
                       for n in visible(container.locator(HEADER_FALLBACK_NAMES))):
                    matched = True
                    break
        if not matched:
            raise SafeError("HEADER")
        unique(self.page.locator(EDITORS))

    def prepare(self, name: str, text: str):
        self.confirm(name)
        editor = unique(self.page.locator(EDITORS))
        current = composer_text(editor)
        if current.strip():
            raise SafeError("EDITOR")
        editor.click()
        self.page.keyboard.insert_text(text)
        self.page.wait_for_timeout(250)
        actual = composer_text(editor)
        if actual.strip() != text.strip():
            raise SafeError("EDITOR")
        unique(self.page.locator(SEND))  # Never guess an Enter-key behavior.
        self.confirm(name)

    def send_prepared(self, name: str, text: str, timeout=20.0, clean_window=3.0):
        # Caller MUST durably reserve the daily target before calling this method.
        self.confirm(name)
        if composer_text(unique(self.page.locator(EDITORS))).strip() != text.strip():
            raise SafeError("EDITOR")
        anchor = uuid.uuid4().hex
        self.page.locator(OUTGOING).evaluate_all(
            "(nodes, value) => nodes.forEach(e => e.setAttribute('data-spark-before', value))", anchor)
        unique(self.page.locator(SEND)).click(timeout=10_000)
        deadline = time.monotonic() + timeout
        clean_since = None
        while time.monotonic() < deadline:
            health(self.page)
            self.confirm(name)
            fresh = []
            for item in visible(self.page.locator(OUTGOING)):
                if item.get_attribute("data-spark-before") == anchor:
                    continue
                if any(c.inner_text().strip() == text.strip()
                       for c in visible(item.locator(CONTENT))):
                    fresh.append(item)
            if len(fresh) == 1:
                item = fresh[0]
                if visible(item.locator(FAIL)) or visible(item.get_by_text("发送失败", exact=True)):
                    raise SafeError("REJECTED")
                if not visible(item.locator(PENDING)):
                    if clean_since is None:
                        clean_since = time.monotonic()
                    if time.monotonic() - clean_since >= clean_window:
                        return  # UI-confirmed, NOT a guarantee of streak renewal.
                else:
                    clean_since = None
            else:
                clean_since = None
            self.page.wait_for_timeout(200)
        raise SafeError("UNCERTAIN")
