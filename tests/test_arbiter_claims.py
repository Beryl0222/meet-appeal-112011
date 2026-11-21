"""仲裁桌建案与解析测试：动作识别、对象绑定、候选保留与否定/条件处理。"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401  隔离模式路径引导
from arbiter.board import 仲裁桌
from arbiter.model import 业务动作, 争点对象, 争点状态
from arbiter.parse import 解析消息
from arbiter.timeutils import 提取分钟数, 序号, 未届满, 加分钟

ROOT = Path(__file__).resolve().parents[1]


class 建案基类(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.桌 = 仲裁桌(ROOT / "data")

    def 争点(self, iid):
        return self.桌.争点表[iid]

    def 说法(self, cid):
        return self.桌.说法表[cid]


class 时限工具测试(unittest.TestCase):
    def test_中文时限提取(self):
        self.assertEqual(提取分钟数("单场结果从该场签字起十五分钟内提出"), 15)
        self.assertEqual(提取分钟数("名单申诉从登记签字起二十分钟内提出"), 20)
        self.assertIsNone(提取分钟数("无时限规定"))

    def test_序号与时间比较(self):
        self.assertEqual(序号("second"), 2)
        self.assertEqual(序号("二"), 2)
        self.assertEqual(序号("2nd"), 2)
        self.assertEqual(加分钟("10:13", 15), "10:28")
        self.assertTrue(未届满("10:15", "10:24"))
        self.assertFalse(未届满("10:27", "10:25"))


class 消息解析测试(建案基类):
    def test_动作四分类(self):
        self.assertEqual(self.说法("M1-C1").动作, 业务动作.申诉)
        self.assertEqual(self.说法("M4-C1").动作, 业务动作.咨询)
        self.assertEqual(self.说法("M6-C2").动作, 业务动作.补证)
        self.assertEqual(self.说法("M7-C1").动作, 业务动作.撤回)

    def test_否定声明不构成申诉(self):
        # “not contesting the team total” 是独立否定句，只登记排除范围
        self.assertTrue(self.说法("M1-C2").否定)
        self.assertEqual(self.说法("M1-C2").对象类型, 争点对象.团体汇总)
        self.assertIn("M1-C2", [s.id for s in self.桌.否定说法])
        self.assertFalse(any(i.对象类型 == 争点对象.团体汇总 for i in self.桌.争点表.values()))

    def test_条件句绑定到所限定的申诉(self):
        s = self.说法("M5-C1")
        self.assertIn("if", s.条件)
        self.assertEqual(s.对象类型, 争点对象.单场记录)
        self.assertEqual(s.场次序号, 2)

    def test_澄清定语不否决新申诉且对象不被抢占(self):
        # “not bout two. We now also appeal ... bout one” 整体是一个正向申诉，
        # 指向 bout one，否定词只作范围澄清
        s = self.说法("M3-C1")
        self.assertFalse(s.否定)
        self.assertEqual(s.场次序号, 1)
        self.assertTrue(s.定语否定)

    def test_连字符场次词(self):
        self.assertEqual(self.说法("M7-C2").场次序号, 2)

    def test_登记位置识别(self):
        self.assertEqual(self.说法("M1-C1").登记位置, 2)


class 争点建案测试(建案基类):
    def test_名单争点指向登记表与可能引用被争名字的分项(self):
        i1 = self.争点("I1")
        self.assertEqual(i1.对象类型, 争点对象.名单录入)
        self.assertEqual(i1.指向.签字单, ["S10", "S12"])  # S11 是 P1，不纳入
        self.assertEqual(i1.指向.登记号, ["P2"])
        self.assertEqual(i1.指向.汇总, ["T1"])

    def test_名单时限按登记签字计算(self):
        i1 = self.争点("I1")
        self.assertEqual(i1.时限, "10:24")       # S10 10:04 + 20
        self.assertEqual(i1.首次时间, "10:15")

    def test_二次口译不独立建案只作候选读法(self):
        # M2 把名单错读成第二场、把暂不争议翻成申诉总分，不得自行建案
        self.assertEqual(
            [i.id for i in self.桌.争点表.values() if self.说法(i.说法[0]).消息 == "M2"],
            [],
        )
        self.assertIn("M2-C1", self.争点("I1").说法)

    def test_澄清沿用首次时间而另提新争点单独计时(self):
        i2 = self.争点("I2")
        self.assertEqual(i2.根消息, "M1")
        self.assertEqual(i2.首次时间, "10:27")   # 新争点按新来件时间
        self.assertEqual(i2.时限, "10:25")       # S11 10:10 + 15
        self.assertEqual(i2.状态, 争点状态.未受理)

    def test_条件性申诉先待核后受理且按原始时间判断(self):
        i3 = self.争点("I3")
        self.assertEqual(i3.时间线[0], ("10:19", 争点状态.待核条件))
        self.assertEqual(i3.时限, "10:28")       # S12 10:13 + 15
        self.assertEqual(i3.状态, 争点状态.已维持)
        self.assertEqual(i3.受理时间, "10:22")   # D3 核明受理
        # 受理后按原始收到 10:19 判断，在限内
        self.assertTrue(i3.首次时间 <= i3.时限)

    def test_撤回只及于名单争点_第二场争点保留(self):
        self.assertEqual(self.争点("I1").状态, 争点状态.已撤回)
        self.assertNotEqual(self.争点("I3").状态, 争点状态.已撤回)
        self.assertIn("M7-C2", self.争点("I3").说法)  # bout-two 补证落 I3
        self.assertNotIn("M7-C2", self.争点("I1").说法)

    def test_咨询不产生争点(self):
        self.assertTrue(all(i.队伍 != "南队" for i in self.桌.争点表.values()))
        self.assertEqual(self.桌.咨询[0].说法.id, "M4-C1")


class 候选保留测试(建案基类):
    def test_构造无法匹配的说法保留候选与原话(self):
        坏消息 = {"id": "MX", "队伍": "北队", "时间": "10:50", "来件": "原语",
                  "引用": "", "内容": "We appeal the mark in bout nine."}
        句 = 解析消息(坏消息, 0)[0]
        句.指向 = self.桌.解析.解析(句)
        self.assertFalse(句.指向.匹配)
        self.assertTrue(句.指向.候选)            # 候选单据保留
        self.assertEqual(句.时间, "10:50")       # 原始收到时间保留
        self.assertIn("bout nine", 句.原文)      # 原话保留

    def test_上场资格争点保留人员候选不硬绑单据(self):
        消息 = {"id": "ME", "队伍": "北队", "时间": "10:50", "来件": "原语",
                "引用": "", "内容": "We question the eligibility of a player."}
        句 = 解析消息(消息, 0)[0]
        句.指向 = self.桌.解析.解析(句)
        self.assertEqual(句.对象类型, 争点对象.上场资格)
        self.assertFalse(句.指向.匹配)
        self.assertTrue(句.指向.候选)            # 人员候选保留，等待复核员绑定


if __name__ == "__main__":
    unittest.main()
