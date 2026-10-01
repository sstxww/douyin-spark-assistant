import base64
import copy
import json
import unittest
from datetime import date
from spark.core import SafeError
from spark.ledger import GitHubLedger

KEY = "b" * 64


class MemoryLedger(GitHubLedger):
    def __init__(self, day, previous=None, branch=True, fail_write=False):
        self.previous = previous
        self.branch_exists = branch
        self.fail_write = fail_write
        self.writes = []
        super().__init__("example/repo", "fake-token", day)

    def api(self, method, path, body=None, missing=False):
        if method == "GET" and path == "/git/ref/heads/main":
            return {"object": {"sha": "base"}}
        if method == "GET" and path.startswith("/git/ref/"):
            return {"object": {"sha": "state"}} if self.branch_exists else None
        if method == "POST":
            self.branch_exists = True
            return {}
        if method == "GET":
            return {"sha": "old", "content": base64.b64encode(json.dumps(self.previous).encode()).decode()} if self.previous is not None else None
        if method == "PUT":
            if self.fail_write:
                raise SafeError("LEDGER")
            self.previous = json.loads(base64.b64decode(body["content"]))
            self.writes.append(copy.deepcopy(self.previous))
            return {"content": {"sha": "updated"}}
        raise AssertionError("Unexpected API request")


class LedgerTests(unittest.TestCase):
    def test_initialize_reserve_then_confirm(self):
        ledger = MemoryLedger(date(2026, 10, 1), branch=False)
        self.assertTrue(ledger.reserve(KEY))
        self.assertFalse(ledger.reserve(KEY))
        self.assertEqual(ledger.writes[-1]["entries"][KEY], "reserved")
        ledger.confirm(KEY)
        self.assertEqual(ledger.writes[-1]["entries"][KEY], "ui_confirmed")

    def test_reserved_is_not_retried(self):
        previous = {"version": 1, "day": "2026-10-01", "entries": {KEY: "reserved"}}
        ledger = MemoryLedger(date(2026, 10, 1), previous)
        self.assertFalse(ledger.reserve(KEY))
        self.assertEqual(ledger.writes, [])

    def test_new_day_can_send(self):
        previous = {"version": 1, "day": "2026-09-30", "entries": {KEY: "ui_confirmed"}}
        ledger = MemoryLedger(date(2026, 10, 1), previous)
        self.assertTrue(ledger.reserve(KEY))

    def test_write_failure_raises_before_send(self):
        previous = {"version": 1, "day": "2026-10-01", "entries": {}}
        ledger = MemoryLedger(date(2026, 10, 1), previous, fail_write=True)
        with self.assertRaises(SafeError):
            ledger.reserve(KEY)

    def test_deleted_ledger_fails_closed(self):
        with self.assertRaises(SafeError):
            MemoryLedger(date(2026, 10, 1), previous=None, branch=True)

    def test_corrupt_or_future_ledger_rejected(self):
        for previous in [{"version": 1, "day": "2099-01-01", "entries": {}},
                         {"version": 1, "day": "2026-10-01", "entries": {"real name": "sent"}}]:
            with self.subTest(previous=previous), self.assertRaises(SafeError):
                MemoryLedger(date(2026, 10, 1), previous)
