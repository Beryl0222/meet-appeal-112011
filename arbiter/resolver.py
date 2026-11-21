"""把说法中的争点对象绑定到签字单、登记号与团体汇总。

匹配不上签字单时不猜测：标记为不匹配，保留候选单据、原话（在说法上）与原始收到时间。
名单争点的影响范围按公告 R2 计算：只保留“可能引用被争名字”的分项。
"""
from __future__ import annotations

from .model import 争点对象, 对象指向, 说法

数字转中文 = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
             6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


class 解析器:
    def __init__(self, 资料: dict):
        self.签字单 = {r["id"]: r for r in 资料["signoff"]}
        self.登记 = {r["id"]: r for r in 资料["roster"]}
        self.归入 = 资料["links"]
        self.公告 = 资料["bulletins"]

    # ---- 基础查询 ----------------------------------------------------------
    def 本队签字单(self, 队伍: str) -> list[dict]:
        return [r for r in self.签字单.values() if r["队伍"] == 队伍]

    def 汇总_of(self, 签字单id: str) -> list[str]:
        return [r["汇总"] for r in self.归入 if r["签字单"] == 签字单id]

    def 签字单_of_汇总(self, 汇总: str) -> list[str]:
        return [r["签字单"] for r in self.归入 if r["汇总"] == 汇总]

    def 本队汇总(self, 队伍: str) -> list[str]:
        单 = {r["id"] for r in self.本队签字单(队伍)}
        return sorted({r["汇总"] for r in self.归入 if r["签字单"] in 单})

    # ---- 主入口 ------------------------------------------------------------
    def 解析(self, s: 说法) -> 对象指向:
        if s.动作 is None or s.对象类型 is None:
            return 对象指向(类型=s.对象类型, 匹配=False, 依据="说法未指明争点对象")
        方法 = {
            争点对象.名单录入: self._名单,
            争点对象.单场记录: self._单场,
            争点对象.团体汇总: self._汇总,
            争点对象.上场资格: self._资格,
        }[s.对象类型]
        return 方法(s)

    def _名单(self, s: 说法) -> 对象指向:
        登记表 = next((r for r in self.本队签字单(s.队伍) if r["场次"] == "团体登记"), None)
        候选登记 = [r for r in self.登记.values() if r["队伍"] == s.队伍]
        if 登记表 is None:
            return 对象指向(
                类型=争点对象.名单录入, 匹配=False,
                候选=[{"登记号": r["id"], "姓名": r["姓名"], "英文": r["英文"]} for r in 候选登记],
                依据="本队无团体登记签字单，保留候选与原话",
            )
        指向 = 对象指向(类型=争点对象.名单录入, 匹配=True, 签字单=[登记表["id"]], 依据="团体登记签字单")
        if s.登记位置 is not None and 1 <= s.登记位置 <= len(登记表["名单"]):
            pid = 登记表["名单"][s.登记位置 - 1]
            指向.登记号 = [pid]
            指向.依据 = f"登记表第{s.登记位置}个名字为 {pid}"
            被争登记号 = [pid]
        else:
            # 无法定位到具体位置时，才把表内全部登记号列为候选，影响范围按全部处理
            指向.登记号 = sorted({pid for pid in 登记表["名单"]})
            指向.候选 = [{"登记号": r["id"], "姓名": r["姓名"], "英文": r["英文"]} for r in 候选登记]
            被争登记号 = 指向.登记号
        # R2：只保留可能引用被争名字的分项（同队、同项目、名单含该登记号的单场签字单）
        项目 = 登记表["项目"]
        for pid in 被争登记号:
            for r in self.本队签字单(s.队伍):
                if r["场次"] == "团体登记" or r["项目"] != 项目:
                    continue
                if pid in r["名单"] and r["id"] not in 指向.签字单:
                    指向.签字单.append(r["id"])
        指向.汇总 = sorted({t for sid in 指向.签字单 for t in self.汇总_of(sid)})
        return 指向

    def _单场(self, s: 说法) -> 对象指向:
        候选 = [{"签字单": r["id"], "场次": r["场次"], "名单": r["名单"]}
                for r in self.本队签字单(s.队伍) if r["场次"] != "团体登记"]
        if s.场次序号 is None:
            return 对象指向(类型=争点对象.单场记录, 匹配=False, 候选=候选,
                            依据="只提到单场未给场次，保留候选与原话")
        场次名 = 数字转中文.get(s.场次序号, str(s.场次序号))
        单 = next((r for r in self.本队签字单(s.队伍) if r["场次"] == 场次名), None)
        if 单 is None:
            return 对象指向(类型=争点对象.单场记录, 匹配=False, 候选=候选,
                            依据=f"本队无第{场次名}场签字单，保留候选与原话")
        return 对象指向(
            类型=争点对象.单场记录, 匹配=True,
            签字单=[单["id"]], 汇总=self.汇总_of(单["id"]),
            登记号=list(单["名单"]), 依据=f"第{场次名}场对应签字单 {单['id']}",
        )

    def _汇总(self, s: 说法) -> 对象指向:
        汇总 = self.本队汇总(s.队伍)
        if not 汇总:
            return 对象指向(类型=争点对象.团体汇总, 匹配=False, 依据="本队无团体汇总归入关系")
        return 对象指向(类型=争点对象.团体汇总, 匹配=True, 汇总=汇总,
                        签字单=self.签字单_of_汇总(汇总[0]) if len(汇总) == 1 else [],
                        依据="按 links 归入关系得到本队团体汇总")

    def _资格(self, s: 说法) -> 对象指向:
        候选 = [{"登记号": r["id"], "姓名": r["姓名"], "英文": r["英文"], "项目": r["项目"]}
                for r in self.登记.values() if r["队伍"] == s.队伍]
        return 对象指向(类型=争点对象.上场资格, 匹配=False, 候选=候选,
                        依据="上场资格未落到具体签字单，保留候选与原话")
