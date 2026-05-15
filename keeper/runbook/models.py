"""Runbook 数据模型

定义 Runbook 的结构：步骤、变量、触发条件、安全等级。
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class StepSafety(str, Enum):
    """步骤安全等级"""
    SAFE = "safe"
    CAUTION = "caution"
    DESTRUCTIVE = "destructive"


class StepStatus(str, Enum):
    """步骤执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CONFIRM_WAIT = "confirm_wait"


class OnFailAction(str, Enum):
    """失败处理策略"""
    ABORT = "abort"
    NOTIFY = "notify"
    ROLLBACK = "rollback"
    CONTINUE = "continue"


@dataclass
class RunbookStep:
    """Runbook 单步"""
    name: str
    action: str = "shell"       # shell / k8s / check
    command: str = ""
    safety: StepSafety = StepSafety.SAFE
    confirm: bool = False       # 是否需要人工确认
    timeout: int = 30           # 超时秒数
    expect: str = ""            # 预期结果表达式（如 "< 85%"）
    on_fail: OnFailAction = OnFailAction.ABORT
    rollback: str = ""          # 回滚命令
    # 执行状态（运行时填充）
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    duration_ms: int = 0


@dataclass
class Runbook:
    """Runbook 完整定义"""
    name: str
    description: str = ""
    trigger: str = ""           # 触发条件表达式
    variables: Dict[str, Any] = field(default_factory=dict)
    steps: List[RunbookStep] = field(default_factory=list)
    # 元数据
    author: str = ""
    version: str = "1.0"
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Runbook":
        """从字典创建 Runbook"""
        steps = []
        for s in data.get("steps", []):
            steps.append(RunbookStep(
                name=s.get("name", ""),
                action=s.get("action", "shell"),
                command=s.get("command", ""),
                safety=StepSafety(s.get("safety", s.get("type", "safe"))),
                confirm=s.get("confirm", False),
                timeout=s.get("timeout", 30),
                expect=s.get("expect", ""),
                on_fail=OnFailAction(s.get("on_fail", "abort")),
                rollback=s.get("rollback", ""),
            ))

        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            trigger=data.get("trigger", ""),
            variables=data.get("variables", {}),
            steps=steps,
            author=data.get("author", ""),
            version=data.get("version", "1.0"),
            tags=data.get("tags", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "variables": self.variables,
            "steps": [
                {
                    "name": s.name,
                    "action": s.action,
                    "command": s.command,
                    "safety": s.safety.value,
                    "confirm": s.confirm,
                    "timeout": s.timeout,
                    "expect": s.expect,
                    "on_fail": s.on_fail.value,
                    "rollback": s.rollback,
                }
                for s in self.steps
            ],
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
        }
