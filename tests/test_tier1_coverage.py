"""Tier 1 补充测试 — 将覆盖率 90%+ 模块推到 100%

覆盖：
- validators: validate_host 空输入边界
- nlu/base: NLUEngine 抽象类实例化
- core/context: ContextManager profile / MemoryManager clear
- comparator: 空记录 / 下降趋势 / format
- history: cleanup 方法
- audit: 轮转边界 / 空状态统计
"""
import pytest
import json
import sqlite3
from unittest.mock import patch, PropertyMock
from pathlib import Path


# ─── Validators ───────────────────────────────────────────────────

class TestValidateHostEdgeCases:
    """覆盖 validate_host 的空输入边界"""

    def test_empty_host_raises(self):
        from keeper.validators import validate_host, ValidationError
        with pytest.raises(ValidationError):
            validate_host("")
        with pytest.raises(ValidationError):
            validate_host("   ")

    def test_valid_host_ip(self):
        from keeper.validators import validate_host
        assert validate_host("192.168.1.1") == "192.168.1.1"

    def test_valid_hostname(self):
        from keeper.validators import validate_host
        assert validate_host("localhost") == "localhost"


# ─── NLU Base ──────────────────────────────────────────────────────

class TestNLUEngineBase:
    """覆盖 NLUEngine 抽象基类的实例化路径"""

    def test_concrete_subclass_parse(self):
        from keeper.nlu.base import NLUEngine, ParsedIntent, IntentType
        class MyEngine(NLUEngine):
            def parse(self, user_input, context=None):
                return ParsedIntent(intent=IntentType.INSPECT, raw_input=user_input)
            def load(self):
                pass

        engine = MyEngine()
        result = engine.parse("test")
        assert result.intent == IntentType.INSPECT

    def test_concrete_subclass_load(self):
        from keeper.nlu.base import NLUEngine
        loaded_flag = []

        class MyEngine(NLUEngine):
            def parse(self, user_input, context=None):
                pass
            def load(self):
                loaded_flag.append(True)

        engine = MyEngine()
        engine.load()
        assert loaded_flag == [True]


# ─── Context ───────────────────────────────────────────────────────

class TestContextManagerProfile:
    """覆盖 ContextManager 的 profile 实体处理"""

    def test_update_with_profile(self):
        from keeper.core.context import ContextManager
        cm = ContextManager()
        cm.update("inspect", {"host": "server1", "profile": "production"})
        assert cm.current_host == "server1"
        assert cm.current_profile == "production"

    def test_update_without_profile(self):
        from keeper.core.context import ContextManager
        cm = ContextManager()
        cm.update("inspect", {"host": "server2"})
        assert cm.current_host == "server2"
        assert cm.current_profile is None


class TestMemoryManagerClear:
    """覆盖 MemoryManager.clear()"""

    def test_clear_with_turns(self):
        from keeper.core.context import MemoryManager
        mm = MemoryManager()
        mm.add_turn("check cpu", "CPU 15%", "inspect", {"host": "localhost"})
        assert len(mm.get_recent_turns(5)) == 1
        mm.clear()
        assert len(mm.get_recent_turns(5)) == 0

    def test_clear_empty(self):
        from keeper.core.context import MemoryManager
        mm = MemoryManager()
        mm.clear()  # no error
        assert mm.get_recent_turns(5) == []


# ─── Comparator ────────────────────────────────────────────────────

class TestComparatorEdgeCases:
    """覆盖 InspectionComparator 边界路径"""

    def test_no_history_returns_none(self, tmp_path):
        from keeper.tools.comparator import InspectionComparator
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        comparator = InspectionComparator(history)
        assert comparator.compare_with_last("unknown_host") is None

    def test_get_trend_with_no_records(self, tmp_path):
        from keeper.tools.comparator import InspectionComparator
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        comparator = InspectionComparator(history)
        result = comparator.get_trend("no_such_host", hours=168)
        assert result == {}

    def test_compare_with_known_host(self, tmp_path):
        from keeper.tools.comparator import InspectionComparator
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        # Insert 2 records
        history.save("test-host", 50.0, 60.0, 70.0, 2.0)
        history.save("test-host", 60.0, 65.0, 75.0, 3.0)
        comparator = InspectionComparator(history)
        report = comparator.compare_with_last("test-host")
        assert report is not None
        assert "CPU" in [d.name for d in report.diffs]

    def test_compare_decreasing_metrics(self, tmp_path):
        """覆盖下降趋势"""
        from keeper.tools.comparator import InspectionComparator
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        history.save("host1", 80.0, 70.0, 80.0, 5.0)
        history.save("host1", 50.0, 60.0, 70.0, 2.0)
        comparator = InspectionComparator(history)
        report = comparator.compare_with_last("host1")
        assert report is not None
        # 应该有下降的指标
        down_diffs = [d for d in report.diffs if d.direction == "down"]
        assert len(down_diffs) > 0

    def test_get_trend_with_data(self, tmp_path):
        """覆盖趋势分析"""
        from keeper.tools.comparator import InspectionComparator
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        for i in range(5):
            history.save("host-trend", 50.0 + i, 60.0, 70.0, 2.0)
        comparator = InspectionComparator(history)
        trend = comparator.get_trend("host-trend", hours=168)
        assert "cpu" in trend
        assert "current" in trend["cpu"]

    def test_format_comparison(self, tmp_path):
        from keeper.tools.comparator import InspectionComparator, ComparisonReport, MetricDiff
        report = ComparisonReport(
            host="test", current_time="2026-01-01T12:00", previous_time="2026-01-01T10:00",
            diffs=[
                MetricDiff("CPU", 60.0, 50.0, 10.0, 20.0, "up", warning=True),
                MetricDiff("内存", 65.0, 60.0, 5.0, 8.3, "up", warning=False),
            ],
            summary="异常变化: CPU ↑10.0%",
        )
        comparator = InspectionComparator()
        text = comparator.format_comparison(report)
        assert "test" in text
        assert "⚠️" in text
        assert "↑" in text


