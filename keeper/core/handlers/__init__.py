"""Handler 模块 — 经典路由器模式的各意图处理器

从 core/agent.py 拆分而来，按功能域划分：
- inspect: 服务器巡检
- k8s: K8s 集群管理
- docker: Docker 容器管理
- network: 网络诊断
- security: 安全扫描 & 证书监控
- fix: 自动修复
- logs: 日志查询
- notify: 通知推送
- schedule: 定时任务
- misc: 帮助/导出/配置/安装等通用处理
"""

from .inspect import handle_inspect
from .k8s import handle_k8s_inspect, handle_k8s_logs, handle_k8s_export, handle_k8s_config, handle_k8s_ops
from .docker import handle_docker
from .network import handle_network
from .security import handle_scan, handle_cert_check
from .fix import handle_auto_fix
from .logs import handle_logs
from .notify import handle_send_notify
from .schedule import handle_schedule
from .misc import (
    handle_help, handle_chat, handle_unknown, handle_config,
    handle_export, handle_install, handle_confirm_no_task,
)

__all__ = [
    "handle_inspect",
    "handle_k8s_inspect", "handle_k8s_logs", "handle_k8s_export", "handle_k8s_config", "handle_k8s_ops",
    "handle_docker",
    "handle_network",
    "handle_scan", "handle_cert_check",
    "handle_auto_fix",
    "handle_logs",
    "handle_send_notify",
    "handle_schedule",
    "handle_help", "handle_chat", "handle_unknown", "handle_config",
    "handle_export", "handle_install", "handle_confirm_no_task",
]
