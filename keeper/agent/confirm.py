"""交互式终端确认模块 - Claude Code 风格的确认交互

三种核心交互形态：
1. confirm_action: Yes / No / Always Allow（工具执行确认）
2. select_option: 多选项列表（方案选择）
3. select_or_input: 选项列表 + 自定义输入（选中"其他"后输入文本）

使用阻塞式编号输入（print + input）：
- 兼容 Agent Loop 的 asyncio 事件循环上下文
- 并行工具调用通过全局锁序列化，防止输出重叠

非 TTY 环境自动降级：
- WRITE 级别自动放行
- DESTRUCTIVE 级别自动拒绝
- select_option 返回第一个选项
"""
import sys
import json
import logging
import threading
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# prompt_toolkit 组件
PROMPT_TOOLKIT_AVAILABLE = False
try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style as PTStyle
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    pass


# ─── 全局锁：防止并行工具调用导致确认弹窗重叠 ─────────────
_confirm_lock = threading.Lock()


# ─── 会话级缓存：始终允许的工具 ──────────────────────────────────
_always_allowed_tools: set = set()


def reset_always_allowed():
    """重置始终允许列表（新会话时调用）"""
    _always_allowed_tools.clear()


# ─── 样式定义 ─────────────────────────────────────────────────

_CONFIRM_STYLE = PTStyle.from_dict({
    "dialog": "bg:#1a1a2e",
    "dialog.body": "",
    "radio-list": "",
    "radio": "",
    "radio-selected": "fg:ansicyan bold",
    "label": "bold",
    "title": "fg:ansiyellow bold",
    "info": "fg:ansibrightblack",
}) if PROMPT_TOOLKIT_AVAILABLE else None


# ─── 工具函数 ─────────────────────────────────────────────────

def _format_args_summary(args: dict, max_len: int = 80) -> str:
    """格式化参数摘要"""
    if not args:
        return "(无参数)"
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def _safety_icon(safety_level: str) -> str:
    """安全等级图标"""
    icons = {
        "read_only": "🟢",
        "write": "🟡",
        "destructive": "🟠",
        "dangerous": "🔴",
    }
    return icons.get(safety_level.lower(), "⚪")


# ═══════════════════════════════════════════════════════════════
# 形态 1: Yes / No / Always Allow（工具执行确认）
# ═══════════════════════════════════════════════════════════════

def confirm_action(tool_name: str, args: dict, safety_level: str) -> bool:
    """确认工具操作 - 阻塞式编号输入

    显示工具信息，用户通过输入编号选择：
      1. 允许执行
      2. 拒绝
      3. 始终允许此工具

    Args:
        tool_name: 工具名称
        args: 工具参数字典
        safety_level: 安全等级 (write/destructive/dangerous)

    Returns:
        True 表示用户确认执行，False 表示拒绝
    """
    # 会话级缓存：已始终允许的工具直接通过
    if tool_name in _always_allowed_tools:
        return True

    # 非 TTY 环境：自动处理
    if not sys.stdin.isatty():
        level = safety_level.lower()
        if level == "write":
            return True
        return False

    # 获取全局锁：防止并行工具调用导致确认弹窗重叠
    # 注意：获取锁后需再次检查缓存（可能在等待期间被其他线程添加了）
    with _confirm_lock:
        if tool_name in _always_allowed_tools:
            return True
        return _confirm_interactive(tool_name, args, safety_level)


def _confirm_interactive(tool_name: str, args: dict, safety_level: str) -> bool:
    """交互式确认（调用方需持有 _confirm_lock）"""
    icon = _safety_icon(safety_level)
    args_summary = _format_args_summary(args)

    # 显示工具信息
    header = (
        f"\n{icon} 操作确认 {safety_level.upper()}\n"
        f"  工具: {tool_name}\n"
        f"  参数: {args_summary}\n"
    )

    options = [
        ("allow", "允许执行"),
        ("deny", "拒绝"),
        ("always", f"始终允许 {tool_name}（本次会话）"),
    ]

    if PROMPT_TOOLKIT_AVAILABLE:
        result = _blocking_select(header, options, default="allow")
    else:
        result = _fallback_select(header, [opt[1] for opt in options])
        # 映射回 key
        result_map = {opt[1]: opt[0] for opt in options}
        result = result_map.get(result, "deny")

    if result == "allow":
        return True
    elif result == "always":
        _always_allowed_tools.add(tool_name)
        return True
    else:
        return False


# ═══════════════════════════════════════════════════════════════
# 形态 2: 多选项列表（方案选择）
# ═══════════════════════════════════════════════════════════════

