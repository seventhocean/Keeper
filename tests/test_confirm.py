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

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_allows(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "allow"
        reset_always_allowed()
        result = confirm_action("k8s_scale_deployment", {"replicas": 3}, "write")
        assert result is True

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_denies(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "deny"
        reset_always_allowed()
        result = confirm_action("docker_prune", {}, "destructive")
        assert result is False

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_always_allow(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "always"
        reset_always_allowed()
        result = confirm_action("manage_systemd_service", {"action": "restart"}, "write")
        assert result is True
        assert "manage_systemd_service" in _always_allowed_tools

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_always_allow_cache(self, mock_stdin, mock_radiolist):
        """始终允许后不再弹出确认"""
        mock_stdin.isatty.return_value = True
        reset_always_allowed()
        _always_allowed_tools.add("my_tool")
        # 不应调用 _run_radiolist
        result = confirm_action("my_tool", {}, "write")
        assert result is True
        mock_radiolist.assert_not_called()

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_escape_returns_false(self, mock_stdin, mock_radiolist):
        """Esc（空字符串）视为拒绝"""
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = ""
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

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "查看日志"
        result = select_option("选择操作:", ["重启服务", "查看日志", "忽略"])
        assert result == "查看日志"

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_escape_returns_first(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = ""
        result = select_option("选择:", ["A", "B"])
        assert result == "A"


class TestSelectOrInput:
    """select_or_input 形态测试"""

    @patch("sys.stdin")
    def test_non_tty_returns_first(self, mock_stdin):
        mock_stdin.isatty.return_value = False
        result = select_or_input("选择:", ["A", "B"])
        assert result == "A"

    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_preset(self, mock_stdin, mock_radiolist):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "重启服务"
        result = select_or_input("选择操作:", ["重启服务", "查看日志"])
        assert result == "重启服务"

    @patch("keeper.agent.confirm._text_input", return_value="自定义方案")
    @patch("keeper.agent.confirm._run_radiolist")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_other(self, mock_stdin, mock_radiolist, mock_text_input):
        mock_stdin.isatty.return_value = True
        mock_radiolist.return_value = "输入其他..."
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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
