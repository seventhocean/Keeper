"""交互式终端确认模块 - 使用 prompt_toolkit 提供用户确认交互

功能：
- confirm_action: 对 WRITE/DESTRUCTIVE 级别的工具调用进行确认
- select_option: 显示编号选项列表供用户选择

非 TTY 环境（管道、CI 等）自动降级：
- WRITE 级别自动放行
- DESTRUCTIVE 级别自动拒绝
- select_option 返回第一个选项
"""
import sys
import json
import logging
from typing import List

logger = logging.getLogger(__name__)

# prompt_toolkit 可能未安装，做优雅降级
try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False


def _format_args_summary(args: dict, max_len: int = 80) -> str:
    """格式化参数摘要，超长时截断"""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def _safety_badge(safety_level: str) -> str:
    """根据安全等级返回标记"""
    badges = {
        "read_only": "[READ_ONLY]",
        "write": "[WRITE]",
        "destructive": "[DESTRUCTIVE]",
        "dangerous": "[DANGEROUS]",
    }
    return badges.get(safety_level.lower(), f"[{safety_level.upper()}]")


def confirm_action(tool_name: str, args: dict, safety_level: str) -> bool:
    """确认工具操作

    对 WRITE/DESTRUCTIVE 级别的工具调用显示确认提示。

    Args:
        tool_name: 工具名称
        args: 工具参数字典
        safety_level: 安全等级 (write/destructive/dangerous)

    Returns:
        True 表示用户确认执行，False 表示拒绝
    """
    # 非 TTY 环境：自动处理
    if not sys.stdin.isatty():
        level = safety_level.lower()
        if level == "write":
            logger.info(
                "Non-TTY auto-approve: tool=%s args=%s safety_level=%s",
                tool_name, _format_args_summary(args), safety_level,
            )
            return True
        # destructive 及以上自动拒绝
        return False

    # TTY 环境：交互确认
    badge = _safety_badge(safety_level)
    args_summary = _format_args_summary(args)

    display_text = (
        f"\n{'=' * 50}\n"
        f"  工具: {tool_name}\n"
        f"  参数: {args_summary}\n"
        f"  安全等级: {badge}\n"
        f"{'=' * 50}\n"
    )

    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            print(display_text)
            answer = pt_prompt(
                HTML("<b>是否执行? (Y/n): </b>"),
                default="Y",
            )
            return answer.strip().lower() in ("y", "yes", "")
        except (EOFError, KeyboardInterrupt):
            return False
    else:
        # 降级到内置 input()
        try:
            print(display_text)
            answer = input("是否执行? (Y/n): ")
            return answer.strip().lower() in ("y", "yes", "")
        except (EOFError, KeyboardInterrupt):
            return False


def select_option(question: str, options: List[str]) -> str:
    """显示编号选项列表供用户选择

    Args:
        question: 提问文本
        options: 选项列表

    Returns:
        用户选择的选项文本
    """
    if not options:
        return ""

    # 非 TTY 环境：返回第一个选项
    if not sys.stdin.isatty():
        return options[0]

    # TTY 环境：交互选择
    display_text = f"\n{question}\n"
    for i, opt in enumerate(options, 1):
        display_text += f"  {i}. {opt}\n"

    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            print(display_text)
            answer = pt_prompt(
                HTML("<b>请选择 (输入编号): </b>"),
                default="1",
            )
            idx = int(answer.strip()) - 1
            if 0 <= idx < len(options):
                return options[idx]
            return options[0]
        except (EOFError, KeyboardInterrupt):
            return options[0]
        except (ValueError, IndexError):
            return options[0]
    else:
        # 降级到内置 input()
        try:
            print(display_text)
            answer = input("请选择 (输入编号): ")
            idx = int(answer.strip()) - 1
            if 0 <= idx < len(options):
                return options[idx]
            return options[0]
        except (EOFError, KeyboardInterrupt):
            return options[0]
        except (ValueError, IndexError):
            return options[0]
