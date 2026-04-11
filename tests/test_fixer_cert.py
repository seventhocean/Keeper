"""自动修复和证书监控测试"""
import unittest
from keeper.tools.fixer import FixSuggester, SafetyLevel, FixPlan, FixSuggestion
from keeper.tools.cert_monitor import CertMonitor, CertInfo, format_cert_report


class TestFixSuggester(unittest.TestCase):
    """修复建议引擎测试"""

    def test_generate_disk_fixes(self):
        """磁盘使用率高时生成修复建议"""
        data = {
            "disk_percent": 92,
            "memory_percent": 50,
            "swap_percent": 10,
            "load_avg": {"1m": 0.5},
            "load_per_cpu": 0.5,
            "network": {"errin": 0, "errout": 0},
        }
        fixes = FixSuggester.generate_rule_based_fixes(data)
        self.assertGreaterEqual(len(fixes), 1)
        self.assertTrue(any("清理" in f.title for f in fixes))
        # 清理类命令应为 DESTRUCTIVE 级别
        self.assertTrue(
            any(f.safety == SafetyLevel.DESTRUCTIVE for f in fixes),
            "清理命令应标记为 DESTRUCTIVE 级别"
        )

    def test_generate_memory_fixes(self):
        """内存不足时生成修复建议"""
        data = {
            "disk_percent": 50,
            "memory_percent": 90,
            "swap_percent": 60,
            "cpu_percent": 30,
            "load_avg": {"1m": 0.5},
            "load_per_cpu": 0.5,
            "top_memory_processes": [{"name": "java", "memory_percent": 40}],
            "network": {"errin": 0, "errout": 0},
        }
        fixes = FixSuggester.generate_rule_based_fixes(data)
        self.assertTrue(any("内存" in f.title or "Swap" in f.title for f in fixes))

    def test_generate_oom_fix(self):
        """OOM 日志生成修复建议"""
        data = {
            "disk_percent": 50,
            "memory_percent": 70,
            "swap_percent": 10,
            "load_avg": {"1m": 0.5},
            "load_per_cpu": 0.5,
            "error_logs": "Out of memory: Killed process 1234",
            "network": {"errin": 0, "errout": 0},
        }
        fixes = FixSuggester.generate_rule_based_fixes(data)
        self.assertTrue(any("OOM" in f.title for f in fixes))

    def test_generate_ssh_bruteforce_fix(self):
        """SSH 暴力破解生成修复建议"""
        data = {
            "disk_percent": 50,
            "memory_percent": 50,
            "swap_percent": 10,
            "load_avg": {"1m": 0.5},
            "load_per_cpu": 0.5,
            "error_logs": "Failed password for root from 10.0.0.1",
            "network": {"errin": 0, "errout": 0},
        }
        fixes = FixSuggester.generate_rule_based_fixes(data)
        self.assertTrue(any("SSH" in f.title for f in fixes))

    def test_no_fixes_when_healthy(self):
        """服务器健康时不生成修复建议"""
        data = {
            "disk_percent": 40,
            "memory_percent": 30,
            "swap_percent": 5,
            "cpu_percent": 20,
            "load_avg": {"1m": 0.3},
            "load_per_cpu": 0.3,
            "network": {"errin": 0, "errout": 0},
        }
        fixes = FixSuggester.generate_rule_based_fixes(data)
        self.assertEqual(len(fixes), 0)

    def test_dangerous_command_blacklist(self):
        """危险命令被绝对拒绝"""
        dangerous = [
            "rm -rf /",
            "rm -rf /tmp",
            "rm -rf *",
            "rm -r /var/log",
            "rm -f /tmp/test.log",
            "rm file.txt",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "echo xxx > /etc/passwd",
            "chmod 777 /",
            "kill -9 1",
            "shred -vfz -n 5 /etc/shadow",
            "wipe /var/log",
        ]
        for cmd in dangerous:
            valid, _ = FixSuggester.validate_command(cmd)
            self.assertFalse(valid, f"危险命令未被拦截: {cmd}")

    def test_rm_variants_all_blocked(self):
        """rm 命令所有常见变体都被拦截"""
        rm_variants = [
            "rm -rf /",
            "rm -rf /var/log/*",
            "rm -f /tmp/a.log",
            "rm -r /opt/data",
            "rm --force /etc/config",
            "rm -rf *",
            "rm /important/file",
        ]
        for cmd in rm_variants:
            valid, msg = FixSuggester.validate_command(cmd)
            self.assertFalse(valid, f"rm 命令未被拦截: {cmd}")

    def test_needs_confirmation(self):
        """破坏性命令需要二次确认"""
        destructive = [
            "docker system prune -f",
            "docker image prune -a",
            "apt-get clean",
            "apt-get autoremove",
            "journalctl --vacuum-size=100M",
            "truncate -s 0 /var/log/syslog",
        ]
        for cmd in destructive:
            needs = FixSuggester.needs_confirmation(cmd)
            self.assertTrue(needs, f"应需要确认: {cmd}")

    def test_safe_commands_no_confirmation(self):
        """安全命令不需要二次确认"""
        safe = [
            "systemctl restart nginx",
            "journalctl -u sshd",
            "free -h",
            "ps aux --sort=-%cpu",
            "dmesg -T | grep -i oom",
        ]
        for cmd in safe:
            needs = FixSuggester.needs_confirmation(cmd)
            self.assertFalse(needs, f"不应需要确认: {cmd}")

    def test_dangerous_does_not_need_confirmation(self):
        """黑名单命令不需要确认（因为直接拒绝）"""
        needs = FixSuggester.needs_confirmation("rm -rf /")
        self.assertFalse(needs)

    def test_safe_command_allowed(self):
        """安全命令被放行"""
        safe = [
            "journalctl --vacuum-size=100M",
            "systemctl restart nginx",
            "docker system prune -f",
            "free -h",
        ]
        for cmd in safe:
            valid, _ = FixSuggester.validate_command(cmd)
            self.assertTrue(valid, f"安全命令被拒绝: {cmd}")

    def test_command_too_long(self):
        """超长命令被拒绝"""
        cmd = "echo " + "x" * 600
        valid, _ = FixSuggester.validate_command(cmd)
        self.assertFalse(valid)

    def test_too_many_pipes(self):
        """过多管道符被拒绝"""
        valid, _ = FixSuggester.validate_command("cat a | grep b | sort | uniq | head | tail | wc")
        self.assertFalse(valid)

    def test_fix_plan_format(self):
        """修复计划格式化"""
        fixes = [
            FixSuggestion(
                title="测试修复",
                description="磁盘使用率高",
                command="journalctl --vacuum-size=100M",
                safety=SafetyLevel.CAUTION,
                expected_result="释放磁盘空间",
                rollback="无需回滚",
            ),
        ]
        plan = FixPlan(
            summary="测试",
            diagnosis="磁盘满",
            suggestions=fixes,
            llm_advice="",
        )
        output = FixSuggester.format_fix_plan(plan)
        self.assertIn("测试修复", output)
        self.assertIn("磁盘使用率高", output)

    def test_verify_fix_improved(self):
        """修复效果验证 - 改善"""
        before = {"disk_percent": 92}
        after = {"disk_percent": 80}
        improved, msg = FixSuggester.verify_fix(before, after, "disk")
        self.assertTrue(improved)
        self.assertIn("改善", msg)

    def test_verify_fix_worse(self):
        """修复效果验证 - 恶化"""
        before = {"disk_percent": 80}
        after = {"disk_percent": 95}
        improved, msg = FixSuggester.verify_fix(before, after, "disk")
        self.assertFalse(improved)
        self.assertIn("恶化", msg)

    def test_verify_load_avg(self):
        """修复效果验证 - 负载指标"""
        before = {"load_avg": {"1m": 5.0}}
        after = {"load_avg": {"1m": 2.0}}
        improved, msg = FixSuggester.verify_fix(before, after, "load")
        self.assertTrue(improved)