# ─── History ───────────────────────────────────────────────────────

class TestHistoryCleanup:
    """覆盖 InspectionHistory.cleanup()"""

    def test_cleanup_old_records(self, tmp_path):
        from keeper.storage.history import InspectionHistory
        db = tmp_path / "test.db"
        history = InspectionHistory(db_path=db)
        history.save("test", 50.0, 60.0, 70.0, 2.0)
        assert history.count() == 1
        # cleanup 0 days → delete all
        history.cleanup(days=0)
        # Records just created should still be there (timestamp >= now - 0 days)
        # cleanup 90 days → keep everything
        history.cleanup(days=90)
        # cleanup with no records → no error
        history2 = InspectionHistory(db_path=tmp_path / "empty.db")
        history2.cleanup(days=30)


# ─── Audit ─────────────────────────────────────────────────────────

class TestAuditEdgeCases:
    """覆盖 AuditLogger 边界路径"""

    def test_should_rotate_no_file(self, tmp_path):
        from keeper.core.audit import AuditLogger
        logger = AuditLogger(log_path=str(tmp_path / "nonexistent" / "audit.log"))
        assert logger._should_rotate() is False

    def test_rotate_and_log_with_error_recovery(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file), max_size_bytes=10)  # tiny
        # Write enough to trigger rotation
        logger.log_turn("test", {"host": "x"}, "success", 100)
        logger.log_turn("test", {"host": "y"}, "success", 200)
        # Should not crash even if rotation is triggered
        assert log_file.exists()

    def test_get_stats_empty(self, tmp_path):
        from keeper.core.audit import AuditLogger
        logger = AuditLogger(log_path=str(tmp_path / "nonexistent" / "audit.log"))
        stats = logger.get_stats()
        assert stats["total"] == 0

    def test_get_log_info(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file))
        info = logger.get_log_info()
        assert "log_file" in info
        assert info["max_size_mb"] == 10

    def test_get_history_with_filtering(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file))
        logger.log_turn("inspect", {"host": "a"}, "success", 100, host="a")
        logger.log_turn("fix", {"host": "b"}, "error", 200, host="b", error_message="failed")
        # Filter by host
        records = logger.get_history(host="a", hours=24)
        assert len(records) == 1
        assert records[0].host == "a"

    def test_search(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file))
        logger.log_turn("inspect", {"host": "prod-01"}, "success", 100, host="prod-01")
        logger.log_turn("fix", {"host": "dev-02"}, "error", 200, host="dev-02", error_message="disk full")
        results = logger.search("disk full")
        assert len(results) == 1
        assert results[0].host == "dev-02"

    def test_clear(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file))
        logger.log_turn("test", {}, "success", 100)
        assert log_file.exists()
        logger.clear()
        assert not log_file.exists()

    def test_get_history_with_intent_filter(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_file))
        logger.log_turn("inspect", {}, "success", 100)
        logger.log_turn("fix", {}, "success", 200)
        records = logger.get_history(intent="fix", hours=24)
        assert len(records) == 1
        assert records[0].intent == "fix"

    def test_get_history_skip_blank_lines(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        # Manually add a blank line
        with open(log_file, "w") as f:
            f.write("\n")
        logger = AuditLogger(log_path=str(log_file))
        records = logger.get_history()
        assert len(records) == 0  # blank line skipped

    def test_get_history_skip_invalid_json(self, tmp_path):
        from keeper.core.audit import AuditLogger
        log_file = tmp_path / "audit.log"
        with open(log_file, "w") as f:
            f.write("not valid json\n")
        logger = AuditLogger(log_path=str(log_file))
        records = logger.get_history()
        assert len(records) == 0  # invalid line skipped


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
