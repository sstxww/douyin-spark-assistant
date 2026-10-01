import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from spark.core import SafeError
from webui.cloud import GitHubCloud
from test_web_config import sample


class WebCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = GitHubCloud(Path(self.temp.name), 'owner/demo')
        self.ws = sample()
        self.ws.update(published=True, repository='owner/demo', revision='a'*16)

    def tearDown(self): self.temp.cleanup()

    def test_no_builtin_codespace_token_reused(self):
        self.assertNotIn('GITHUB_TOKEN', self.cloud.env)
        self.assertNotIn('GH_TOKEN', self.cloud.env)

    def test_cannot_replace_dedup_key_from_new_workspace(self):
        with self.assertRaises(SafeError):
            self.cloud.installation(self.ws, {'SPARK_WEB_INSTALLATION': 'another-installation'})

    def test_enable_requires_current_complete_check(self):
        for changed in ({'conclusion':'failure'}, {'head_sha':'wrong'}, {'display_title':'check · a1 · '+ 'a'*16}, {'status':'in_progress'}):
            row = {'display_title':'check · all · '+ 'a'*16, 'head_sha':'HEAD',
                   'status':'completed', 'event':'workflow_dispatch', 'conclusion':'success'}
            row.update(changed)
            with patch.object(self.cloud, 'current'), patch.object(self.cloud, 'api', return_value={'object':{'sha':'HEAD'}}), patch.object(self.cloud, 'runs', return_value=[row]), patch.object(self.cloud, 'variable') as write:
                with self.assertRaises(SafeError): self.cloud.enable(self.ws)
                write.assert_not_called()

    def test_enable_after_current_success(self):
        row = {'display_title':'check · all · '+ 'a'*16, 'head_sha':'HEAD',
               'status':'completed', 'event':'workflow_dispatch', 'conclusion':'success'}
        with patch.object(self.cloud, 'current'), patch.object(self.cloud, 'api', return_value={'object':{'sha':'HEAD'}}), patch.object(self.cloud, 'runs', return_value=[row]), patch.object(self.cloud, 'variable') as write:
            self.cloud.enable(self.ws)
            write.assert_called_once_with('SPARK_WEB_ENABLED','true')

    def test_send_dispatch_honors_pause(self):
        with patch.object(self.cloud, 'current', return_value={'SPARK_WEB_ENABLED':'false'}), patch.object(self.cloud, 'api') as call:
            with self.assertRaises(SafeError): self.cloud.dispatch(self.ws, 'send')
            call.assert_not_called()

    def test_publish_pauses_and_refuses_active_jobs(self):
        with patch.object(self.cloud, 'identity'), patch.object(self.cloud, 'variables', return_value={}), patch.object(self.cloud, 'pause') as pause, patch.object(self.cloud, 'runs', return_value=[{'status':'in_progress'}]), patch.object(self.cloud, 'gh') as call:
            with self.assertRaises(SafeError): self.cloud.publish(self.ws)
            pause.assert_called_once()
            call.assert_not_called()

    def test_dispatch_payload_has_no_private_content(self):
        with patch.object(self.cloud, 'current', return_value={}), patch.object(self.cloud, 'api') as call:
            self.cloud.dispatch(self.ws, 'check', 'a1')
            args=call.call_args.args
            self.assertEqual(args[2]['inputs'],{'mode':'check','account':'a1','revision':'a'*16})
            self.assertNotIn('测试好友', str(args))


if __name__ == '__main__': unittest.main()