def select_option(question: str, options: List[str]) -> str:
    """多选项列表 - 上下选择 + Enter 确认

    显示：
      问题文本
      ❯ 选项 1
        选项 2
        选项 3

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

    # TTY 环境
    header = f"\n{question}\n"
    values = [(opt, opt) for opt in options]

    if PROMPT_TOOLKIT_AVAILABLE:
        result = _blocking_select(header, values, default=options[0])
        return result if result else options[0]
    else:
        return _fallback_select(header, options)


# ═══════════════════════════════════════════════════════════════
# 形态 3: 选项列表 + 自定义输入
# ═══════════════════════════════════════════════════════════════

_OTHER_SENTINEL = "__OTHER_INPUT__"


def select_or_input(question: str, options: List[str], other_label: str = "输入其他...") -> str:
    """选项列表 + 自定义输入

    选项末尾追加一个"输入其他..."选项，选中后弹出文本输入框。

    显示：
      问题文本
      ❯ 选项 1
        选项 2
        输入其他...

    Args:
        question: 提问文本
        options: 预设选项列表
        other_label: "其他"选项的显示文本

    Returns:
        用户选择的选项文本，或自定义输入的文本
    """
    if not options:
        # 无预设选项，直接文本输入
        return _text_input(question)

    # 非 TTY 环境：返回第一个选项
    if not sys.stdin.isatty():
        return options[0]

    # 构建选项列表，末尾追加"其他"
    all_options = options + [other_label]
    header = f"\n{question}\n"
    values = [(opt, opt) for opt in all_options]

    if PROMPT_TOOLKIT_AVAILABLE:
        result = _blocking_select(header, values, default=all_options[0])
        if result == other_label:
            # 用户选择了"其他"，弹出文本输入
            return _text_input("  请输入:")
        return result if result else options[0]
    else:
        result = _fallback_select(header, all_options)
        if result == other_label:
            return _fallback_text_input("  请输入: ")
        return result


# ═══════════════════════════════════════════════════════════════
# 内部实现：阻塞式编号选择（print + input）
# ═══════════════════════════════════════════════════════════════

def _blocking_select(header: str, values: List[Tuple[str, str]], default: str = "") -> str:
    """阻塞式编号输入（print + input）

    适用于：
    - Agent Loop 已在 asyncio 事件循环中运行，无法使用 prompt_toolkit Application
    - 多个并行工具调用需要序列化确认（由 _confirm_lock 保护）

    Args:
        header: 显示在选项上方的文本
        values: [(value, label), ...] 选项列表
        default: 默认选中的 value

    Returns:
        选中的 value
    """
    # 打印 header + 编号选项列表
    sys.stdout.write(header)
    for i, (_, label) in enumerate(values, 1):
        sys.stdout.write(f"  {i}. {label}\n")
    sys.stdout.flush()

    # 确定默认编号
    default_idx = 1
    if default:
        for i, (v, _) in enumerate(values, 1):
            if v == default:
                default_idx = i
                break

    # 读取编号输入
    try:
        answer = input(f"  请选择 [{default_idx}]: ")
        answer = answer.strip()
        if answer == "":
            idx = default_idx
        else:
            idx = int(answer)
        if 1 <= idx <= len(values):
            return values[idx - 1][0]
        return values[default_idx - 1][0]
    except (EOFError, KeyboardInterrupt):
        return ""
    except (ValueError, IndexError):
        return values[default_idx - 1][0]


# ═══════════════════════════════════════════════════════════════
# 内部实现：文本输入
# ═══════════════════════════════════════════════════════════════

def _text_input(prompt_text: str) -> str:
    """prompt_toolkit 文本输入"""
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            return pt_prompt(HTML(f"<b>{prompt_text} </b>"))
        except (EOFError, KeyboardInterrupt):
            return ""
    else:
        return _fallback_text_input(prompt_text)


def _fallback_text_input(prompt_text: str) -> str:
    """内置 input() 降级"""
    try:
        return input(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return ""


# ═══════════════════════════════════════════════════════════════
# 内部实现：降级交互（无 prompt_toolkit）
# ═══════════════════════════════════════════════════════════════

def _fallback_select(header: str, options: List[str]) -> str:
    """无 prompt_toolkit 时的降级选择"""
    print(header)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")

    try:
        answer = input("\n请选择 (输入编号): ")
        idx = int(answer.strip()) - 1
        if 0 <= idx < len(options):
            return options[idx]
        return options[0]
    except (EOFError, KeyboardInterrupt):
        return options[0]
    except (ValueError, IndexError):
        return options[0]
