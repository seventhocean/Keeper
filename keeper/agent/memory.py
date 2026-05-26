"""Agent 记忆系统 — 跨会话持久化

设计理念：
- 短期记忆：当前对话的上下文（在 loop.py 的 conversation_history 中）
- 长期记忆：跨会话的操作摘要（持久化到文件）
- 用于：让 Agent 能参考历史操作（"上次也是这个问题"）
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from keeper.config import _file_lock


@dataclass
class AgentMemoryEntry:
    """Agent 记忆条目"""
    timestamp: str
    user_input: str
    tools_used: List[str]
    conclusion: str      # 最终结论摘要
    host: str = ""       # 涉及的主机
    category: str = ""   # 分类：inspect/network/k8s/security/fix


class AgentMemory:
    """Agent 长期记忆管理器

    持久化到 ~/.keeper/agent_memory.json
    保留最近 100 条记录
    """

    MAX_ENTRIES = 100
    MAX_CONCLUSION_LEN = 300

    def __init__(self, memory_dir: Optional[Path] = None):
        self.memory_dir = memory_dir or Path.home() / ".keeper"
        self.memory_file = self.memory_dir / "agent_memory.json"
        self._entries: List[AgentMemoryEntry] = []
        self._load()

    def _load(self):
        """从文件加载记忆"""
        if self.memory_file.exists():
            try:
                with _file_lock(self.memory_file, exclusive=False):
                    with open(self.memory_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._entries = [
                            AgentMemoryEntry(**entry) for entry in data.get("entries", [])
                        ]
            except (json.JSONDecodeError, TypeError, KeyError):
                self._entries = []

    def _save(self):
        """持久化记忆到文件"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "entries": [asdict(e) for e in self._entries[-self.MAX_ENTRIES:]],
        }
        with _file_lock(self.memory_file, exclusive=True):
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def add(
        self,
        user_input: str,
        tools_used: List[str],
        conclusion: str,
        host: str = "",
        category: str = "",
    ):
        """添加一条记忆

        Args:
            user_input: 用户原始输入
            tools_used: 使用的工具列表
            conclusion: 最终结论摘要
            host: 涉及的主机
            category: 任务分类
        """
        entry = AgentMemoryEntry(
            timestamp=datetime.now().isoformat(),
            user_input=user_input[:200],
            tools_used=tools_used[:10],
            conclusion=conclusion[:self.MAX_CONCLUSION_LEN],
            host=host,
            category=category,
        )
        self._entries.append(entry)

        # 控制长度
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]

        self._save()

    def get_recent(self, n: int = 10) -> List[AgentMemoryEntry]:
        """获取最近 N 条记忆"""
        return self._entries[-n:]

    def search(self, keyword: str, limit: int = 5) -> List[AgentMemoryEntry]:
        """按关键词搜索记忆"""
        keyword_lower = keyword.lower()
        results = []
        for entry in reversed(self._entries):
            if (keyword_lower in entry.user_input.lower() or
                keyword_lower in entry.conclusion.lower() or
                keyword_lower in entry.host.lower()):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def get_host_history(self, host: str, limit: int = 5) -> List[AgentMemoryEntry]:
        """获取某主机的操作历史"""
        results = []
        for entry in reversed(self._entries):
            if entry.host == host:
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def get_context_for_prompt(self, user_input: str, host: str = "") -> str:
        """生成供 LLM 参考的历史上下文

        根据当前输入查找相关历史记录，格式化为 prompt 片段。
        """
        relevant = []

        # 按主机查找
        if host:
            relevant.extend(self.get_host_history(host, limit=3))

        # 按关键词查找
        keywords = user_input.split()[:3]  # 取前 3 个词
        for kw in keywords:
            if len(kw) >= 2:  # 跳过太短的词
                relevant.extend(self.search(kw, limit=2))

        if not relevant:
            return ""

        # 去重
        seen = set()
        unique = []
        for entry in relevant:
            key = entry.timestamp
            if key not in seen:
                seen.add(key)
                unique.append(entry)

        if not unique:
            return ""

        # 格式化
        lines = ["[历史操作参考]"]
        for entry in unique[:5]:
            time_str = entry.timestamp[:16].replace("T", " ")
            lines.append(f"  • [{time_str}] {entry.user_input}")
            lines.append(f"    结论: {entry.conclusion[:100]}")
        lines.append("")

        return "\n".join(lines)

    def clear(self):
        """清空所有记忆"""
        self._entries = []
        self._save()

    @property
    def count(self) -> int:
        """记忆条目数量"""
        return len(self._entries)

    def format_recent(self, n: int = 5) -> str:
        """格式化显示最近记忆"""
        entries = self.get_recent(n)
        if not entries:
            return "(暂无历史记忆)"

        lines = [f"[Agent 记忆] 最近 {len(entries)} 条操作:"]
        lines.append("━" * 50)
        for i, entry in enumerate(entries, 1):
            time_str = entry.timestamp[:16].replace("T", " ")
            tools_str = ", ".join(entry.tools_used[:3])
            lines.append(f"  {i}. [{time_str}] {entry.user_input[:50]}")
            lines.append(f"     工具: {tools_str}")
            lines.append(f"     结论: {entry.conclusion[:80]}")
        lines.append("━" * 50)
        lines.append(f"共 {self.count} 条记忆")
        return "\n".join(lines)
