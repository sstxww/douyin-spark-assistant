"""Independent scheduling / retry tests. Fictional accounts, no live network."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from spark.core import SafeError, TZ
from spark.watchdog import (build_plan, due_period, export_plan, ledger_entries,
                            load_budget, tick, validate_plan, MAX_DISPATCHES)
from spark.web_config import cloud_accounts, cloud_secrets
from test_web_config import sample
from test_ledger import MemoryLedger


def at(hour=9, minute=0, day=2):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class FakeClient:
    def __init__(self, plan):
        self.base = 'repos/owner/demo'
        self.values = {'SPARK_WEB_ENABLED':'true', 'SPARK_WEB_REVISION':plan['revision'],
                       'SPARK_WEB_INSTALLATION':plan['installation']}
        self.entries = {}
        self.head = 'TEST_HEAD'
        self.runs = [{'display_title':'check · all · '+plan['revision'], 'head_sha':self.head,
                      'status':'completed','conclusion':'success','event':'workflow_dispatch',
                      'created_at':at(8).isoformat(),'id':123}]
        self.legacy = []
        self.calls = []
        self.codes = set()
        self.fail_dispatch = False
        self.var_reads = 0
        self.pause_before_dispatch = False

    def api(self, path, method='GET', body=None):
        self.calls.append((path, method, body))
        if path.endswith('/actions/variables?per_page=100'):
            self.var_reads += 1
            values = dict(self.values)
            if self.pause_before_dispatch and self.var_reads >= 2:
                values['SPARK_WEB_ENABLED'] = 'false'
            return {'variables':[{'name':k,'value':v} for k,v in values.items()]}
        if '/spark-web.yml/runs?' in path: return {'workflow_runs':self.runs}
        if '/spark.yml/runs?' in path: return {'workflow_runs':self.legacy}
        if path.endswith('/git/ref/heads/main'): return {'object':{'sha':self.head}}
        if path.endswith('/dispatches'):
            if self.fail_dispatch: raise SafeError('GITHUB')
            return None
        raise AssertionError('Unexpected endpoint')

    def ledger(self, day): return dict(self.entries)
    def blocking_codes(self, run_id): return self.codes


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.ws=sample()
        self.ws.update(repository='owner/demo',revision='a'*16,published=True)
        self.plan=build_plan(self.ws)
        self.client=FakeClient(self.plan)
        self.budget={'version':1,'slots':{}}
        self.persist=Mock()

    def run_tick(self, now=None, **kwargs):
        return tick(self.plan,self.client,self.budget,self.persist,now or at(),**kwargs)

    def test_projection_has_no_cookies_names_text_or_secret(self):
        text=json.dumps(self.plan,ensure_ascii=False)
        for value in ('FAKE_TEST_ONLY','sessionid','测试好友','今天也来',self.ws['key']):
            self.assertNotIn(value,text)
        with tempfile.TemporaryDirectory() as d:
            export_plan(Path(d),self.ws)
            self.assertEqual(json.loads((Path(d)/'watchdog-plan.json').read_text('utf-8')),self.plan)

    def test_unpublished_plan_cannot_export(self):
        self.ws['published']=False
        with self.assertRaises(SafeError): build_plan(self.ws)

    def test_two_slots_and_no_early_send(self):
        self.assertIsNone(due_period('20:17',at(8,16)))
        self.assertEqual(due_period('20:17',at(8,17)).index,1)
        self.assertEqual(due_period('20:17',at(20,17)).index,2)
        self.assertEqual(self.run_tick(at(8,16))['status'],'not_due')
        self.assertEqual(self.client.calls,[])
        with self.assertRaises(SafeError): self.run_tick(datetime(2026,10,2))

    def test_missing_cron_actively_dispatches(self):
        result=self.run_tick()
        self.assertEqual(result['status'],'dispatched')
        self.assertEqual(len(self.budget['slots']['2026-10-02:1']),1)
        writes=[c for c in self.client.calls if c[1]=='POST']
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][2],{'ref':'main','inputs':{'mode':'send','account':'all','revision':'a'*16}})
        self.assertNotIn('测试好友',json.dumps(writes,ensure_ascii=False))

    def test_confirmed_ledger_no_new_jobs_and_no_browser(self):
        self.client.entries={k:'ui_confirmed' for a in self.plan['accounts'] for k in a['keys']['1']}
        r=self.run_tick()
        self.assertEqual(r['status'],'confirmed')
        self.assertEqual(r['confirmed'],2)
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))
        self.persist.assert_not_called()

    def test_reserved_is_not_treated_as_delivered(self):
        self.client.entries={k:'reserved' for a in self.plan['accounts'] for k in a['keys']['1']}
        r=self.run_tick()
        self.assertEqual(r['status'],'needs_attention')
        self.assertEqual(r['uncertain'],2)
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_partial_confirmed_only_remaining_is_eligible(self):
        k=self.plan['accounts'][0]['keys']['1'][0]
        self.client.entries={k:'ui_confirmed'}
        r=self.run_tick()
        self.assertEqual((r['confirmed'],r['missing'],r['status']),(1,1,'dispatched'))

    def test_pending_job_blocks_parallel_dispatch(self):
        for location in ('runs','legacy'):
            setattr(self.client,location,[{'status':'queued'}])
            self.assertEqual(self.run_tick()['status'],'job_active')
            setattr(self.client,location,[])
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_pause_and_stale_plan_never_dispatch(self):
        self.client.values['SPARK_WEB_ENABLED']='false'
        self.assertEqual(self.run_tick()['status'],'paused')
        self.client.values['SPARK_WEB_ENABLED']='true'
        self.client.values['SPARK_WEB_REVISION']='b'*16
        self.assertEqual(self.run_tick()['status'],'plan_stale')
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_pause_rechecked_immediately_before_dispatch(self):
        self.client.pause_before_dispatch=True
        self.assertEqual(self.run_tick()['status'],'paused')
        self.assertEqual(self.budget['slots'],{})
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_new_code_requires_current_check(self):
        self.client.head='OTHER_HEAD'
        self.assertEqual(self.run_tick()['status'],'check_required')
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_verified_code_survives_check_pagination(self):
        self.run_tick()
        self.client.runs=[]
        self.client.calls=[]
        self.assertEqual(self.run_tick(at(10))['status'],'dispatched')
        self.client.head='DIFFERENT_HEAD'
        self.assertEqual(self.run_tick(at(11))['status'],'check_required')

    def test_transient_failure_backoff_and_retry_budget(self):
        self.run_tick()
        self.assertEqual(self.run_tick(at(9,1))['status'],'backoff')
        self.assertEqual(self.run_tick(at(9,5))['status'],'dispatched')
        self.budget['slots']['2026-10-02:1']=[at(8).isoformat()]*MAX_DISPATCHES
        self.assertEqual(self.run_tick(at(15))['status'],'retry_exhausted')

    def test_uncertain_dispatch_response_still_consumes_budget(self):
        self.client.fail_dispatch=True
        with self.assertRaises(SafeError): self.run_tick()
        self.assertEqual(len(self.budget['slots']['2026-10-02:1']),1)
        self.client.fail_dispatch=False
        self.assertEqual(self.run_tick(at(9,1))['status'],'backoff')

    def test_login_or_identity_error_is_not_hammered(self):
        row={'status':'completed','conclusion':'failure','head_sha':self.client.head,
             'display_title':'send · all · '+self.plan['revision'],
             'created_at':at(8,30).isoformat(),'id':321}
        self.client.runs.append(row)
        self.client.codes={'RISK'}
        self.assertEqual(self.run_tick()['status'],'needs_attention')
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_dry_run_no_writes_or_budget_changes(self):
        self.assertEqual(self.run_tick(dry_run=True)['status'],'would_dispatch')
        self.persist.assert_not_called()
        self.assertEqual(self.budget,{'version':1,'slots':{}})
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_near_boundary_does_not_create_job(self):
        self.assertEqual(self.run_tick(at(20,9))['status'],'window_ending')
        self.assertEqual(self.run_tick(at(23,55))['status'],'window_ending')
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_budget_write_failure_prevents_dispatch(self):
        self.persist.side_effect=OSError('private path')
        with self.assertRaises(OSError): self.run_tick()
        self.assertFalse(any(c[1]=='POST' for c in self.client.calls))

    def test_ledger_validation_preserves_same_day_and_rejects_future(self):
        k=self.plan['accounts'][0]['keys']['1'][0]
        value={'version':1,'day':'2026-10-02','entries':{k:'reserved'}}
        self.assertEqual(ledger_entries(value,at().date()),{k:'reserved'})
        self.assertEqual(ledger_entries(value,at(day=3).date()),{})
        with self.assertRaises(SafeError): ledger_entries(value,at(day=1).date())
        value['entries'][k]='unknown'
        with self.assertRaises(SafeError): ledger_entries(value,at().date())

    def test_duplicate_plan_keys_rejected(self):
        plan=copy.deepcopy(self.plan)
        plan['accounts'][1]['keys']['1']=plan['accounts'][0]['keys']['1']
        with self.assertRaises(SafeError): validate_plan(plan)

    def test_corrupt_budget_does_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'budget.json'
            self.assertEqual(load_budget(path),{'version':1,'slots':{}})
            path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(SafeError): load_budget(path)


class PerTargetRunnerTests(unittest.TestCase):
    def invoke(self, first_error=None, reserved=False):
        import run_web
        ws=sample();ws['accounts']=ws['accounts'][:1]
        ws['accounts'][0]['config']['targets'].append({'name':'第二个虚构好友','enabled':True})
        env=cloud_secrets(ws,'a'*16)
        env.update(SPARK_MODE='send',SPARK_WEB_ENABLED='true',GITHUB_EVENT_NAME='workflow_dispatch')
        ledger=MemoryLedger(at().date(),{'version':1,'day':'2026-10-02','entries':{}})
        _, rows=cloud_accounts(env)
        from spark.schedule import occurrence_key
        if reserved:
            cfg=rows[0][1]
            ledger.data['entries'][occurrence_key(ws['key'],cfg,cfg.targets[0],1)]='reserved'
        manager=Mock();manager.return_value.__enter__=Mock(return_value=Mock())
        manager.return_value.__exit__=Mock(return_value=False)
        first=Mock();second=Mock()
        if first_error: first.open.side_effect=SafeError(first_error)
        chats=[second] if reserved else [first,second]
        with patch.dict(os.environ,env,clear=True), patch('run_web.run_created_at',return_value=at()), \
             patch('run_web.now_local',return_value=at()), patch('run_web.report'), \
             patch('spark.ledger.GitHubLedger',return_value=ledger), \
             patch('playwright.sync_api.sync_playwright',manager), \
             patch('spark.browser.wait_chat_ready'), patch('spark.browser.Chat',side_effect=chats):
            result=run_web.main()
        return result,first,second,ledger

    def test_first_recipient_failure_does_not_block_second(self):
        result,first,second,ledger=self.invoke('LOADING')
        self.assertEqual(result,1)
        first.send_prepared.assert_not_called()
        second.send_prepared.assert_called_once()
        self.assertEqual(list(ledger.data['entries'].values()),['ui_confirmed'])

    def test_reserved_first_is_not_resent_but_second_can_complete(self):
        result,first,second,ledger=self.invoke(reserved=True)
        self.assertEqual(result,1)
        self.assertEqual(list(ledger.data['entries'].values()),['reserved','ui_confirmed'])
        second.send_prepared.assert_called_once()

    def test_risk_stops_remaining_recipients_for_account(self):
        result,first,second,ledger=self.invoke('RISK')
        self.assertEqual(result,1)
        first.send_prepared.assert_not_called()
        second.send_prepared.assert_not_called()
        self.assertEqual(ledger.data['entries'],{})


if __name__=='__main__': unittest.main()
