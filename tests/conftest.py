"""Keeper 测试公共 Fixture 和标记定义

标记 (markers):
- @pytest.mark.integration: 依赖真实系统环境的测试（psutil 采集、网络、Docker 等）
- @pytest.mark.slow: 运行时间较长的测试（>5s）
- @pytest.mark.requires_llm: 需要 LLM API Key 的测试

使用方式：
    # 只运行单元测试（跳过集成测试）
    pytest tests/ -m "not integration"

    # 只运行集成测试
    pytest tests/ -m integration

    # 跳过需要 LLM 的测试
    pytest tests/ -m "not requires_llm"
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

import pytest

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── 自定义标记注册 ──────────────────────────────────────────

def pytest_configure(config):
    """注册自定义标记"""
    config.addinivalue_line("markers", "integration: 依赖真实系统环境的测试")
    config.addinivalue_line("markers", "slow: 运行时间较长的测试 (>5s)")
    config.addinivalue_line("markers", "requires_llm: 需要 LLM API Key 的测试")


# ─── 配置相关 Fixture ─────────────────────────────────────────

@pytest.fixture
def tmp_config_dir(tmp_path):
    """创建临时配置目录"""
    config_dir = tmp_path / ".keeper"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_config(tmp_config_dir):
    """创建 mock 配置（不依赖真实 ~/.keeper）"""
    from keeper.config import AppConfig, LLMConfig

    config = AppConfig(
        log_level="DEBUG",
        current_profile="test",
        llm=LLMConfig(
            provider="openai_compatible",
            api_key="sk-test-fake-key-for-testing",
            base_url="http://localhost:11434/v1",
            model="test-model",
        ),
        profiles={
            "test": {
                "hosts": ["localhost"],
                "thresholds": {"cpu": 80, "memory": 85, "disk": 90},
            }
        },
    )
    config._config_dir = tmp_config_dir
    config._config_file = tmp_config_dir / "config.yaml"
    return config


@pytest.fixture
def mock_config_no_llm(tmp_config_dir):
    """创建未配置 LLM 的 mock 配置"""
    from keeper.config import AppConfig, LLMConfig

    config = AppConfig(
        log_level="DEBUG",
        current_profile="test",
        llm=LLMConfig(provider="openai_compatible", api_key="", base_url="", model=""),
    )
    config._config_dir = tmp_config_dir
    config._config_file = tmp_config_dir / "config.yaml"
    return config


# ─── 服务器状态 Mock ──────────────────────────────────────────

@pytest.fixture
def mock_server_status():
    """创建 mock 服务器状态对象"""
    from keeper.tools.server import ServerStatus

    return ServerStatus(
        host="localhost",
        timestamp="2026-05-15 12:00:00",
        cpu_percent=25.5,
        memory_percent=42.0,
        memory_used_gb=3.36,
        memory_total_gb=8.0,
        disk_percent=60.0,
        disk_used_gb=120.0,
        disk_total_gb=200.0,
        load_avg_1m=0.5,
        load_avg_5m=0.4,
        load_avg_15m=0.3,
        boot_time="2026-05-01 08:00:00",
        top_processes=[
            {"pid": 1, "name": "systemd", "cpu_percent": 0.1, "memory_percent": 0.5},
            {"pid": 100, "name": "python", "cpu_percent": 5.0, "memory_percent": 3.0},
            {"pid": 200, "name": "nginx", "cpu_percent": 2.0, "memory_percent": 1.5},
        ],
        ssh_failed=False,
    )


@pytest.fixture
def mock_server_status_critical():
    """创建告警级别的 mock 服务器状态"""
    from keeper.tools.server import ServerStatus

    return ServerStatus(
        host="production-01",
        timestamp="2026-05-15 12:00:00",
        cpu_percent=95.0,
        memory_percent=92.0,
        memory_used_gb=7.36,
        memory_total_gb=8.0,
        disk_percent=96.0,
        disk_used_gb=192.0,
        disk_total_gb=200.0,
        load_avg_1m=12.5,
        load_avg_5m=10.0,
        load_avg_15m=8.0,
        boot_time="2026-04-01 08:00:00",
        top_processes=[
            {"pid": 500, "name": "mysql", "cpu_percent": 85.0, "memory_percent": 60.0},
            {"pid": 501, "name": "java", "cpu_percent": 10.0, "memory_percent": 20.0},
        ],
        ssh_failed=False,
    )


# ─── 审计日志 Fixture ─────────────────────────────────────────

@pytest.fixture
def tmp_audit_logger(tmp_path):
    """创建临时目录下的审计日志"""
    from keeper.core.audit import AuditLogger

    log_file = tmp_path / "test_audit.log"
    return AuditLogger(log_path=str(log_file))


# ─── Agent 相关 Fixture ───────────────────────────────────────

@pytest.fixture
def mock_nlu_engine():
    """创建 mock NLU 引擎"""
    engine = MagicMock()
    engine.parse.return_value = MagicMock(
        is_task=True,
        intent=MagicMock(value="inspect"),
        entities={"host": "localhost"},
        raw_input="检查本机",
        error_message=None,
        direct_response=None,
    )
    engine.load.return_value = None
    return engine


@pytest.fixture
def mock_agent_memory(tmp_path):
    """创建临时目录下的 Agent 记忆"""
    from keeper.agent.memory import AgentMemory

    return AgentMemory(memory_dir=tmp_path)


# ─── 网络相关 Mock ────────────────────────────────────────────

@pytest.fixture
def mock_subprocess_success():
    """Mock subprocess.run 返回成功"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "mock output"
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result) as mocked:
        yield mocked


@pytest.fixture
def mock_subprocess_failure():
    """Mock subprocess.run 返回失败"""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "command failed"
    with patch("subprocess.run", return_value=mock_result) as mocked:
        yield mocked


# ─── 环境检测 Fixture ─────────────────────────────────────────

@pytest.fixture
def has_docker():
    """检查 Docker 是否可用，不可用则跳过"""
    import shutil
    if not shutil.which("docker"):
        pytest.skip("Docker not available")


@pytest.fixture
def has_nmap():
    """检查 nmap 是否可用"""
    import shutil
    if not shutil.which("nmap"):
        pytest.skip("nmap not available")


@pytest.fixture
def has_llm_key():
    """检查是否配置了 LLM API Key"""
    if not os.getenv("KEEPER_API_KEY"):
        pytest.skip("KEEPER_API_KEY not set")
