"""Two-slot regressions. All identities and messages are fictional; no network."""
import copy
import json
import os
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

from spark.core import Config, SafeError, TZ, target_key, to_cron
from spark.deploy import schedule_text
from spark.schedule import daily_times, occurrence, occurrence_key, run_created_at
from spark.web_config import cloud_accounts, cloud_secrets, public_view
from test_ledger import MemoryLedger
from test_web_config import sample


def at(hour, minute=0, day=2):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class TwiceDailyTests(unittest.TestCase):
    def setUp(self):
        self.ws = sample()
        self.ws['accounts'] = self.ws['accounts'][:1]
        self.env = cloud_secrets(self.ws, 'a' * 16)
        self.env.update(SPARK_MODE='send', SPARK_WEB_ENABLED='true',
                        GITHUB_EVENT_NAME='workflow_dispatch')
        self.manifest, self.accounts = cloud_accounts(self.env)
        self.cfg = self.accounts[0][1]
        self.target = self.cfg.targets[0]
        self.key = self.manifest['key']

    def test_times_and_utc_conversion(self):
        self.assertEqual(daily_times('20:17'), ('08:17','20:17'))
        self.assertEqual([to_cron(t) for t in daily_times('20:17')], ['17 0 * * *','17 12 * * *'])
        self.assertEqual(daily_times('08:17'), ('08:17','20:17'))
        with self.assertRaises(SafeError): daily_times('25:17')

    def test_public_ui_exposes_both_times_not_key(self):
        data=public_view(self.ws)
        self.assertEqual(data['daily_times'], ['08:17','20:17'])
        self.assertNotIn('key', data)

    def test_manual_early_send_counts_first_slot(self):
        for hour,minute in ((0,0),(5,55),(8,17),(20,16)):
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(occurrence('20:17', at(hour,minute)).index, 1)
        self.assertEqual(occurrence('20:17', at(20,17)).index, 2)

    def test_scheduled_slots_and_delay_boundaries(self):
        first = occurrence('20:17', at(8,17), 'schedule', '17 0 * * *')
        second = occurrence('20:17', at(20,17), 'schedule', '17 12 * * *')
        self.assertFalse(first.active(at(8,16)))
        self.assertTrue(first.active(at(10)))
        self.assertFalse(first.active(at(20,17)))
        self.assertTrue(second.active(at(23,59)))
        self.assertFalse(second.active(at(0,day=3)))

    def test_old_run_cannot_borrow_later_slot_or_day(self):
        original=occurrence('20:17', at(9))
        self.assertFalse(original.active(at(21)))
        self.assertFalse(original.active(at(9,day=3)))

    def test_invalid_event_or_cron_fails_closed(self):
        for event,cron in [('push',''),('schedule','* * * * *'),('schedule','')]:
            with self.assertRaises(SafeError): occurrence('20:17',at(9),event,cron)
        with self.assertRaises(SafeError): occurrence('20:17',datetime(2026,10,2))

    def test_first_key_matches_legacy_and_second_is_distinct_hmac(self):
        first=occurrence_key(self.key,self.cfg,self.target,1)
        second=occurrence_key(self.key,self.cfg,self.target,2)
        self.assertEqual(first,target_key(self.key,self.cfg,self.target))
        self.assertNotEqual(first,second)
        self.assertRegex(second, r'^[a-f0-9]{64}$')
        with self.assertRaises(SafeError): occurrence_key(self.key,self.cfg,self.target,3)

    def test_legacy_attempt_consumes_first_not_second(self):
        first=target_key(self.key,self.cfg,self.target)
        second=occurrence_key(self.key,self.cfg,self.target,2)
        for status in ('reserved','ui_confirmed'):
            ledger=MemoryLedger(at(9).date(), {'version':1,'day':'2026-10-02','entries':{first:status}})
            self.assertFalse(ledger.reserve(first))
            self.assertTrue(ledger.reserve(second))
            self.assertFalse(ledger.reserve(second))
            self.assertEqual(len(ledger.data['entries']),2)

    def test_time_edits_do_not_reset_slot_keys(self):
        raw=copy.deepcopy(self.ws['accounts'][0]['config'])
        raw['time']='22:30'
        edited=Config.parse(raw)
        for index in (1,2):
            self.assertEqual(occurrence_key(self.key,self.cfg,self.target,index),
                             occurrence_key(self.key,edited,self.target,index))

    def test_schedule_publish_preserves_two_entries(self):
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/spark-web.yml').read_text('utf-8')
        self.assertEqual(schedule_text(source,'20:17'),source)
        changed=schedule_text(source,'22:30')
        self.assertIn("'30 2 * * *' # managed-spark-morning",changed)
        self.assertIn("'30 14 * * *' # managed-spark-schedule",changed)
        self.assertEqual(changed.count('    - cron:'),2)
        self.assertEqual(schedule_text(changed,'22:30'),changed)

    def test_metadata_original_creation_time(self):
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'owner/demo',
             'GITHUB_RUN_ID':'123','GITHUB_TOKEN':'FICTIONAL_TEST_TOKEN'}
        with patch('spark.schedule.urlopen',return_value=BytesIO(json.dumps(
                {'id':123,'created_at':'2026-10-02T00:17:00Z'}).encode())):
            self.assertEqual(run_created_at(env),at(8,17))
        with patch('spark.schedule.urlopen',side_effect=URLError('private raw message')):
            with self.assertRaises(SafeError) as err: run_created_at(env)
            self.assertNotIn('private raw message',str(err.exception))

    def test_invalid_metadata_rejected(self):
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'owner/demo',
             'GITHUB_RUN_ID':'123','GITHUB_TOKEN':'FICTIONAL_TEST_TOKEN'}
        for body in ({'id':321,'created_at':'2026-10-02T00:17:00Z'},
                     {'id':123,'created_at':'2026-10-02T00:17:00'}):
            with patch('spark.schedule.urlopen',return_value=BytesIO(json.dumps(body).encode())):
                with self.assertRaises(SafeError): run_created_at(env)

    def invoke_runner(self, ledger, created, now, chat=None, env=None):
        import run_web
        manager=Mock()
        pw=manager.return_value.__enter__=Mock(return_value=Mock())
        manager.return_value.__exit__=Mock(return_value=False)
        chat=chat or Mock()
        actual=self.env.copy()
        if env: actual.update(env)
        with patch.dict(os.environ,actual,clear=True), patch('run_web.run_created_at',return_value=created), \
             patch('run_web.now_local',return_value=now), patch('run_web.report'), \
             patch('spark.ledger.GitHubLedger',return_value=ledger), \
             patch('playwright.sync_api.sync_playwright',manager), \
             patch('spark.browser.wait_chat_ready'), patch('spark.browser.Chat',return_value=chat):
            result=run_web.main()
        return result,chat

    def test_runner_two_actual_slots_and_repeats_skip(self):
        ledger=MemoryLedger(at(9).date(),{'version':1,'day':'2026-10-02','entries':{}})
        result,chat=self.invoke_runner(ledger,at(9),at(9))
        self.assertEqual(result,0)
        self.assertEqual(chat.send_prepared.call_count,1)
        result,chat=self.invoke_runner(ledger,at(10),at(10))
        self.assertEqual(result,0)
        chat.send_prepared.assert_not_called()
        result,chat=self.invoke_runner(ledger,at(21),at(21))
        self.assertEqual(result,0)
        self.assertEqual(chat.send_prepared.call_count,1)
        result,chat=self.invoke_runner(ledger,at(22),at(22))
        self.assertEqual(result,0)
        chat.send_prepared.assert_not_called()
        self.assertEqual(list(ledger.data['entries'].values()),['ui_confirmed','ui_confirmed'])

    def test_runner_preserves_test_send_already_in_legacy_ledger(self):
        key=target_key(self.key,self.cfg,self.target)
        ledger=MemoryLedger(at(9).date(),{'version':1,'day':'2026-10-02','entries':{key:'ui_confirmed'}})
        result,chat=self.invoke_runner(ledger,at(8,17),at(8,18),env={'GITHUB_EVENT_NAME':'schedule','SPARK_SCHEDULE':'17 0 * * *'})
        self.assertEqual(result,0)
        chat.send_prepared.assert_not_called()
        result,chat=self.invoke_runner(ledger,at(20,17),at(20,18),env={'GITHUB_EVENT_NAME':'schedule','SPARK_SCHEDULE':'17 12 * * *'})
        self.assertEqual(result,0)
        self.assertEqual(chat.send_prepared.call_count,1)

    def test_runner_uncertain_stays_reserved_and_no_repeat(self):
        ledger=MemoryLedger(at(9).date(),{'version':1,'day':'2026-10-02','entries':{}})
        failing=Mock(); failing.send_prepared.side_effect=SafeError('UNCERTAIN')
        result,_=self.invoke_runner(ledger,at(9),at(9),failing)
        self.assertEqual(result,1)
        self.assertEqual(list(ledger.data['entries'].values()),['reserved'])
        result,chat=self.invoke_runner(ledger,at(10),at(10))
        self.assertEqual(result,1)  # reserved is uncertain, never successful delivery
        chat.send_prepared.assert_not_called()

    def test_runner_cross_date_and_late_morning_does_not_send(self):
        for now in (at(21),at(9,day=3)):
            ledger=MemoryLedger(at(9).date(),{'version':1,'day':'2026-10-02','entries':{}})
            result,chat=self.invoke_runner(ledger,at(9),now)
            self.assertEqual(result,0)
            chat.send_prepared.assert_not_called()
            self.assertEqual(ledger.writes,[])

    def test_runner_check_has_no_writes_or_sends(self):
        ledger=MemoryLedger(at(9).date(),{'version':1,'day':'2026-10-02','entries':{}})
        result,chat=self.invoke_runner(ledger,at(9),at(9),env={'SPARK_MODE':'check'})
        self.assertEqual(result,0)
        chat.prepare.assert_not_called()
        chat.send_prepared.assert_not_called()
        self.assertEqual(ledger.writes,[])
