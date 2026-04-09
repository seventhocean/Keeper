"""报告生成测试模块"""
import pytest
import json
import os
from pathlib import Path
from keeper.tools.server import ServerStatus, ServerTools
from keeper.tools.reporter import ReportExporter


class TestReportExporter:
    """测试报告导出功能"""

    @pytest.fixture
    def sample_status(self):
        """创建示例服务器状态"""
        return ServerTools.inspect_server("localhost")

    @pytest.fixture
    def sample_statuses(self, sample_status):
        """创建示例服务器状态列表"""
        return [sample_status]

    @pytest.fixture
    def thresholds(self):
        """创建示例阈值"""
        return {"cpu": 80, "memory": 85, "disk": 90}

    def test_export_json(self, sample_statuses, thresholds, tmp_path):
        """测试导出 JSON 报告"""
        output_path = str(tmp_path / "report.json")
        result = ReportExporter.export_json(sample_statuses, thresholds, output_path)

        assert "已保存" in result
        assert Path(output_path).exists()

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["report_type"] == "server_inspect"
        assert "generated_at" in data
        assert len(data["hosts"]) == 1
        assert data["hosts"][0]["health_status"] in ("healthy", "warning")
        assert "metrics" in data["hosts"][0]
        assert "summary" in data
        assert data["summary"]["total_hosts"] == 1

    def test_export_html(self, sample_statuses, thresholds, tmp_path):
        """测试导出 HTML 报告"""
        output_path = str(tmp_path / "report.html")
        result = ReportExporter.export_html(sample_statuses, thresholds, output_path)

        assert "已保存" in result
        assert Path(output_path).exists()

        with open(output_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert "<!DOCTYPE html>" in html
        assert "Keeper 服务器巡检报告" in html
        assert "summary-card" in html
        assert "metric" in html

    def test_export_markdown(self, sample_statuses, thresholds, tmp_path):
        """测试导出 Markdown 报告"""
        output_path = str(tmp_path / "report.md")
        result = ReportExporter.export_markdown(sample_statuses, thresholds, output_path)

        assert "已保存" in result
        assert Path(output_path).exists()

        with open(output_path, "r", encoding="utf-8") as f:
            md = f.read()

        assert "# Keeper 服务器巡检报告" in md
        assert "| 主机 |" in md
        assert "## 汇总" in md
        assert "## 详细报告" in md

    def test_export_json_with_failed_host(self, thresholds, tmp_path):
        """测试导出包含失败主机的 JSON 报告"""
        failed_status = ServerStatus(
            host="192.168.1.999",
            timestamp="2026-04-09 10:00:00",
            cpu_percent=0,
            memory_percent=0,
            memory_used_gb=0,
            memory_total_gb=0,
            disk_percent=0,
            disk_used_gb=0,
            disk_total_gb=0,
            load_avg_1m=0,
            load_avg_5m=0,
            load_avg_15m=0,
            boot_time="",
            top_processes=[],
            ssh_failed=True,
        )

        output_path = str(tmp_path / "report_failed.json")
        result = ReportExporter.export_json([failed_status], thresholds, output_path)

        assert "已保存" in result

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["hosts"][0]["health_status"] == "failed"
        assert data["summary"]["failed"] == 1

    def test_export_creates_parent_directory(self, sample_statuses, thresholds, tmp_path):
        """测试导出时自动创建父目录"""
        output_path = str(tmp_path / "subdir" / "report.json")
        result = ReportExporter.export_json(sample_statuses, thresholds, output_path)

        assert "已保存" in result
        assert Path(output_path).exists()

    def test_export_invalid_path(self, sample_statuses, thresholds):
        """测试导出到无效路径（权限拒绝）"""
        # 使用 root 用户时可写入，改为测试 null byte 等真正无效路径
        result = ReportExporter.export_json(sample_statuses, thresholds, "")
        assert "失败" in result
