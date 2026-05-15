"""配置管理模块

增强：
- 文件锁（fcntl.flock）防止并发读写冲突
- 跨平台兼容（Windows 使用 msvcrt，Linux/Mac 使用 fcntl）
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, Any, Generator
from dataclasses import dataclass, field


# ─── 跨平台文件锁 ─────────────────────────────────────────────

@contextmanager
def _file_lock(file_path: Path, exclusive: bool = True) -> Generator:
    """跨平台文件锁上下文管理器

    Args:
        file_path: 要锁定的文件路径（使用 .lock 后缀的锁文件）
        exclusive: True=排他锁（写）, False=共享锁（读）
    """
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = None
    try:
        lock_fd = open(lock_path, "w")

        if sys.platform == "win32":
            # Windows: msvcrt
            import msvcrt
            if exclusive:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            # Linux/Mac: fcntl
            import fcntl
            if exclusive:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            else:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)

        yield

    finally:
        if lock_fd is not None:
            if sys.platform == "win32":
                try:
                    import msvcrt
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                try:
                    import fcntl
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            lock_fd.close()


# ─── 配置数据类 ───────────────────────────────────────────────

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
    language: str = "zh"  # 语言设置 (zh / en)
    llm: LLMConfig = field(default_factory=LLMConfig)
    profiles: Dict[str, Any] = field(default_factory=dict)
    k8s: Dict[str, Any] = field(default_factory=dict)  # K8s 集群配置
    notifications: Dict[str, Any] = field(default_factory=dict)  # 通知配置
    timeouts: Dict[str, int] = field(default_factory=lambda: {
        "ssh": 30,
        "k8s": 30,
        "llm": 60,
        "network": 10,
        "shell": 30,
    })  # 超时配置（秒）
    _config_dir: Optional[Path] = field(default=None, repr=False)
    _config_file: Optional[Path] = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量加载配置（仅作为默认值）"""
        config = cls(
            log_level=os.getenv("KEEPER_LOG_LEVEL", "INFO"),
            llm=LLMConfig.from_env(),
        )
        # 自动从配置文件加载（覆盖默认值）
        config.load()
        return config

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
        """从配置文件加载（带共享锁）"""
        import yaml

        if not self.config_file.exists():
            return

        with _file_lock(self.config_file, exclusive=False):
            with open(self.config_file) as f:
                data = yaml.safe_load(f)
                if data:
                    self.current_profile = data.get("current_profile", "default")
                    self.language = data.get("language", "zh")
                    self.profiles = data.get("profiles", {})
                    self.k8s = data.get("k8s", {})
                    self.notifications = data.get("notifications", {})
                    self.timeouts.update(data.get("timeouts", {}))
                    llm_data = data.get("llm", {})
                    if llm_data:
                        self.llm.provider = llm_data.get("provider", self.llm.provider)
                        self.llm.api_key = llm_data.get("api_key", self.llm.api_key)
                        self.llm.base_url = llm_data.get("base_url", self.llm.base_url)
                        self.llm.model = llm_data.get("model", self.llm.model)

    def save(self) -> None:
        """保存配置到文件（带排他锁）"""
        import yaml

        self.config_dir.mkdir(parents=True, exist_ok=True)

        with _file_lock(self.config_file, exclusive=True):
            with open(self.config_file, "w") as f:
                yaml.safe_dump({
                    "current_profile": self.current_profile,
                    "language": self.language,
                    "profiles": self.profiles,
                    "k8s": self.k8s,
                    "notifications": self.notifications,
                    "timeouts": self.timeouts,
                    "llm": self.llm.to_dict(),
                }, f, default_flow_style=False, allow_unicode=True)

    def save_llm_config(self, api_key: Optional[str] = None) -> None:
        """保存 LLM 配置（带排他锁）"""
        import yaml

        self.config_dir.mkdir(parents=True, exist_ok=True)

        if api_key is not None:
            self.llm.api_key = api_key

        with _file_lock(self.config_file, exclusive=True):
            # 先读取现有配置再合并，避免覆盖其他进程的修改
            existing = {}
            if self.config_file.exists():
                with open(self.config_file) as f:
                    existing = yaml.safe_load(f) or {}

            existing.update({
                "current_profile": self.current_profile,
                "profiles": self.profiles,
                "k8s": self.k8s,
                "notifications": self.notifications,
                "llm": self.llm.to_dict(),
            })

            with open(self.config_file, "w") as f:
                yaml.safe_dump(existing, f, default_flow_style=False, allow_unicode=True)

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

    def get_notification_config(self) -> Dict[str, Any]:
        """获取通知配置"""
        return self.notifications

    def set_notification_config(self, config: Dict[str, Any]) -> None:
        """设置通知配置"""
        self.notifications.update(config)
        self.save()
