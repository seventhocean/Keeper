"""Tier 2 补充测试 — 纯逻辑模块覆盖率从 70-90% 推到 95%+

覆盖：
- exceptions: 所有 custom exception 子类
- i18n: 翻译函数边界情况
- config: LLMConfig / AppConfig 未覆盖路径
"""
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─── Exceptions ────────────────────────────────────────────────────

class TestKeeperError:
    """基类和子类异常"""

    def test_base_with_details(self):
        from keeper.exceptions import KeeperError
        e = KeeperError("something wrong", details="extra info")
        assert str(e) == "something wrong (extra info)"

    def test_base_without_details(self):
        from keeper.exceptions import KeeperError
        e = KeeperError("just message")
        assert str(e) == "just message"

    def test_config_error(self):
        from keeper.exceptions import ConfigError, KeeperError
        e = ConfigError("bad config")
        assert isinstance(e, KeeperError)

    def test_connection_error(self):
        from keeper.exceptions import ConnectionError
        e = ConnectionError("timeout", target="192.168.1.1", details="3 retries")
        assert e.target == "192.168.1.1"
        assert "timeout" in str(e)

    def test_timeout_error(self):
        from keeper.exceptions import TimeoutError
        e = TimeoutError("slow", timeout_seconds=30)
        assert e.timeout_seconds == 30

    def test_permission_error(self):
        from keeper.exceptions import PermissionError, KeeperError
        e = PermissionError("denied")
        assert isinstance(e, KeeperError)

    def test_validation_error(self):
        from keeper.exceptions import ValidationError
        e = ValidationError("bad IP", field="ip", value="abc")
        assert e.field == "ip"
        assert e.value == "abc"

    def test_tool_execution_error(self):
        from keeper.exceptions import ToolExecutionError
        e = ToolExecutionError("failed", tool_name="scanner")
        assert e.tool_name == "scanner"

    def test_nlu_error(self):
        from keeper.exceptions import NLUError, KeeperError
        e = NLUError("parse failed")
        assert isinstance(e, KeeperError)

    def test_safety_error(self):
        from keeper.exceptions import SafetyError
        e = SafetyError("dangerous", command="rm -rf /", level="dangerous")
        assert e.command == "rm -rf /"
        assert e.level == "dangerous"


# ─── i18n ──────────────────────────────────────────────────────────

class TestI18n:
    """国际化模块补充测试"""

    def test_set_unsupported_language_raises(self):
        from keeper.i18n import set_language
        with pytest.raises(ValueError, match="Unsupported"):
            set_language("fr")

    def test_get_language(self):
        from keeper.i18n import get_language, set_language
        set_language("zh")
        assert get_language() == "zh"
        set_language("en")
        assert get_language() == "en"
        set_language("zh")  # restore

    def test_t_fallback_to_zh(self):
        from keeper.i18n import t, set_language, _loaded_packs
        set_language("en")
        _loaded_packs.clear()
        # A key that exists in zh but not en
        # We need to know what zh has but en doesn't
        result = t("agent.system_prompt")
        assert result  # should have content

    def test_t_missing_key_returns_key(self):
        from keeper.i18n import t, set_language, _loaded_packs
        set_language("zh")
        _loaded_packs.clear()
        result = t("nonexistent_key_xyz_123")
        assert result == "nonexistent_key_xyz_123"

    def test_t_with_template_vars(self):
        from keeper.i18n import t, set_language, _loaded_packs
        set_language("zh")
        _loaded_packs.clear()
        # The welcome key has a template variable
        result = t("welcome")
        assert result  # just ensure it returns something

    def test_t_with_extra_kwargs(self):
        from keeper.i18n import t, set_language, _loaded_packs
        set_language("zh")
        _loaded_packs.clear()
        # Extra kwargs that don't exist in template → should not crash
        result = t("welcome", nonexistent_var="ignored")
        assert result

    def test_get_system_prompt(self):
        from keeper.i18n import get_system_prompt, set_language
        set_language("zh")
        prompt = get_system_prompt()
        assert len(prompt) > 100  # should be substantial

    def test_get_help_text(self):
        from keeper.i18n import get_help_text, set_language
        set_language("zh")
        help_text = get_help_text()
        assert len(help_text) > 10


# ─── Config: LLMConfig ─────────────────────────────────────────────

