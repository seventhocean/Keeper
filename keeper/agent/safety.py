"""安全控制层 — Agent 工具调用安全审查

设计理念：
- Agent 模式下 LLM 可能生成任意 shell 命令
- 必须在执行前进行安全分级和拦截
- 三级控制：白名单（直接执行）、灰名单（需确认）、黑名单（拒绝）

安全等级：
- READ_ONLY:  只读操作，无风险（ps, df, cat, grep...）
- WRITE:      写操作，需用户确认（systemctl restart, docker stop...）
- DESTRUCTIVE: 破坏性，强制确认+警告（truncate, prune, autoremove...）
- DANGEROUS:  高危，绝对拒绝（rm -rf, dd, mkfs, fork bomb...）
"""
import re
from enum import Enum
from typing import List, Tuple, Optional
from dataclasses import dataclass


class SafetyLevel(str, Enum):
    """命令安全等级"""
    READ_ONLY = "read_only"        # 只读，直接执行
    WRITE = "write"                # 写操作，需确认
    DESTRUCTIVE = "destructive"    # 破坏性，强制确认+警告
    DANGEROUS = "dangerous"        # 高危，拒绝执行


@dataclass
class SafetyVerdict:
    """安全审查结论"""
    level: SafetyLevel
    allowed: bool
    reason: str
    command: str
    requires_confirmation: bool = False


class CommandSafetyChecker:
    """命令安全检查器"""

    # ─── 黑名单：绝对拒绝 ─────────────────────────────────────
    DANGEROUS_PATTERNS = [
        (r"\brm\s+-[rRf]", "rm 带 -r/-f 参数"),
        (r"\brm\s+--force", "rm --force"),
        (r"\brm\s+-\w*r\w*f", "rm -rf 组合"),
        (r"\bdd\s+", "dd 写磁盘"),
        (r"\bmkfs\b", "格式化磁盘"),
        (r">\s*/etc/", "重写系统配置"),
        (r">\s*/boot/", "写引导分区"),
        (r"\bchmod\s+777\s+/", "全局 777 权限"),
        (r"\bkill\s+-9\s+1\b", "kill init 进程"),
        (r":\(\)\{\s*:\|:\s*&\s*\};:", "fork bomb"),
        (r"\bshred\b", "安全删除工具"),
        (r"\bwipe\b", "磁盘擦除"),
        (r"\bfdisk\b", "分区操作"),
        (r"\bparted\b", "分区操作"),
        (r"\biptables\s+-F", "清空防火墙规则"),
        (r"\bufw\s+disable", "关闭防火墙"),
        (r"\bpasswd\b", "修改密码"),
        (r"\buseradd\b", "添加用户"),
        (r"\buserdel\b", "删除用户"),
        (r"\bvisudo\b", "修改 sudoers"),
        (r"\bcurl\b.*\|\s*(ba)?sh", "curl pipe to shell"),
        (r"\bwget\b.*\|\s*(ba)?sh", "wget pipe to shell"),
        (r">\s*/dev/[sh]d", "写裸设备"),
        (r"\bsystemctl\s+(disable|mask)\s+(sshd|networking|network)", "禁用关键服务"),
    ]

    # ─── 灰名单：需要确认 ─────────────────────────────────────
    WRITE_PATTERNS = [
        (r"\bsystemctl\s+(restart|stop|start|reload)\s+", "服务操作"),
        (r"\bdocker\s+(stop|rm|kill|restart)\s+", "Docker 容器操作"),
        (r"\bkubectl\s+(delete|apply|patch|scale)\s+", "K8s 写操作"),
        (r"\bapt-get\s+(install|remove|purge)", "包管理安装/删除"),
        (r"\byum\s+(install|remove|erase)", "包管理安装/删除"),
        (r"\bpip\s+install\b", "pip 安装"),
        (r"\bnpm\s+install\b", "npm 安装"),
        (r"\bkill\s+", "终止进程"),
        (r"\bpkill\s+", "按名称终止进程"),
        (r"\bmv\s+/", "移动系统文件"),
        (r"\bcp\s+.*\s+/etc/", "覆盖配置文件"),
        (r"\btee\s+/etc/", "写入配置文件"),
    ]

    # ─── 破坏性操作：需强制确认 ───────────────────────────────
    DESTRUCTIVE_PATTERNS = [
        (r"\bdocker\s+(system\s+)?prune", "Docker 清理"),
        (r"\bapt-get\s+(clean|autoremove)", "包清理"),
        (r"\byum\s+clean\s+", "Yum 清理"),
        (r"\bjournalctl\s+--vacuum", "日志清理"),
        (r"\btruncate\b", "截断文件"),
        (r"\bfind\s+.*-delete", "批量删除文件"),
        (r"\bfind\s+.*-exec\s+rm", "find + rm"),
        (r"\blogrotate\s+-f", "强制日志轮转"),
    ]

    # ─── 白名单：安全的只读命令前缀 ──────────────────────────
    SAFE_PREFIXES = [
        "ps", "top", "htop", "df", "du", "free", "uptime", "w", "who",
        "cat", "head", "tail", "less", "more", "wc",
        "ls", "ll", "find", "locate", "which", "whereis", "file", "stat",
        "grep", "awk", "sed", "sort", "uniq", "cut", "tr",
        "netstat", "ss", "ip", "ifconfig", "route", "arp",
        "ping", "traceroute", "tracepath", "dig", "nslookup", "host",
        "curl", "wget",  # 不带 pipe to shell 时安全
        "systemctl status", "systemctl is-active", "systemctl is-enabled",
        "journalctl", "dmesg",
        "docker ps", "docker images", "docker inspect", "docker logs", "docker stats",
        "kubectl get", "kubectl describe", "kubectl logs", "kubectl top",
        "lsof", "fuser", "strace", "ltrace",
        "uname", "hostname", "date", "timedatectl",
        "id", "groups", "last", "lastlog", "history",
        "mount", "lsblk", "blkid", "fdisk -l",
        "crontab -l", "at -l",
        "env", "printenv", "echo",
        "python --version", "python3 --version", "pip list", "pip show",
        "mysql -e", "mysqladmin",
        "redis-cli info", "redis-cli ping",
        "nginx -t", "nginx -T",
    ]

    @classmethod
    def check(cls, command: str) -> SafetyVerdict:
        """检查命令安全等级

        Args:
            command: 要检查的 shell 命令

        Returns:
            SafetyVerdict 安全审查结论
        """
        command = command.strip()

        if not command:
            return SafetyVerdict(
                level=SafetyLevel.READ_ONLY,
                allowed=True,
                reason="空命令",
                command=command,
            )

        # 1. 黑名单检查（绝对拒绝）
        for pattern, desc in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return SafetyVerdict(
                    level=SafetyLevel.DANGEROUS,
                    allowed=False,
                    reason=f"高危操作: {desc}",
                    command=command,
                )

        # 2. 破坏性检查
        for pattern, desc in cls.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return SafetyVerdict(
                    level=SafetyLevel.DESTRUCTIVE,
                    allowed=False,
                    reason=f"破坏性操作: {desc}",
                    command=command,
                    requires_confirmation=True,
                )

        # 3. 写操作检查
        for pattern, desc in cls.WRITE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return SafetyVerdict(
                    level=SafetyLevel.WRITE,
                    allowed=False,
                    reason=f"写操作: {desc}",
                    command=command,
                    requires_confirmation=True,
                )

        # 4. 白名单检查
        cmd_lower = command.lower().strip()
        for prefix in cls.SAFE_PREFIXES:
            if cmd_lower.startswith(prefix):
                return SafetyVerdict(
                    level=SafetyLevel.READ_ONLY,
                    allowed=True,
                    reason=f"白名单命令: {prefix}",
                    command=command,
                )

        # 5. 默认：未识别的命令 → 需要确认
        return SafetyVerdict(
            level=SafetyLevel.WRITE,
            allowed=False,
            reason="未识别的命令，默认需要确认",
            command=command,
            requires_confirmation=True,
        )

    @classmethod
    def batch_check(cls, commands: List[str]) -> List[SafetyVerdict]:
        """批量检查命令安全性"""
        return [cls.check(cmd) for cmd in commands]

    @classmethod
    def format_verdict(cls, verdict: SafetyVerdict) -> str:
        """格式化安全审查结论"""
        icons = {
            SafetyLevel.READ_ONLY: "🟢",
            SafetyLevel.WRITE: "🟡",
            SafetyLevel.DESTRUCTIVE: "🟠",
            SafetyLevel.DANGEROUS: "🔴",
        }
        icon = icons.get(verdict.level, "⚪")
        status = "允许" if verdict.allowed else ("需确认" if verdict.requires_confirmation else "拒绝")
        return f"{icon} [{verdict.level.value}] {status} | {verdict.reason}\n   命令: {verdict.command}"


