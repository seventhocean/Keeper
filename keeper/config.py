"""配置管理模块"""
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "openai_compatible"
    api_key: str = ""
    base_url: str = ""
    model: str = "claude-sonnet-4-6"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量加载（仅作为默认值）"""
        return cls(
            provider=os.getenv("KEEPER_PROVIDER", "openai_compatible"),
            api_key=os.getenv("KEEPER_API_KEY", ""),
            base_url=os.getenv("KEEPER_BASE_URL", ""),
            model=os.getenv("KEEPER_MODEL", "claude-sonnet-4-6"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于保存）"""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
        }

    def is_configured(self) -> bool:
        """检查是否已配置"""
        return bool(self.api_key)


@dataclass
class AppConfig:
    """应用配置"""
    log_level: str = "INFO"
    current_profile: str = "default"
    llm: LLMConfig = field(default_factory=LLMConfig)
    profiles: Dict[str, Any] = field(default_factory=dict)
    k8s: Dict[str, Any] = field(default_factory=dict)  # K8s 集群配置
    _config_dir: Optional[Path] = field(default=None, repr=False)
    _config_file: Optional[Path] = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量加载配置（仅作为默认值）"""
        return cls(
            log_level=os.getenv("KEEPER_LOG_LEVEL", "INFO"),
            llm=LLMConfig.from_env(),
        )

    @property
    def config_dir(self) -> Path:
        """配置目录"""
        if self._config_dir is None:
            self._config_dir = Path.home() / ".keeper"
        return self._config_dir

    @property
    def config_file(self) -> Path:
        """配置文件路径"""
        if self._config_file is None:
            self._config_file = self.config_dir / "config.yaml"
        return self._config_file

    def load(self) -> None:
        """从配置文件加载"""
        import yaml

        if self.config_file.exists():
            with open(self.config_file) as f:
                data = yaml.safe_load(f)
                if data:
                    self.current_profile = data.get("current_profile", "default")
                    self.profiles = data.get("profiles", {})
                    self.k8s = data.get("k8s", {})
                    llm_data = data.get("llm", {})
                    if llm_data:
                        self.llm.provider = llm_data.get("provider", self.llm.provider)
                        self.llm.api_key = llm_data.get("api_key", self.llm.api_key)
                        self.llm.base_url = llm_data.get("base_url", self.llm.base_url)
                        self.llm.model = llm_data.get("model", self.llm.model)

    def save(self) -> None:
        """保存配置到文件"""
        import yaml

        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 保存所有配置到一个文件
        with open(self.config_file, "w") as f:
            yaml.safe_dump({
                "current_profile": self.current_profile,
                "profiles": self.profiles,
                "k8s": self.k8s,
                "llm": self.llm.to_dict(),
            }, f, default_flow_style=False, allow_unicode=True)

    def save_llm_config(self, api_key: Optional[str] = None) -> None:
        """保存 LLM 配置"""
        import yaml

        self.config_dir.mkdir(parents=True, exist_ok=True)

        if api_key is not None:
            self.llm.api_key = api_key

        # 保存配置
        with open(self.config_file, "w") as f:
            yaml.safe_dump({
                "current_profile": self.current_profile,
                "profiles": self.profiles,
                "k8s": self.k8s,
                "llm": self.llm.to_dict(),
            }, f, default_flow_style=False, allow_unicode=True)

    def is_llm_configured(self) -> bool:
        """检查 LLM 是否已配置"""
        return self.llm.is_configured()

    def get_profile(self, name: Optional[str] = None) -> Dict[str, Any]:
        """获取指定环境配置"""
        profile_name = name or self.current_profile
        return self.profiles.get(profile_name, {})

    def set_profile(self, name: str, config: Dict[str, Any]) -> None:
        """设置环境配置"""
        self.profiles[name] = config
        self.save()

    def get_threshold(self, metric: str, profile: Optional[str] = None) -> int:
        """获取阈值配置"""
        profile_config = self.get_profile(profile)
        thresholds = profile_config.get("thresholds", {})
        defaults = {"cpu": 80, "memory": 85, "disk": 90}
        return thresholds.get(metric, defaults.get(metric, 80))

    def get_k8s_config(self) -> Dict[str, Any]:
        """获取 K8s 集群配置"""
        return self.k8s
