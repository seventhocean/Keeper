"""confirm 模块测试 - 交互式确认功能

测试场景：
- 非 TTY 环境自动处理
- TTY 环境的 prompt_toolkit 交互确认
- prompt_toolkit 不可用时的降级处理
"""
import sys
from unittest.mock import patch

sys.path.insert(0, ".")

from keeper.agent.confirm import confirm_action, select_option  # noqa: E402


class TestConfirmActionNonTTY:
    """非 TTY 环境下 confirm_action 行为测试"""

    @patch("sys.stdin")
    def test_write_level_auto_approve(self, mock_stdin):
        """非 TTY + write 级别应自动放行"""
        mock_stdin.isatty.return_value = False
        result = confirm_action("manage_systemd_service", {"action": "restart"}, "write")
        assert result is True

    @patch("sys.stdin")
    def test_destructive_level_auto_reject(self, mock_stdin):
        """非 TTY + destructive 级别应自动拒绝"""
        mock_stdin.isatty.return_value = False
        result = confirm_action("docker_prune", {"all": True}, "destructive")
        assert result is False

    @patch("sys.stdin")
    def test_dangerous_level_auto_reject(self, mock_stdin):
        """非 TTY + dangerous 级别应自动拒绝"""
        mock_stdin.isatty.return_value = False
        result = confirm_action("execute_shell_command", {"cmd": "rm -rf /"}, "dangerous")
        assert result is False

    @patch("sys.stdin")
    def test_empty_args(self, mock_stdin):
        """非 TTY + 空参数应正常处理"""
        mock_stdin.isatty.return_value = False
        result = confirm_action("some_tool", {}, "write")
        assert result is True


class TestSelectOptionNonTTY:
    """非 TTY 环境下 select_option 行为测试"""

    @patch("sys.stdin")
    def test_returns_first_option(self, mock_stdin):
        """非 TTY 应返回第一个选项"""
        mock_stdin.isatty.return_value = False
        result = select_option("选择操作:", ["重启服务", "查看日志", "忽略"])
        assert result == "重启服务"

    @patch("sys.stdin")
    def test_single_option(self, mock_stdin):
        """单个选项应返回该选项"""
        mock_stdin.isatty.return_value = False
        result = select_option("确认?", ["继续"])
        assert result == "继续"

    @patch("sys.stdin")
    def test_empty_options(self, mock_stdin):
        """空选项列表应返回空字符串"""
        mock_stdin.isatty.return_value = False
        result = select_option("选择:", [])
        assert result == ""


class TestConfirmActionTTY:
    """TTY 环境下 confirm_action 行为测试"""

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_confirms(self, mock_stdin, mock_prompt):
        """用户输入 Y 应返回 True"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "Y"
        result = confirm_action("k8s_scale_deployment", {"replicas": 3}, "write")
        assert result is True

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_confirms_empty_input(self, mock_stdin, mock_prompt):
        """用户直接回车（默认 Y）应返回 True"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = ""
        result = confirm_action("manage_systemd_service", {"action": "restart"}, "write")
        assert result is True

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_rejects(self, mock_stdin, mock_prompt):
        """用户输入 n 应返回 False"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "n"
        result = confirm_action("docker_prune", {"all": True}, "destructive")
        assert result is False

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_keyboard_interrupt(self, mock_stdin, mock_prompt):
        """用户 Ctrl+C 应返回 False"""
        mock_stdin.isatty.return_value = True
        mock_prompt.side_effect = KeyboardInterrupt()
        result = confirm_action("some_tool", {}, "write")
        assert result is False

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_eof_error(self, mock_stdin, mock_prompt):
        """EOF 应返回 False"""
        mock_stdin.isatty.return_value = True
        mock_prompt.side_effect = EOFError()
        result = confirm_action("some_tool", {}, "write")
        assert result is False


class TestSelectOptionTTY:
    """TTY 环境下 select_option 行为测试"""

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_option(self, mock_stdin, mock_prompt):
        """用户选择第2项应返回对应选项"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "2"
        result = select_option("选择操作:", ["重启服务", "查看日志", "忽略"])
        assert result == "查看日志"

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_user_selects_first_option(self, mock_stdin, mock_prompt):
        """用户选择第1项应返回第一个选项"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "1"
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "A"

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_invalid_input_returns_first(self, mock_stdin, mock_prompt):
        """无效输入应返回第一个选项"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "abc"
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "A"

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_out_of_range_returns_first(self, mock_stdin, mock_prompt):
        """超出范围的编号应返回第一个选项"""
        mock_stdin.isatty.return_value = True
        mock_prompt.return_value = "99"
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "A"

    @patch("keeper.agent.confirm.pt_prompt")
    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", True)
    @patch("sys.stdin")
    def test_keyboard_interrupt_returns_first(self, mock_stdin, mock_prompt):
        """Ctrl+C 应返回第一个选项"""
        mock_stdin.isatty.return_value = True
        mock_prompt.side_effect = KeyboardInterrupt()
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "A"


class TestFallbackWithoutPromptToolkit:
    """prompt_toolkit 不可用时的降级测试"""

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False)
    @patch("builtins.input", return_value="y")
    @patch("sys.stdin")
    def test_confirm_fallback_approve(self, mock_stdin, mock_input):
        """无 prompt_toolkit 时用 input 降级，用户输入 y"""
        mock_stdin.isatty.return_value = True
        result = confirm_action("some_tool", {"key": "value"}, "write")
        assert result is True

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False)
    @patch("builtins.input", return_value="n")
    @patch("sys.stdin")
    def test_confirm_fallback_reject(self, mock_stdin, mock_input):
        """无 prompt_toolkit 时用 input 降级，用户输入 n"""
        mock_stdin.isatty.return_value = True
        result = confirm_action("some_tool", {}, "destructive")
        assert result is False

    @patch("keeper.agent.confirm.PROMPT_TOOLKIT_AVAILABLE", False)
    @patch("builtins.input", return_value="2")
    @patch("sys.stdin")
    def test_select_fallback(self, mock_stdin, mock_input):
        """无 prompt_toolkit 时 select_option 用 input 降级"""
        mock_stdin.isatty.return_value = True
        result = select_option("选择:", ["A", "B", "C"])
        assert result == "B"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
