import copy
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from spark.core import SafeError, target_key
from spark.web_config import (Workspace, cloud_accounts, cloud_secrets, new_account,
                              new_workspace, pack, public_view, unpack, validate_workspace)
from webui.backup import decrypt, encrypt


def sample():
    ws = new_workspace()
    for slot in ('a1', 'a2'):
        a = new_account(slot, '演示账号 ' + slot)
        a['config']['targets'] = [{'name': '测试好友', 'enabled': True, 'messages': None}]
        a['state'] = {'cookies': [{'name': 'sessionid', 'value': 'FAKE_TEST_ONLY', 'domain': '.douyin.com', 'path': '/'}], 'origins': []}
        ws['accounts'].append(a)
    return ws


class WebConfigTests(unittest.TestCase):
    def test_round_trip_and_select_account(self):
        env = cloud_secrets(sample(), 'a' * 16)
        manifest, accounts = cloud_accounts(env)
        self.assertEqual(len(accounts), 2)
        self.assertEqual(cloud_accounts(env, 'a2')[1][0][0], 'a2')

    def test_account_keys_are_isolated(self):
        m, rows = cloud_accounts(cloud_secrets(sample(), 'a' * 16))
        keys = [target_key(m['key'], cfg, cfg.targets[0]) for _, cfg, state in rows]
        self.assertNotEqual(*keys)

    def test_stale_account_rejected_before_any_send(self):
        env = cloud_secrets(sample(), 'a' * 16)
        value = unpack(env['SPARK_WEB_A2'])
        value['revision'] = 'b' * 16
        env['SPARK_WEB_A2'] = pack(value)
        with self.assertRaises(SafeError):
            cloud_accounts(env, 'a1')  # Even a nonselected mismatched slot fails closed.

    def test_stale_dispatch_rejected(self):
        env = cloud_secrets(sample(), 'a' * 16)
        env['SPARK_REVISION'] = 'b' * 16
        with self.assertRaises(SafeError): cloud_accounts(env)

    def test_unknown_slot_rejected(self):
        with self.assertRaises(SafeError): cloud_accounts(cloud_secrets(sample(), 'a' * 16), 'a3')

    def test_duplicate_account_id_rejected(self):
        ws = sample()
        ws['accounts'][1]['config']['account_id'] = ws['accounts'][0]['config']['account_id']
        with self.assertRaises(SafeError): validate_workspace(ws)

    def test_global_recipient_limit(self):
        ws = sample()
        for a in ws['accounts']:
            a['config']['targets'] = [{'name': f'测试{i}', 'enabled': True} for i in range(6)]
        with self.assertRaises(SafeError): cloud_secrets(ws, 'a' * 16)

    def test_empty_draft_allowed_but_publish_blocked(self):
        ws = new_workspace()
        ws['accounts'] = [new_account('a1', '测试')]
        validate_workspace(ws)
        with self.assertRaises(SafeError): cloud_secrets(ws, 'a' * 16)

    def test_disabled_account_excluded(self):
        ws = sample()
        ws['accounts'][1]['enabled'] = False
        env = cloud_secrets(ws, 'a' * 16)
        self.assertNotIn('SPARK_WEB_A2', env)
        self.assertEqual(len(cloud_accounts(env)[1]), 1)

    def test_public_view_never_includes_login_or_key(self):
        ws = sample()
        result = json.dumps(public_view(ws))
        self.assertNotIn(ws['key'], result)
        self.assertNotIn('FAKE_TEST_ONLY', result)
        self.assertNotIn('sessionid', result)

    def test_draft_save_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store = Workspace(Path(d))
            data = sample()
            data['published'] = True
            store.save(data)
            loaded = Workspace(Path(d))
            self.assertEqual(data['key'], loaded.data['key'])
            self.assertFalse(loaded.data['published'])
            self.assertEqual(loaded.data['accounts'][0]['config']['account_id'], data['accounts'][0]['config']['account_id'])

    def test_backup_round_trip_preserves_identity(self):
        ws = sample()
        backup = encrypt(ws, 'a long test password')
        self.assertNotIn('FAKE_TEST_ONLY', json.dumps(backup))
        restored = decrypt(backup, 'a long test password')
        self.assertEqual(ws['key'], restored['key'])
        self.assertEqual(ws['accounts'], restored['accounts'])

    def test_backup_wrong_password_and_tamper(self):
        backup = encrypt(sample(), 'a long test password')
        with self.assertRaises(SafeError): decrypt(backup, 'wrong long password')
        backup['data'] = 'A' + backup['data'][1:]
        with self.assertRaises(SafeError): decrypt(backup, 'a long test password')

    def test_backup_requires_strong_length(self):
        with self.assertRaises(SafeError): encrypt(sample(), '123')

    def test_gzip_bomb_limited(self):
        import gzip, base64
        value = base64.b64encode(gzip.compress(b'a' * 3_000_001)).decode()
        with self.assertRaises(SafeError): unpack(value)

    def test_secret_size_limit(self):
        import secrets
        with self.assertRaises(SafeError): pack({'large': secrets.token_hex(60_000)})

    def test_real_send_disabled_before_config_browser(self):
        import run_web
        with patch.dict(os.environ, {'SPARK_MODE': 'send', 'SPARK_WEB_ENABLED': 'false'}, clear=True), patch.object(run_web, 'report') as report:
            self.assertEqual(run_web.main(), 1)
            self.assertIn('DISABLED', report.call_args.args[0])

    def test_message_template_reusable_and_daily_stable(self):
        ws = sample()
        cfg = cloud_accounts(cloud_secrets(ws, 'a' * 16))[1][0][1]
        day = date(2026, 10, 1)
        self.assertEqual(cfg.message(cfg.targets[0], day), cfg.message(cfg.targets[0], day))


if __name__ == '__main__': unittest.main()
