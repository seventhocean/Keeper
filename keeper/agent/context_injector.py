"""上下文注入器 — 让 Agent 在开口前就"知道该知道的事"

设计理念（参考 Claude Code 的 getSystemContext/getUserContext）：
- 不是简单拼 prompt，而是结构化的上下文治理
- 在 AgentLoop.run() 入口处统一注入到 system prompt
- 并行收集主机上下文、任务上下文、记忆摘要

三类上下文：
1. 主机上下文：SSH 连通性、最近巡检结果、告警状态
2. 任务上下文：最近操作的主机、相关工具调用历史
3. 记忆摘要：跨会话的操作回顾
"""
import time
import subprocess
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HostContext:
    """主机级别上下文"""
    hostname: str = ""
    os_info: str = ""
    uptime: str = ""
    last_inspect_cpu: Optional[float] = None
    last_inspect_mem: Optional[float] = None
    last_inspect_disk: Optional[float] = None
    last_inspect_time: str = ""


@dataclass
class TaskContext:
    """任务级别上下文"""
    recent_hosts: list = field(default_factory=list)       # 最近操作过的主机
    recent_tools: list = field(default_factory=list)       # 最近使用的工具
    recent_conclusions: list = field(default_factory=list) # 最近的结论摘要


@dataclass
class InjectedContext:
    """注入到 LLM 的完整上下文"""
    host: HostContext
    task: TaskContext
    memory_summary: str = ""  # 跨会话记忆摘要

    def format_for_system_prompt(self) -> str:
        """格式化为可注入 system prompt 的文本"""
        lines = ["[环境上下文]"]

        # 主机上下文
        if self.host.hostname:
            lines.append(f"  当前主机: {self.host.hostname}")
        if self.host.os_info:
            lines.append(f"  系统: {self.host.os_info}")
        if self.host.uptime:
            lines.append(f"  运行时间: {self.host.uptime}")
        if self.host.last_inspect_cpu is not None:
            lines.append(
                f"  上次巡检({self.host.last_inspect_time}): "
                f"CPU {self.host.last_inspect_cpu}% / MEM {self.host.last_inspect_mem}% / DISK {self.host.last_inspect_disk}%"
            )

        # 任务上下文
        if self.task.recent_hosts:
            lines.append(f"  最近操作主机: {', '.join(self.task.recent_hosts)}")
        if self.task.recent_tools:
            lines.append(f"  最近使用工具: {', '.join(self.task.recent_tools[:5])}")

        # 记忆摘要
        if self.memory_summary:
            lines.append("")
            lines.append(self.memory_summary)

        lines.append("")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        """判断上下文是否为空"""
        return (
            not self.host.hostname
            and not self.host.os_info
            and not self.memory_summary
            and not self.task.recent_hosts
        )


class ContextInjector:
    """上下文注入器 — 收集并格式化 Agent 运行所需的上下文"""

    def __init__(self, memory=None):
        """
        Args:
            memory: AgentMemory 实例（可选，用于获取记忆摘要）
        """
        self.memory = memory
        self._last_context: Optional[InjectedContext] = None
        self._last_collect_time: float = 0
        self._cache_ttl = 300  # 5 分钟缓存

    def collect(self, user_input: str = "") -> InjectedContext:
        """收集上下文

        Args:
            user_input: 用户输入（用于记忆匹配）

        Returns:
            InjectedContext 完整上下文
        """
        # 缓存：短时间内不重复收集
        now = time.time()
        if self._last_context and (now - self._last_collect_time) < self._cache_ttl:
            return self._last_context

        ctx = InjectedContext(
            host=self._collect_host_context(),
            task=self._collect_task_context(),
            memory_summary=self._collect_memory_summary(user_input),
        )
        self._last_context = ctx
        self._last_collect_time = now
        return ctx

    def _collect_host_context(self) -> HostContext:
        """并行收集主机上下文"""
        host_ctx = HostContext()

        try:
            import socket
            host_ctx.hostname = socket.gethostname()
        except Exception:
            pass

        # 并行收集 os_info 和 uptime
        try:
            result = subprocess.run(
                ["uname", "-s", "-r"], capture_output=True, text=True, timeout=5,
            )
            host_ctx.os_info = result.stdout.strip()
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["uptime", "-p"], capture_output=True, text=True, timeout=5,
            )
            host_ctx.uptime = result.stdout.strip()
        except Exception:
            pass

        # 从巡检历史获取最近数据
        try:
            from keeper.storage.history import InspectionHistory
            history = InspectionHistory()
            records = history.get_latest("localhost", n=1)
            if records:
                last = records[0]
                host_ctx.last_inspect_cpu = last.cpu_percent
                host_ctx.last_inspect_mem = last.memory_percent
                host_ctx.last_inspect_disk = last.disk_percent
                host_ctx.last_inspect_time = last.timestamp[:16].replace("T", " ") if last.timestamp else "未知"
        except Exception:
            pass

        return host_ctx

    def _collect_task_context(self) -> TaskContext:
        """从巡检历史和审计日志中提取任务上下文"""
        task_ctx = TaskContext()

        # 从巡检历史获取最近操作的主机
        try:
            from keeper.storage.history import InspectionHistory
            history = InspectionHistory()
            recent = history.get_latest("localhost", n=5)
            hosts = []
            for r in recent:
                h = r.host
                if h and h not in hosts:
                    hosts.append(h)
            task_ctx.recent_hosts = hosts
        except Exception:
            pass

        return task_ctx

    def _collect_memory_summary(self, user_input: str = "") -> str:
        """收集记忆摘要

        策略：
        - 首次调用：注入最近 3 条记忆摘要
        - 后续调用：仅注入与当前输入相关的记忆
        """
        if not self.memory:
            return ""

        lines = []
        try:
            if user_input:
                # 关键词匹配相关记忆
                history_context = self.memory.get_context_for_prompt(user_input)
                if history_context:
                    lines.append(history_context)
            else:
                # 无特定输入时注入最近记忆
                recent = self.memory.get_recent(3)
                if recent:
                    lines.append("[上次工作回顾]")
                    for entry in recent:
                        time_str = entry.timestamp[:16].replace("T", " ")
                        lines.append(f"  • [{time_str}] {entry.user_input[:50]}")
                        lines.append(f"    结论: {entry.conclusion[:80]}")
        except Exception:
            pass

        return "\n".join(lines)

    def refresh(self):
        """强制刷新缓存，下次 collect() 重新收集"""
        self._last_context = None
        self._last_collect_time = 0
