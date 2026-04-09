"""系统日志查询测试模块"""
import pytest
import os
from pathlib import Path
from keeper.tools.logs import LogTools


class TestLogTools:
    """测试系统日志查询功能"""

    def test_query_file_nonexistent(self):
        """测试查询不存在的文件"""
        success, output = LogTools.query_file("/tmp/nonexistent_log_12345.log")
        assert not success
        assert "不存在" in output

    def test_query_file_with_valid_file(self, tmp_path):
        """测试查询有效日志文件"""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1: INFO something happened\nline2: ERROR something failed\nline3: INFO all good\n")

        success, output = LogTools.query_file(str(log_file), lines=3)
        assert success
        assert "INFO" in output
        assert "ERROR" in output

    def test_query_file_with_keyword(self, tmp_path):
        """测试关键词过滤"""
        log_file = tmp_path / "test.log"
        log_file.write_text("INFO normal\nERROR problem\nINFO normal\nERROR problem2\n")

        success, output = LogTools.query_file(str(log_file), lines=10, keyword="ERROR")
        assert success
        assert "problem" in output
        assert "normal" not in output

    def test_list_log_files(self):
        """测试列出日志文件路径"""
        success, log_files = LogTools.list_log_files()
        assert success
        assert len(log_files) > 0
        # 至少包含一些常见的日志路径
        names = [lf["name"] for lf in log_files]
        assert "system" in names or "messages" in names

    def test_query_file_tail_lines(self, tmp_path):
        """测试只获取最后 N 行"""
        log_file = tmp_path / "test.log"
        # 写入 20 行
        lines = [f"line {i}" for i in range(20)]
        log_file.write_text("\n".join(lines) + "\n")

        success, output = LogTools.query_file(str(log_file), lines=5)
        assert success
        output_lines = output.strip().split("\n")
        assert len(output_lines) <= 5
        assert "line 19" in output
        assert "line 0" not in output

    def test_search_logs_keyword(self, tmp_path):
        """测试搜索日志"""
        log_file = tmp_path / "search_test.log"
        log_file.write_text("INFO normal\nERROR critical issue\nINFO another normal\n")

        # 模拟通过文件查询
        success, output = LogTools.query_file(str(log_file), keyword="ERROR")
        assert success
        assert "critical issue" in output
        assert len(output.strip().split("\n")) == 1
