"""交互式终端确认模块 - Claude Code 风格的上下选择交互

三种核心交互形态：
1. confirm_action: Yes / No / Always Allow（工具执行确认）
2. select_option: 多选项列表（方案选择）
3. select_or_input: 选项列表 + 自定义输入（选中"其他"后输入文本）

使用 prompt_toolkit 的 Application + RadioList 实现：
- 上下箭头切换高亮项
- Enter 确认选择
- Esc 取消（等同拒绝）

非 TTY 环境自动降级：
- WRITE 级别自动放行
- DESTRUCTIVE 级别自动拒绝
- select_option 返回第一个选项
"""
import sys
import json
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# prompt_toolkit 组件
PROMPT_TOOLKIT_AVAILABLE = False
try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, D
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.formatted_text import HTML, FormattedText
    from prompt_toolkit.widgets import RadioList, Label, Box, Frame
    from prompt_toolkit.styles import Style as PTStyle
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    pass


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
    """确认工具操作 - Claude Code 风格上下选择

    显示工具信息，用户通过方向键选择：
      ❯ 允许执行
        拒绝
        始终允许此工具

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

    # TTY 环境：交互选择
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
        result = _run_radiolist(header, options, default="allow")
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
        result = _run_radiolist(header, values, default=options[0])
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
        result = _run_radiolist(header, values, default=all_options[0])
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
# 内部实现：prompt_toolkit RadioList Application
# ═══════════════════════════════════════════════════════════════

def _run_radiolist(header: str, values: List[Tuple[str, str]], default: str = "") -> str:
    """运行 RadioList 选择器

    Args:
        header: 显示在选项上方的文本
        values: [(value, label), ...] 选项列表
        default: 默认选中的 value

    Returns:
        选中的 value
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        return default

    # 打印 header（在 Application 外部）
    sys.stdout.write(header)
    sys.stdout.flush()

    # 创建 RadioList
    radio = RadioList(values=values, default=default)

    # 自定义按键绑定
    kb = KeyBindings()

    result_holder = [default]  # 用 list 包装以允许闭包修改

    @kb.add("enter")
    def _enter(event):
        result_holder[0] = radio.current_value
        event.app.exit()

    @kb.add("escape")
    def _escape(event):
        result_holder[0] = ""  # Esc 视为取消
        event.app.exit()

    # 构建 Layout
    layout = Layout(HSplit([
        radio,
    ]))

    # 创建并运行 Application
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=_CONFIRM_STYLE,
        full_screen=False,
        mouse_support=False,
    )

    try:
        app.run()
    except (EOFError, KeyboardInterrupt):
        result_holder[0] = ""

    return result_holder[0]


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
