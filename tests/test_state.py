"""AgentStateStore & TodoList 测试

覆盖：
- SessionState / AgentStateStore 状态读写
- 钩子系统 (hooks)
- 会话控制 (stop/reset/add_warning)
- 状态快照和格式化
- TodoItem / TodoList 任务追踪
"""
import pytest
from unittest.mock import MagicMock
from keeper.agent.state import (
    SessionState,
    AgentStateStore,
    TodoItem,
    TodoList,
    global_todo_list,
)


class TestSessionState:
    """SessionState dataclass"""

    def test_defaults(self):
        s = SessionState()
        assert s.is_running is False
        assert s.current_host == ""
        assert s.tool_mode == "all"
        assert s.permission_mode == "allow"
        assert s.active_loop_mode == ""
        assert s.last_intent == ""
        assert s.last_tool_calls == []
        assert s.warnings == []

    def test_custom_values(self):
        s = SessionState(
            is_running=True,
            current_host="192.168.1.1",
            tool_mode="free",
            permission_mode="read_only",
            active_loop_mode="langgraph",
            last_intent="inspect",
            last_tool_calls=["inspect_server", "ping_host"],
            warnings=["disk 90%"],
        )
        assert s.is_running is True
        assert s.current_host == "192.168.1.1"
        assert s.tool_mode == "free"
        assert len(s.last_tool_calls) == 2
        assert len(s.warnings) == 1


class TestAgentStateStoreBasic:
    """AgentStateStore 基本读写"""

    def test_get_set(self):
        store = AgentStateStore()
        store.set("current_host", "10.0.0.1")
        assert store.get("current_host") == "10.0.0.1"

    def test_get_with_default(self):
        store = AgentStateStore()
        assert store.get("nonexistent", "fallback") == "fallback"

    def test_property_is_running(self):
        store = AgentStateStore()
        assert store.is_running is False
        store.is_running = True
        assert store.is_running is True

    def test_property_current_host(self):
        store = AgentStateStore()
        store.current_host = "prod-01"
        assert store.current_host == "prod-01"


class TestAgentStateStoreHooks:
    """钩子系统"""

    def test_register_and_trigger_hook(self):
        store = AgentStateStore()
        calls = []

        def my_hook(old, new):
            calls.append((old, new))

        store.register_hook("current_host", my_hook)
        store.set("current_host", "new-host")
        assert len(calls) == 1
        assert calls[0] == ("", "new-host")

    def test_multiple_hooks_same_key(self):
        store = AgentStateStore()
        results = []

        store.register_hook("tool_mode", lambda o, n: results.append(("a", o, n)))
        store.register_hook("tool_mode", lambda o, n: results.append(("b", o, n)))
        store.set("tool_mode", "routed")
        assert len(results) == 2

    def test_hook_not_triggered_for_other_keys(self):
        store = AgentStateStore()
        called = []

        store.register_hook("tool_mode", lambda o, n: called.append(True))
        store.set("current_host", "something")  # different key
        assert len(called) == 0

    def test_hook_receives_old_and_new(self):
        store = AgentStateStore()
        store.set("tool_mode", "free")
        captured = []

        store.register_hook("tool_mode", lambda o, n: captured.append((o, n)))
        store.set("tool_mode", "all")
        assert captured[0] == ("free", "all")


class TestAgentStateStoreLifecycle:
    """会话生命周期"""

    def test_stop(self):
        store = AgentStateStore()
        store.is_running = True
        store.stop()
        assert store.is_running is False

    def test_reset_preserves_warnings(self):
        store = AgentStateStore()
        store.set("current_host", "old-host")
        store.add_warning("disk 95%")
        store.add_warning("memory 90%")

        store.reset()

        assert store.get("current_host") == ""  # reset
        assert len(store.get_warnings()) == 2  # warnings preserved
        assert store.get("current_host") == ""

    def test_reset_creates_new_session(self):
        store = AgentStateStore()
        store.set("tool_mode", "free")
        store.reset()
        assert store.get("tool_mode") == "all"  # default

    def test_add_warning_and_get(self):
        store = AgentStateStore()
        store.add_warning("disk full")
        store.add_warning("cpu high")
        warnings = store.get_warnings()
        assert warnings == ["disk full", "cpu high"]
        # get_warnings clears
        assert store.get_warnings() == []

    def test_get_warnings_empty(self):
        store = AgentStateStore()
        assert store.get_warnings() == []


