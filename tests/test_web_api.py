import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from webui.server import create_app


class WebAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name), 'owner/demo', hosts={'testserver'})
        self.client = TestClient(self.app)
        csrf = self.client.get('/api/bootstrap').json()['csrf']
        self.headers = {'X-Spark-CSRF': csrf, 'Origin': 'http://testserver'}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, path, data):
        return self.client.post('/api/' + path, json=data, headers=self.headers)

    def test_initial_state(self):
        data = self.client.get('/api/state', headers=self.headers).json()
        self.assertEqual(data['workspace']['accounts'], [])

    def test_no_csrf_read_or_write_denied(self):
        self.assertEqual(self.client.get('/api/state').status_code, 403)
        self.assertEqual(self.client.post('/api/account/add', json={'label': 'test'}).status_code, 403)

    def test_cross_origin_denied(self):
        for origin in ('https://evil.example', 'http://testserver.evil.example', ''):
            headers = {**self.headers, 'Origin': origin}
            self.assertEqual(self.client.post('/api/account/add', json={'label': 'x'}, headers=headers).status_code, 403)

    def test_cross_site_and_bad_host_denied(self):
        self.assertEqual(self.client.get('/', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={**self.headers, 'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_private_files_not_served(self):
        self.assertEqual(self.client.get('/static/workspace.json').status_code, 404)
        self.assertEqual(self.client.get('/.local/web/workspace.json').status_code, 404)

    def test_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])

    def test_add_three_accounts_limit(self):
        for i in range(3): self.assertEqual(self.post('account/add', {'label': f'test{i}'}).status_code, 200)
        self.assertEqual(self.post('account/add', {'label': 'fourth'}).status_code, 400)

    def test_change_settings_cannot_replace_account_id_or_cookie(self):
        result = self.post('account/add', {'label': 'test'}).json()
        original = result['workspace']['accounts'][0]['config']['account_id']
        accounts = result['workspace']['accounts']
        accounts[0]['config']['account_id'] = 'f' * 32
        accounts[0]['state'] = {'fake': 'INJECTED'}
        accounts[0]['config']['messages'] = ['{name}，你好']
        accounts[0]['config']['targets'] = [{'name': '测试好友', 'enabled': True, 'messages': None}]
        updated = self.post('settings', {'time': '21:17', 'accounts': accounts})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['workspace']['accounts'][0]['config']['account_id'], original)
        self.assertIsNone(self.app.state.workspace.data['accounts'][0]['state'])

    def test_template_save_and_remove(self):
        res = self.post('template/save', {'title': '你好', 'mode': 'cycle', 'messages': ['你好']})
        self.assertEqual(res.status_code, 200)
        id = res.json()['workspace']['templates'][0]['id']
        self.assertEqual(self.post('template/remove', {'id': id}).json()['workspace']['templates'], [])

    def test_real_send_and_auth_require_confirmation(self):
        with patch.object(self.app.state.cloud, 'dispatch') as dispatch:
            self.assertEqual(self.post('run', {'mode': 'send'}).status_code, 400)
            dispatch.assert_not_called()
        self.assertEqual(self.post('github/login', {}).status_code, 400)
        self.assertEqual(self.post('enable', {}).status_code, 400)

    def test_qr_requires_live_session_and_consent(self):
        self.assertEqual(self.client.get('/api/login/frame', headers=self.headers).status_code, 400)
        self.assertEqual(self.post('login/finish', {'slot': 'a1'}).status_code, 400)

    def test_backup_export_import(self):
        self.post('account/add', {'label': '测试'})
        output = self.post('backup/export', {'password': 'a long test password'})
        self.assertEqual(output.status_code, 200)
        restored = self.post('backup/import', {'password': 'a long test password',
                               'backup': output.json()['backup'], 'confirmed': True})
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(restored.json()['workspace']['published'])

    def test_errors_do_not_echo_private_input(self):
        private = 'DO-NOT-ECHO-MY-CREDENTIAL'
        response = self.post('settings', {'accounts': private, 'time': 'oops'})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(private, response.text)


if __name__ == '__main__': unittest.main()
