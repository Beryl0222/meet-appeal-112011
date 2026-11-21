"""仲裁记录的领域模型。

所有对象只描述仲裁桌自己的登记与判断；原始签字单、来件永远不在此改写，
更正只以“裁定 overlay”的形式另行记录（见公告 R6）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class 业务动作(str, Enum):
    """一句话在业务上构成的动作。"""

    申诉 = "申诉"
    补证 = "补证"
    咨询 = "咨询"
    撤回 = "撤回"
    说明 = "说明"  # 无独立动作的片段，依附同线程争点


class 争点对象(str, Enum):
    """争议指向的业务对象类别。"""

    上场资格 = "上场资格"
    名单录入 = "名单录入"
    单场记录 = "单场记录"
    团体汇总 = "团体汇总"


class 争点状态(str, Enum):
    候选待绑 = "候选待绑"          # 指向匹配不上签字单，保留候选与原话
    待核条件 = "待核条件"          # 已受理方向但条件待核明（R5）
    待受理 = "待受理"              # 时限内提出，等待复核员受理
    已受理 = "已受理"
    待撤回 = "待撤回"              # 队伍已表达撤回，等待撤回记录签发
    已更正 = "已更正"              # 接受登记更正
    已维持 = "已维持"              # 维持原记录
    已驳回 = "已驳回"
    已撤回 = "已撤回"
    未受理 = "未受理"              # 届满后新争点或咨询等，不停止签发


# 会对签发产生限制的状态：待核条件只产生“留待核明”级别的软暂缓。
限制状态 = {争点状态.待受理, 争点状态.已受理, 争点状态.待撤回}
软限制状态 = {争点状态.待核条件}
终局状态 = {争点状态.已更正, 争点状态.已维持, 争点状态.已驳回, 争点状态.已撤回, 争点状态.未受理}


@dataclass
class 说法:
    """从来件中切分出的一句话/一个分句，及其业务解读。"""

    id: str
    消息: str
    时间: str
    队伍: str
    来件类型: str           # 原语 / 口译
    引用: str
    语言: str
    动作: 业务动作 | None
    原文: str
    否定: bool = False
    定语否定: list[str] = field(default_factory=list)  # 无动作定语里的否定澄清（not bout two）
    条件: str = ""
    引述: list[str] = field(default_factory=list)
    对象类型: 争点对象 | None = None
    场次序号: int | None = None
    登记位置: int | None = None
    根消息: str = ""
    # 解析后的指向（resolver 回填）
    指向: "对象指向 | None" = None
    # 解释确认时逐句标注：已确认 / 未采纳 / 空
    采纳: str = ""
    采纳依据: str = ""


@dataclass
class 对象指向:
    """说法或争点对业务对象的解析结果。匹配不上时候选与原话保留。"""

    类型: 争点对象 | None
    匹配: bool
    签字单: list[str] = field(default_factory=list)
    汇总: list[str] = field(default_factory=list)
    登记号: list[str] = field(default_factory=list)
    候选: list[dict] = field(default_factory=list)
    依据: str = ""


@dataclass
class 争点:
    id: str
    队伍: str
    对象类型: 争点对象
    指向: 对象指向
    首次时间: str                       # 首次有效提出时间（澄清可沿用）
    时限: str | None
    时限依据: str
    状态: 争点状态
    根消息: str
    说法: list[str] = field(default_factory=list)      # 说法 id
    受理时间: str | None = None
    终局时间: str | None = None
    裁定依据: str = ""
    裁定动作: str = ""
    更正签字单: list[str] = field(default_factory=list)
    条件原文: str = ""
    # 状态时间线：[(时刻, 状态)]，用于还原任一历史时刻的暂缓范围
    时间线: list[tuple[str, 争点状态]] = field(default_factory=list)

    @property
    def 在限(self) -> bool:
        return self.状态 != 争点状态.未受理

    @property
    def 活跃(self) -> bool:
        return self.状态 in 限制状态 | 软限制状态


@dataclass
class 签发事件:
    时间: str
    签字单: str
    决定: str
    内容: str


@dataclass
class 暂缓项:
    签字单: str
    级别: str               # 暂缓 / 留待核明（多争点并存时取最强级别）
    争点: str               # 主导争点 id
    依据: str
    全部争点: list[str] = field(default_factory=list)   # 该单上并存的全部未决争点


@dataclass
class 咨询记录:
    说法: 说法
    根消息: str