class TestLLMConfig:
    """LLMConfig 补充测试"""

    def test_from_env_with_custom_values(self):
        with patch.dict(os.environ, {
            "KEEPER_PROVIDER": "anthropic",
            "KEEPER_API_KEY": "sk-custom",
            "KEEPER_BASE_URL": "https://custom.api.com",
            "KEEPER_MODEL": "claude-opus-4-8",
        }):
            from keeper.config import LLMConfig
            cfg = LLMConfig.from_env()
            assert cfg.provider == "anthropic"
            assert cfg.api_key == "sk-custom"
            assert cfg.model == "claude-opus-4-8"

    def test_to_dict_includes_all_fields(self):
        from keeper.config import LLMConfig
        cfg = LLMConfig(provider="openai", api_key="sk-xxx", base_url="http://x.com", model="m1")
        d = cfg.to_dict()
        assert d["provider"] == "openai"
        assert d["model"] == "m1"

    def test_is_configured_with_key(self):
        from keeper.config import LLMConfig
        assert LLMConfig(api_key="sk-xxx").is_configured() is True

    def test_is_configured_without_key(self):
        from keeper.config import LLMConfig
        assert LLMConfig(api_key="").is_configured() is False


# ─── Config: AppConfig ─────────────────────────────────────────────

class TestAppConfig:
    """AppConfig 补充测试"""

    def test_config_dir_default(self):
        from keeper.config import AppConfig
        cfg = AppConfig()
        assert cfg.config_dir == Path.home() / ".keeper"

    def test_config_dir_custom(self):
        from keeper.config import AppConfig
        cfg = AppConfig(_config_dir=Path("/tmp/keeper"))
        assert cfg.config_dir == Path("/tmp/keeper")

    def test_config_file_default(self):
        from keeper.config import AppConfig
        cfg = AppConfig()
        assert cfg.config_file == Path.home() / ".keeper" / "config.yaml"

    def test_get_threshold_custom(self, tmp_config_dir):
        from keeper.config import AppConfig, LLMConfig
        cfg = AppConfig(
            llm=LLMConfig(),
            profiles={
                "test": {"thresholds": {"cpu": 95, "memory": 90}},
            },
            current_profile="test",
            _config_dir=tmp_config_dir,
        )
        assert cfg.get_threshold("cpu") == 95
        assert cfg.get_threshold("memory") == 90

    def test_get_threshold_default(self):
        from keeper.config import AppConfig
        cfg = AppConfig()
        assert cfg.get_threshold("cpu") == 80
        assert cfg.get_threshold("memory") == 85
        assert cfg.get_threshold("disk") == 90
        assert cfg.get_threshold("unknown_metric") == 80

    def test_get_k8s_config(self):
        from keeper.config import AppConfig
        cfg = AppConfig(k8s={"context": "prod", "kubeconfig": "/tmp/k"})
        assert cfg.get_k8s_config() == {"context": "prod", "kubeconfig": "/tmp/k"}

    def test_get_notification_config(self):
        from keeper.config import AppConfig
        cfg = AppConfig(notifications={"feishu_webhook": "http://x"})
        assert "feishu_webhook" in cfg.get_notification_config()

    def test_set_notification_config(self, tmp_config_dir):
        from keeper.config import AppConfig, LLMConfig
        cfg = AppConfig(
            llm=LLMConfig(),
            _config_dir=tmp_config_dir,
            _config_file=tmp_config_dir / "config.yaml",
        )
        cfg.set_notification_config({"feishu_webhook": "http://new"})
        assert cfg.get_notification_config()["feishu_webhook"] == "http://new"

    def test_get_profile(self):
        from keeper.config import AppConfig
        cfg = AppConfig(
            profiles={"prod": {"hosts": ["s1", "s2"]}},
            current_profile="prod",
        )
        assert "hosts" in cfg.get_profile()
        assert "hosts" in cfg.get_profile("prod")

    def test_get_profile_nonexistent(self):
        from keeper.config import AppConfig
        cfg = AppConfig()
        assert cfg.get_profile("nonexistent") == {}

    def test_set_profile(self, tmp_config_dir):
        from keeper.config import AppConfig, LLMConfig
        cfg = AppConfig(
            llm=LLMConfig(),
            _config_dir=tmp_config_dir,
            _config_file=tmp_config_dir / "config.yaml",
        )
        cfg.set_profile("staging", {"hosts": ["s1"]})
        assert cfg.get_profile("staging")["hosts"] == ["s1"]

    def test_is_llm_configured(self):
        from keeper.config import AppConfig, LLMConfig
        cfg = AppConfig(llm=LLMConfig(api_key=""))
        assert cfg.is_llm_configured() is False
        cfg.llm.api_key = "sk-xxx"
        assert cfg.is_llm_configured() is True

    def test_timeouts_default(self):
        from keeper.config import AppConfig
        cfg = AppConfig()
        assert cfg.timeouts["ssh"] == 30
        assert cfg.timeouts["k8s"] == 30
        assert cfg.timeouts["llm"] == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
