import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

from spark.core import Config, SafeError, pack_state, unpack_state, target_key, to_cron
from spark.deploy import schedule_text

RAW = {"version": 1, "account_id": "a" * 32, "time": "20:17", "mode": "cycle",
       "messages": ["你好 {name} {date} {weekday}", "今天也在"],
       "targets": [{"name": "好友甲", "enabled": True, "messages": None}]}
STATE = {"cookies": [{"name": "test", "value": "not-a-real-cookie", "domain": ".douyin.com", "path": "/"}], "origins": []}


class CoreTests(unittest.TestCase):
    def test_time_conversion(self):
        self.assertEqual(to_cron("20:17"), "17 12 * * *")
        self.assertEqual(to_cron("00:03"), "3 16 * * *")
        self.assertEqual(to_cron("08:00"), "0 0 * * *")

    def test_bad_time_and_injection(self):
        for value in ["24:00", "12:60", "8:00", "20:17\nrun: evil", None]:
            with self.subTest(value=value), self.assertRaises(SafeError):
                to_cron(value)

    def test_duplicate_rejected(self):
        raw = copy.deepcopy(RAW)
        raw["targets"].append(copy.deepcopy(raw["targets"][0]))
        with self.assertRaises(SafeError):
            Config.parse(raw)

    def test_string_false_rejected(self):
        raw = copy.deepcopy(RAW)
        raw["targets"][0]["enabled"] = "false"
        with self.assertRaises(SafeError):
            Config.parse(raw)

    def test_no_enabled_targets_rejected(self):
        raw = copy.deepcopy(RAW)
        raw["targets"][0]["enabled"] = False
        with self.assertRaises(SafeError):
            Config.parse(raw)

    def test_too_many_targets_rejected(self):
        raw = copy.deepcopy(RAW)
        raw["targets"] = [{"name": str(i)} for i in range(11)]
        with self.assertRaises(SafeError):
            Config.parse(raw)

    def test_template_and_override(self):
        raw = copy.deepcopy(RAW)
        raw["mode"] = "fixed"
        cfg = Config.parse(raw)
        self.assertEqual(cfg.message(cfg.targets[0], date(2026, 10, 1)), "你好 好友甲 2026-10-01 星期四")
        raw["targets"][0]["messages"] = ["专属 {name}"]
        cfg = Config.parse(raw)
        self.assertEqual(cfg.message(cfg.targets[0], date(2026, 10, 1)), "专属 好友甲")

    def test_random_stable_per_day(self):
        raw = copy.deepcopy(RAW)
        raw["mode"] = "random"
        cfg = Config.parse(raw)
        day = date(2026, 10, 1)
        self.assertEqual(cfg.message(cfg.targets[0], day), cfg.message(cfg.targets[0], day))

    def test_state_round_trip(self):
        self.assertEqual(unpack_state(pack_state(STATE)), STATE)

    def test_state_invalid(self):
        for value in ["", "not-base64", "a" * 49000]:
            with self.subTest(value=value[:8]), self.assertRaises(SafeError):
                unpack_state(value)

    def test_foreign_only_cookie_rejected(self):
        with self.assertRaises(SafeError):
            pack_state({"cookies": [{"name": "x", "value": "y", "domain": "evil-douyin.com"}]})

    def test_hmac_not_plain_name_hash(self):
        cfg = Config.parse(RAW)
        first = target_key("b" * 64, cfg, cfg.targets[0])
        second = target_key("c" * 64, cfg, cfg.targets[0])
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, second)
        self.assertNotIn("好友", first)

    def test_schedule_only_managed_line(self):
        original = "name: example\n    - cron: '17 12 * * *' # managed-spark-schedule\nother: keep\n"
        self.assertEqual(schedule_text(original, "09:38"), original.replace("17 12 * * *", "38 1 * * *"))
        with self.assertRaises(SafeError):
            schedule_text("missing-marker", "20:17")

    def test_real_send_disabled_before_browser(self):
        import run
        with patch.dict("os.environ", {"SPARK_ENABLED": "false"}, clear=True), patch("sys.argv", ["run.py", "--mode", "send"]):
            output = io.StringIO()
            with redirect_stdout(output):
                result = run.main()
            self.assertEqual(result, 1)
            self.assertIn("DISABLED", output.getvalue())

    def test_invalid_config_does_not_leak(self):
        import run
        with patch.dict("os.environ", {"SPARK_CONFIG": "PRIVATE_MESSAGE_NOT_JSON"}, clear=True), patch("sys.argv", ["run.py"]):
            output = io.StringIO()
            with redirect_stdout(output):
                run.main()
            self.assertNotIn("PRIVATE_MESSAGE", output.getvalue())
