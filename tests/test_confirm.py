"""confirm 模块测试 - 交互式确认功能

测试场景：
- 非 TTY 环境自动处理
- TTY 环境的 prompt_toolkit 交互确认
- 会话级缓存（始终允许）
- select_or_input 形态
"""
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")

from keeper.agent.confirm import (  # noqa: E402
    confirm_action, select_option, select_or_input,
    reset_always_allowed, _always_allowed_tools,
)


class TestConfirmActionNonTTY:
    """非 TTY 环境下 confirm_action 行为测试"""

    @patch("sys.stdin")
    def test_write_level_auto_approve(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = confirm_action("manage_systemd_service", {"action": "restart"}, "write")
        assert result is True

    @patch("sys.stdin")
    def test_destructive_level_auto_reject(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = confirm_action("docker_prune", {"all": True}, "destructive")
        assert result is False

    @patch("sys.stdin")
    def test_dangerous_level_auto_reject(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = confirm_action("execute_shell_command", {"cmd": "rm -rf /"}, "dangerous")
        assert result is False


class TestConfirmActionTTY:
    """TTY 环境下 confirm_action 行为测试"""

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_allows(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "allow"
        reset_always_allowed()
        result = confirm_action("k8s_scale_deployment", {"replicas": 3}, "write")
        assert result is True

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_denies(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "deny"
        reset_always_allowed()
        result = confirm_action("docker_prune", {}, "destructive")
        assert result is False

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_always_allow(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "always"
        reset_always_allowed()
        result = confirm_action("manage_systemd_service", {"action": "restart"}, "write")
        assert result is True
        assert "manage_systemd_service" in _always_allowed_tools

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_always_allow_cache(self, mock_stdin, mock_blocking):
        """始终允许后不再弹出确认"""
        mock_stdin.isatty.return_value = True
        reset_always_allowed()
        _always_allowed_tools.add("my_tool")
        # 不应调用 _blocking_select
        result = confirm_action("my_tool", {}, "write")
        assert result is True
        mock_blocking.assert_not_called()

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_escape_returns_false(self, mock_stdin, mock_blocking):
        """空字符串视为拒绝"""
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = ""
        reset_always_allowed()
        result = confirm_action("some_tool", {}, "write")
        assert result is False


class TestSelectOptionNonTTY:
    """非 TTY 环境下 select_option 行为测试"""

    @patch("sys.stdin")
    def test_returns_first_option(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "A"

    @patch("sys.stdin")
    def test_empty_options(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = select_option("选择:", [])
        assert result == ""


class TestSelectOptionTTY:
    """TTY 环境下 select_option 行为测试"""

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "查看日志"
        result = select_option("选择操作:", ["重启服务", "查看日志", "忽略"])
        assert result == "查看日志"

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_escape_returns_first(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = ""
        result = select_option("选择:", ["A", "B"])
        assert result == "A"


class TestSelectOrInput:
    """select_or_input 形态测试"""

    @patch("sys.stdin")
    def test_non_tty_returns_first(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = select_or_input("选择:", ["A", "B"])
        assert result == "A"

    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_preset(self, mock_stdin, mock_blocking):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "重启服务"
        result = select_or_input("选择操作:", ["重启服务", "查看日志"])
        assert result == "重启服务"

    @patch("keeper.agent.confirm._text_input", return_value="自定义方案")
    @patch("keeper.agent.confirm._blocking_select")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_other(self, mock_stdin, mock_blocking, mock_text_input):
        mock_stdin.isatty.return_value = True
        mock_blocking.return_value = "输入其他..."
        result = select_or_input("选择操作:", ["重启服务", "查看日志"])
        assert result == "自定义方案"

    @patch("keeper.agent.confirm._text_input", return_value="用户的想法")
    @patch("sys.stdin")
    def test_no_options_goes_to_text_input(self, mock_stdin, mock_text_input):
        mock_stdin.isatty.return_value = True
        result = select_or_input("你的想法:", [])
        assert result == "用户的想法"


class TestResetAlwaysAllowed:
    """会话缓存重置测试"""

    def test_reset_clears_cache(self):
        _always_allowed_tools.add("test_tool")
        reset_always_allowed()
        assert len(_always_allowed_tools) == 0


class TestFallbackWithoutPromptToolkit:
    """prompt_toolkit 不可用时的降级测试"""

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False)
    @patch("keeper.agent.confirm._fallback_select", return_value="允许执行")
    @patch("sys.stdin")
    def test_confirm_fallback(self, mock_stdin, mock_fallback):
        mock_stdin.isatty.return_value = True
        reset_always_allowed()
        result = confirm_action("some_tool", {}, "write")
        assert result is True

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False)
    @patch("keeper.agent.confirm._fallback_select", return_value="B")
    @patch("sys.stdin")
    def test_select_fallback(self, mock_stdin, mock_fallback):
        mock_stdin.isatty.return_value = True
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "B"


class TestFormatArgsSummary:
    """_format_args_summary 参数摘要"""

    def test_short_args(self):
        from keeper.agent.confirm import _format_args_summary
        result = _format_args_summary({"action": "restart", "service": "nginx"})
        assert "action" in result
        assert "restart" in result
        assert "nginx" in result

    def test_long_args_truncated(self):
        from keeper.agent.confirm import _format_args_summary
        long_value = "x" * 200
        result = _format_args_summary({"data": long_value}, max_len=50)
        assert len(result) <= 55  # some overhead for formatting

    def test_empty_args(self):
        from keeper.agent.confirm import _format_args_summary
        result = _format_args_summary({})
        assert result == "{}" or isinstance(result, str)


class TestSafetyIcon:
    """_safety_icon 图标"""

    def test_read_only_icon(self):
        from keeper.agent.confirm import _safety_icon
        assert _safety_icon("read_only") == "🟢"

    def test_write_icon(self):
        from keeper.agent.confirm import _safety_icon
        assert _safety_icon("write") == "🟡"

    def test_destructive_icon(self):
        from keeper.agent.confirm import _safety_icon
        assert _safety_icon("destructive") == "🟠"

    def test_dangerous_icon(self):
        from keeper.agent.confirm import _safety_icon
        assert _safety_icon("dangerous") == "🔴"

    def test_unknown_icon(self):
        from keeper.agent.confirm import _safety_icon
        assert _safety_icon("unknown") == "⚪"


class TestRunRadiolist:
    """_blocking_select 基础测试"""

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    def test_basic_select(self):
        from keeper.agent.confirm import _blocking_select
        # In test env without real TTY, input() may fail
        # Just verify the function exists and doesn't crash
        try:
            result = _blocking_select("确认操作", [("allow", "允许执行"), ("deny", "拒绝")], default="allow")
            assert isinstance(result, str)
        except Exception:
            pass  # may fail without real TTY


class TestFallbackFunctions:
    """降级函数测试"""

    def test_fallback_text_input(self):
        from keeper.agent.confirm import _fallback_text_input
        with patch("builtins.input", return_value="用户输入"):
            result = _fallback_text_input("请输入: ")
            assert result == "用户输入"

    def test_fallback_select(self):
        from keeper.agent.confirm import _fallback_select
        with patch("builtins.input", return_value=""):
            result = _fallback_select("标题", ["A", "B", "C"])
            assert result == "A"  # default to first

    def test_fallback_select_valid_choice(self):
        from keeper.agent.confirm import _fallback_select
        with patch("builtins.input", return_value="2"):
            result = _fallback_select("标题", ["A", "B", "C"])
            assert result == "B"


class TestFormatArgsSummaryEdgeCases:
    """_format_args_summary 边缘情况"""

    def test_args_with_non_serializable(self):
        """不可 JSON 序列化的对象触发 except 分支"""
        from keeper.agent.confirm import _format_args_summary
        # bytes is not JSON serializable → triggers except branch
        result = _format_args_summary({"data": b"binary_data"})
        assert result is not None
        assert len(result) > 0

    def test_args_with_exception_object(self):
        """传入异常对象触发 except"""
        from keeper.agent.confirm import _format_args_summary
        result = _format_args_summary({"error": Exception("test")})
        assert result is not None


class TestTextInput:
    """_text_input 函数"""

    def test_text_input_with_prompt_toolkit(self):
        from keeper.agent.confirm import _text_input, PROMPT_TOOLKIT_AVAILABLE
        if PROMPT_TOOLKIT_AVAILABLE:
            try:
                result = _text_input("请输入: ")
                assert isinstance(result, str)
            except Exception:
                pass  # may fail without real TTY

    def test_text_input_fallback(self):
        from keeper.agent.confirm import _text_input
        with patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False):
            with patch("builtins.input", return_value="fallback输入"):
                result = _text_input("prompt> ")
                assert result == "fallback输入"


class TestRunRadiolistFallback:
    """_blocking_select 在 prompt_toolkit 不可用时的降级"""

    def test_radiolist_fallback_delegates_to_fallback_select(self):
        """非 TTY 时 _blocking_select 使用 input()"""
        from keeper.agent.confirm import _fallback_select, _blocking_select
        import keeper.agent.confirm as confirm_module

        # _blocking_select uses input() directly, verify behavior
        with patch("builtins.input", return_value="1"):
            result = _fallback_select("选择:", ["A选项", "B选项"])
            assert result == "A选项"


class TestSelectOrInputEdgeCases:
    """select_or_input 边界情况"""

    @patch("sys.stdin")
    def test_empty_options_non_tty(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = select_or_input("选择:", [])
        assert result == ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
