"""审计日志测试模块"""
import pytest
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from keeper.core.audit import AuditLogger, AuditRecord


class TestAuditLogger:
    """测试审计日志功能"""

    def test_log_turn(self, tmp_path):
        """测试记录一次操作"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录一次操作
        logger.log_turn(
            intent="inspect",
            entities={"host": "192.168.1.100"},
            result="success",
            response_time_ms=1250,
            host="192.168.1.100",
        )

        # 验证文件存在
        assert log_file.exists()

        # 验证内容
        with open(log_file, "r", encoding="utf-8") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert data["intent"] == "inspect"
            assert data["host"] == "192.168.1.100"
            assert data["result"] == "success"
            assert data["response_time_ms"] == 1250

    def test_get_history(self, tmp_path):
        """测试获取历史记录"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录多条操作
        for i in range(5):
            logger.log_turn(
                intent="inspect",
                entities={"host": f"192.168.1.{100+i}"},
                result="success",
                response_time_ms=1000 + i * 100,
                host=f"192.168.1.{100+i}",
            )

        # 获取历史记录
        records = logger.get_history(hours=24, limit=10)
        assert len(records) == 5
        assert records[0].host == "192.168.1.104"  # 最新的在前

    def test_get_history_with_host_filter(self, tmp_path):
        """测试按主机过滤历史记录"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录多条操作
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.100"}, result="success", response_time_ms=1000, host="192.168.1.100")
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.101"}, result="success", response_time_ms=1000, host="192.168.1.101")
        logger.log_turn(intent="scan", entities={"host": "192.168.1.100"}, result="success", response_time_ms=2000, host="192.168.1.100")

        # 按主机过滤
        records = logger.get_history(hours=24, host="192.168.1.100")
        assert len(records) == 2

    def test_get_history_with_intent_filter(self, tmp_path):
        """测试按意图过滤历史记录"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录多条操作
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        logger.log_turn(intent="scan", entities={}, result="success", response_time_ms=2000)
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1500)

        # 按意图过滤
        records = logger.get_history(hours=24, intent="inspect")
        assert len(records) == 2

    def test_search(self, tmp_path):
        """测试搜索历史记录"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录多条操作
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.100"}, result="success", response_time_ms=1000, host="192.168.1.100")
        logger.log_turn(intent="inspect", entities={"host": "192.168.1.101"}, result="error", response_time_ms=1000, host="192.168.1.101", error_message="连接失败")

        # 搜索
        records = logger.search(query="192.168.1.101")
        assert len(records) == 1
        assert records[0].host == "192.168.1.101"

    def test_get_stats(self, tmp_path):
        """测试获取统计信息"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录多条操作
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=2000)
        logger.log_turn(intent="scan", entities={}, result="error", response_time_ms=3000)

        # 获取统计
        stats = logger.get_stats(hours=24)
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["error"] == 1
        assert stats["by_intent"]["inspect"] == 2
        assert stats["by_intent"]["scan"] == 1
        assert stats["avg_response_time_ms"] == 2000

    def test_clear(self, tmp_path):
        """测试清空审计日志"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 记录一条操作
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)
        assert log_file.exists()

        # 清空
        logger.clear()
        assert not log_file.exists()

    def test_empty_log_file(self, tmp_path):
        """测试空日志文件"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 未写入时获取历史记录
        records = logger.get_history(hours=24)
        assert len(records) == 0

    def test_invalid_json_lines(self, tmp_path):
        """测试处理无效 JSON 行"""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))

        # 写入有效记录
        logger.log_turn(intent="inspect", entities={}, result="success", response_time_ms=1000)

        # 追加无效行
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("invalid json line\n")
            f.write("{}\n")  # 空对象，缺少必需字段

        # 应该跳过无效行，只返回有效记录
        records = logger.get_history(hours=24)
        assert len(records) == 1
