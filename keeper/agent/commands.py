"""命令系统 — 用户显式控制（/clear, /tools, /memory 等）

设计理念（参考 Claude Code 的 commands.ts）：
- 命令系统：给用户显式输入（显式控制）
- 工具系统：给模型隐式调用（自动干活）
- 两者共享底层（配置/状态/工具注册表）
"""
from typing import Optional


class CommandRegistry:
    """命令注册表 — 注册和查找斜杠命令"""

    def __init__(self):
        self._commands = {}

    def register(self, name: str, handler, aliases=None):
        """注册一个命令

        Args:
            name: 命令名称（不带 / 前缀）
            handler: 处理函数 (args: str) -> str
            aliases: 别名列表（如 ["清空", "reset"]）
        """
        self._commands[name] = handler
        if aliases:
            for alias in aliases:
                self._commands[alias] = handler

    def dispatch(self, cmd: str) -> Optional[str]:
        """查找并执行命令

        Args:
            cmd: 用户输入的命令（已 lowercase，不带 / 前缀）

        Returns:
            命令执行结果，或 None（表示未找到）
        """
        handler = self._commands.get(cmd)
        if handler:
            return handler()
        return None

    def list_commands(self) -> list:
        """列出所有已注册的命令"""
        return list(self._commands.keys())


def create_default_registry(agent_loop_getter, memory_getter) -> CommandRegistry:
    """创建默认命令注册表（包含所有内置命令）

    Args:
        agent_loop_getter: 获取 AgentLoop 实例的函数
        memory_getter: 获取 AgentMemory 实例的函数

    Returns:
        已注册的 CommandRegistry
    """
    registry = CommandRegistry()

    @registry.register("clear", lambda: _clear(agent_loop_getter))
    def _clear_cmd():
        pass  # 注册器会自动忽略，实际由装饰器注册

    registry.register("clear", lambda: _clear(agent_loop_getter), aliases=["清空", "reset"])
    registry.register("history", lambda: _history(agent_loop_getter), aliases=["上次", "last"])
    registry.register("tools", _tools, aliases=["能力"])
    registry.register("mode", lambda: _mode(agent_loop_getter), aliases=["状态"])
    registry.register("plugins", _plugins, aliases=["插件"])

    # /memory 特殊处理（需要解析参数）
    registry.register("memory", lambda: _memory_help())
    registry.register("记忆", lambda: _memory_help())

    return registry


def _clear(agent_loop_getter) -> str:
    loop = agent_loop_getter()
    if loop:
        loop.clear_history()
    return "[系统] 对话历史已清空。"


def _history(agent_loop_getter) -> str:
    loop = agent_loop_getter()
    if loop:
        return loop.get_execution_summary()
    return "(无执行记录)"


def _tools() -> str:
    from .free_tools import get_free_tools_description
    from .tools_registry import get_tools_description
    return get_free_tools_description() + "\n" + get_tools_description()


def _mode(agent_loop_getter) -> str:
    loop = agent_loop_getter()
    mode = loop.active_mode if loop else "未初始化"
    return f"[系统] 当前模式: Agent Loop ({mode})"


def _plugins() -> str:
    from .plugins import format_plugins_info
    return format_plugins_info()


def _memory_help() -> str:
    return (
        "[系统] 用法: /memory [数量] [--host xxx] [--cat 类别] [--search 关键词] [--date YYYY-MM-DD]\n"
        "示例: /memory 10 | /memory --host localhost | /memory --search cpu"
    )


def handle_memory_command(cmd: str, memory) -> str:
    """处理 /memory 命令（支持筛选参数）

    用法：
      /memory              — 显示最近 5 条
      /memory 10           — 显示最近 10 条
      /memory --host xxx   — 按主机筛选
      /memory --cat xxx    — 按类别筛选
      /memory --search xxx — 按关键词搜索
      /memory --date 2026-05-15 — 按日期筛选
    """
    parts = cmd.strip().split()
    args = parts[1:] if len(parts) > 1 else []

    if not args:
        return memory.format_recent(5)

    # 解析参数
    host_filter = None
    cat_filter = None
    search_kw = None
    date_filter = None
    count = 10

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--host", "-h") and i + 1 < len(args):
            host_filter = args[i + 1]
            i += 2
        elif arg in ("--cat", "--category", "-c") and i + 1 < len(args):
            cat_filter = args[i + 1]
            i += 2
        elif arg in ("--search", "--keyword", "-s", "-k") and i + 1 < len(args):
            search_kw = args[i + 1]
            i += 2
        elif arg in ("--date", "-d") and i + 1 < len(args):
            date_filter = args[i + 1]
            i += 2
        elif arg.isdigit():
            count = int(arg)
            i += 1
        else:
            search_kw = arg
            i += 1

    # 执行筛选
    if search_kw:
        entries = memory.search(search_kw, limit=count)
    elif host_filter:
        entries = memory.get_host_history(host_filter, limit=count)
    else:
        entries = memory.get_recent(count)

    # 二次过滤
    if cat_filter:
        entries = [e for e in entries if e.category == cat_filter]
    if date_filter:
        entries = [e for e in entries if e.timestamp.startswith(date_filter)]

    if not entries:
        hints = []
        if host_filter:
            hints.append(f"主机={host_filter}")
        if cat_filter:
            hints.append(f"类别={cat_filter}")
        if search_kw:
            hints.append(f"关键词={search_kw}")
        if date_filter:
            hints.append(f"日期={date_filter}")
        filter_desc = ", ".join(hints) if hints else "无"
        return f"[Agent 记忆] 未找到匹配记录 (筛选: {filter_desc})"

    # 格式化输出
    lines = [f"[Agent 记忆] 匹配 {len(entries)} 条记录:"]
    lines.append("━" * 50)
    for idx, entry in enumerate(entries, 1):
        time_str = entry.timestamp[:16].replace("T", " ")
        tools_str = ", ".join(entry.tools_used[:3])
        cat_str = f" [{entry.category}]" if entry.category else ""
        host_str = f" @{entry.host}" if entry.host else ""
        lines.append(f"  {idx}. [{time_str}]{cat_str}{host_str} {entry.user_input[:50]}")
        lines.append(f"     工具: {tools_str}")
        lines.append(f"     结论: {entry.conclusion[:80]}")
    lines.append("━" * 50)
    lines.append(f"共 {memory.count} 条记忆 | 显示 {len(entries)} 条")
    lines.append("筛选: /memory --host <ip> | --cat <类别> | --search <关键词> | --date <YYYY-MM-DD>")
    return "\n".join(lines)
