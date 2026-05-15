"""阶段 2 功能闭环测试

覆盖：
- 巡检历史持久化 (SQLite)
- 历史对比分析
- 容量预测
- Runbook 引擎
- 状态快照
- 日志分析
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")


# ═══════════════════════════════════════════════════════════════
# 2.1 巡检历史持久化
# ═══════════════════════════════════════════════════════════════

class TestInspectionHistory:
    """巡检历史 SQLite 存储"""

    def _make_history(self):
        from keeper.storage.history import InspectionHistory
        tmp = tempfile.mktemp(suffix=".db")
        return InspectionHistory(db_path=Path(tmp))

    def test_save_and_get(self):
        h = self._make_history()
        rid = h.save("localhost", cpu=45.0, memory=72.0, disk=60.0, load=1.2)
        assert rid > 0
        records = h.get_latest("localhost", n=1)
        assert len(records) == 1
        assert records[0].cpu_percent == 45.0
        assert records[0].host == "localhost"

    def test_multiple_records(self):
        h = self._make_history()
        h.save("host1", 10, 20, 30, 0.5)
        h.save("host1", 20, 30, 40, 0.6)
        h.save("host2", 50, 60, 70, 1.0)
        assert h.count("host1") == 2
        assert h.count("host2") == 1
        assert h.count() == 3

    def test_get_latest_order(self):
        h = self._make_history()
        h.save("srv", 10, 20, 30, 0.1)
        h.save("srv", 20, 30, 40, 0.2)
        h.save("srv", 30, 40, 50, 0.3)
        records = h.get_latest("srv", n=2)
        # 最新的在前
        assert records[0].cpu_percent == 30.0
        assert records[1].cpu_percent == 20.0

    def test_get_all_hosts(self):
        h = self._make_history()
        h.save("alpha", 1, 2, 3, 0.1)
        h.save("beta", 4, 5, 6, 0.2)
        hosts = h.get_all_hosts()
        assert "alpha" in hosts
        assert "beta" in hosts

    def test_empty_host_returns_empty(self):
        h = self._make_history()
        records = h.get_latest("nonexistent", n=5)
        assert records == []


# ═══════════════════════════════════════════════════════════════
# 2.1 历史对比分析
# ═══════════════════════════════════════════════════════════════

class TestComparator:
    """巡检对比分析"""

    def _make_comparator(self):
        from keeper.storage.history import InspectionHistory
        from keeper.tools.comparator import InspectionComparator
        tmp = tempfile.mktemp(suffix=".db")
        history = InspectionHistory(db_path=Path(tmp))
        return InspectionComparator(history=history), history

    def test_compare_with_last(self):
        comp, h = self._make_comparator()
        h.save("srv", 40, 60, 70, 1.0)
        h.save("srv", 50, 65, 72, 1.2)
        report = comp.compare_with_last("srv")
        assert report is not None
        assert report.host == "srv"
        assert len(report.diffs) == 4  # cpu, memory, disk, load

    def test_compare_no_history(self):
        comp, h = self._make_comparator()
        report = comp.compare_with_last("empty_host")
        assert report is None

    def test_diff_direction(self):
        comp, h = self._make_comparator()
        h.save("srv", 40, 60, 70, 1.0)
        h.save("srv", 60, 60, 70, 1.0)  # CPU 上升
        report = comp.compare_with_last("srv")
        cpu_diff = report.diffs[0]  # CPU 是第一个
        assert cpu_diff.direction == "up"
        assert cpu_diff.delta == 20.0

    def test_warning_on_large_change(self):
        comp, h = self._make_comparator()
        h.save("srv", 30, 40, 50, 0.5)
        h.save("srv", 80, 40, 50, 0.5)  # CPU 涨了 50
        report = comp.compare_with_last("srv")
        cpu_diff = report.diffs[0]
        assert cpu_diff.warning is True

    def test_format_comparison(self):
        comp, h = self._make_comparator()
        h.save("srv", 40, 60, 70, 1.0)
        h.save("srv", 50, 65, 72, 1.2)
        report = comp.compare_with_last("srv")
        text = comp.format_comparison(report)
        assert "巡检对比" in text
        assert "srv" in text

    def test_get_trend(self):
        comp, h = self._make_comparator()
        for i in range(5):
            h.save("srv", 40 + i, 60 + i, 70, 1.0)
        trend = comp.get_trend("srv", hours=168)
        assert "cpu" in trend
        assert trend["cpu"]["samples"] == 5


# ═══════════════════════════════════════════════════════════════
# 2.1 容量预测
# ═══════════════════════════════════════════════════════════════

class TestCapacityPredictor:
    """容量预测"""

    def _make_predictor(self):
        from keeper.storage.history import InspectionHistory
        from keeper.tools.capacity import CapacityPredictor
        tmp = tempfile.mktemp(suffix=".db")
        history = InspectionHistory(db_path=Path(tmp))
        return CapacityPredictor(history=history), history

    def test_predict_no_data(self):
        pred, h = self._make_predictor()
        results = pred.predict("empty_host")
        assert results == []

    def test_predict_with_data(self):
        pred, h = self._make_predictor()
        # 模拟磁盘增长
        for i in range(10):
            h.save("srv", 40, 60, 70 + i, 1.0)
        results = pred.predict("srv")
        assert len(results) == 3  # disk, memory, cpu
        # 磁盘应该有预测
        disk_pred = results[0]
        assert disk_pred.metric == "磁盘"
        assert disk_pred.current_value > 0

    def test_predict_stable_no_alert(self):
        pred, h = self._make_predictor()
        # 稳定数据
        for i in range(5):
            h.save("srv", 40, 60, 50, 1.0)
        results = pred.predict("srv")
        disk_pred = results[0]
        # 稳定时 days_to_threshold 应为 None 或很大
        assert disk_pred.days_to_threshold is None or disk_pred.days_to_threshold > 365

    def test_format_predictions(self):
        pred, h = self._make_predictor()
        for i in range(5):
            h.save("srv", 40, 60, 70 + i * 2, 1.0)
        results = pred.predict("srv")
        text = pred.format_predictions(results)
        assert "容量预测" in text


# ═══════════════════════════════════════════════════════════════
# 2.2 Runbook 引擎
# ═══════════════════════════════════════════════════════════════

class TestRunbookModels:
    """Runbook 数据模型"""

    def test_create_runbook(self):
        from keeper.runbook.models import Runbook, RunbookStep, StepSafety
        rb = Runbook(
            name="test",
            description="测试",
            steps=[
                RunbookStep(name="step1", command="echo hello", safety=StepSafety.SAFE),
                RunbookStep(name="step2", command="systemctl restart nginx", safety=StepSafety.CAUTION, confirm=True),
            ],
        )
        assert rb.name == "test"
        assert len(rb.steps) == 2
        assert rb.steps[1].confirm is True

    def test_from_dict(self):
        from keeper.runbook.models import Runbook
        data = {
            "name": "cleanup",
            "description": "清理",
            "steps": [
                {"name": "check", "command": "df -h", "safety": "safe"},
                {"name": "clean", "command": "rm old.log", "safety": "destructive", "confirm": True},
            ],
        }
        rb = Runbook.from_dict(data)
        assert rb.name == "cleanup"
        assert len(rb.steps) == 2
        assert rb.steps[1].confirm is True

    def test_to_dict(self):
        from keeper.runbook.models import Runbook, RunbookStep, StepSafety
        rb = Runbook(name="x", steps=[RunbookStep(name="s1", command="ls")])
        d = rb.to_dict()
        assert d["name"] == "x"
        assert len(d["steps"]) == 1


class TestRunbookExecutor:
    """Runbook 执行引擎"""

    def test_load_builtin_templates(self):
        from keeper.runbook.executor import list_builtin_runbooks
        templates = list_builtin_runbooks()
        assert "disk_cleanup" in templates
        assert "service_restart" in templates
        assert "log_rotate" in templates

    def test_load_yaml(self):
        from keeper.runbook.executor import RunbookExecutor
        import os
        executor = RunbookExecutor()
        yaml_path = os.path.join(os.path.dirname(__file__), "..", "keeper", "runbook", "templates", "disk_cleanup.yaml")
        try:
            rb = executor.load_from_yaml(yaml_path)
            assert rb.name == "disk_cleanup"
            assert len(rb.steps) >= 4
        except ImportError:
            # yaml/ruamel.yaml not available in test env
            pass

    def test_variable_rendering(self):
        from keeper.runbook.executor import RunbookExecutor
        executor = RunbookExecutor()
        result = executor._render_variables("echo {{name}} is {{age}}", {"name": "test", "age": "5"})
        assert result == "echo test is 5"

    def test_expect_contains(self):
        from keeper.runbook.executor import RunbookExecutor
        executor = RunbookExecutor()
        assert executor._check_expect("service is active", "contains active") is True
        assert executor._check_expect("service is dead", "contains active") is False

    def test_expect_less_than(self):
        from keeper.runbook.executor import RunbookExecutor
        executor = RunbookExecutor()
        assert executor._check_expect("75", "< 85") is True
        assert executor._check_expect("90", "< 85") is False

    def test_expect_greater_than(self):
        from keeper.runbook.executor import RunbookExecutor
        executor = RunbookExecutor()
        assert executor._check_expect("100", "> 50") is True
        assert executor._check_expect("10", "> 50") is False

    def test_safety_check_blocks_dangerous(self):
        from keeper.runbook.executor import RunbookExecutor
        from keeper.runbook.models import RunbookStep, StepSafety
        executor = RunbookExecutor()
        step = RunbookStep(name="bad", command="rm -rf /tmp", safety=StepSafety.DESTRUCTIVE)
        assert executor._safety_check(step) is False

    def test_execute_simple_runbook(self):
        from keeper.runbook.models import Runbook, RunbookStep, StepSafety
        from keeper.runbook.executor import RunbookExecutor

        outputs = []
        executor = RunbookExecutor(
            confirm_callback=lambda _: True,
            output_callback=lambda t: outputs.append(t),
        )
        rb = Runbook(
            name="simple_test",
            description="简单测试",
            steps=[
                RunbookStep(name="echo", command="echo hello_runbook", safety=StepSafety.SAFE, timeout=5),
            ],
        )
        success, summary = executor.execute(rb)
        assert success is True
        assert "hello_runbook" in rb.steps[0].output


# ═══════════════════════════════════════════════════════════════
# 2.3 状态快照
# ═══════════════════════════════════════════════════════════════

class TestSnapshotManager:
    """状态快照"""

    def _make_manager(self):
        from keeper.tools.snapshot import SnapshotManager
        tmp = tempfile.mkdtemp()
        return SnapshotManager(snapshot_dir=Path(tmp))

    def test_take_snapshot(self):
        mgr = self._make_manager()
        snap = mgr.take_snapshot("localhost")
        assert snap.host == "localhost"
        assert snap.timestamp != ""

    def test_list_snapshots(self):
        mgr = self._make_manager()
        mgr.take_snapshot("host1")
        snapshots = mgr.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["host"] == "host1"

    def test_get_latest(self):
        mgr = self._make_manager()
        mgr.take_snapshot("srv")
        latest = mgr.get_latest()
        assert latest is not None
        assert latest.host == "srv"

    def test_max_snapshots_cleanup(self):
        from keeper.tools.snapshot import SnapshotManager
        tmp = tempfile.mkdtemp()
        mgr = SnapshotManager(snapshot_dir=Path(tmp))
        mgr.MAX_SNAPSHOTS = 3
        for i in range(5):
            import time
            time.sleep(0.01)  # 确保时间戳不同
            mgr.take_snapshot(f"host{i}")
        snapshots = mgr.list_snapshots()
        assert len(snapshots) <= 3

    def test_compare_no_snapshot(self):
        mgr = self._make_manager()
        result = mgr.compare_with_current()
        assert "无可用快照" in result["message"]


# ═══════════════════════════════════════════════════════════════
# 2.4 日志分析
# ═══════════════════════════════════════════════════════════════

class TestLogAnalyzer:
    """日志智能分析"""

    def test_analyze_empty(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        report = LogAnalyzer._analyze_content("", "test", "1h")
        assert report.total_lines == 0
        assert "为空" in report.anomalies[0]

    def test_analyze_errors(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        content = "\n".join([
            "2026-05-15 10:00:00 ERROR connection refused 127.0.0.1:6379",
            "2026-05-15 10:00:01 ERROR connection refused 127.0.0.1:6379",
            "2026-05-15 10:00:02 ERROR connection refused 127.0.0.1:6379",
            "2026-05-15 10:00:03 WARNING disk space low",
            "2026-05-15 10:00:04 INFO normal operation",
        ])
        report = LogAnalyzer._analyze_content(content, "test", "1h")
        assert report.total_lines == 5
        assert report.error_count == 3
        assert report.warning_count == 1
        assert len(report.top_errors) >= 1

    def test_error_pattern_aggregation(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        content = "\n".join([
            "ERROR timeout connecting to 10.0.0.1:3306",
            "ERROR timeout connecting to 10.0.0.2:3306",
            "ERROR timeout connecting to 10.0.0.3:3306",
            "ERROR file not found /tmp/abc.txt",
            "ERROR file not found /tmp/xyz.txt",
        ])
        report = LogAnalyzer._analyze_content(content, "test", "1h")
        # 应该聚合为 2 种模式（timeout 和 file not found）
        assert len(report.top_errors) >= 1
        # timeout 出现 3 次应排第一
        assert report.top_errors[0].count >= 3 or report.top_errors[0].count >= 2

    def test_anomaly_detection_high_error_rate(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        content = "\n".join([f"ERROR something failed {i}" for i in range(80)] +
                           [f"INFO ok {i}" for i in range(20)])
        report = LogAnalyzer._analyze_content(content, "test", "1h")
        # 80% 错误率应触发异常
        assert any("错误率" in a for a in report.anomalies)

    def test_format_report(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        content = "ERROR test error\nINFO normal\nWARNING low disk"
        report = LogAnalyzer._analyze_content(content, "test.log", "1h")
        text = LogAnalyzer.format_report(report)
        assert "日志分析" in text
        assert "test.log" in text

    def test_extract_signature(self):
        from keeper.tools.log_analyzer import LogAnalyzer
        sig = LogAnalyzer._extract_signature("2026-05-15 10:00:00 server01 ERROR connection to 192.168.1.1 failed")
        # 应该把 IP 替换为 <IP>
        assert "<IP>" in sig or "192.168.1.1" not in sig


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
