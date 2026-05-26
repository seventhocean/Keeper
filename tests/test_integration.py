"""集成测试 — 端到端流程覆盖

测试覆盖：
1. CLI 入口点 (status, logs, init)
2. 配置加载与保存
3. HybridAgent 完整流程 (Fast Path + Degradation + Agent Loop 初始化)
4. Agent Loop + Memory/Planner 集成
5. 降级路径验证
"""
import sys
sys.path.insert(0, ".")

import os
import json
import tempfile
from pathlib import Path

import pytest

# 标记整个模块为集成测试
pytestmark = pytest.mark.integration

from keeper.config import AppConfig, LLMConfig
from keeper.agent.hybrid import HybridAgent, _classify_input
from keeper.agent.loop import AgentLoop, LANGCHAIN_AVAILABLE, LANGGRAPH_AVAILABLE
from keeper.agent.tools_registry import ALL_TOOLS
from keeper.core.audit import AuditLogger


class TestCLIEntryPoints:
    """CLI 入口点测试"""

    def test_status_output(self):
        config = AppConfig.from_env()
        config.load()
        assert config.config_file is not None
        assert config.current_profile == "default"
        assert config.llm.provider in ("openai_compatible", "anthropic")
        assert config.llm.model

    def test_logs_read(self):
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "audit.log"
            log_file.write_text(json.dumps({
                "timestamp": "2026-05-15T22:00:00",
                "user": "test",
                "intent": "inspect",
                "entities": {"host": "localhost"},
                "result": "success",
                "response_time_ms": 100,
                "host": "localhost",
                "response": "OK",
            }) + "\n")
            with open(log_file) as f:
                lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["intent"] == "inspect"

    def test_init_config_flow(self):
        with tempfile.TemporaryDirectory() as td:
            config = AppConfig.from_env()
            config.profiles = {
                "dev": {"hosts": ["localhost"], "thresholds": {"cpu": 90, "memory": 90, "disk": 95}}
            }
            config.current_profile = "dev"
            assert config.current_profile == "dev"
            assert config.get_profile()["hosts"] == ["localhost"]


class TestConfigLoading:
    """配置加载与保存测试"""

    def test_llm_config_from_env(self):
        os.environ["KEEPER_API_KEY"] = "env-test-key-xyz"
        os.environ["KEEPER_MODEL"] = "env-test-model-xyz"
        llm = LLMConfig.from_env()
        assert llm.api_key == "env-test-key-xyz"
        assert llm.model == "env-test-model-xyz"
        del os.environ["KEEPER_API_KEY"]
        del os.environ["KEEPER_MODEL"]

    def test_llm_config_validation(self):
        llm = LLMConfig(api_key="", base_url="https://test.com/v1", model="test")
        assert not llm.is_configured()
        llm.api_key = "sk-test123"
        assert llm.is_configured()

    def test_config_save_load(self):
        with tempfile.TemporaryDirectory() as td:
            config_file = Path(td) / "config.yaml"
            config = AppConfig.from_env()
            config._config_file = config_file
            config.profiles = {
                "dev": {"hosts": ["localhost"], "thresholds": {"cpu": 90, "memory": 90, "disk": 95}},
            }
            config.current_profile = "dev"
            config.llm = LLMConfig(api_key="sk-test", base_url="https://test.com/v1", model="test")
            config.save()

            assert config_file.exists()
            content = config_file.read_text()
            assert "dev" in content
            assert "sk-test" in content

    def test_thresholds(self):
        config = AppConfig.from_env()
        config.profiles = {"dev": {"thresholds": {}}}
        config.current_profile = "dev"
        assert config.get_threshold("cpu") == 80  # default
        assert config.get_threshold("disk") == 90  # default

    def test_profile_switching(self):
        config = AppConfig.from_env()
        config.profiles = {
            "dev": {"hosts": ["localhost"], "thresholds": {"cpu": 90}},
            "staging": {"hosts": ["10.0.0.5"], "thresholds": {"cpu": 70}},
        }
        config.current_profile = "dev"
        assert config.get_profile()["hosts"] == ["localhost"]
        config.current_profile = "staging"
        assert config.get_profile()["hosts"] == ["10.0.0.5"]


