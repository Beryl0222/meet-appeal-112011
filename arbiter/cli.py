"""仲裁记录工具命令行。

示例：
  python3 -m arbiter.claims                 # 全部争点与状态
  python3 -m arbiter.claims --team 北队
  python3 -m arbiter.held                   # 暂缓/照常签发视图
  python3 -m arbiter.held --at 10:20        # 历史时点的暂缓状态
  python3 -m arbiter.receipt 北队           # 队伍回执（只含本队材料）
  python3 -m arbiter.audit                  # 工作人员审计轨迹
  python3 -m arbiter.decide ...             # 复核员处置（见 --help）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许以 `python3 -I arbiter/cli.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from arbiter.board import 仲裁桌
    from arbiter.serialize import 转普通值
else:
    from .board import 仲裁桌
    from .serialize import 转普通值

数据目录 = Path(__file__).resolve().parents[1] / "data"


def _打印(结构, as_json: bool):
    if as_json:
        print(json.dumps(转普通值(结构), ensure_ascii=False, indent=2))
    else:
        _文本(结构)


def _文本(结构, 缩进=0):
    pad = "  " * 缩进
    if isinstance(结构, dict):
        for k, v in 结构.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}：")
                _文本(v, 缩进 + 1)
            else:
                print(f"{pad}{k}：{v}")
    elif isinstance(结构, list):
        for v in 结构:
            if isinstance(v, (dict, list)):
                _文本(v, 缩进)
                print("-" * 40)
            else:
                print(f"{pad}- {v}")
    else:
        print(f"{pad}{结构}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="团体赛仲裁记录工具")
    parser.add_argument("--data", default=str(数据目录), help="资料目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    sub = parser.add_subparsers(dest="命令", required=True)

    sub.add_parser("claims", help="列出争点、时限与状态")
    p_held = sub.add_parser("held", help="签字单暂缓/照常签发与汇总状态")
    p_held.add_argument("--at", dest="时刻", help="按历史时刻计算（HH:MM）")
    p_receipt = sub.add_parser("receipt", help="生成队伍回执")
    p_receipt.add_argument("队伍")
    sub.add_parser("audit", help="工作人员审计轨迹")
    sub.add_parser("rules", help="列出仲裁规则与解析出的时限")

    p_decide = sub.add_parser("decide", help="复核员处置")
    p_decide.add_argument("动作", choices=["更正", "维持", "驳回", "撤回", "核明条件"])
    p_decide.add_argument("争点")
    p_decide.add_argument("时间")
    p_decide.add_argument("--sheets", default="", help="更正指向的签字单编号，逗号分隔")
    p_decide.add_argument("--reason", default="", help="裁定依据")
    p_decide.add_argument("--condition-fails", action="store_true", help="核明条件时记条件不成立")

    args = parser.parse_args(argv)
    桌 = 仲裁桌(args.data)

    if args.命令 == "claims":
        数据 = [转普通值(i) for i in 桌.争点表.values()]
        _打印(数据, args.json)
    elif args.命令 == "held":
        _打印(桌.签发视图(args.时刻), args.json)
    elif args.命令 == "receipt":
        _打印(桌.队伍回执(args.队伍), args.json)
    elif args.命令 == "audit":
        _打印(桌.工作人员审计(), args.json)
    elif args.命令 == "rules":
        _打印({"规则": 桌.资料["bulletins"],
               "解析时限": {"名单申诉": 桌._规则分钟("名单申诉"),
                            "单场结果": 桌._规则分钟("单场结果")}}, args.json)
    elif args.命令 == "decide":
        方法 = {
            "更正": lambda: 桌.接受更正(args.争点, args.时间,
                                       [s for s in args.sheets.split(",") if s], args.reason),
            "维持": lambda: 桌.维持原记录(args.争点, args.时间, args.reason),
            "驳回": lambda: 桌.驳回(args.争点, args.时间, args.reason),
            "撤回": lambda: 桌.记录撤回(args.争点, args.时间, args.reason),
            "核明条件": lambda: 桌.核明条件(args.争点, args.时间,
                                           not args.condition_fails, args.reason),
        }[args.动作]
        _打印(方法(), args.json)


if __name__ == "__main__":
    main()