class TestAgentStateStoreSnapshot:
    """状态快照"""

    def test_snapshot_default(self):
        store = AgentStateStore()
        snap = store.snapshot()
        assert snap["is_running"] is False
        assert snap["current_host"] == ""
        assert snap["tool_mode"] == "all"
        assert snap["permission_mode"] == "allow"
        assert snap["active_loop_mode"] == ""

    def test_snapshot_after_changes(self):
        store = AgentStateStore()
        store.is_running = True
        store.current_host = "prod"
        store.set("last_intent", "inspect")
        store.set("last_tool_calls", ["t1", "t2"])

        snap = store.snapshot()
        assert snap["is_running"] is True
        assert snap["current_host"] == "prod"
        assert snap["last_intent"] == "inspect"
        assert snap["last_tool_count"] == 2

    def test_format_status(self):
        store = AgentStateStore()
        store.is_running = True
        store.current_host = "10.0.0.1"
        store.set("active_loop_mode", "langgraph")
        store.add_warning("test warning")

        text = store.format_status()
        assert "10.0.0.1" in text
        assert "langgraph" in text
        assert "是" in text or "True" in text
        assert "警告" in text

    def test_format_status_no_warnings(self):
        store = AgentStateStore()
        text = store.format_status()
        assert "未指定" in text or "" in text


class TestTodoItem:
    """TodoItem 测试"""

    def test_pending_icon(self):
        item = TodoItem(subject="test", status="pending")
        assert item.icon() == "○"

    def test_in_progress_icon(self):
        item = TodoItem(subject="test", status="in_progress")
        assert item.icon() == "◉"

    def test_completed_icon(self):
        item = TodoItem(subject="test", status="completed")
        assert item.icon() == "✓"

    def test_unknown_status_icon(self):
        item = TodoItem(subject="test", status="unknown")
        assert item.icon() == "?"

    def test_defaults(self):
        item = TodoItem(subject="do something")
        assert item.status == "pending"


class TestTodoList:
    """TodoList 任务追踪"""

    def test_set_todos(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "step 1", "status": "pending"},
            {"subject": "step 2", "status": "in_progress"},
            {"subject": "step 3", "status": "completed"},
        ])
        assert len(tl.items) == 3
        assert tl.items[0].status == "pending"
        assert tl.items[1].status == "in_progress"
        assert tl.items[2].status == "completed"

    def test_set_todos_replaces_old(self):
        tl = TodoList()
        tl.set_todos([{"subject": "old"}])
        tl.set_todos([{"subject": "new"}])
        assert len(tl.items) == 1
        assert tl.items[0].subject == "new"

    def test_update(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "a"},
            {"subject": "b"},
        ])
        tl.update(0, "completed")
        assert tl.items[0].status == "completed"
        assert tl.items[1].status == "pending"

    def test_update_out_of_range(self):
        tl = TodoList()
        tl.set_todos([{"subject": "only"}])
        tl.update(5, "completed")  # no error
        assert tl.items[0].status == "pending"

    def test_mark_all_pending(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "a", "status": "completed"},
            {"subject": "b", "status": "completed"},
            {"subject": "c", "status": "in_progress"},
        ])
        tl.mark_all_pending()
        assert all(i.status == "pending" for i in tl.items)

    def test_is_complete_all_done(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "a", "status": "completed"},
            {"subject": "b", "status": "completed"},
        ])
        assert tl.is_complete() is True

    def test_is_complete_partial(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "a", "status": "completed"},
            {"subject": "b", "status": "pending"},
        ])
        assert tl.is_complete() is False

    def test_is_complete_empty(self):
        tl = TodoList()
        assert tl.is_complete() is False  # empty = not complete

    def test_format_empty(self):
        tl = TodoList()
        assert "无待办" in tl.format()

    def test_format_with_items(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "检查资源", "status": "done"},
            {"subject": "查看日志", "status": "pending"},
        ])
        text = tl.format()
        assert "[执行计划]" in text
        assert "检查资源" in text
        assert "查看日志" in text

    def test_to_dict_and_from_dict(self):
        tl = TodoList()
        tl.set_todos([
            {"subject": "a", "status": "completed"},
            {"subject": "b", "status": "pending"},
        ])
        d = tl.to_dict()
        assert "items" in d
        assert len(d["items"]) == 2

        tl2 = TodoList()
        tl2.from_dict(d)
        assert len(tl2.items) == 2
        assert tl2.items[0].subject == "a"
        assert tl2.items[0].status == "completed"

    def test_from_dict_empty(self):
        tl = TodoList()
        tl.from_dict({"items": []})
        assert len(tl.items) == 0

    def test_set_todos_with_default_status(self):
        """未指定 status 时默认 pending"""
        tl = TodoList()
        tl.set_todos([{"subject": "task without status"}])
        assert tl.items[0].status == "pending"


class TestGlobalTodoList:
    """全局 TodoList 实例"""

    def test_global_instance(self):
        assert isinstance(global_todo_list, TodoList)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
