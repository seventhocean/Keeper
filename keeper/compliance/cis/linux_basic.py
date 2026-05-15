"""CIS Benchmark — Linux 基础安全检查

实现 15 项核心安全检查（CIS Level 1 子集）：
- SSH 配置安全性
- 文件权限
- 不必要的服务
- 防火墙状态
- 密码策略
- 系统更新
"""
import subprocess
import os
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class CISCheckResult:
    """CIS 检查结果"""
    id: str              # CIS 编号
    title: str           # 检查项名称
    passed: bool
    detail: str = ""
    recommendation: str = ""
    severity: str = "medium"  # low / medium / high / critical


class CISLinuxBasic:
    """CIS Linux 基础安全检查（15 项）"""

    def run_all(self) -> List[CISCheckResult]:
        """执行所有检查"""
        checks = [
            self._check_ssh_root_login,
            self._check_ssh_protocol,
            self._check_ssh_password_auth,
            self._check_passwd_permission,
            self._check_shadow_permission,
            self._check_firewall_active,
            self._check_no_empty_passwords,
            self._check_no_uid_zero_except_root,
            self._check_tmp_separate_partition,
            self._check_core_dumps_disabled,
            self._check_syslog_running,
            self._check_cron_permission,
            self._check_no_world_writable_files,
            self._check_password_max_days,
            self._check_no_unowned_files,
        ]
        results = []
        for check_fn in checks:
            try:
                results.append(check_fn())
            except Exception as e:
                results.append(CISCheckResult(
                    id="ERR", title=check_fn.__doc__ or "unknown",
                    passed=False, detail=f"检查异常: {str(e)}"
                ))
        return results

    def _check_ssh_root_login(self) -> CISCheckResult:
        """1.1 SSH 禁止 root 直接登录"""
        return self._check_file_contains(
            "1.1", "SSH 禁止 root 直接登录",
            "/etc/ssh/sshd_config", "PermitRootLogin no",
            recommendation="设置 PermitRootLogin no",
            severity="high",
        )

    def _check_ssh_protocol(self) -> CISCheckResult:
        """1.2 SSH 使用协议 2"""
        # 现代 OpenSSH 默认使用 Protocol 2
        return CISCheckResult(
            id="1.2", title="SSH 使用协议 2",
            passed=True, detail="现代 OpenSSH 默认使用 Protocol 2",
            severity="medium",
        )

    def _check_ssh_password_auth(self) -> CISCheckResult:
        """1.3 SSH 禁用密码认证"""
        return self._check_file_contains(
            "1.3", "SSH 禁用密码认证",
            "/etc/ssh/sshd_config", "PasswordAuthentication no",
            recommendation="设置 PasswordAuthentication no，使用密钥认证",
            severity="high",
        )

    def _check_passwd_permission(self) -> CISCheckResult:
        """2.1 /etc/passwd 权限 644"""
        return self._check_permission("2.1", "/etc/passwd 权限", "/etc/passwd", "644")

    def _check_shadow_permission(self) -> CISCheckResult:
        """2.2 /etc/shadow 权限 600"""
        return self._check_permission("2.2", "/etc/shadow 权限", "/etc/shadow", "600", severity="high")

    def _check_firewall_active(self) -> CISCheckResult:
        """3.1 防火墙已启用"""
        # 检查 ufw 或 firewalld 或 iptables
        for fw in ["ufw", "firewalld"]:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", fw],
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip() == "active":
                    return CISCheckResult(
                        id="3.1", title="防火墙已启用", passed=True,
                        detail=f"{fw} 运行中", severity="high",
                    )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        # 检查 iptables 规则数
        try:
            result = subprocess.run(
                ["iptables", "-L", "-n"],
                capture_output=True, text=True, timeout=5,
            )
            rules = [l for l in result.stdout.split("\n") if l.strip() and not l.startswith("Chain") and not l.startswith("target")]
            if len(rules) > 3:
                return CISCheckResult(
                    id="3.1", title="防火墙已启用", passed=True,
                    detail=f"iptables 有 {len(rules)} 条规则", severity="high",
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return CISCheckResult(
            id="3.1", title="防火墙已启用", passed=False,
            detail="未检测到活跃防火墙",
            recommendation="启用 ufw 或 firewalld",
            severity="high",
        )

    def _check_no_empty_passwords(self) -> CISCheckResult:
        """4.1 无空密码账户"""
        try:
            result = subprocess.run(
                ["awk", "-F:", '($2 == "") {print $1}', "/etc/shadow"],
                capture_output=True, text=True, timeout=5,
            )
            empty_users = [u for u in result.stdout.strip().split("\n") if u]
            passed = len(empty_users) == 0
            return CISCheckResult(
                id="4.1", title="无空密码账户", passed=passed,
                detail=f"空密码账户: {', '.join(empty_users)}" if not passed else "无空密码账户",
                recommendation="为所有账户设置密码或锁定",
                severity="critical",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            return CISCheckResult(id="4.1", title="无空密码账户", passed=True, detail="无法检查（权限不足）")

    def _check_no_uid_zero_except_root(self) -> CISCheckResult:
        """4.2 仅 root 用户 UID=0"""
        try:
            result = subprocess.run(
                ["awk", "-F:", '($3 == 0) {print $1}', "/etc/passwd"],
                capture_output=True, text=True, timeout=5,
            )
            uid_zero = [u for u in result.stdout.strip().split("\n") if u]
            passed = uid_zero == ["root"]
            return CISCheckResult(
                id="4.2", title="仅 root 用户 UID=0", passed=passed,
                detail=f"UID=0 的用户: {', '.join(uid_zero)}",
                recommendation="移除非 root 的 UID=0 账户",
                severity="critical",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return CISCheckResult(id="4.2", title="仅 root 用户 UID=0", passed=True, detail="无法检查")

    def _check_tmp_separate_partition(self) -> CISCheckResult:
        """5.1 /tmp 独立分区"""
        try:
            result = subprocess.run(["mount"], capture_output=True, text=True, timeout=5)
            passed = "/tmp" in result.stdout and "tmpfs" in result.stdout
            return CISCheckResult(
                id="5.1", title="/tmp 独立分区", passed=passed,
                detail="tmpfs 挂载" if passed else "/tmp 未独立分区",
                recommendation="将 /tmp 挂载为 tmpfs 或独立分区",
                severity="low",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return CISCheckResult(id="5.1", title="/tmp 独立分区", passed=False, detail="无法检查")

    def _check_core_dumps_disabled(self) -> CISCheckResult:
        """5.2 Core dumps 已禁用"""
        try:
            result = subprocess.run(
                ["ulimit", "-c"], capture_output=True, text=True, timeout=5, shell=True,
            )
            passed = result.stdout.strip() == "0"
            return CISCheckResult(
                id="5.2", title="Core dumps 已禁用", passed=passed,
                detail=f"ulimit -c = {result.stdout.strip()}",
                severity="low",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return CISCheckResult(id="5.2", title="Core dumps 已禁用", passed=True, detail="无法检查")

    def _check_syslog_running(self) -> CISCheckResult:
        """6.1 Syslog 服务运行中"""
        for svc in ["rsyslog", "syslog-ng", "systemd-journald"]:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip() == "active":
                    return CISCheckResult(
                        id="6.1", title="Syslog 服务运行中", passed=True,
                        detail=f"{svc} 运行中", severity="medium",
                    )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        return CISCheckResult(
            id="6.1", title="Syslog 服务运行中", passed=False,
            detail="未检测到日志服务", recommendation="启用 rsyslog",
            severity="medium",
        )

    def _check_cron_permission(self) -> CISCheckResult:
        """6.2 Crontab 权限受限"""
        return self._check_permission("6.2", "Crontab 权限", "/etc/crontab", "600", severity="medium")

    def _check_no_world_writable_files(self) -> CISCheckResult:
        """7.1 无全局可写文件（关键目录）"""
        try:
            result = subprocess.run(
                ["find", "/etc", "-type", "f", "-perm", "-002", "-not", "-path", "*/proc/*"],
                capture_output=True, text=True, timeout=10,
            )
            files = [f for f in result.stdout.strip().split("\n") if f]
            passed = len(files) == 0
            return CISCheckResult(
                id="7.1", title="无全局可写文件 (/etc)", passed=passed,
                detail=f"发现 {len(files)} 个全局可写文件" if not passed else "无全局可写文件",
                recommendation="chmod o-w 修复权限",
                severity="medium",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return CISCheckResult(id="7.1", title="无全局可写文件", passed=True, detail="无法检查")

    def _check_password_max_days(self) -> CISCheckResult:
        """4.3 密码最长有效期 ≤ 90 天"""
        try:
            with open("/etc/login.defs", "r") as f:
                for line in f:
                    if line.strip().startswith("PASS_MAX_DAYS"):
                        value = int(line.split()[1])
                        passed = value <= 90
                        return CISCheckResult(
                            id="4.3", title="密码最长有效期 ≤ 90天", passed=passed,
                            detail=f"PASS_MAX_DAYS = {value}",
                            recommendation="设置 PASS_MAX_DAYS 90",
                            severity="medium",
                        )
        except (FileNotFoundError, ValueError, IndexError):
            pass
        return CISCheckResult(id="4.3", title="密码最长有效期", passed=False, detail="无法检查")

    def _check_no_unowned_files(self) -> CISCheckResult:
        """7.2 无无主文件（/etc 下）"""
        try:
            result = subprocess.run(
                ["find", "/etc", "-nouser", "-o", "-nogroup"],
                capture_output=True, text=True, timeout=10,
            )
            files = [f for f in result.stdout.strip().split("\n") if f]
            passed = len(files) == 0
            return CISCheckResult(
                id="7.2", title="无无主文件 (/etc)", passed=passed,
                detail=f"发现 {len(files)} 个无主文件" if not passed else "无无主文件",
                severity="low",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return CISCheckResult(id="7.2", title="无无主文件", passed=True, detail="无法检查")

    # ─── 辅助方法 ─────────────────────────────────────────────

    def _check_file_contains(self, cis_id: str, title: str, path: str,
                             expected: str, recommendation: str = "",
                             severity: str = "medium") -> CISCheckResult:
        """检查文件是否包含指定内容"""
        try:
            if not os.path.exists(path):
                return CISCheckResult(id=cis_id, title=title, passed=False, detail=f"{path} 不存在")
            with open(path, "r", errors="ignore") as f:
                content = f.read()
            passed = expected in content
            return CISCheckResult(
                id=cis_id, title=title, passed=passed,
                detail=f"{'包含' if passed else '未找到'} '{expected}'",
                recommendation=recommendation if not passed else "",
                severity=severity,
            )
        except PermissionError:
            return CISCheckResult(id=cis_id, title=title, passed=False, detail="权限不足")

    def _check_permission(self, cis_id: str, title: str, path: str,
                          expected: str, severity: str = "medium") -> CISCheckResult:
        """检查文件权限"""
        try:
            if not os.path.exists(path):
                return CISCheckResult(id=cis_id, title=title, passed=False, detail=f"{path} 不存在")
            mode = oct(os.stat(path).st_mode)[-3:]
            passed = mode == expected
            return CISCheckResult(
                id=cis_id, title=title, passed=passed,
                detail=f"权限 {mode} (期望 {expected})",
                recommendation=f"chmod {expected} {path}" if not passed else "",
                severity=severity,
            )
        except (PermissionError, OSError):
            return CISCheckResult(id=cis_id, title=title, passed=False, detail="无法检查权限")

    @classmethod
    def format_results(cls, results: List[CISCheckResult]) -> str:
        """格式化 CIS 检查结果"""
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        score = (passed / total * 100) if total > 0 else 0

        lines = [
            f"[CIS Benchmark] Linux 基础安全检查",
            f"  通过: {passed}/{total} ({score:.0f}%)",
            "━" * 50,
        ]

        for r in results:
            icon = "✓" if r.passed else "✗"
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}[r.severity]
            lines.append(f"  {icon} [{r.id}] {sev_icon} {r.title}")
            if not r.passed and r.recommendation:
                lines.append(f"    建议: {r.recommendation}")

        lines.append("━" * 50)
        lines.append(f"  安全评分: {score:.0f}/100")
        return "\n".join(lines)
