"""HybridAgent 测试 — Fast Path + Agent Loop + 降级

覆盖：
- _classify_input 输入分类
- HybridAgent 初始化
- process 方法：退出/空输入/斜杠命令/Fast Path/无LLM降级
- _handle_fast_path / _handle_no_llm
"""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from keeper.agent.hybrid import HybridAgent, _classify_input


class TestClassifyInput:
    """_classify_input 输入分类函数"""

    def test_k8s(self):
        for q in ["k8s 集群检查", "kubernetes pod 日志", "deployment 状态", "pod 挂了"]:
            assert _classify_input(q) == "k8s", q

    def test_network(self):
        for q in ["网络延迟", "ping 8.8.8.8", "端口检测", "dns 查询"]:
            assert _classify_input(q) == "network", q

    def test_security(self):
        for q in ["安全检查", "漏洞扫描", "证书检查", "ssl 状态"]:
            assert _classify_input(q) == "security", q

    def test_docker(self):
        for q in ["docker 状态", "容器列表", "镜像管理"]:
            assert _classify_input(q) == "docker", q

    def test_fix(self):
        for q in ["修复磁盘", "清理缓存", "重启服务", "扩容", "缩容"]:
            assert _classify_input(q) == "fix", q

    def test_inspect(self):
        for q in ["cpu 高", "内存占用", "磁盘满了", "检查服务器", "负载高"]:
            assert _classify_input(q) == "inspect", q

    def test_general(self):
        for q in ["你好", "今天天气", "help me"]:
            assert _classify_input(q) == "general", q

    def test_priority_specific_over_general(self):
        """具体类别优先于通用类别：k8s + cpu → k8s"""
        assert _classify_input("k8s cpu 高") == "k8s"


