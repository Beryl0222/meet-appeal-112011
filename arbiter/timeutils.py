"""赛场当地时间（HH:MM）与时限计算。"""
from __future__ import annotations

import re

中文数字 = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
英文数字 = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "one": 1, "two": 2, "three": 3,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
}


def 分钟(时间: str) -> int:
    """HH:MM 转为当日分钟数，便于比较。"""
    时, 分 = 时间.split(":")
    return int(时) * 60 + int(分)


def 加分钟(时间: str, 分钟数: int) -> str:
    总 = 分钟(时间) + 分钟数
    return f"{总 // 60:02d}:{总 % 60:02d}"


def 未届满(提出: str, 截止: str | None) -> bool:
    return 截止 is None or 分钟(提出) <= 分钟(截止)


def 序号(词: str) -> int | None:
    """把 '二'/'2'/'second'/'two' 统一成序号。"""
    词 = 词.strip().lower()
    if 词 in 中文数字:
        return 中文数字[词]
    if 词 in 英文数字:
        return 英文数字[词]
    if 词.isdigit():
        return int(词)
    return None


def 提取分钟数(文本: str) -> int | None:
    """从规则原文提取“二十分钟”“十五分钟”等时限。"""
    匹配 = re.search(r"([一二三四五六七八九十百0-9]+)\s*分钟", 文本)
    if not 匹配:
        return None
    原 = 匹配.group(1)
    if 原.isdigit():
        return int(原)
    if 原 == "十":
        return 10
    if "十" in 原:
        头, 尾 = 原.split("十")
        return (中文数字[头] if 头 else 1) * 10 + (中文数字[尾] if 尾 else 0)
    return 中文数字.get(原)
