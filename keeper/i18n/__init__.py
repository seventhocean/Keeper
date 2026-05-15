"""国际化（i18n）模块 — 多语言支持

设计：
- 使用 YAML 文件存储各语言的文本模板
- 通过 get_text(key) 获取当前语言的文本
- 支持运行时切换语言
- 默认跟随配置文件或环境变量 KEEPER_LANG

支持的语言：
- zh: 中文（默认）
- en: English

使用方式：
    from keeper.i18n import t, set_language

    set_language("en")
    print(t("welcome"))  # "Hello! I'm Keeper, your intelligent ops assistant."
    print(t("agent.system_prompt"))  # English system prompt
"""
import os
from typing import Dict, Any, Optional
from pathlib import Path

# 支持的语言
SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"

# 当前语言（模块级状态）
_current_language: str = os.getenv("KEEPER_LANG", DEFAULT_LANGUAGE)

# 缓存已加载的语言包
_loaded_packs: Dict[str, Dict[str, str]] = {}


def set_language(lang: str) -> None:
    """设置当前语言

    Args:
        lang: 语言代码 (zh / en)
    """
    global _current_language
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}. Available: {SUPPORTED_LANGUAGES}")
    _current_language = lang


def get_language() -> str:
    """获取当前语言"""
    return _current_language


def _load_pack(lang: str) -> Dict[str, str]:
    """加载语言包"""
    if lang in _loaded_packs:
        return _loaded_packs[lang]

    pack_dir = Path(__file__).parent / "packs"
    pack_file = pack_dir / f"{lang}.py"

    if not pack_file.exists():
        # Fallback to zh
        pack_file = pack_dir / "zh.py"

    # 动态导入语言包模块
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"keeper_i18n_{lang}", pack_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pack = getattr(module, "TEXTS", {})
    _loaded_packs[lang] = pack
    return pack


def t(key: str, **kwargs) -> str:
    """获取翻译文本

    Args:
        key: 文本键名（点分隔路径，如 "agent.system_prompt"）
        **kwargs: 模板变量替换

    Returns:
        翻译后的文本。找不到时返回 key 本身。

    Example:
        t("welcome")  # "你好！我是 Keeper..."
        t("error.connection", host="192.168.1.1")  # "无法连接到 192.168.1.1"
    """
    pack = _load_pack(_current_language)

    # 支持点分隔的嵌套键
    text = pack.get(key, "")
    if not text:
        # 尝试 fallback 到中文
        if _current_language != "zh":
            zh_pack = _load_pack("zh")
            text = zh_pack.get(key, key)
        else:
            text = key

    # 变量替换
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return text


def get_system_prompt() -> str:
    """获取当前语言的 Agent System Prompt"""
    return t("agent.system_prompt")


def get_help_text() -> str:
    """获取帮助文本"""
    return t("agent.help")
