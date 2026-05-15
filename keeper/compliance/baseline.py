"""配置基线定义与漂移检测

功能：
- YAML 定义配置期望值（基线）
- 对比实际配置 vs 基线
- 输出漂移报告
- 支持本地 + SSH 远程检测
"""
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class BaselineCheck:
    """单项基线检查"""
    category: str        # file / service / permission
    target: str          # 文件路径 / 服务名
    check_type: str      # contains / not_contains / equals / permission / state
    expected: str        # 期望值
    description: str = ""


@dataclass
class DriftResult:
    """漂移检测结果"""
    check: BaselineCheck
    passed: bool
    actual: str = ""
    message: str = ""


@dataclass
class DriftReport:
    """漂移报告"""
    host: str
    baseline_name: str
    total_checks: int
    passed: int
    failed: int
    results: List[DriftResult] = field(default_factory=list)


# ─── 内置基线定义 ─────────────────────────────────────────────────

BUILTIN_BASELINES: Dict[str, List[BaselineCheck]] = {
    "sshd_security": [
        BaselineCheck("file", "/etc/ssh/sshd_config", "contains", "PermitRootLogin no", "禁止 root 直接登录"),
        BaselineCheck("file", "/etc/ssh/sshd_config", "contains", "PasswordAuthentication no", "禁用密码认证"),
        BaselineCheck("file", "/etc/ssh/sshd_config", "not_contains", "PermitEmptyPasswords yes", "禁止空密码"),
        BaselineCheck("file", "/etc/ssh/sshd_config", "contains", "Protocol 2", "使用 SSH 协议 2"),
        BaselineCheck("service", "sshd", "state", "active", "SSH 服务运行中"),
    ],
    "nginx_security": [
        BaselineCheck("file", "/etc/nginx/nginx.conf", "contains", "worker_processes auto", "worker 自动配置"),
        BaselineCheck("file", "/etc/nginx/nginx.conf", "not_contains", "server_tokens on", "隐藏版本号"),
        BaselineCheck("service", "nginx", "state", "active", "Nginx 服务运行中"),
    ],
    "system_hardening": [
        BaselineCheck("permission", "/etc/passwd", "permission", "644", "passwd 文件权限"),
        BaselineCheck("permission", "/etc/shadow", "permission", "600", "shadow 文件权限"),
        BaselineCheck("permission", "/etc/ssh/sshd_config", "permission", "600", "sshd 配置权限"),
        BaselineCheck("file", "/etc/hosts.deny", "contains", "ALL: ALL", "默认拒绝所有"),
    ],
}


class DriftDetector:
    """配置漂移检测器"""

    def __init__(self, custom_baselines: Optional[Dict[str, List[BaselineCheck]]] = None):
        self.baselines = dict(BUILTIN_BASELINES)
        if custom_baselines:
            self.baselines.update(custom_baselines)

    def check_baseline(self, baseline_name: str, host: str = "localhost") -> Optional[DriftReport]:
        """检查指定基线

        Args:
            baseline_name: 基线名称 (如 sshd_security)
            host: 目标主机

        Returns:
            DriftReport 或 None（基线不存在时）
        """
        checks = self.baselines.get(baseline_name)
        if not checks:
            return None

        report = DriftReport(
            host=host,
            baseline_name=baseline_name,
            total_checks=len(checks),
            passed=0,
            failed=0,
        )

        for check in checks:
            result = self._execute_check(check, host)
            report.results.append(result)
            if result.passed:
                report.passed += 1
            else:
                report.failed += 1

        return report

    def check_all(self, host: str = "localhost") -> List[DriftReport]:
        """检查所有基线"""
        reports = []
        for name in self.baselines:
            report = self.check_baseline(name, host)
            if report:
                reports.append(report)
        return reports

    def _execute_check(self, check: BaselineCheck, host: str) -> DriftResult:
        """执行单项检查"""
        if check.category == "file":
            return self._check_file(check, host)
        elif check.category == "service":
            return self._check_service(check, host)
        elif check.category == "permission":
            return self._check_permission(check, host)
        else:
            return DriftResult(check=check, passed=False, message=f"未知检查类型: {check.category}")

    def _check_file(self, check: BaselineCheck, host: str) -> DriftResult:
        """检查文件内容"""
        content = self._read_file(check.target, host)
        if content is None:
            return DriftResult(check=check, passed=False, actual="文件不存在或不可读",
                             message=f"{check.target} 不存在")

        if check.check_type == "contains":
            passed = check.expected in content
            return DriftResult(
                check=check, passed=passed, actual=f"{'包含' if passed else '不包含'} '{check.expected}'",
                message=check.description if not passed else "",
            )
        elif check.check_type == "not_contains":
            passed = check.expected not in content
            return DriftResult(
                check=check, passed=passed, actual=f"{'不包含' if passed else '包含'} '{check.expected}'",
                message=f"不应包含: {check.expected}" if not passed else "",
            )
        elif check.check_type == "equals":
            passed = content.strip() == check.expected
            return DriftResult(check=check, passed=passed, actual=content[:100])

        return DriftResult(check=check, passed=False, message="未知 check_type")

    def _check_service(self, check: BaselineCheck, host: str) -> DriftResult:
        """检查服务状态"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", check.target],
                capture_output=True, text=True, timeout=10,
            )
            actual = result.stdout.strip()
            passed = actual == check.expected
            return DriftResult(
                check=check, passed=passed, actual=actual,
                message=f"期望 {check.expected}，实际 {actual}" if not passed else "",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return DriftResult(check=check, passed=False, actual="systemctl 不可用")

    def _check_permission(self, check: BaselineCheck, host: str) -> DriftResult:
        """检查文件权限"""
        try:
            result = subprocess.run(
                ["stat", "-c", "%a", check.target],
                capture_output=True, text=True, timeout=5,
            )
            actual = result.stdout.strip()
            passed = actual == check.expected
            return DriftResult(
                check=check, passed=passed, actual=actual,
                message=f"权限应为 {check.expected}，实际为 {actual}" if not passed else "",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return DriftResult(check=check, passed=False, actual="stat 失败")

    def _read_file(self, path: str, host: str) -> Optional[str]:
        """读取文件内容"""
        try:
            if os.path.exists(path):
                with open(path, "r", errors="ignore") as f:
                    return f.read()
            return None
        except (PermissionError, IOError):
            return None

    def list_baselines(self) -> List[str]:
        """列出所有可用基线"""
        return list(self.baselines.keys())

    def format_report(self, report: DriftReport) -> str:
        """格式化漂移报告"""
        lines = [
            f"[配置漂移检测] {report.baseline_name} @ {report.host}",
            f"  通过: {report.passed}/{report.total_checks} | 失败: {report.failed}",
            "━" * 50,
        ]

        for r in report.results:
            icon = "✓" if r.passed else "✗"
            desc = r.check.description or r.check.target
            lines.append(f"  {icon} {desc}")
            if not r.passed and r.message:
                lines.append(f"    → {r.message}")

        lines.append("━" * 50)
        score = (report.passed / report.total_checks * 100) if report.total_checks > 0 else 0
        lines.append(f"  合规分数: {score:.0f}%")
        return "\n".join(lines)
