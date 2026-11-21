"""仲裁桌：建案、时限、暂缓范围、裁定处置与回执。

原件（data/ 下各 JSON）只读；本工具的登记、裁定另存为工作记录，
原始签字单不会因申诉登记或裁定而被改写（公告 R4/R6）。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from corpus import read_collection

from .model import (
    业务动作, 争点, 争点对象, 争点状态, 签发事件, 咨询记录, 暂缓项, 说法,
    限制状态, 软限制状态, 终局状态,
)
from .parse import 解析消息
from .resolver import 解析器
from .timeutils import 加分钟, 提取分钟数, 未届满, 分钟


class 仲裁桌:
    def __init__(self, 数据目录: str | Path):
        目录 = Path(数据目录)
        self.资料 = {名: read_collection(目录 / f"{名}.json")
                     for 名 in ("signoff", "roster", "links", "messages", "bulletins", "decisions")}
        self.解析 = 解析器(self.资料)
        self.签字单 = {r["id"]: r for r in self.资料["signoff"]}
        self.说法表: dict[str, 说法] = {}
        self.争点表: dict[str, 争点] = {}
        self.咨询: list[咨询记录] = []
        self.否定说法: list[说法] = []
        self.签发: list[签发事件] = []
        self.审计: list[dict] = []
        self._序号 = 0
        self._建案()
        self._录入已载决定()

    # ------------------------------------------------------------------ 建案
    def _新号(self, 前缀: str) -> str:
        self._序号 += 1
        return f"{前缀}{self._序号}"

    def _规则分钟(self, 关键词: str) -> int | None:
        # 关键词须落在“从……起 N 分钟内”的同一小句内（R1 用逗号并列两个时限）
        for r in self.资料["bulletins"]:
            for 分句 in re.split(r"[。；;，,]", r["内容"]):
                if 关键词 in 分句:
                    v = 提取分钟数(分句)
                    if v is not None:
                        return v
        return None

    def _时限(self, 指向类型: 争点对象, 指向) -> tuple[str | None, str]:
        if 指向类型 == 争点对象.名单录入:
            表 = next((self.签字单[sid] for sid in 指向.签字单
                       if self.签字单[sid]["场次"] == "团体登记"), None)
            分钟数 = self._规则分钟("名单申诉")
            if 表 and 分钟数:
                return 加分钟(表["签署"], 分钟数), f"R1 名单申诉自 {表['id']} 签署 {表['签署']} 起 {分钟数} 分钟"
        if 指向类型 == 争点对象.单场记录 and 指向.签字单:
            表 = self.签字单[指向.签字单[0]]
            分钟数 = self._规则分钟("单场结果")
            if 分钟数:
                return 加分钟(表["签署"], 分钟数), f"R1 单场结果自 {表['id']} 签署 {表['签署']} 起 {分钟数} 分钟"
        if 指向类型 == 争点对象.上场资格:
            分钟数 = self._规则分钟("名单申诉")
            if 分钟数:
                return None, f"R1 资格参照名单时限 {分钟数} 分钟（无锚定签字单，按收到即审）"
        return None, "规则未规定该对象的固定时限"

    def _建案(self) -> None:
        # 先解析全部来件（按文件顺序，即收到顺序），回填对象指向
        按消息: dict[str, list[说法]] = {}
        for 消息 in self.资料["messages"]:
            本封 = 解析消息(消息, len(self.说法表))
            按消息[消息["id"]] = 本封
            for s in 本封:
                s.指向 = self.解析.解析(s)
                self.说法表[s.id] = s
        # 条件从句、补证/说明句常省略场次词：仅当自身完全未匹配时，
        # 才继承同封同对象类型邻句的指向（不跨对象继承，避免名单句覆盖单场句）
        for 本封 in 按消息.values():
            for s in 本封:
                if s.指向.匹配:
                    continue
                邻句 = next((x for x in 本封
                             if x is not s and x.指向 and x.指向.匹配
                             and x.对象类型 == s.对象类型), None)
                if 邻句 is not None:
                    s.指向 = 邻句.指向

        # 根消息映射：引用链收敛到最初一封
        根 = {}
        for s in self.说法表.values():
            根[s.消息] = s.引用 or s.消息
        self.根映射 = 根

        for s in self.说法表.values():
            s.根消息 = 根[s.消息]
            if s.动作 == 业务动作.咨询:
                self.咨询.append(咨询记录(说法=s, 根消息=s.根消息))
            elif s.否定 and s.动作 in (业务动作.申诉, 业务动作.说明):
                # 否定性声明（not contesting）不构成争点，只登记其排除范围
                self.否定说法.append(s)
            elif s.来件类型 == "口译" and s.动作 == 业务动作.申诉 and not s.否定:
                # 二次口译不得自行建案/硬绑场次：只作为同线程候选读法保留
                self._候选读法(s)
            elif s.动作 == 业务动作.申诉 and not s.否定:
                self._开争点(s)
            elif s.动作 in (业务动作.补证, 业务动作.撤回, 业务动作.说明):
                self._并入争点(s)

    def _改状态(self, i: 争点, 新状态: 争点状态, 时间: str | None) -> None:
        """统一的状态迁移入口，完整时间线用于历史时点暂缓还原。"""
        if 新状态 == i.状态:
            return
        i.状态 = 新状态
        if 时间 is not None:
            i.时间线.append((时间, 新状态))
        if 新状态 in 终局状态:
            i.终局时间 = 时间

    def _时点状态(self, i: 争点, 时刻: str) -> 争点状态:
        """按时间线还原争点在某时刻的状态。"""
        当前 = i.时间线[0][1]
        for t, st in i.时间线:
            if 分钟(t) <= 分钟(时刻):
                当前 = st
            else:
                break
        return 当前

    def _开争点(self, s: 说法) -> 争点 | None:
        指向 = s.指向
        时限, 时限依据 = self._时限(s.对象类型, 指向)
        if not 指向.匹配:
            状态 = 争点状态.候选待绑
        elif s.条件:
            状态 = 争点状态.待核条件           # R5：条件不明，留待核明
        elif 时限 is not None and not 未届满(s.时间, 时限):
            状态 = 争点状态.未受理             # R3：届满后的新争点不保留签发
        else:
            状态 = 争点状态.待受理
        i = 争点(
            id=self._新号("I"), 队伍=s.队伍, 对象类型=s.对象类型, 指向=指向,
            首次时间=s.时间, 时限=时限, 时限依据=时限依据, 状态=状态,
            根消息=s.根消息, 说法=[s.id], 条件原文=s.条件,
            时间线=[(s.时间, 状态)],
        )
        self.争点表[i.id] = i
        self.审计.append({"时间": s.时间, "动作": "建案", "争点": i.id,
                          "来源": s.id, "状态": 状态.value, "原话": s.原文})
        return i

    def _候选读法(self, s: 说法) -> None:
        """口译中的申诉说法挂到同线程争点作候选读法；无线程则保留待绑，不停发。"""
        同线 = [i for i in self.争点表.values()
                if i.队伍 == s.队伍 and i.根消息 == s.根消息]
        if not 同线:
            self.审计.append({"时间": s.时间, "动作": "口译待绑", "来源": s.id,
                              "说明": "口译说法无线程争点可挂，保留原话与收到时间，不停止签发"})
            return
        for i in 同线:
            i.说法.append(s.id)
            self.审计.append({"时间": s.时间, "动作": "候选读法", "争点": i.id,
                              "来源": s.id, "原话": s.原文,
                              "说明": "二次口译仅作候选，未经逐句确认不绑定场次/汇总"})

    def _并入争点(self, s: 说法) -> None:
        """补证/撤回/说明按引用线程并回原争点；找不到线程则留候选，不硬绑。"""
        同根 = [i for i in self.争点表.values()
                if i.队伍 == s.队伍 and i.根消息 == s.根消息]
        # 路由优先级：同队+同对象+同单据（可跨线程） > 同根同对象 > 同根任意。
        # 这样“一封多争点”里指另一线程争点的补证（M7 的 bout-two 指 M5 案）
        # 不会错挂到同线程的其他争点。
        全表同对象 = [i for i in self.争点表.values()
                      if i.队伍 == s.队伍 and i.对象类型 == s.对象类型]
        同对象 = []
        if s.指向.匹配 and s.指向.签字单:
            同对象 = [i for i in 全表同对象 if set(i.指向.签字单) & set(s.指向.签字单)]
        if not 同对象:
            同对象 = [i for i in 同根 if i.对象类型 == s.对象类型]
        # 单据信息缺失时，若全表同对象争点唯一（另一线程），直接落位；
        # 多个候选则不猜测，留在同根并交复核员绑定
        if not 同对象 and s.动作 == 业务动作.补证 and len(全表同对象) == 1:
            同对象 = 全表同对象
        同线 = 同对象 or [i for i in 同根 if s.对象类型 is None or i.对象类型 == s.对象类型]
        if not 同线:
            self.审计.append({"时间": s.时间, "动作": "未匹配", "来源": s.id,
                              "说明": "无线程争点可并入，原话与时间保留待复核员绑定"})
            return
        # 撤回/对象明确的补证只入精确匹配的争点；说明类才并入该线程全部争点
        if 同对象:
            目标 = 同对象
        elif s.动作 == 业务动作.说明:
            目标 = 同线
        else:
            目标 = 同线[:1]
        for i in 目标:
            i.说法.append(s.id)
            if s.动作 == 业务动作.撤回 and i.状态 not in (争点状态.已撤回, 争点状态.未受理):
                self._改状态(i, 争点状态.待撤回, s.时间)
                self.审计.append({"时间": s.时间, "动作": "撤回登记", "争点": i.id,
                                  "来源": s.id, "原话": s.原文})
            elif s.动作 == 业务动作.补证:
                self.审计.append({"时间": s.时间, "动作": "补证并入", "争点": i.id,
                                  "来源": s.id, "原话": s.原文,
                                  "说明": "只解释原争点，首次提出时间不变"})

    # ------------------------------------------------------------ 已载决定录入
    def _录入已载决定(self) -> None:
        for d in self.资料["decisions"]:
            动作 = d["业务动作"]
            if 动作 == "已发分项":
                self.签发.append(签发事件(d["时间"], d["签字单"], 动作, d["内容"]))
                self.审计.append({"时间": d["时间"], "动作": 动作, "签字单": d["签字单"], "说明": d["内容"]})
            elif 动作 == "受理记录":
                命中 = [i for i in self.争点表.values()
                        if i.队伍 == d["队伍"]
                        and any(self.说法表[c].消息 == d["原来件"] for c in i.说法)]
                待核 = [i for i in 命中 if i.状态 == 争点状态.待核条件]
                if 待核:
                    for i in 待核:
                        self.核明条件(i.id, d["时间"], True, d["内容"])
                else:
                    self._按原来源处置(d, 争点状态.已受理, d["时间"], "受理", 受理=True)
            elif 动作 == "解释确认":
                self.解释确认(d["原来件"], d["时间"], d["内容"], 决定id=d["id"])
            elif 动作 == "撤回记录":
                self._按原来源处置(d, 争点状态.已撤回, d["时间"], "撤回")
            elif 动作 == "裁定":
                维持 = "维持" in d["内容"]
                self._按原来源处置(
                    d, 争点状态.已维持 if 维持 else 争点状态.已更正,
                    d["时间"], "裁定", 裁定内容=d["内容"],
                )

    def _按原来源处置(self, d: dict, 新状态: 争点状态, 时间: str, 标签: str,
                      受理: bool = False, 裁定内容: str = "") -> None:
        命中 = [i for i in self.争点表.values()
                if i.队伍 == d["队伍"] and any(self.说法表[c].消息 == d["原来件"] for c in i.说法)]
        # 只对决定指定签字单相关、且属于该来源的争点生效，不波及同线程其他争点
        命中 = [i for i in 命中 if not d["签字单"] or d["签字单"] in i.指向.签字单
                or (i.对象类型 == 争点对象.名单录入 and d["签字单"] in i.指向.签字单)]
        for i in 命中:
            self._改状态(i, 新状态, 时间)
            i.裁定依据 = d["内容"]
            i.裁定动作 = 标签
            if 受理:
                i.受理时间 = 时间
            self.审计.append({"时间": 时间, "动作": 标签, "争点": i.id,
                              "决定": d["id"], "说明": d["内容"]})
        if not 命中:
            self.审计.append({"时间": 时间, "动作": f"{标签}未命中", "决定": d["id"], "说明": d["内容"]})

    # ------------------------------------------------------- 复核员逐句确认（R5/R6）
    def 解释确认(self, 消息id: str, 时间: str, 说明: str, 决定id: str = "") -> dict:
        """复核员确认某封来件每句说法所表达的业务动作，逐句而非整封背书。

        同线程的二次口译一并过堂：除非说明明确采纳，口译里与原语冲突的读法
        （错绑场次、把“暂不争议”翻成“申诉总分”）逐句标未采纳，不产生争点效力。
        """
        句 = [s for s in self.说法表.values() if s.消息 == 消息id]
        根 = 句[0].根消息 if 句 else 消息id
        口译句 = [s for s in self.说法表.values()
                  if s.根消息 == 根 and s.来件类型 == "口译" and s.消息 != 消息id]
        结果 = {"消息": 消息id, "时间": 时间, "逐句": []}
        for s in 句 + 口译句:
            if s.否定:
                采纳, 依据 = "未采纳", "否定性声明，仅登记排除范围，不构成争点"
            elif s.来件类型 == "口译":
                采纳, 依据 = "未采纳", "口译候选读法未经确认；以原语与复核员确认为准"
            elif s.动作 == 业务动作.申诉 and not s.指向.匹配:
                采纳, 依据 = "未采纳", "指向无法匹配本队签字单，保留候选不据此停发"
            elif s.动作 == 业务动作.申诉 and s.指向.匹配:
                采纳, 依据 = "已确认", 说明
            else:
                采纳, 依据 = "已确认", 说明
            s.采纳, s.采纳依据 = 采纳, 依据
            结果["逐句"].append({"说法": s.id, "动作": s.动作.value if s.动作 else "",
                                  "原话": s.原文, "采纳": 采纳, "依据": 依据})
            self.审计.append({"时间": 时间, "动作": "逐句确认", "来源": s.id,
                              "决定": 决定id, "采纳": 采纳, "说明": 说明})
        return 结果

    def 核明条件(self, 争点id: str, 时间: str, 条件成立: bool, 依据: str) -> dict:
        """R5：核明条件性申诉。条件获得支持则受理，时限按原始收到时间回溯判断。"""
        i = self.争点表[争点id]
        if not 条件成立:
            self._改状态(i, 争点状态.未受理, 时间)
            i.裁定依据 = 依据
            self.审计.append({"时间": 时间, "动作": "条件不成立", "争点": i.id, "说明": 依据})
            return {"争点": i.id, "结果": "未受理", "说明": 依据}
        if i.时限 is not None and not 未届满(i.首次时间, i.时限):
            self._改状态(i, 争点状态.未受理, 时间)
            i.裁定依据 = f"条件成立但按原始收到时间 {i.首次时间} 已届满（截止 {i.时限}）"
            self.审计.append({"时间": 时间, "动作": "条件成立但届满", "争点": i.id, "说明": i.裁定依据})
            return {"争点": i.id, "结果": "未受理", "说明": i.裁定依据}
        self._改状态(i, 争点状态.已受理, 时间)
        i.受理时间 = 时间
        i.裁定依据 = 依据
        self.审计.append({"时间": 时间, "动作": "条件核明受理", "争点": i.id,
                          "说明": f"{依据}；按原始收到时间 {i.首次时间} 判断，在限"})
        return {"争点": i.id, "结果": "已受理", "首次时间": i.首次时间}

    # ------------------------------------------------------------- 复核员处置
    def 接受更正(self, 争点id: str, 时间: str, 更正到签字单: list[str], 依据: str) -> dict:
        """接受登记更正：R6 要求逐编号指名单据，且不变更原签字单。"""
        i = self.争点表[争点id]
        存在 = [sid for sid in 更正到签字单 if sid in self.签字单]
        缺失 = [sid for sid in 更正到签字单 if sid not in self.签字单]
        self._改状态(i, 争点状态.已更正, 时间)
        i.更正签字单 = 存在
        i.裁定依据 = 依据
        i.裁定动作 = "接受更正"
        self.审计.append({"时间": 时间, "动作": "接受更正", "争点": i.id,
                          "更正到签字单": 存在, "未匹配编号": 缺失,
                          "说明": "原签字单不重录，更正以裁定 overlay 另行登记；" + 依据})
        return {"争点": i.id, "状态": i.状态.value, "更正": 存在, "未匹配编号": 缺失}

    def 维持原记录(self, 争点id: str, 时间: str, 依据: str) -> dict:
        i = self.争点表[争点id]
        self._改状态(i, 争点状态.已维持, 时间)
        i.裁定依据 = 依据
        i.裁定动作 = "维持原记录"
        self.审计.append({"时间": 时间, "动作": "维持原记录", "争点": i.id, "说明": 依据})
        return {"争点": i.id, "状态": i.状态.value}

    def 驳回(self, 争点id: str, 时间: str, 依据: str) -> dict:
        i = self.争点表[争点id]
        self._改状态(i, 争点状态.已驳回, 时间)
        i.裁定依据 = 依据
        i.裁定动作 = "驳回"
        self.审计.append({"时间": 时间, "动作": "驳回", "争点": i.id, "说明": 依据})
        return {"争点": i.id, "状态": i.状态.value}

    def 记录撤回(self, 争点id: str, 时间: str, 依据: str) -> dict:
        i = self.争点表[争点id]
        self._改状态(i, 争点状态.已撤回, 时间)
        i.裁定依据 = 依据
        i.裁定动作 = "记录撤回"
        self.审计.append({"时间": 时间, "动作": "记录撤回", "争点": i.id, "说明": 依据})
        return {"争点": i.id, "状态": i.状态.value}

    # ------------------------------------------------------------- 暂缓与签发
    def 暂缓清单(self, 时刻: str | None = None) -> list[暂缓项]:
        """计算各签字单当前（或指定时刻）的暂缓状态。

        只有规则规定会被该争点改变的汇总/分项才进入待定（R2）；
        待核条件争点只给“留待核明”级别限制（R5），未受理争点不停止签发（R3）。
        """
        表: dict[str, 暂缓项] = {}

        def 放(sid: str, 级别: str, iid: str, 依据: str):
            if sid not in 表:
                表[sid] = 暂缓项(sid, 级别, iid, 依据, [iid])
                return
            项 = 表[sid]
            if iid not in 项.全部争点:
                项.全部争点.append(iid)
            if 级别 == "暂缓":                      # 硬暂缓覆盖软暂缓，并存争点全部留痕
                项.级别, 项.争点, 项.依据 = "暂缓", iid, 依据

        for i in self.争点表.values():
            历史状态 = self._时点状态(i, 时刻) if 时刻 else i.状态
            if 历史状态 not in 限制状态 | 软限制状态:
                continue
            if 时刻 and 分钟(时刻) < 分钟(i.首次时间):
                continue
            级别 = "留待核明" if 历史状态 in 软限制状态 else "暂缓"
            依据 = f"{i.id}（{i.对象类型.value}，{历史状态.value}）"
            for sid in i.指向.签字单:
                放(sid, 级别, i.id, 依据)
        return sorted(表.values(), key=lambda x: x.签字单)

    def 汇总状态(self, 时刻: str | None = None) -> dict[str, dict]:
        """每个团体汇总：是否可公告，以及被哪条待定分项拖累（R2）。"""
        暂缓单 = {x.签字单 for x in self.暂缓清单(时刻)}
        out = {}
        for r in self.资料["links"]:
            t = r["汇总"]
            out.setdefault(t, {"汇总": t, "说明": r["说明"], "待定分项": [], "可公告": True})
            if r["签字单"] in 暂缓单 and r["签字单"] not in out[t]["待定分项"]:
                out[t]["待定分项"].append(r["签字单"])
        for t in out.values():
            t["可公告"] = not t["待定分项"]
        return dict(sorted(out.items()))

    def 签发视图(self, 时刻: str | None = None) -> dict:
        """接案视图：哪些签字单照常签发、哪些暂缓，含原因与复核截止期。"""
        暂缓 = {x.签字单: x for x in self.暂缓清单(时刻)}
        分项, 截止 = [], {}
        for sid, 表 in self.签字单.items():
            关联争点 = [i for i in self.争点表.values() if sid in i.指向.签字单]
            关联争点.sort(key=lambda i: i.首次时间)
            for i in 关联争点:
                if i.时限:
                    截止[sid] = min(截止.get(sid, i.时限), i.时限)
            if sid in 暂缓:
                x = 暂缓[sid]
                分项.append({"签字单": sid, "队伍": 表["队伍"], "项目": 表["项目"],
                             "场次": 表["场次"], "处置": x.级别, "争点": x.争点,
                             "并存争点": x.全部争点, "依据": x.依据})
            else:
                分项.append({"签字单": sid, "队伍": 表["队伍"], "项目": 表["项目"],
                             "场次": 表["场次"], "处置": "照常签发",
                             "争点": "", "并存争点": [],
                             "依据": "无在限且已受理的未决争点"})
        return {"时刻": 时刻 or "当前", "分项": sorted(分项, key=lambda x: x["签字单"]),
                "截止期": 截止, "汇总": self.汇总状态(时刻)}

    # ------------------------------------------------------------- 回执与审计
    def 队伍回执(self, 队伍: str) -> dict:
        """只含本队材料：争点、裁定、原文/译文对应；不披露别队任何内部材料（R6）。"""
        本队说法 = [s for s in self.说法表.values() if s.队伍 == 队伍]
        # 双语对照按“同一原始来件”的引用链配对：M1 原语与 M2（引用 M1）口译归为一组
        原始消息 = {m["id"]: m for m in self.资料["messages"] if m["队伍"] == 队伍}
        组到成员: dict[str, list[str]] = defaultdict(list)
        for mid, m in 原始消息.items():
            根 = m["引用"] or mid
            组到成员[根].append(mid)
        双语 = []
        for 根, 成员 in sorted(组到成员.items(), key=lambda kv: min(原始消息[x]["时间"] for x in kv[1])):
            成员说法 = [s for s in 本队说法 if s.消息 in 成员]
            原语 = " ｜ ".join(dict.fromkeys(s.原文 for s in 成员说法 if s.来件类型 == "原语"))
            口译 = " ｜ ".join(dict.fromkeys(s.原文 for s in 成员说法 if s.来件类型 == "口译"))
            双语.append({"原始来件": 根, "关联来件": sorted(成员),
                          "时间": min(原始消息[x]["时间"] for x in 成员),
                          "原语": 原语, "口译": 口译})
        争点回 = []
        for i in self.争点表.values():
            if i.队伍 != 队伍:
                continue
            争点回.append({
                "争点": i.id, "对象": i.对象类型.value, "状态": i.状态.value,
                "首次有效提出": i.首次时间, "复核截止": i.时限 or "无固定时限",
                "时限依据": i.时限依据, "指向": self._指向摘要(i),
                "裁定动作": i.裁定动作, "裁定依据": i.裁定依据,
                "原话与译文": [self._双语对应(c) for c in i.说法],
            })
        咨询回 = [{"说法": q.说法.id, "消息": q.说法.消息, "时间": q.说法.时间,
                    "原话": q.说法.原文,
                    "处理": "咨询登记，不构成申诉、不停止签发（R3）"}
                   for q in self.咨询 if q.说法.队伍 == 队伍]
        排除 = [{"说法": s.id, "消息": s.消息, "原话": s.原文,
                  "说明": "否定性声明，仅登记排除范围，不作为争点、不停止签发"}
                for s in self.否定说法 if s.队伍 == 队伍]
        return {"队伍": 队伍, "争点": 争点回, "咨询": 咨询回, "否定声明": 排除, "来件双语对照": 双语}

    def _双语对应(self, 说法id: str) -> dict:
        s = self.说法表[说法id]
        同根 = [x for x in self.说法表.values()
                if x.消息 == s.消息 or (x.根消息 == s.根消息 and x.队伍 == s.队伍)]
        原语 = next((x.原文 for x in 同根 if x.来件类型 == "原语"), "")
        口译 = next((x.原文 for x in 同根 if x.来件类型 == "口译"), "")
        return {"说法": s.id, "收到时间": s.时间, "原文": s.原文,
                "同件原语": 原语, "同线程口译": 口译}

    def _指向摘要(self, i: 争点) -> dict:
        p = i.指向
        return {"匹配": p.匹配, "签字单": p.签字单, "汇总": p.汇总,
                "登记号": p.登记号, "候选": p.候选, "依据": p.依据}

    def 工作人员审计(self) -> dict:
        """追溯原签字与后续全部决定的完整轨迹。"""
        return {
            "原始签字单": [{"签字单": r["id"], "项目": r["项目"], "场次": r["场次"],
                            "队伍": r["队伍"], "名单": r["名单"], "签署": r["签署"],
                            "说明": "原件只读，任何裁定不重录此单（R4/R6）"}
                           for r in self.资料["signoff"]],
            "已载签发": [e.__dict__ for e in self.签发],
            "争点轨迹": self.争点表,
            "操作流水": self.审计,
        }
