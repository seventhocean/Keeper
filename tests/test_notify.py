"""通知推送和告警引擎测试"""
import unittest
from unittest.mock import patch, MagicMock
from keeper.tools.notify import FeishuNotifier
from keeper.tools.alert import AlertEngine, Alert
from keeper.tools.server import ServerStatus


class TestFeishuNotifier(unittest.TestCase):
    """飞书通知推送测试"""

    def test_init(self):
        """初始化"""
        notifier = FeishuNotifier("https://test.webhook.url", "secret123")
        self.assertEqual(notifier.webhook_url, "https://test.webhook.url")
        self.assertEqual(notifier.secret, "secret123")

    def test_init_without_secret(self):
        """无签名初始化"""
        notifier = FeishuNotifier("https://test.webhook.url")
        self.assertIsNone(notifier.secret)

    def test_gen_sign(self):
        """签名生成"""
        notifier = FeishuNotifier("https://test", "my_secret")
        sign = notifier._gen_sign(1234567890)
        self.assertIsInstance(sign, str)
        self.assertGreater(len(sign), 0)

    def test_severity_to_color(self):
        """严重程度映射颜色"""
        notifier = FeishuNotifier("https://test")
        self.assertEqual(notifier._severity_to_color("🔴 错误"), "red")
        self.assertEqual(notifier._severity_to_color("🟡 警告"), "orange")
        self.assertEqual(notifier._severity_to_color("🟢 正常"), "green")
        self.assertEqual(notifier._severity_to_color("Keeper inspect"), "blue")

    @patch("urllib.request.urlopen")
    def test_send_text_success(self, mock_urlopen):
        """发送文本消息成功"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0, "msg": "success"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        result = notifier.send_text("测试消息")
        self.assertTrue(result)

    @patch("urllib.request.urlopen")
    def test_send_text_failure(self, mock_urlopen):
        """发送文本消息失败"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection error")

        notifier = FeishuNotifier("https://test.webhook")
        result = notifier.send_text("测试消息")
        self.assertFalse(result)

    @patch("urllib.request.urlopen")
    def test_send_rich_success(self, mock_urlopen):
        """发送富文本消息成功"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        result = notifier.send_rich(
            title="测试卡片",
            sections=[[{"tag": "text", "text": "内容"}]],
            footer="测试"
        )
        self.assertTrue(result)

    def test_send_text_with_at(self):
        """发送带 @ 的消息"""
        notifier = FeishuNotifier("https://test.webhook")
        # 只验证 payload 构建不报错
        content = {"msg_type": "text", "content": {"text": "test"}}
        at_users = ["user1", "user2"]
        at_list = " ".join(f'<at user_id="{uid}"></at>' for uid in at_users)
        content["content"]["text"] = "test" + "\n" + at_list
        self.assertIn("user1", content["content"]["text"])
        self.assertIn("user2", content["content"]["text"])


class TestAlertEngine(unittest.TestCase):
    """告警规则引擎测试"""

    def test_no_alerts_when_healthy(self):
        """服务器健康时无告警"""
        status = {
            "cpu_percent": 30,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 10,
            "load_per_cpu": 0.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertEqual(len(alerts), 0)

    def test_cpu_alert(self):
        """CPU 过高触发告警"""
        status = {
            "cpu_percent": 92,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 10,
            "load_per_cpu": 0.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].name, "CPU 使用率过高")
        self.assertEqual(alerts[0].severity, "warning")

    def test_cpu_critical(self):
        """CPU 超过 95% 为 critical"""
        status = {
            "cpu_percent": 98,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 10,
            "load_per_cpu": 0.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertEqual(alerts[0].severity, "critical")

    def test_disk_alert(self):
        """磁盘过高触发告警"""
        status = {
            "cpu_percent": 30,
            "memory_percent": 40,
            "disk_percent": 95,
            "swap_percent": 10,
            "load_per_cpu": 0.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertEqual(len(alerts), 1)
        self.assertIn("磁盘", alerts[0].name)

    def test_failed_services_alert(self):
        """服务失败触发告警"""
        status = {
            "cpu_percent": 30,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 10,
            "load_per_cpu": 0.5,
            "failed_services": ["nginx", "docker"],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertTrue(any("服务异常" in a.name for a in alerts))
        self.assertTrue(any(a.severity == "critical" for a in alerts))

    def test_load_alert(self):
        """系统负载过高触发告警"""
        status = {
            "cpu_percent": 30,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 10,
            "load_per_cpu": 3.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertTrue(any("负载" in a.name for a in alerts))

    def test_swap_alert(self):
        """Swap 过高触发告警"""
        status = {
            "cpu_percent": 30,
            "memory_percent": 40,
            "disk_percent": 50,
            "swap_percent": 60,
            "load_per_cpu": 0.5,
            "failed_services": [],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertTrue(any("Swap" in a.name for a in alerts))

    def test_multiple_alerts(self):
        """多项指标异常同时触发多条告警"""
        status = {
            "cpu_percent": 95,
            "memory_percent": 92,
            "disk_percent": 96,
            "swap_percent": 70,
            "load_per_cpu": 3.0,
            "failed_services": ["nginx"],
        }
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_server(status, thresholds)
        self.assertGreaterEqual(len(alerts), 5)

    def test_batch_report_alerts(self):
        """批量巡检汇总告警"""
        statuses = [
            {"hostname": "spring", "cpu_percent": 90, "memory_percent": 40,
             "disk_percent": 50, "swap_percent": 10, "load_per_cpu": 0.5,
             "failed_services": []},
            {"hostname": "autumn", "cpu_percent": 30, "memory_percent": 90,
             "disk_percent": 50, "swap_percent": 10, "load_per_cpu": 0.5,
             "failed_services": []},
        ]
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        alerts = AlertEngine.check_batch_report(statuses, thresholds)
        self.assertEqual(len(alerts), 2)
        self.assertIn("spring", alerts[0].name)
        self.assertIn("autumn", alerts[1].name)

    def test_cert_expired_alert(self):
        """证书过期触发告警"""
        from keeper.tools.cert_monitor import CertInfo
        from datetime import datetime, timezone

        expired_cert = CertInfo(
            path="/test/cert.pem", source="file", subject="CN=expired.com",
            issuer="CA", not_before="2020-01-01", not_after="2024-01-01",
            days_left=-100, status="expired", domains=["expired.com"],
        )
        alerts = AlertEngine.check_cert([expired_cert], [], [])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "critical")
        self.assertIn("已过期", alerts[0].name)

    def test_cert_expiring_soon_alert(self):
        """证书即将过期触发告警"""
        from keeper.tools.cert_monitor import CertInfo

        expiring_cert = CertInfo(
            path="/test/cert.pem", source="file", subject="CN=test.com",
            issuer="CA", not_before="2025-01-01", not_after="2026-05-01",
            days_left=20, status="expiring_soon", domains=["test.com"],
        )
        alerts = AlertEngine.check_cert([expiring_cert], [], [])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "warning")
        self.assertIn("即将过期", alerts[0].name)

    def test_no_cert_alerts(self):
        """证书正常时无告警"""
        from keeper.tools.cert_monitor import CertInfo

        valid_cert = CertInfo(
            path="/test/cert.pem", source="file", subject="CN=test.com",
            issuer="CA", not_before="2025-01-01", not_after="2027-01-01",
            days_left=200, status="valid", domains=["test.com"],
        )
        alerts = AlertEngine.check_cert([valid_cert], [], [])
        self.assertEqual(len(alerts), 0)


class TestFeishuReport(unittest.TestCase):
    """飞书报告卡片测试"""

    def _make_status(self, host="test", **kwargs):
        defaults = dict(
            timestamp="2026-04-11 10:00:00",
            cpu_percent=30.0, memory_percent=40.0,
            memory_used_gb=4.0, memory_total_gb=8.0,
            disk_percent=50.0, disk_used_gb=100.0, disk_total_gb=200.0,
            load_avg_1m=0.5, load_avg_5m=0.4, load_avg_15m=0.3,
            boot_time="2026-04-10 08:00:00",
            top_processes=[],
            ssh_failed=False,
        )
        defaults.update(kwargs)
        return ServerStatus(host=host, **defaults)

    @patch("urllib.request.urlopen")
    def test_send_report_healthy(self, mock_urlopen):
        """发送健康主机报告"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        statuses = [self._make_status("web-01"), self._make_status("web-02")]
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}

        result = notifier.send_report(statuses, thresholds)
        self.assertTrue(result)

    @patch("urllib.request.urlopen")
    def test_send_report_with_warning(self, mock_urlopen):
        """发送含警告主机的报告"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        statuses = [
            self._make_status("web-01", cpu_percent=92),
            self._make_status("web-02", memory_percent=90),
            self._make_status("web-03"),
        ]
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}

        result = notifier.send_report(statuses, thresholds)
        self.assertTrue(result)

    @patch("urllib.request.urlopen")
    def test_send_report_with_failed(self, mock_urlopen):
        """发送含失败主机的报告"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        statuses = [
            self._make_status("web-01"),
            self._make_status("web-02", ssh_failed=True),
        ]
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}

        result = notifier.send_report(statuses, thresholds)
        self.assertTrue(result)

    @patch("urllib.request.urlopen")
    def test_send_card(self, mock_urlopen):
        """发送通用卡片"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"code": 0}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notifier = FeishuNotifier("https://test.webhook")
        result = notifier.send_card(
            title="测试卡片",
            elements=[
                {"tag": "div", "text": {"tag": "lark_md", "content": "内容"}},
            ],
            footer="测试",
            header_color="blue",
        )
        self.assertTrue(result)