class TestCertMonitor(unittest.TestCase):
    """证书监控测试"""

    def test_cert_info_dataclass(self):
        """CertInfo 数据结构"""
        cert = CertInfo(
            path="/test/cert.pem",
            source="file",
            subject="CN=test.com",
            issuer="CA",
            not_before="2025-01-01",
            not_after="2026-12-01",
            days_left=200,
            status="valid",
            domains=["test.com"],
        )
        self.assertEqual(cert.subject, "CN=test.com")
        self.assertEqual(cert.days_left, 200)

    def test_format_cert_report_empty(self):
        """空证书报告"""
        report = format_cert_report([], [], [])
        self.assertIn("未发现证书", report)

    def test_format_cert_report_with_valid(self):
        """包含有效证书的报告"""
        cert = CertInfo(
            path="/test/cert.pem", source="file", subject="CN=test.com",
            issuer="CA", not_before="2025-01-01", not_after="2026-12-01",
            days_left=200, status="valid", domains=["test.com"],
        )
        report = format_cert_report([cert], [], [])
        self.assertIn("正常", report)
        self.assertIn("/test/cert.pem", report)

    def test_format_cert_report_with_expired(self):
        """包含过期证书的报告"""
        expired_cert = CertInfo(
            path="/test/expired.pem", source="file", subject="CN=expired.com",
            issuer="CA", not_before="2020-01-01", not_after="2024-01-01",
            days_left=-100, status="expired", domains=["expired.com"],
        )
        valid_cert = CertInfo(
            path="/test/valid.pem", source="file", subject="CN=valid.com",
            issuer="CA", not_before="2025-01-01", not_after="2026-12-01",
            days_left=200, status="valid", domains=["valid.com"],
        )
        report = format_cert_report([expired_cert, valid_cert], [], [])
        self.assertIn("已过期", report)
        self.assertIn("问题证书", report)
        self.assertIn("expired.com", report)

    def test_format_cert_report_sorted_by_status(self):
        """问题证书排在前面"""
        expired = CertInfo(
            path="/expired.pem", source="file", subject="S", issuer="I",
            not_before="2020-01-01", not_after="2024-01-01",
            days_left=-100, status="expired", domains=[],
        )
        valid = CertInfo(
            path="/valid.pem", source="file", subject="S", issuer="I",
            not_before="2025-01-01", not_after="2026-12-01",
            days_left=200, status="valid", domains=[],
        )
        report = format_cert_report([valid, expired], [], [])
        # 问题证书部分应该在正常证书部分之前
        problem_pos = report.index("问题证书")
        normal_pos = report.index("正常证书")
        self.assertLess(problem_pos, normal_pos)
        self.assertIn("/expired.pem", report)
        self.assertIn("/valid.pem", report)
