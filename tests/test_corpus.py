"""交接资料格式和原文完整性测试。"""
from pathlib import Path
import json
import subprocess
import sys
import unittest

from corpus import read_collection

ROOT = Path(__file__).resolve().parents[1]


def records(name):
    return read_collection(ROOT / "data" / (name + ".json"))


class MaterialTests(unittest.TestCase):
    def test_collections_are_utf8_record_arrays(self):
        for name, fields in FIELDS.items():
            with self.subTest(collection=name):
                rows = records(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row), set(fields))
                    self.assertIsInstance(row["id"], str)
                    self.assertTrue(row["id"])

    def test_reader_retains_exact_text_and_order(self):
        result = subprocess.check_output(
            [sys.executable, "-m", "corpus", PRIMARY, "--id", LINE_ID],
            cwd=ROOT, text=True, encoding="utf-8",
        )
        original = [row for row in records(PRIMARY) if row["id"] == LINE_ID]
        self.assertTrue(original)
        self.assertEqual(json.loads(result), original)

    def test_interpretation_and_appeal_refer_to_same_original(self):
        messages = {row["id"]: row for row in records("messages")}
        self.assertEqual(messages["M2"]["引用"], messages["M3"]["引用"])
        self.assertLess(messages["M1"]["时间"], messages["M3"]["时间"])
        self.assertNotEqual(messages["M1"]["来件"], messages["M2"]["来件"])
        sheets = {row["id"]: row for row in records("signoff")}
        self.assertNotEqual(sheets["S10"]["名单"], sheets["S12"]["名单"])
        self.assertTrue(all(row["签字单"] in sheets for row in records("links")))


PRIMARY = 'messages'
LINE_ID = 'M1'
FIELDS = {
    "signoff": [
        "id",
        "项目",
        "场地",
        "队伍",
        "场次",
        "名单",
        "签署"
    ],
    "roster": [
        "id",
        "姓名",
        "英文",
        "队伍",
        "项目"
    ],
    "links": [
        "id",
        "签字单",
        "汇总",
        "说明"
    ],
    "messages": [
        "id",
        "队伍",
        "时间",
        "来件",
        "引用",
        "内容"
    ],
    "bulletins": [
        "id",
        "内容"
    ],
    "decisions": [
        "id",
        "时间",
        "队伍",
        "签字单",
        "原来件",
        "业务动作",
        "内容"
    ]
}
