"""NLU 引擎抽象基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class IntentType(str, Enum):
    """支持的意图类型"""
    INSPECT = "inspect"      # 服务器巡检
    SCAN = "scan"            # 漏洞扫描
    CONFIG = "config"        # 配置管理
    LOGS = "logs"            # 日志查询
    HELP = "help"            # 帮助
    INSTALL = "install"      # 安装软件
    CONFIRM = "confirm"      # 确认执行
    CHAT = "chat"            # 闲聊/知识问答（非任务）
    EXPORT = "export"        # 导出报告
    K8S_INSPECT = "k8s_inspect"   # K8s 集群巡检
    K8S_LOGS = "k8s_logs"         # K8s Pod 日志
    K8S_EXPORT = "k8s_export"     # 导出 K8s 报告
    K8S_CONFIG = "k8s_config"     # K8s 配置
    K8S_OPS = "k8s_ops"           # K8s 深度操作 (exec/扩缩容/回滚/重启)
    DOCKER_INSPECT = "docker_inspect"  # Docker 容器管理
    RCA_ANALYSIS = "rca_analysis"      # 根因分析
    NETWORK_DIAG = "network_diag"      # 网络诊断
    SCHEDULE_TASK = "schedule_task"    # 定时任务
    AUTO_FIX = "auto_fix"              # 自动修复
    CERT_CHECK = "cert_check"          # 证书监控
    UNKNOWN = "unknown"      # 未知意图


@dataclass
class ParsedIntent:
    """解析结果"""
    is_task: bool = True                      # 是否是运维任务
    intent: IntentType = IntentType.UNKNOWN
    entities: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    raw_input: str = ""
    direct_response: Optional[str] = None     # 非任务时的直接回复
    followup_questions: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


class NLUEngine(ABC):
    """NLU 引擎抽象基类"""

    @abstractmethod
    def parse(self, user_input: str, context: Optional[Dict] = None) -> ParsedIntent:
        """解析用户输入

        Args:
            user_input: 用户输入文本
            context: 上下文信息（如最近提到的主机）

        Returns:
            ParsedIntent: 解析结果
        """
        pass

    @abstractmethod
    def load(self) -> None:
        """加载资源（模型、配置等）"""
        pass