class TestHybridAgentIntegration:
    """HybridAgent 集成测试"""

    def test_agent_initialization(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = "test-key"
        agent = HybridAgent(config)
        assert agent.state.is_running
        assert agent.memory is not None
        assert isinstance(agent.audit, AuditLogger)

    def test_fast_path_help(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = "test-key"
        agent = HybridAgent(config)
        resp = agent.process("帮助")
        assert "Keeper" in resp
        assert len(resp) > 200

    def test_fast_path_exit(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = "test-key"
        agent = HybridAgent(config)
        assert agent.state.is_running
        agent.process("exit")
        assert not agent.state.is_running

    def test_empty_input(self):
        config = AppConfig.from_env()
        config.load()
        agent = HybridAgent(config)
        assert agent.process("") == ""

    def test_all_slash_commands(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = "test-key"
        agent = HybridAgent(config)
        for cmd in ["/clear", "/history", "/tools", "/mode", "/memory"]:
            resp = agent.process(cmd)
            assert len(resp) > 0, f"{cmd} returned empty"

    def test_unknown_slash(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = "test-key"
        agent = HybridAgent(config)
        resp = agent.process("/nonexistent")
        assert "未知命令" in resp

    def test_no_llm_degradation(self):
        config = AppConfig.from_env()
        config.load()
        config.llm.api_key = ""
        agent = HybridAgent(config)
        resp = agent.process("检查本机")
        assert "降级模式" in resp
        assert "LLM 未配置" in resp


class TestClassifyInput:
    def test_inspect(self):
        assert _classify_input("检查本机服务器状态") == "inspect"
        assert _classify_input("服务器负载高") == "inspect"
        assert _classify_input("CPU 高") == "inspect"

    def test_k8s(self):
        assert _classify_input("K8s 集群异常") == "k8s"
        assert _classify_input("pod 挂了") == "k8s"

    def test_network(self):
        assert _classify_input("网络不通") == "network"
        assert _classify_input("ping 测试") == "network"
        assert _classify_input("DNS 解析失败") == "network"

    def test_security(self):
        assert _classify_input("安全审计") == "security"
        assert _classify_input("检查证书") == "security"

    def test_docker(self):
        assert _classify_input("Docker 容器") == "docker"
        assert _classify_input("查看镜像") == "docker"

    def test_fix(self):
        assert _classify_input("修复服务器") == "fix"
        assert _classify_input("重启服务") == "fix"

    def test_general(self):
        assert _classify_input("你好") == "general"
        assert _classify_input("今天天气") == "general"


class TestAgentMemoryIntegration:
    def test_memory_cycle(self):
        from keeper.agent.memory import AgentMemory
        with tempfile.TemporaryDirectory() as td:
            mem = AgentMemory(memory_dir=Path(td))
            assert mem.count == 0
            mem.add("检查本机", ["inspect_server"], "CPU 30%, 正常", host="localhost", category="inspect")
            assert mem.count == 1
            results = mem.search("CPU")
            assert len(results) == 1
            ctx = mem.get_context_for_prompt("检查服务器", host="localhost")
            assert "检查本机" in ctx
            mem.clear()
            assert mem.count == 0

    def test_memory_cap(self):
        from keeper.agent.memory import AgentMemory
        with tempfile.TemporaryDirectory() as td:
            mem = AgentMemory(memory_dir=Path(td))
            for i in range(105):
                mem.add(f"in{i}", ["t"], "c", category="g")
            assert mem.count <= 100


class TestAuditLoggerIntegration:
    def test_audit_write_read(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "audit.log"
            audit = AuditLogger(log_path=str(log_path))
            audit.log_turn(intent="inspect", entities={"host": "localhost"},
                          result="success", response_time_ms=100, response="ok")
            records = audit.get_history(hours=24)
            assert len(records) == 1
            assert records[0].intent == "inspect"

    def test_audit_host_filter(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "audit.log"
            audit = AuditLogger(log_path=str(log_path))
            audit.log_turn(intent="inspect", entities={}, host="server-x", response_time_ms=50, result="success", response="ok")
            audit.log_turn(intent="inspect", entities={}, host="server-y", response_time_ms=50, result="success", response="ok")
            records = audit.get_history(hours=24, host="server-x")
            assert len(records) == 1

    def test_audit_intent_filter(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "audit.log"
            audit = AuditLogger(log_path=str(log_path))
            audit.log_turn(intent="inspect", entities={}, result="success", response_time_ms=50, response="ok")
            audit.log_turn(intent="scan", entities={}, result="success", response_time_ms=50, response="ok")
            records = audit.get_history(hours=24, intent="inspect")
            assert len(records) == 1

    def test_audit_stats(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "audit.log"
            audit = AuditLogger(log_path=str(log_path))
            audit.log_turn(intent="inspect", entities={}, result="success", response_time_ms=100, response="ok")
            audit.log_turn(intent="inspect", entities={}, result="error", response_time_ms=50, response="")
            stats = audit.get_stats(hours=24)
            assert stats["total"] == 2
            assert stats["success"] == 1


class TestPlannerIntegration:
    def test_cpu_template_injection(self):
        from keeper.agent.planner import match_plan_template, should_show_plan
        user_input = "分析一下为什么 CPU 高"
        plan = match_plan_template(user_input)
        assert plan is not None
        assert plan.goal == "CPU 使用率高排查"
        assert len(plan.steps) == 3
        if plan and should_show_plan(user_input):
            steps_desc = " → ".join(s.description for s in plan.steps)
            assert "CPU" in steps_desc or "服务器" in steps_desc

    def test_all_templates_use_valid_tools(self):
        from keeper.agent.planner import PLAN_TEMPLATES
        tool_names = {t.name if hasattr(t, "name") else t.__name__ for t in ALL_TOOLS}
        for key, plan in PLAN_TEMPLATES.items():
            assert len(plan.steps) > 0, f"{key} empty"
            for step in plan.steps:
                assert step.tool_name in tool_names, f"{key}: {step.tool_name} not registered"


class TestAgentLoopModes:
    def test_mode_detection(self):
        if LANGGRAPH_AVAILABLE and LANGCHAIN_AVAILABLE:
            loop = AgentLoop(LLMConfig(api_key="t", base_url="https://x.com/v1", model="m"))
            assert loop._detect_mode() in ("langgraph", "manual")

    def test_tool_mode_all(self):
        loop = AgentLoop(LLMConfig(api_key="t", base_url="https://x.com/v1", model="m"), tool_mode="all")
        tools = loop._get_tools()
        assert len(tools) > len(ALL_TOOLS)

    def test_tool_mode_free(self):
        loop = AgentLoop(LLMConfig(api_key="t", base_url="https://x.com/v1", model="m"), tool_mode="free")
        assert len(loop._get_tools()) == 5

    def test_tool_mode_routed(self):
        loop = AgentLoop(LLMConfig(api_key="t", base_url="https://x.com/v1", model="m"), tool_mode="routed")
        assert len(loop._get_tools()) == len(ALL_TOOLS)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