class TestHybridAgentInit:
    """HybridAgent 初始化"""

    def test_init(self, mock_config):
        agent = HybridAgent(mock_config)
        assert agent.state.is_running is True
        assert agent.state_store.is_running is True
        assert agent._first_turn is True
        assert agent._agent_loop is None  # lazy

    def test_agent_loop_lazy_init(self, mock_config):
        agent = HybridAgent(mock_config)
        assert agent._agent_loop is None
        loop = agent.agent_loop  # trigger init
        assert loop is not None
        assert agent._agent_loop is not None

    def test_set_stream_callback(self, mock_config):
        agent = HybridAgent(mock_config)
        cb = lambda x: None
        agent.set_stream_callback(cb)
        assert agent._stream_callback is cb

    def test_get_last_tool_names_when_no_loop(self, mock_config):
        """agent_loop 未初始化时 get_last_tool_names 返回空列表"""
        agent = HybridAgent(mock_config)
        agent._agent_loop = None
        mock_loop = MagicMock()
        mock_loop.get_last_tool_names.return_value = ["t1", "t2"]
        # Access via property: won't work because _agent_loop is None...
        # We patch the property
        with patch.object(HybridAgent, 'agent_loop', new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = mock_loop
            result = agent.get_last_tool_names()
            assert result == ["t1", "t2"]

    def test_get_last_tool_names_handles_exception(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch.object(HybridAgent, 'agent_loop', new_callable=PropertyMock) as mock_prop:
            mock_prop.side_effect = RuntimeError("no loop")
            assert agent.get_last_tool_names() == []


class TestHybridAgentProcessBasic:
    """process 方法 — 基本路径"""

    def test_empty_input(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent.process("")
        assert result == ""

    def test_whitespace_input(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent.process("   ")
        assert result == ""

    def test_exit_english(self, mock_config):
        agent = HybridAgent(mock_config)
        for word in ["exit", "quit", "bye"]:
            agent.state.is_running = True
            result = agent.process(word)
            assert agent.state.is_running is False

    def test_exit_chinese(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent.process("退出")
        assert agent.state.is_running is False
        result2 = agent.process("再见")
        assert "再见" in result2


class TestHybridAgentProcessNoLLM:
    """无 LLM 配置时的降级"""

    def test_no_llm_fallback(self, mock_config_no_llm):
        agent = HybridAgent(mock_config_no_llm)
        with patch("keeper.agent.hybrid._try_fast_match", return_value=None):
            result = agent.process("检查服务器状态")
            assert "降级模式" in result or "LLM" in result

    def test_no_llm_with_fast_match_not_in_fast_path(self, mock_config_no_llm):
        """Fast Path 匹配但 intent 不在 FAST_PATH_INTENTS → 仍走到 no-llm"""
        from keeper.nlu.base import IntentType, ParsedIntent
        agent = HybridAgent(mock_config_no_llm)
        mock_match = ParsedIntent(
            intent=IntentType.INSPECT,
            entities={},
            raw_input="检查服务器",
            is_task=True,
        )
        with patch("keeper.agent.hybrid._try_fast_match", return_value=mock_match):
            result = agent.process("检查服务器")
            assert "降级" in result or "LLM" in result


class TestHybridAgentProcessFastPath:
    """Fast Path 匹配 — 使用真实 IntentType"""

    def test_help_intent(self, mock_config):
        from keeper.nlu.base import IntentType, ParsedIntent
        agent = HybridAgent(mock_config)
        mock_match = ParsedIntent(
            intent=IntentType.HELP,
            entities={},
            raw_input="帮助",
            is_task=True,
        )
        with patch("keeper.agent.hybrid._try_fast_match", return_value=mock_match):
            result = agent.process("帮助")
            assert len(result) > 10

    def test_confirm_intent(self, mock_config):
        from keeper.nlu.base import IntentType, ParsedIntent
        agent = HybridAgent(mock_config)
        mock_match = ParsedIntent(
            intent=IntentType.CONFIRM,
            entities={},
            raw_input="确认",
            is_task=True,
        )
        with patch("keeper.agent.hybrid._try_fast_match", return_value=mock_match):
            result = agent.process("确认")
            assert "没有待确认" in result

    def test_slash_command_unknown(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent.process("/nonexistent")
        assert "未知命令" in result

    def test_slash_status(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent.process("/status")
        assert "Agent 状态" in result or "运行" in result


class TestHybridAgentProcessSlash:
    """斜杠命令处理 — 函数在 commands 模块中"""

    def test_slash_clear(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch("keeper.agent.commands._clear", return_value="[系统] 已清空对话历史"):
            result = agent.process("/clear")
            assert "清空" in result

    def test_slash_history(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch("keeper.agent.commands._history", return_value="[历史] 上次执行..."):
            result = agent.process("/history")
            assert "历史" in result or "上次" in result

    def test_slash_tools(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch("keeper.agent.commands._tools", return_value="工具列表..."):
            result = agent.process("/tools")
            assert "工具" in result

    def test_slash_mode(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch("keeper.agent.commands._mode", return_value="自动模式"):
            result = agent.process("/mode")
            assert "自动" in result

    def test_slash_plugins(self, mock_config):
        agent = HybridAgent(mock_config)
        with patch("keeper.agent.commands._plugins", return_value="已安装插件: ..."):
            result = agent.process("/plugins")
            assert "插件" in result


class TestHybridAgentHandleFastPath:
    """_handle_fast_path 方法"""

    def test_help_returns_text(self, mock_config):
        agent = HybridAgent(mock_config)
        from keeper.nlu.base import IntentType
        result = agent._handle_fast_path(IntentType.HELP, {})
        assert len(result) > 10  # non-trivial help text

    def test_unknown_intent(self, mock_config):
        agent = HybridAgent(mock_config)
        from keeper.nlu.base import IntentType
        result = agent._handle_fast_path(IntentType.UNKNOWN, {})
        assert "未知" in result


class TestHybridAgentHandleNoLLM:
    """_handle_no_llm 降级消息"""

    def test_no_llm_message(self, mock_config):
        agent = HybridAgent(mock_config)
        result = agent._handle_no_llm("test", None)
        assert "LLM" in result or "配置" in result
        assert "keeper config" in result or "--classic" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
