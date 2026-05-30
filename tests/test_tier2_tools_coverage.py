"""Tier 2 工具模块补充测试

覆盖：
- tools/notify: FeishuNotifier 格式化方法
- tools/reporter: 边界路径 (失败主机 / 不含 hosts / 异常提醒)
- tools/capacity: CapacityPredictor 预测逻辑
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# ─── Notify ────────────────────────────────────────────────────────

class TestFeishuNotifierFormats:
    """FeishuNotifier 消息格式化测试（不实际发送 HTTP）"""

    def test_severity_to_color_red(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        assert notifier._severity_to_color("🔴 告警") == "red"
        assert notifier._severity_to_color("🚨 紧急") == "red"

    def test_severity_to_color_orange(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        assert notifier._severity_to_color("🟡 警告") == "orange"
        assert notifier._severity_to_color("⚠️ 注意") == "orange"

    def test_severity_to_color_green(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        assert notifier._severity_to_color("🟢 正常") == "green"
        assert notifier._severity_to_color("✅ 成功") == "green"

    def test_severity_to_color_default_blue(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        assert notifier._severity_to_color("常规报告") == "blue"

    def test_gen_sign(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test", secret="my-secret-key")
        sign = notifier._gen_sign(1234567890)
        assert sign  # base64 encoded
        assert len(sign) > 0

    def test_send_card_with_footer(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_card(
                title="Card",
                elements=[{"tag": "div", "text": {"tag": "plain_text", "content": "hello"}}],
                footer="By Keeper",
            )
            assert result is True

    def test_send_card_without_footer(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_card(
                title="Card", elements=[],
            )
            assert result is True

    def test_send_text_with_at_users(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_text("Hello", at_user_ids=["user1", "user2"])
            assert result is True

    def test_send_text_without_at(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_text("Hello")
            assert result is True

    def test_send_rich(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        sections = [
            [{"tag": "text", "text": "CPU is high"}],
        ]
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_rich("Rich Card", sections, footer="footer")
            assert result is True

    def test_send_report_with_mock_server_statuses(self, mock_server_status, mock_server_status_critical):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test")
        with patch.object(notifier, "_send", return_value=True):
            result = notifier.send_report(
                [mock_server_status, mock_server_status_critical],
                {"cpu": 80, "memory": 85, "disk": 90},
            )
            assert result is True

    def test_send_http_failure(self):
        """_send 方法 HTTP 失败"""
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://invalid-url-that-will-fail")
        # Without mocking, the HTTP request should fail gracefully
        result = notifier._send({"msg_type": "text", "content": {"text": "test"}})
        # Should return False on failure, not raise
        assert result is False

    def test_send_with_secret_signature(self):
        from keeper.tools.notify import FeishuNotifier
        notifier = FeishuNotifier("http://test", secret="key")
        payload = {"msg_type": "text", "content": {"text": "test"}}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"code": 0}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            result = notifier._send(payload)
            assert result is True
            assert "timestamp" in payload
            assert "sign" in payload


# ─── Reporter ──────────────────────────────────────────────────────

class TestReporterEdgeCases:
    """ReportExporter 边界路径补充"""

    @pytest.fixture
    def sample_statuses(self, mock_server_status, mock_server_status_critical):
        return [mock_server_status, mock_server_status_critical]

    @pytest.fixture
    def thresholds(self):
        return {"cpu": 80, "memory": 85, "disk": 90}

    def test_export_json_with_all_healthy(self, mock_server_status, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "report.json"
        result = ReportExporter.export_json(
            [mock_server_status],
            {"cpu": 80, "memory": 85, "disk": 90},
            str(output),
        )
        assert "已保存" in result
        assert output.exists()

    def test_export_json_with_critical_host(self, mock_server_status_critical, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "report.json"
        result = ReportExporter.export_json(
            [mock_server_status_critical],
            {"cpu": 80, "memory": 85, "disk": 90},
            str(output),
        )
        assert output.exists()
        import json
        data = json.loads(output.read_text())
        assert data["summary"]["total_hosts"] == 1
        assert data["summary"]["warning"] >= 0

    def test_export_json_with_failed_ssh(self, tmp_path):
        from keeper.tools.server import ServerStatus
        from keeper.tools.reporter import ReportExporter
        failed = ServerStatus(
            host="dead-host", timestamp="", cpu_percent=0, memory_percent=0,
            memory_used_gb=0, memory_total_gb=0, disk_percent=0,
            disk_used_gb=0, disk_total_gb=0, load_avg_1m=0,
            load_avg_5m=0, load_avg_15m=0, boot_time="", top_processes=[],
            ssh_failed=True,
        )
        output = tmp_path / "report.json"
        result = ReportExporter.export_json([failed], {"cpu": 80, "memory": 85, "disk": 90}, str(output))
        assert "已保存" in result
        import json
        data = json.loads(output.read_text())
        assert data["summary"]["failed"] == 1

    def test_export_json_failure(self, mock_server_status):
        from keeper.tools.reporter import ReportExporter
        # Use /dev/null/... which cannot be a directory
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = ReportExporter.export_json(
                [mock_server_status],
                {"cpu": 80, "memory": 85, "disk": 90},
                "/fake/report.json",
            )
            assert "失败" in result

    def test_export_html_failure(self, mock_server_status):
        from keeper.tools.reporter import ReportExporter
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = ReportExporter.export_html(
                [mock_server_status],
                {"cpu": 80, "memory": 85, "disk": 90},
                "/fake/report.html",
            )
            assert "失败" in result

    def test_export_markdown_failure(self, mock_server_status):
        from keeper.tools.reporter import ReportExporter
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = ReportExporter.export_markdown(
                [mock_server_status],
                {"cpu": 80, "memory": 85, "disk": 90},
                "/fake/report.md",
            )
            assert "失败" in result

    def test_export_html_content(self, mock_server_status, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "report.html"
        result = ReportExporter.export_html(
            [mock_server_status],
            {"cpu": 80, "memory": 85, "disk": 90},
            str(output),
        )
        assert "已保存" in result
        content = output.read_text()
        assert "<!DOCTYPE html>" in content
        assert "Keeper" in content

    def test_export_markdown_content(self, mock_server_status, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "report.md"
        result = ReportExporter.export_markdown(
            [mock_server_status],
            {"cpu": 80, "memory": 85, "disk": 90},
            str(output),
        )
        assert "已保存" in result
        content = output.read_text()
        assert "# Keeper" in content

    def test_export_markdown_with_failed_host(self, tmp_path):
        from keeper.tools.server import ServerStatus
        from keeper.tools.reporter import ReportExporter
        failed = ServerStatus(
            host="dead", timestamp="", cpu_percent=0, memory_percent=0,
            memory_used_gb=0, memory_total_gb=0, disk_percent=0,
            disk_used_gb=0, disk_total_gb=0, load_avg_1m=0,
            load_avg_5m=0, load_avg_15m=0, boot_time="", top_processes=[],
            ssh_failed=True,
        )
        output = tmp_path / "report.md"
        result = ReportExporter.export_markdown([failed], {"cpu": 80, "memory": 85, "disk": 90}, str(output))
        assert "已保存" in result
        content = output.read_text()
        assert "❌ 失败" in content

    def test_export_html_with_failed_host(self, tmp_path):
        from keeper.tools.server import ServerStatus
        from keeper.tools.reporter import ReportExporter
        failed = ServerStatus(
            host="dead", timestamp="", cpu_percent=0, memory_percent=0,
            memory_used_gb=0, memory_total_gb=0, disk_percent=0,
            disk_used_gb=0, disk_total_gb=0, load_avg_1m=0,
            load_avg_5m=0, load_avg_15m=0, boot_time="", top_processes=[],
            ssh_failed=True,
        )
        output = tmp_path / "report.html"
        result = ReportExporter.export_html([failed], {"cpu": 80, "memory": 85, "disk": 90}, str(output))
        assert "已保存" in result

    def test_export_json_with_health_status_warning(self, mock_server_status_critical, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "report.json"
        result = ReportExporter.export_json(
            [mock_server_status_critical],
            {"cpu": 80, "memory": 85, "disk": 90},
            str(output),
        )
        assert output.exists()
        import json
        data = json.loads(output.read_text())
        assert data["summary"]["warning"] == 1

    def test_export_creates_parent_dir(self, mock_server_status, tmp_path):
        from keeper.tools.reporter import ReportExporter
        output = tmp_path / "deep" / "nested" / "report.json"
        result = ReportExporter.export_json([mock_server_status], {"cpu": 80, "memory": 85, "disk": 90}, str(output))
        assert "已保存" in result


# ─── Capacity ──────────────────────────────────────────────────────

class TestCapacityPredictor:
    """CapacityPredictor 补充测试"""

    def test_predict_no_history(self, tmp_path):
        from keeper.tools.capacity import CapacityPredictor
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        predictor = CapacityPredictor(history)
        predictions = predictor.predict("unknown_host")
        assert predictions == []

    def test_predict_with_data(self, tmp_path):
        from keeper.tools.capacity import CapacityPredictor
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        # Add growing data
        for i in range(10):
            history.save("host1", 50.0 + i * 0.5, 60.0 + i, 70.0 + i, 2.0)
        predictor = CapacityPredictor(history)
        predictions = predictor.predict("host1")
        assert len(predictions) == 3  #磁盘, 内存, CPU
        assert all(p.metric for p in predictions)

    def test_predict_above_threshold(self, tmp_path):
        from keeper.tools.capacity import CapacityPredictor
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        history.save("host1", 95.0, 95.0, 98.0, 5.0)  # already above
        history.save("host1", 95.0, 95.0, 98.0, 5.0)
        predictor = CapacityPredictor(history)
        predictions = predictor.predict("host1")
        # 磁盘超过阈值
        disk_pred = predictions[0]
        assert "超过" in disk_pred.prediction

    def test_predict_decreasing_trend(self, tmp_path):
        from keeper.tools.capacity import CapacityPredictor
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        for i in range(5):
            history.save("host1", 60.0 - i, 60.0 - i, 70.0 - i, 2.0)
        predictor = CapacityPredictor(history)
        predictions = predictor.predict("host1")
        disk_pred = predictions[0]
        assert "不会" in disk_pred.prediction or "下降" in disk_pred.prediction

    def test_format_predictions_empty(self):
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        text = predictor.format_predictions([])
        assert "历史数据不足" in text

    def test_format_predictions_with_data(self, tmp_path):
        from keeper.tools.capacity import CapacityPredictor
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        for i in range(10):
            history.save("h1", 50.0, 60.0, 70.0 + i, 2.0)
        predictor = CapacityPredictor(history)
        preds = predictor.predict("h1")
        text = predictor.format_predictions(preds)
        assert "[容量预测]" in text
        assert "置信度" in text

    def test_linear_regression_single_point(self):
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        slope, intercept = predictor._linear_regression([(0, 50.0)])
        assert slope == 0.0
        assert intercept == 50.0

    def test_linear_regression_two_points(self):
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        slope, intercept = predictor._linear_regression([(0, 50.0), (1, 55.0)])
        assert abs(slope - 5.0) < 0.01

    def test_linear_regression_denominator_zero(self):
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        slope, intercept = predictor._linear_regression([(5, 50.0), (5, 55.0)])
        # All x values are the same → denominator = 0 → returns (0.0, avg)
        assert slope == 0.0
        assert intercept == 52.5

    def test_predict_with_empty_data(self):
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        result = predictor._predict_metric("test_metric", [], 80, 0)
        assert result.metric == "test_metric"
        assert "无历史数据" in result.prediction


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
