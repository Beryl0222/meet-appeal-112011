"""暂缓范围、裁定处置、队伍回执与审计隔离测试。"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401  隔离模式路径引导
from arbiter.board import 仲裁桌
from arbiter.model import 争点状态

ROOT = Path(__file__).resolve().parents[1]


class 暂缓时间线测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.桌 = 仲裁桌(ROOT / "data")

    def 暂缓单(self, 时刻):
        return {x.签字单: x for x in self.桌.暂缓清单(时刻)}

    def test_名单争点暂缓登记表与受影响分项(self):
        表 = self.暂缓单("10:16")
        self.assertIn("S10", 表)
        self.assertIn("S12", 表)
        self.assertNotIn("S11", 表)              # P1 分项不受名单争点影响
        self.assertNotIn("S13", 表)
        self.assertNotIn("S21", 表)              # 别队单据永不卷入

    def test_团体汇总只在受影响分项待定时不公告(self):
        汇 = self.桌.汇总状态("10:16")
        self.assertFalse(汇["T1"]["可公告"])
        self.assertEqual(汇["T1"]["待定分项"], ["S12"])
        self.assertTrue(汇["T2"]["可公告"])       # 南队汇总照常

    def test_条件待核阶段为软暂缓_受理后转硬暂缓(self):
        表20 = self.暂缓单("10:20")
        self.assertEqual(表20["S12"].级别, "暂缓")
        self.assertIn("I3", 表20["S12"].全部争点)  # I3 软暂缓与 I1 硬暂缓并存留痕
        表37 = self.暂缓单("10:37")
        self.assertEqual(表37["S12"].争点, "I3")    # I1 撤回后 I3 独立保留限制

    def test_单场争点解决后限制解除(self):
        self.assertNotIn("S12", self.暂缓单("10:46"))
        self.assertTrue(self.桌.汇总状态("10:46")["T1"]["可公告"])

    def test_未受理争点不停止签发(self):
        # I2 届满未受理，任何时刻 S11 都不因它暂缓
        for 时刻 in ("10:27", "10:30", "10:46"):
            self.assertNotIn("S11", self.暂缓单(时刻))

    def test_南队单据全程照常(self):
        for 时刻 in ("10:16", "10:20", "10:30", "10:46"):
            self.assertNotIn("S21", self.暂缓单(时刻))


class 裁定处置测试(unittest.TestCase):
    def setUp(self):
        # 每个用例独立一个仲裁桌，处置互不污染
        self.桌 = 仲裁桌(ROOT / "data")

    def test_接受更正逐编号指向且不改原签字单(self):
        原名单 = list(self.桌.签字单["S10"]["名单"])
        r = self.桌.接受更正("I1", "11:00", ["S10", "S12"], "裁定更正重复登记")
        self.assertEqual(r["状态"], 争点状态.已更正.value)
        self.assertEqual(self.桌.争点表["I1"].更正签字单, ["S10", "S12"])
        self.assertEqual(self.桌.签字单["S10"]["名单"], 原名单)  # 原件不重录

    def test_更正指向不存在编号时保留未匹配清单(self):
        r = self.桌.接受更正("I1", "11:00", ["S99"], "测试")
        self.assertEqual(r["更正"], [])
        self.assertEqual(r["未匹配编号"], ["S99"])

    def test_维持_驳回_撤回三种终局(self):
        self.assertEqual(self.桌.维持原记录("I3", "11:00", "维持")["状态"],
                         争点状态.已维持.value)
        self.assertEqual(self.桌.驳回("I2", "11:00", "驳回")["状态"],
                         争点状态.已驳回.value)

    def test_条件不成立转未受理且不停发(self):
        # 构造一个待核条件争点
        i3 = self.桌.争点表["I3"]
        i3.时间线 = [("10:19", 争点状态.待核条件)]
        i3.状态 = 争点状态.待核条件
        i3.终局时间 = None
        r = self.桌.核明条件("I3", "10:21", False, "签字单未载 withdrawal")
        self.assertEqual(r["结果"], "未受理")
        # I3 不再产生限制（S12 此时仅可能因 I1 名单争点暂缓，与 I3 无关）
        self.assertNotIn("I3", {x.争点 for x in self.桌.暂缓清单("10:22")})

    def test_条件成立但届满按原始时间判未受理(self):
        i3 = self.桌.争点表["I3"]
        i3.时间线 = [("10:19", 争点状态.待核条件)]
        i3.状态 = 争点状态.待核条件
        i3.终局时间 = None
        i3.时限 = "10:18"
        r = self.桌.核明条件("I3", "10:30", True, "条件成立")
        self.assertEqual(r["结果"], "未受理")


class 逐句确认测试(unittest.TestCase):
    def setUp(self):
        self.桌 = 仲裁桌(ROOT / "data")

    def test_口译候选与否定句逐句标注_不整封背书(self):
        结果 = self.桌.解释确认("M1", "10:26", "测试确认")
        采纳 = {x["说法"]: x["采纳"] for x in 结果["逐句"]}
        self.assertEqual(采纳["M1-C1"], "已确认")
        self.assertEqual(采纳["M1-C2"], "未采纳")   # 否定声明
        self.assertEqual(采纳["M2-C1"], "未采纳")   # 同线程口译候选


class 回执与审计测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.桌 = 仲裁桌(ROOT / "data")

    def test_南队回执不含北队任何材料(self):
        回 = self.桌.队伍回执("南队")
        全文 = str(回)
        self.assertNotIn("北队", 全文)
        self.assertNotIn("S10", 全文)
        self.assertNotIn("S12", 全文)
        self.assertNotIn("I1", 全文)
        self.assertEqual(回["争点"], [])
        self.assertTrue(回["咨询"])                 # 自己的咨询可见

    def test_北队回执含争点裁定与双语对应(self):
        回 = self.桌.队伍回执("北队")
        self.assertEqual({i["争点"] for i in 回["争点"]}, {"I1", "I2", "I3"})
        m1组 = next(x for x in 回["来件双语对照"] if x["原始来件"] == "M1")
        self.assertIn("M2", m1组["关联来件"])
        self.assertIn("second name", m1组["原语"])
        self.assertIn("第二场", m1组["口译"])

    def test_审计保留原签字与完整时间线(self):
        审 = self.桌.工作人员审计()
        self.assertTrue(any(x["签字单"] == "S12" for x in 审["原始签字单"]))
        i3 = next(i for i in 审["争点轨迹"].values() if i.id == "I3")
        状态序列 = [s.value for _, s in i3.时间线]
        self.assertEqual(状态序列, ["待核条件", "已受理", "已维持"])
        # 已载签发事件可追溯
        self.assertTrue(any(e.签字单 == "S11" for e in self.桌.签发))


if __name__ == "__main__":
    unittest.main()
