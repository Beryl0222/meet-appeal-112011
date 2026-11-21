"""把双语来件解析为带业务解读的说法，原话逐字保留。

设计原则：
- 标记表可扩充、按优先级匹配，覆盖语料中的原语（英文）与口译（中文）词形；
- 否定、条件、引述独立识别，否定句不生成正式申诉（“not contesting” 不构成争点）；
- 同一条来件里多个分句各算一句说法，便于复核员逐句确认，
  不存在“一次整封确认替所有争点背书”。
"""
from __future__ import annotations

import re

from .model import 业务动作, 争点对象, 说法
from .timeutils import 序号

# 动作标记按优先级排列（先判撤回/咨询，再判补证，最后申诉/说明）。
英文动作标记 = [
    (业务动作.撤回, [r"\bwithdraw\b", r"\bwithdrawal of\b"]),
    (业务动作.咨询, [r"\bquestion\b", r"\?\s*$", r"\bwhether\b", r"\bis that about\b"]),
    (业务动作.补证, [r"\bkeep (?:the )?appeal\b", r"\bkeep our\b", r"\bwe keep\b",
                    r"\bconfirm(?:ing)?\b", r"\bread it back\b", r"\bclerk read\b"]),
    (业务动作.申诉, [r"\bappeal\b", r"\bcontest(?:ing)?\b", r"\bchallenge\b"]),
]
中文动作标记 = [
    (业务动作.撤回, [r"撤回", r"撤"]),
    (业务动作.咨询, [r"[？?]$", r"是否", r"是不是", r"咨询"]),
    (业务动作.补证, [r"保持", r"维持申诉", r"补", r"确认", r"核", r"回读", r"仍在审"]),
    (业务动作.申诉, [r"申诉"]),
]

否定标记 = [r"\bnot\b", r"\bno longer\b", r"\bwithout\b", r"不", r"未", r"无"]
条件标记 = [r"\bif\b[^.？?]*", r"如果[^。！!？?]*", r"若[^。！!？?]*", r"条件[^。！!？?]*"]
引述模式 = re.compile(r"'[^']+'|“[^”]+”|\"[^\"]+\"")
CJK = re.compile(r"[一-鿿]")

# 争点对象的词形（顺序即优先级：先认单场，再认名单/汇总/资格）。
对象词形 = {
    争点对象.单场记录: [
        r"\bbout\b", r"\bmark in bout\b", r"\bresult of bout\b", r"\bwithdrawal\b",
        r"第[一二三四五六七八九十0-9]+场", r"单场", r"该场",
    ],
    争点对象.团体汇总: [
        r"\bteam total\b", r"\bteam score\b", r"团体总分", r"团体汇总", r"团体成绩",
    ],
    争点对象.名单录入: [
        r"\bentry list\b", r"\bname(?:s)?\b", r"\bentered\b", r"\bduplicate(?:-entry)?\b",
        r"名单", r"姓名", r"名字", r"参赛人", r"重复记", r"录入", r"登记",
    ],
    争点对象.上场资格: [
        r"\beligibilit", r"\bqualif", r"上场资格", r"参赛资格", r"资格",
    ],
}
场次模式 = re.compile(r"bout[\s-]+(?:number[\s-]+)?([a-z0-9]+)|第([一二三四五六七八九十0-9]+)场")
登记位置模式 = re.compile(r"(first|second|third|fourth|fifth|[0-9]+(?:st|nd|rd|th))\s+name"
                          r"|第([一二三四五六七八九十0-9]+)个(?:姓名|名字)")
# 中文一句话里并列两个动作时（“……，申诉……”），在动作词前再切一刀。
中文动作前切分 = re.compile(r"[，,]\s*(?=申诉|撤回|咨询)")


def _含任一(文本: str, 模式表: list[str]) -> bool:
    return any(re.search(p, 文本, flags=re.IGNORECASE) for p in 模式表)


def _识别动作(文本: str, 语言: str) -> 业务动作 | None:
    表 = 英文动作标记 if 语言 == "原语" else 中文动作标记
    for 动作, 模式表 in 表:
        if _含任一(文本, 模式表):
            return 动作
    return None


def _识别对象(文本: str) -> 争点对象 | None:
    for 对象, 模式表 in 对象词形.items():
        if _含任一(文本, 模式表):
            return 对象
    return None


def _场次序号(文本: str) -> int | None:
    m = 场次模式.search(文本)
    if not m:
        return None
    return 序号(m.group(1) or m.group(2))


