"""Agent 状态总线 — 集中管理 Agent 运行时状态

设计理念（参考 Claude Code 的 AppStateStore）：
- 上层（HybridAgent/CLI）从这里读状态
- 下层（AgentLoop/工具）往这里写状态变化
- 跨模块能力通过它共享会话级信息
"""
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field


@dataclass
class SessionState:
    """会话级别状态"""
    is_running: bool = False
    current_host: str = ""
    tool_mode: str = "all"           # free / routed / all
    permission_mode: str = "allow"   # allow / read_only
    active_loop_mode: str = ""       # langgraph / manual / error
    last_intent: str = ""
    last_tool_calls: list = field(default_factory=list)
    stream_callback: Optional[Callable] = None

    # 通知/提示队列
    warnings: list = field(default_factory=list)


class AgentStateStore:
    """Agent 状态总线

    集中管理 HybridAgent 运行时的所有状态，
    替代散落在 self.state / self._agent_loop / self._stream_callback 等处的私有字段。
    """

    def __init__(self):
        self.session = SessionState()
        self._hooks: Dict[str, list] = {}  # 状态变更钩子

    # ─── 核心状态读写 ──────────────────────────────────────────

    def get(self, key: str, default=None) -> Any:
        """获取状态值"""
        return getattr(self.session, key, default)

    def set(self, key: str, value: Any):
        """设置状态值"""
        old_value = getattr(self.session, key, None)
        setattr(self.session, key, value)
        # 触发钩子
        if key in self._hooks:
            for hook in self._hooks[key]:
                hook(old_value, value)

    def register_hook(self, key: str, hook: Callable):
        """注册状态变更钩子

        Args:
            key: 要监听的字段名
            hook: (old_value, new_value) -> None
        """
        if key not in self._hooks:
            self._hooks[key] = []
        self._hooks[key].append(hook)

    # ─── 便捷属性 ──────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.session.is_running

    @is_running.setter
    def is_running(self, value: bool):
        self.session.is_running = value

    @property
    def current_host(self) -> str:
        return self.session.current_host

    @current_host.setter
    def current_host(self, value: str):
        self.session.current_host = value

    # ─── 会话控制 ──────────────────────────────────────────────

    def stop(self):
        """停止当前会话"""
        self.session.is_running = False

    def reset(self):
        """重置状态（保留 hooks）"""
        old_session = self.session
        self.session = SessionState()
        self.session.warnings = list(old_session.warnings)  # 保留警告

    def add_warning(self, warning: str):
        """添加警告到通知队列"""
        self.session.warnings.append(warning)

    def get_warnings(self) -> list:
        """获取并清空警告队列"""
        warnings = list(self.session.warnings)
        self.session.warnings.clear()
        return warnings

    # ─── 状态快照 ──────────────────────────────────────────────

    def snapshot(self) -> dict:
        """获取当前状态快照（用于调试/审计）"""
        return {
            "is_running": self.session.is_running,
            "current_host": self.session.current_host,
            "tool_mode": self.session.tool_mode,
            "permission_mode": self.session.permission_mode,
            "active_loop_mode": self.session.active_loop_mode,
            "last_intent": self.session.last_intent,
            "last_tool_count": len(self.session.last_tool_calls),
            "pending_warnings": len(self.session.warnings),
        }

    def format_status(self) -> str:
        """格式化状态为可读文本"""
        s = self.session
        lines = [
            f"[Agent 状态] 运行: {'是' if s.is_running else '否'}",
            f"  当前主机: {s.current_host or '未指定'}",
            f"  工具模式: {s.tool_mode}",
            f"  权限模式: {s.permission_mode}",
            f"  引擎: {s.active_loop_mode or '未初始化'}",
            f"  最近工具调用: {len(s.last_tool_calls)} 次",
        ]
        if s.warnings:
            lines.append(f"  警告: {len(s.warnings)} 条待处理")
        return "\n".join(lines)


# ─── TodoWrite 轻量任务追踪 ──────────────────────────────────────

@dataclass
class TodoItem:
    """待办事项"""
    subject: str
    status: str = "pending"  # pending / in_progress / completed

    def icon(self) -> str:
        return {
            "pending": "○",
            "in_progress": "◉",
            "completed": "✓",
        }.get(self.status, "?")


class TodoList:
    """轻量级待办清单 — 会话内追踪

    参考 Claude Code 的 TodoWriteTool。
    让 LLM 在复杂任务中把工作拆成可见的步骤。
    """

    def __init__(self):
        self.items: List[TodoItem] = []

    def set_todos(self, todos: List[dict]):
        """设置完整的待办清单（替换旧的）

        Args:
            todos: [{"subject": "...", "status": "pending"}, ...]
        """
        self.items = []
        for t in todos:
            self.items.append(TodoItem(
                subject=t.get("subject", ""),
                status=t.get("status", "pending"),
            ))

    def update(self, index: int, status: str):
        """更新某个任务的状态"""
        if 0 <= index < len(self.items):
            self.items[index].status = status

    def mark_all_pending(self):
        """重置所有任务为 pending"""
        for item in self.items:
            item.status = "pending"

    def is_complete(self) -> bool:
        """是否所有任务都已完成"""
        return bool(self.items) and all(i.status == "completed" for i in self.items)

    def format(self) -> str:
        """格式化为可读文本"""
        if not self.items:
            return "(无待办事项)"
        lines = ["[执行计划]"]
        for i, item in enumerate(self.items, 1):
            lines.append(f"  {item.icon()} {i}. {item.subject}")
        completed = sum(1 for i in self.items if i.status == "completed")
        lines.append(f"共 {len(self.items)} 项，完成 {completed}/{len(self.items)}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """转换为 dict（用于持久化）"""
        return {
            "items": [{"subject": i.subject, "status": i.status} for i in self.items],
        }

    def from_dict(self, data: dict):
        """从 dict 恢复"""
        self.items = [TodoItem(**item) for item in data.get("items", [])]


# 全局 TodoList 实例（由 AgentStateStore 管理）
global_todo_list = TodoList()


def todo_write_tool():
    """创建 TodoWrite 工具

    Returns:
        一个可调用的 StructuredTool（类似 langchain @tool 风格）
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field
    from typing import List

    class TodoEntry(BaseModel):
        subject: str = Field(description="任务描述")
        status: str = Field(default="pending", description="任务状态: pending/in_progress/completed")

    class TodoWriteInput(BaseModel):
        todos: List[TodoEntry] = Field(description="完整的待办清单（会替换旧的）")

    def _todo_write(todos: List[TodoEntry]) -> str:
        global_todo_list.set_todos([t.model_dump() for t in todos])
        return global_todo_list.format()

    return StructuredTool(
        name="todo_write",
        description="设置或更新当前任务的执行计划。将工作拆成 3-5 个可见步骤。",
        func=_todo_write,
        args_schema=TodoWriteInput,
    )
