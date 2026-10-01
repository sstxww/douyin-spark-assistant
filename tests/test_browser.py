"""DOM contract tests against a synthetic local page; NEVER logs into Douyin."""
import unittest
import os
from playwright.sync_api import sync_playwright
from spark.browser import Chat, health, composer_text, wait_chat_ready
from spark.core import SafeError

HTML = '''<!doctype html><meta charset="utf-8">
<input placeholder="搜索好友">
<div id="results"><div class="SearchPanelitembox">
<span class="SearchPanelitemtitle">好友甲</span>
<button class="SearchPanelitemchat_btn" onclick="document.querySelector('.RightPanelHeadertitle').textContent='好友甲'">发消息</button>
</div></div>
<div class="RightPanelHeadertitle">好友甲</div>
<div class="DraftEditor-root"><div id="editor" contenteditable="true" style="min-height:40px"></div></div>
<button class="messageMsgInputpublishBtn" onclick="send()">发送</button>
<div id="messages"></div>
<script>
window.mode = 'ok';
function send() {
 const box = document.createElement('div'); box.className='messageMessageBoxmessageBox';
 const content = document.createElement('div'); content.className='messageMessageBoxcontentBox messageMessageBoxisFromMe';
 content.setAttribute('data-e2e','msg-item-content'); content.textContent=document.querySelector('#editor').textContent;
 box.append(content); document.querySelector('#messages').append(box); document.querySelector('#editor').textContent='';
 if (mode==='pending') { const spin=document.createElement('span');spin.className='semi-spin';spin.textContent='loading';box.append(spin); }
 if (mode==='late-fail') setTimeout(()=>{const e=document.createElement('span');e.className='ContentSideSendStatusretry';e.textContent='!';box.append(e);},350);
}
</script>'''


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(headless=True, executable_path=os.getenv("SPARK_TEST_BROWSER"))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_content(HTML)
        self.chat = Chat(self.page)

    def tearDown(self):
        self.page.close()

    def test_exact_target_open_and_check_does_not_type(self):
        self.chat.open("好友甲")
        self.assertEqual(self.page.locator('#editor').inner_text(), '')
        self.assertEqual(self.page.locator('#messages').inner_text(), '')

    def test_duplicate_name_stops(self):
        self.page.evaluate("document.querySelector('#results').append(document.querySelector('.SearchPanelitembox').cloneNode(true))")
        with self.assertRaises(SafeError) as cm:
            self.chat.open("好友甲")
        self.assertEqual(cm.exception.code, "TARGET")

    def test_loaded_conversation_wins_over_duplicate_search_categories(self):
        self.page.evaluate("""() => {
            document.querySelector('#results').append(document.querySelector('.SearchPanelitembox').cloneNode(true));
            const row=document.createElement('div');
            row.setAttribute('data-e2e','conversation-item');
            row.innerHTML='<span class="conversationConversationItemtitle">好友甲</span>';
            row.onclick=()=>{document.querySelector('.RightPanelHeadertitle').textContent='好友甲';};
            document.body.prepend(row);
        }""")
        self.chat.open("好友甲")

    def test_nested_conversation_classes_do_not_count_as_extra_rows(self):
        self.page.evaluate("""() => {
            const row=document.createElement('div');
            row.className='conversationConversationItemwrapper conversationConversationItemisStickOnTop';
            row.innerHTML='<div class="conversationConversationItemrowArea2"><div class="conversationConversationItemtitleWrapper"><div class="conversationConversationItemtitle">好友甲</div></div></div>';
            row.onclick=()=>{document.querySelector('.RightPanelHeadertitle').textContent='好友甲';};
            document.body.prepend(row);
            document.querySelector('#results').remove();
        }""")
        self.chat.open("好友甲")

    def test_prefix_is_not_identity(self):
        with self.assertRaises(SafeError):
            self.chat.open("好友")

    def test_wrong_header_stops(self):
        with self.assertRaises(SafeError) as cm:
            self.chat.confirm("好友乙")
        self.assertEqual(cm.exception.code, "HEADER")

    def test_header_container_fallback_is_exact(self):
        self.page.evaluate("""() => {
            const title=document.querySelector('.RightPanelHeadertitle');
            title.outerHTML='<div class="RightPanelHeader"><span class="currentNickname">好友甲</span></div>';
        }""")
        self.chat.confirm("好友甲")
        with self.assertRaises(SafeError) as cm:
            self.chat.confirm("好友")
        self.assertEqual(cm.exception.code, "HEADER")

    def test_existing_draft_not_overwritten(self):
        self.page.locator('#editor').fill('我的草稿')
        with self.assertRaises(SafeError):
            self.chat.prepare("好友甲", "新消息")
        self.assertEqual(self.page.locator('#editor').inner_text(), '我的草稿')

    def set_editor_kit(self, value):
        self.page.locator('#editor').evaluate("""(e, text) => {
            e.className='editor-kit-container messageEditorinputArea';
            const line=document.createElement('div'); line.className='ace-line';
            const span=document.createElement('span'); span.textContent=text;
            line.append(span); e.replaceChildren(line);
        }""", value)

    def test_editor_kit_empty_caret_can_prepare_without_sending(self):
        self.set_editor_kit('\u200b')
        self.chat.prepare('好友甲', '🔥')
        self.assertEqual(composer_text(self.page.locator('#editor')), '🔥')
        self.assertEqual(self.page.locator('#messages').inner_text(), '')

    def test_editor_kit_real_draft_is_not_overwritten(self):
        self.set_editor_kit('\u200b我的草稿')
        before=self.page.locator('#editor').inner_html()
        with self.assertRaises(SafeError):
            self.chat.prepare('好友甲', '🔥')
        self.assertEqual(self.page.locator('#editor').inner_html(), before)

    def test_editor_kit_boundary_only_preserves_emoji_joiner(self):
        self.set_editor_kit('\u200b👩\u200d💻\ufeff')
        self.assertEqual(composer_text(self.page.locator('#editor')), '👩\u200d💻')
        self.set_editor_kit('甲\u200b乙')
        self.assertEqual(composer_text(self.page.locator('#editor')), '甲\u200b乙')

    def test_unknown_editor_zero_width_draft_still_stops(self):
        self.page.locator('#editor').fill('\u200b')
        with self.assertRaises(SafeError):
            self.chat.prepare('好友甲', '🔥')
        self.assertEqual(self.page.locator('#editor').inner_text(), '\u200b')

    def test_editor_kit_image_draft_is_not_empty(self):
        self.set_editor_kit('\u200b')
        self.page.locator('#editor').evaluate("e => e.append(document.createElement('img'))")
        before=self.page.locator('#editor').inner_html()
        with self.assertRaises(SafeError):
            self.chat.prepare('好友甲', '🔥')
        self.assertEqual(self.page.locator('#editor').inner_html(), before)

    def test_send_prepared_rechecks_exact_text_before_click(self):
        self.chat.prepare('好友甲', '原计划')
        self.page.locator('#editor').fill('已改动')
        with self.assertRaises(SafeError):
            self.chat.send_prepared('好友甲', '原计划', timeout=1)
        self.assertEqual(self.page.locator('#messages').inner_text(), '')

    def test_new_bubble_confirmed(self):
        self.chat.prepare("好友甲", "本地测试消息")
        self.chat.send_prepared("好友甲", "本地测试消息", timeout=3, clean_window=0.5)
        self.assertEqual(self.page.locator('#messages').inner_text(), '本地测试消息')

    def test_late_failure_is_not_success(self):
        self.page.evaluate("window.mode='late-fail'")
        self.chat.prepare("好友甲", "失败测试")
        with self.assertRaises(SafeError) as cm:
            self.chat.send_prepared("好友甲", "失败测试", timeout=3, clean_window=0.8)
        self.assertEqual(cm.exception.code, "REJECTED")

    def test_pending_is_not_success(self):
        self.page.evaluate("window.mode='pending'")
        self.chat.prepare("好友甲", "等待测试")
        with self.assertRaises(SafeError) as cm:
            self.chat.send_prepared("好友甲", "等待测试", timeout=1, clean_window=0.3)
        self.assertEqual(cm.exception.code, "UNCERTAIN")

    def test_ready_waits_for_delayed_chat_hydration_without_typing(self):
        self.page.evaluate("""() => setTimeout(() => {
            const row=document.createElement('div');
            row.setAttribute('data-e2e','conversation-item');
            row.innerHTML='<span class="conversationConversationItemtitle">好友甲</span>';
            document.body.prepend(row);
        }, 150)""")
        wait_chat_ready(self.page, timeout=2)
        self.assertEqual(self.page.locator('#editor').inner_text(), '')
        self.assertEqual(self.page.locator('#messages').inner_text(), '')

    def test_ready_does_not_accept_unhydrated_search_only_shell(self):
        with self.assertRaises(SafeError) as cm:
            wait_chat_ready(self.page, timeout=0.1)
        self.assertEqual(cm.exception.code, 'LOADING')

    def test_ready_never_waits_through_security_challenge(self):
        self.page.evaluate("document.body.insertAdjacentHTML('afterbegin','<div>安全验证</div>')")
        with self.assertRaises(SafeError) as cm:
            wait_chat_ready(self.page, timeout=2)
        self.assertEqual(cm.exception.code, 'RISK')

    def test_ready_rejects_duplicate_search_controls(self):
        self.page.evaluate("document.body.append(document.querySelector('input').cloneNode(true))")
        with self.assertRaises(SafeError) as cm:
            wait_chat_ready(self.page, timeout=2)
        self.assertEqual(cm.exception.code, 'TARGET')

    def test_security_challenge_stops(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div>安全验证</div>')")
        with self.assertRaises(SafeError) as cm:
            health(self.page)
        self.assertEqual(cm.exception.code, "RISK")
