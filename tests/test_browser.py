"""DOM contract tests against a synthetic local page; NEVER logs into Douyin."""
import unittest
import os
from playwright.sync_api import sync_playwright
from spark.browser import Chat, health
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

    def test_security_challenge_stops(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div>安全验证</div>')")
        with self.assertRaises(SafeError) as cm:
            health(self.page)
        self.assertEqual(cm.exception.code, "RISK")