# ─── 工具权限分级表 ─────────────────────────────────────────────

TOOL_PERMISSIONS = {
    # 只读工具 — 直接执行
    "inspect_server": SafetyLevel.READ_ONLY,
    "get_top_processes": SafetyLevel.READ_ONLY,
    "query_system_logs": SafetyLevel.READ_ONLY,
    "read_log_file": SafetyLevel.READ_ONLY,
    "ping_host": SafetyLevel.READ_ONLY,
    "check_port": SafetyLevel.READ_ONLY,
    "dns_lookup": SafetyLevel.READ_ONLY,
    "k8s_cluster_inspect": SafetyLevel.READ_ONLY,
    "k8s_pod_logs": SafetyLevel.READ_ONLY,
    "docker_list_containers": SafetyLevel.READ_ONLY,
    "docker_container_logs": SafetyLevel.READ_ONLY,
    "scan_ports": SafetyLevel.READ_ONLY,
    "check_ssl_cert": SafetyLevel.READ_ONLY,
    "inspect_remote_server": SafetyLevel.READ_ONLY,

    # 写操作工具 — 需确认
    "k8s_scale_deployment": SafetyLevel.WRITE,
    "k8s_restart_deployment": SafetyLevel.WRITE,
    "manage_systemd_service": SafetyLevel.WRITE,

    # 需额外审查
    "execute_shell_command": SafetyLevel.WRITE,  # 内部有自己的安全检查
}


def get_tool_permission(tool_name: str) -> SafetyLevel:
    """获取工具权限等级"""
    return TOOL_PERMISSIONS.get(tool_name, SafetyLevel.WRITE)


def is_tool_auto_allowed(tool_name: str) -> bool:
    """工具是否可以自动执行（无需确认）"""
    return get_tool_permission(tool_name) == SafetyLevel.READ_ONLY
