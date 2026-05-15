"""审计日志测试模块"""
import pytest
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from keeper.core.audit import AuditLogger, AuditRecord


class TestAuditLogger:
    """测试审计日志功能"""

    def test_log_turn(self, tmp_audit_logger, tmp_path):
        """测试记录一次操作"""
        logger = tmp_audit_logger
        logger.log_turn(
            intent="inspect",
            entities={"host": "192.168.1.100"},
            result="success",
            response_time_ms=1250,
            host="192.168.1.100",
        )

        assert logger.log_file.exists()
        with open(logger.log_file, "r", encoding="utf-8") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert data["intent"] == "inspect"
            assert data["host"] == "192.168.1.100"
            assert data["result"] == "success"
            assert data["response_time_ms"] == 1250

    def test_get_history(self, tmp_audit_logger):
        """测试获取历史记录"""
        logger = tmp_audit_logger
        for i in range(5):
            logger.log_turn(
                intent="inspect",
                entities={"host": f"192.168.1.{100+i}"},
                result="success",
                response_time_ms=1000 + i * 100,
                host=f"192.168.1.{100+i}",
            )

        records = logger.get_history(hours=24, limit=10)
        assert len(records) == 5
        assert records[0].host == "192.168.1.104"

    def test_get_history_with_host_filter(self, tmp_audit_logger):
        """测试按主机过滤历史记录"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.100"}, result="success", response_time_ms=1000, host="192.168.1.100")
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.101"}, result="success", response_time_ms=1000, host="192.168.1.101")
        logger.log_turn(intent="scan", entities={"host": "192.168.1.100"}, result="success", response_time_ms=2000, host="192.168.1.100")

        records = logger.get_history(hours=24, host="192.168.1.100")
        assert len(records) == 2

    def test_get_history_with_intent_filter(self, tmp_audit_logger):
        """测试按意图过滤历史记录"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        logger.log_turn(intent="scan", entities={}, result="success", response_time_ms=2000)
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1500)

        records = logger.get_history(hours=24, intent="inspect")
        assert len(records) == 2

    def test_search(self, tmp_audit_logger):
        """测试搜索历史记录"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.100"}, result="success", response_time_ms=1000, host="192.168.1.100")
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.101"}, result="error", response_time_ms=1000, host="192.168.1.101", error_message="连接失败")

        records = logger.search(query="192.168.1.101")
        assert len(records) == 1
        assert records[0].host == "192.168.1.101"

    def test_get_stats(self, tmp_audit_logger):
        """测试获取统计信息"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=2000)
        logger.log_turn(intent="scan", entities={}, result="error", response_time_ms=3000)

        stats = logger.get_stats(hours=24)
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["error"] == 1
        assert stats["by_intent"]["inspect"] == 2
        assert stats["by_intent"]["scan"] == 1
        assert stats["avg_response_time_ms"] == 2000

    def test_clear(self, tmp_audit_logger):
        """测试清空审计日志"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        assert logger.log_file.exists()
        logger.clear()
        assert not logger.log_file.exists()

    def test_empty_log_file(self, tmp_audit_logger):
        """测试空日志文件"""
        records = tmp_audit_logger.get_history(hours=24)
        assert len(records) == 0

    def test_invalid_json_lines(self, tmp_audit_logger):
        """测试处理无效 JSON 行"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)

        with open(logger.log_file, "a", encoding="utf-8") as f:
            f.write("invalid json line\n")
            f.write("{}\n")

        records = logger.get_history(hours=24)
        assert len(records) == 1

    def test_log_rotation(self, tmp_path):
        """测试日志轮转"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file), max_size_bytes=500, max_backups=3)

        for i in range(30):
            logger.log_turn(intent="inspect", entities={"i": i}, result="success", response_time_ms=100)

        # 应该产生归档文件
        info = logger.get_log_info()
        assert info["backup_count"] >= 1

    def test_log_info(self, tmp_audit_logger):
        """测试日志信息获取"""
        logger = tmp_audit_logger
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=100)
        info = logger.get_log_info()
        assert info["current_size_bytes"] > 0
        assert info["max_size_mb"] == 10.0
