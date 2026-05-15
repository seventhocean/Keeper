"""Agent Loop 引擎测试

测试 AgentLoop 的核心逻辑（不依赖 LLM/langchain）：
- 模式检测
- 工具调用记录
- 历史管理
- 执行摘要
"""
import sys
sys.path.insert(0, ".")

from keeper.agent.loop import (
    AgentLoop,
    AgentTurn,
    ToolCall,
    LANGGRAPH_AVAILABLE,
    LANGCHAIN_AVAILABLE,
    AGENT_SYSTEM_PROMPT,
)


class TestAgentLoopInit:
    """Agent Loop 初始化测试"""

    def test_import_success(self):
        """AgentLoop 类应能成功导入"""
        assert AgentLoop is not None

    def test_mode_detection_no_langchain(self):
        """无 langchain 时应检测为 unavailable"""
        if not LANGCHAIN_AVAILABLE:
            loop = AgentLoop(llm_config=None, mode="auto")
            mode = loop._detect_mode()
            assert mode == "unavailable"

    def test_mode_detection_forced_manual(self):
        """强制 manual 模式但无 langchain 时应为 unavailable"""
        if not LANGCHAIN_AVAILABLE:
            loop = AgentLoop(llm_config=None, mode="manual")
            mode = loop._detect_mode()
            assert mode == "unavailable"

    def test_constants(self):
        """常量应正确设置"""
        assert AgentLoop.MAX_LOOPS == 10
        assert AgentLoop.MAX_OUTPUT_LEN == 2000
        assert AgentLoop.MAX_HISTORY_TURNS == 5


class TestToolCall:
    """ToolCall 数据类测试"""

    def test_create_tool_call(self):
        tc = ToolCall(
            tool_name="inspect_server",
            args={"host": "localhost"},
            result="CPU: 45%",
            duration_ms=320,
        )
        assert tc.tool_name == "inspect_server"
        assert tc.args == {"host": "localhost"}
        assert tc.duration_ms == 320
        assert tc.success is True

    def test_failed_tool_call(self):
        tc = ToolCall(
            tool_name="ping_host",
            args={"host": "10.0.0.1"},
            result="[错误] 超时",
            duration_ms=5000,
            success=False,
        )
        assert tc.success is False


class TestAgentTurn:
    """AgentTurn 数据类测试"""

    def test_create_turn(self):
        turn = AgentTurn(user_input="检查服务器")
        assert turn.user_input == "检查服务器"
        assert turn.tool_calls == []
        assert turn.final_response == ""
        assert turn.loop_count == 0

    def test_turn_with_tools(self):
        turn = AgentTurn(user_input="排查 CPU 高")
        turn.tool_calls.append(ToolCall("inspect_server", {}, "CPU 92%", 200))
        turn.tool_calls.append(ToolCall("get_top_processes", {"n": 5}, "mysql 85%", 150))
        turn.loop_count = 2
        turn.total_duration_ms = 3500

        assert len(turn.tool_calls) == 2
        assert turn.loop_count == 2


class TestAgentLoopHistory:
    """对话历史管理测试"""

    def test_add_history(self):
        loop = AgentLoop(llm_config=None, mode="auto")
        loop._add_history("检查服务器", "CPU 正常")
        assert len(loop.conversation_history) == 1
        assert loop.conversation_history[0]["user"] == "检查服务器"

    def test_history_length_control(self):
        """历史应不超过 MAX_HISTORY_TURNS * 2"""
        loop = AgentLoop(llm_config=None, mode="auto")
        for i in range(20):
            loop._add_history(f"问题 {i}", f"回答 {i}")
        assert len(loop.conversation_history) <= loop.MAX_HISTORY_TURNS * 2

    def test_history_truncates_long_response(self):
        """过长的回复应被截断存储"""
        loop = AgentLoop(llm_config=None, mode="auto")
        long_response = "x" * 1000
        loop._add_history("test", long_response)
        stored = loop.conversation_history[0]["assistant"]
        assert len(stored) <= 500

    def test_clear_history(self):
        loop = AgentLoop(llm_config=None, mode="auto")
        loop._add_history("test", "response")
        loop.clear_history()
        assert len(loop.conversation_history) == 0


class TestAgentLoopExecution:
    """Agent Loop 执行测试（无 LLM 环境）"""

    def test_run_without_llm_gives_error(self):
        """无 LLM 时运行应给出明确错误"""
        if not LANGCHAIN_AVAILABLE:
            loop = AgentLoop(llm_config=None, mode="auto")
            result = loop.run("检查服务器")
            assert "安装" in result or "不可用" in result or "无可用" in result or "错误" in result

    def test_get_last_tool_calls_empty(self):
        """无执行记录时应返回空列表"""
        loop = AgentLoop(llm_config=None, mode="auto")
        assert loop.get_last_tool_calls() == []

    def test_execution_summary_empty(self):
        """无执行记录时应返回提示"""
        loop = AgentLoop(llm_config=None, mode="auto")
        summary = loop.get_execution_summary()
        assert "无执行记录" in summary


class TestSystemPrompt:
    """System Prompt 测试"""

    def test_prompt_contains_key_elements(self):
        """System Prompt 应包含关键元素"""
        assert "Keeper" in AGENT_SYSTEM_PROMPT
        assert "运维" in AGENT_SYSTEM_PROMPT
        assert "工具" in AGENT_SYSTEM_PROMPT
        assert "安全" in AGENT_SYSTEM_PROMPT

    def test_prompt_contains_patterns(self):
        """应包含排查模式"""
        assert "CPU" in AGENT_SYSTEM_PROMPT
        assert "bash" in AGENT_SYSTEM_PROMPT or "run_bash" in AGENT_SYSTEM_PROMPT
        assert "服务" in AGENT_SYSTEM_PROMPT


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
