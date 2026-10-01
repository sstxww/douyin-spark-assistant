import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient
from spark.core import SafeError
from webui.cloud import GitHubCloud
from webui.login import LoginBrowser
from webui.server import create_app
from test_web_config import sample


class LocalCloudTests(unittest.TestCase):
    def test_local_uses_existing_cli_without_copying_token(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {
            'GH_CONFIG_DIR': str(Path(d)/'existing'), 'GH_TOKEN': 'never-copy',
            'GITHUB_TOKEN':'never-copy-either'}, clear=True):
            cloud=GitHubCloud(Path(d)/'panel','owner/demo',local_cli=True)
            self.assertEqual(cloud.env['GH_CONFIG_DIR'],str(Path(d)/'existing'))
            self.assertNotIn('GH_TOKEN',cloud.env)
            self.assertNotIn('GITHUB_TOKEN',cloud.env)
            self.assertEqual(list(cloud.auth_root.iterdir()),[])

    def test_local_mode_not_allowed_in_codespace(self):
        for env in ({'CODESPACE_NAME':'example'}, {'CODESPACES':'true'}):
            with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,env,clear=True):
                with self.assertRaises(SafeError):
                    GitHubCloud(Path(d),'owner/demo',local_cli=True)

    def test_cloud_mode_still_has_isolated_cli(self):
        with tempfile.TemporaryDirectory() as d:
            cloud=GitHubCloud(Path(d),'owner/demo')
            self.assertEqual(cloud.env['GH_CONFIG_DIR'],str(cloud.auth_root))


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(Path(self.tmp.name),'owner/demo',hosts={'testserver'},local=True)
        self.app.state.workspace.save(sample())
        self.client=TestClient(self.app)
        self.headers={'Origin':'http://testserver','X-Spark-CSRF':self.client.get('/api/bootstrap').json()['csrf']}

    def tearDown(self):
        self.client.close();self.tmp.cleanup()

    def test_health_identifies_local_mode(self):
        data=self.client.get('/health').json()
        self.assertEqual(data,{'ok':True,'application':'spark-assistant','local':True})

    def test_public_view_never_returns_credentials(self):
        data=self.client.get('/api/state',headers=self.headers).json()
        self.assertTrue(data['runtime']['session_reuse'])
        self.assertNotIn('state',data['workspace']['accounts'][0])
        self.assertNotIn('key',data['workspace'])

    def test_local_login_loads_saved_state_but_does_not_deploy(self):
        row=self.app.state.workspace.data['accounts'][0]
        saved=copy.deepcopy(row['state'])
        with patch.object(self.app.state.browser,'start',new_callable=AsyncMock) as start, patch.object(self.app.state.cloud,'publish') as publish:
            res=self.client.post('/api/login/start',json={'slot':row['slot']},headers=self.headers)
            self.assertEqual(res.status_code,200)
            start.assert_awaited_once_with(row['slot'],state=saved)
            self.assertIsNot(start.call_args.kwargs['state'],row['state'])
            publish.assert_not_called()

    def test_save_still_requires_person_to_confirm_account(self):
        with patch.object(self.app.state.browser,'finish',new_callable=AsyncMock) as finish:
            res=self.client.post('/api/login/finish',json={'slot':'a1'},headers=self.headers)
            self.assertEqual(res.status_code,400)
            finish.assert_not_called()

    def test_local_mode_csrf_unchanged(self):
        self.assertEqual(self.client.post('/api/login/start',json={'slot':'a1'}).status_code,403)
        self.assertEqual(self.client.get('/api/state',headers={**self.headers,'Sec-Fetch-Site':'cross-site'}).status_code,403)

    def test_cloud_mode_does_not_restore_saved_state_on_scan(self):
        with tempfile.TemporaryDirectory() as d:
            app=create_app(Path(d),'owner/demo',hosts={'testserver'})
            app.state.workspace.save(sample())
            with TestClient(app) as client, patch.object(app.state.browser,'start',new_callable=AsyncMock) as start:
                headers={'Origin':'http://testserver','X-Spark-CSRF':client.get('/api/bootstrap').json()['csrf']}
                self.assertEqual(client.post('/api/login/start',json={'slot':'a1'},headers=headers).status_code,200)
                start.assert_awaited_once_with('a1')


class LocalBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_state_rejected_by_cloud_login(self):
        browser=LoginBrowser()
        with self.assertRaises(SafeError):
            await browser.start('a1',state=sample()['accounts'][0]['state'])
        self.assertIsNone(browser.pw)

    async def test_local_invalid_state_stops_before_browser_launch(self):
        browser=LoginBrowser(local=True)
        with self.assertRaises(SafeError): await browser.start('a1',state={'cookies':'bad'})
        self.assertIsNone(browser.pw)

    async def test_local_launch_is_visible_and_restores_state(self):
        page=Mock();page.goto=AsyncMock();page.wait_for_timeout=AsyncMock()
        context=Mock();context.new_page=AsyncMock(return_value=page)
        browser=Mock();browser.new_context=AsyncMock(return_value=context);browser.close=AsyncMock()
        pw=Mock();pw.chromium.launch=AsyncMock(return_value=browser);pw.stop=AsyncMock()
        manager=Mock();manager.start=AsyncMock(return_value=pw)
        saved=sample()['accounts'][0]['state']
        with patch('playwright.async_api.async_playwright',return_value=manager):
            login=LoginBrowser(local=True)
            await login.start('a1',state=saved)
            pw.chromium.launch.assert_awaited_once_with(headless=False)
            self.assertEqual(browser.new_context.call_args.kwargs['storage_state'],saved)
            self.assertNotIn('user_data_dir',browser.new_context.call_args.kwargs)
            await login.close()

if __name__=='__main__':unittest.main()