def _登记位置(文本: str) -> int | None:
    m = 登记位置模式.search(文本)
    if not m:
        return None
    if m.group(1):
        return 序号(m.group(1))      # 序号表同时收录 second/2nd 等词形，不做截词
    return 序号(m.group(2))


def _分句(文本: str) -> list[str]:
    """按句末标点和逗号切分，保留原词形（不做翻译、不做大小写归一）。

    逗号两侧往往是两个独立业务动作（澄清一个争点、另提一个争点），
    必须切开后分别成句，再由分组逻辑把无动作的定语并回相邻动作句。
    """
    片段 = [p.strip() for p in re.split(r"[.。!！?？;；,，]\s*", 文本.strip()) if p.strip()]
    展开 = []
    for p in 片段:
        if CJK.search(p):
            展开.extend(x.strip() for x in 中文动作前切分.split(p) if x.strip())
        else:
            展开.append(p)
    return 展开


def _合并无动作句(分句):
    """把分句组成说法（单遍状态机）。

    分句三元组为（原文, 动作或None, 是否否定）：

    - 带动作标记的句子（含独立否定句“not contesting ...”）各自另开一组。
      独立否定句因此成为单独说法，作为排除范围声明，绝不并入相邻正向申诉，
      避免把“暂不争议团体总分”错算成申诉的一部分；
    - 无动作片段先攒入缓冲；遇到下一个动作句时整体后挂——
      条件句（“if ...”）与澄清定语（“Entry list ..., not bout two”）
      都限定它后面的说法；消息结束仍有缓冲，则前挂到最后一组作补充说明。
    """
    组 = []
    缓冲 = []
    for i, (_, 动作, _否定) in enumerate(分句):
        if 动作 is not None:
            组.append(缓冲 + [i])
            缓冲 = []
        else:
            缓冲.append(i)
    if 缓冲:
        if 组:
            组[-1].extend(缓冲)
        else:
            组 = [缓冲]
    return 组


def 解析消息(消息: dict, 序号基: int) -> list[说法]:
    """解析 messages 中的一条记录，返回若干说法。"""
    内容 = 消息["内容"]
    语言 = "口译" if CJK.search(内容) else "原语"
    原始分句 = _分句(内容)
    解读 = []
    for 片段 in 原始分句:
        语言判 = "口译" if CJK.search(片段) else "原语"
        解读.append((片段, _识别动作(片段, 语言判), _含任一(片段, 否定标记)))
    组列表 = _合并无动作句(解读)

    结果: list[说法] = []
    for k, 组 in enumerate(组列表):
        全文 = " ".join(解读[i][0] for i in 组)
        动作句 = next((i for i in 组 if 解读[i][1] is not None), 组[-1])
        动作 = 解读[动作句][1]
        # 否定以动作句本身为准；无动作定语里的否定词（not bout two）是范围澄清，
        # 不否决动作本身，另存在定语否定里供审计。
        否定 = bool(动作 is not None and 解读[动作句][2])
        定语否定 = [解读[i][0] for i in 组 if i != 动作句 and 解读[i][2]]
        引述 = [m.group(0) for i in 组 for m in 引述模式.finditer(解读[i][0])]
        条件 = ""
        for i in 组:
            for p in 条件标记:
                cm = re.search(p, 解读[i][0], flags=re.IGNORECASE)
                if cm:
                    条件 = cm.group(0).strip()
                    break
        # 对象/场次/位置优先取动作句本身，避免被否定定语里排除掉的对象抢占
        # （“not bout two. We appeal the mark in bout one” 应指向 bout one）
        动作原文 = 解读[动作句][0]
        对象 = _识别对象(动作原文) or _识别对象(全文)
        场次 = _场次序号(动作原文)
        if 场次 is None:
            场次 = _场次序号(全文)
        位置 = _登记位置(动作原文)
        if 位置 is None:
            位置 = _登记位置(全文)
        结果.append(说法(
            id=f"{消息['id']}-C{k + 1}",
            消息=消息["id"],
            时间=消息["时间"],
            队伍=消息["队伍"],
            来件类型=消息["来件"],
            引用=消息["引用"],
            语言=语言,
            动作=动作 if 动作 is not None else 业务动作.说明,
            原文=全文,
            否定=否定,
            条件=条件,
            引述=引述,
            对象类型=对象,
            场次序号=场次,
            登记位置=位置,
        ))
        if 定语否定:
            结果[-1].定语否定 = 定语否定
    return 结果
