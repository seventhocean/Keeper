"""Plugin 系统 — 用户自定义工具的自动发现和加载

用户可以在 ~/.keeper/plugins/ 目录下放置 Python 文件来扩展 Keeper 的能力。

## 插件约定

每个插件文件需要满足以下条件：
1. 放在 ~/.keeper/plugins/ 目录下
2. 文件名以 .py 结尾（不以 _ 开头）
3. 文件中使用 @tool 装饰器定义工具函数
4. 导出一个 TOOLS 列表，包含所有要注册的工具

## 示例插件 (~/.keeper/plugins/my_tool.py)

```python
from keeper.agent.plugins import tool

@tool
def check_redis(host: str = "localhost", port: int = 6379) -> str:
    \"\"\"检查 Redis 服务器状态

    Args:
        host: Redis 主机地址
        port: Redis 端口号

    Returns:
        Redis 服务器信息
    \"\"\"
    import subprocess
    result = subprocess.run(
        ["redis-cli", "-h", host, "-p", str(port), "INFO", "server"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return result.stdout[:2000]
    return f"[错误] Redis 连接失败: {result.stderr}"

# 必须导出 TOOLS 列表
TOOLS = [check_redis]
```

## 加载机制

- 启动时扫描 ~/.keeper/plugins/ 目录
- 动态导入每个 .py 文件
- 收集文件中的 TOOLS 列表
- 合并到 Agent Loop 的可用工具中
- 加载失败时记录警告，不影响主流程
"""
import importlib.util
import sys
from pathlib import Path
from typing import List, Any

# 重新导出 tool 装饰器，方便插件使用
try:
    from langchain_core.tools import tool
except ImportError:
    # Fallback 装饰器
    from typing import Callable

    def tool(func: Callable) -> Callable:
        """Fallback @tool decorator for plugins when langchain is not installed."""
        func.name = func.__name__
        func.description = (func.__doc__ or "").split("\n")[0]
        func.is_tool = True

        def invoke(args: dict) -> str:
            return func(**args)

        func.invoke = invoke
        return func


# ─── 插件目录 ────────────────────────────────────────────────

DEFAULT_PLUGINS_DIR = Path.home() / ".keeper" / "plugins"


def get_plugins_dir() -> Path:
    """获取插件目录路径"""
    return DEFAULT_PLUGINS_DIR


def discover_plugins(plugins_dir: Path = None) -> List[Any]:
    """发现并加载所有插件中的工具

    Args:
        plugins_dir: 插件目录，默认 ~/.keeper/plugins/

    Returns:
        所有插件中注册的工具列表
    """
    plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR

    if not plugins_dir.exists():
        return []

    loaded_tools = []
    errors = []

    for plugin_file in sorted(plugins_dir.glob("*.py")):
        # 跳过以 _ 开头的文件（如 __init__.py, _helper.py）
        if plugin_file.name.startswith("_"):
            continue

        try:
            tools = _load_plugin_file(plugin_file)
            loaded_tools.extend(tools)
        except Exception as e:
            errors.append((plugin_file.name, str(e)))

    # 输出加载错误（不中断）
    if errors:
        import logging
        logger = logging.getLogger("keeper.plugins")
        for name, err in errors:
            logger.warning(f"[Plugin] 加载失败: {name} — {err}")

    return loaded_tools


def _load_plugin_file(file_path: Path) -> List[Any]:
    """加载单个插件文件

    Args:
        file_path: 插件 .py 文件路径

    Returns:
        该插件中导出的工具列表
    """
    module_name = f"keeper_plugin_{file_path.stem}"

    # 使用 importlib 动态加载模块
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块规格: {file_path}")

    module = importlib.util.module_from_spec(spec)

    # 临时加入 sys.modules 以支持模块内部的相对导入
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # 清理
        sys.modules.pop(module_name, None)
        raise ImportError(f"执行插件模块失败: {e}") from e

    # 提取 TOOLS 列表
    tools = getattr(module, "TOOLS", None)
    if tools is None:
        # 尝试自动发现所有带 is_tool 属性的对象
        tools = []
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if callable(attr) and (
                getattr(attr, "is_tool", False) or
                hasattr(attr, "name") and hasattr(attr, "description")
            ):
                tools.append(attr)

    if not isinstance(tools, (list, tuple)):
        tools = [tools] if tools else []

    return list(tools)


def list_plugins(plugins_dir: Path = None) -> List[dict]:
    """列出所有已安装的插件信息（不加载执行）

    Returns:
        插件信息列表 [{"name": "xxx", "path": "...", "description": "..."}]
    """
    plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR

    if not plugins_dir.exists():
        return []

    plugins = []
    for plugin_file in sorted(plugins_dir.glob("*.py")):
        if plugin_file.name.startswith("_"):
            continue

        # 从文件头部提取描述
        description = ""
        try:
            with open(plugin_file, "r", encoding="utf-8") as f:
                first_lines = f.readlines()[:10]
                for line in first_lines:
                    line = line.strip()
                    if line.startswith('"""') or line.startswith("'''"):
                        description = line.strip("\"' ")
                        break
                    elif line.startswith("#") and not line.startswith("#!"):
                        description = line.lstrip("# ")
                        break
        except Exception:
            pass

        plugins.append({
            "name": plugin_file.stem,
            "path": str(plugin_file),
            "description": description or "(无描述)",
        })

    return plugins


def format_plugins_info(plugins_dir: Path = None) -> str:
    """格式化插件信息为展示文本"""
    plugins = list_plugins(plugins_dir)
    plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR

    if not plugins:
        return (
            f"[Plugin] 未发现插件\n\n"
            f"插件目录: {plugins_dir}\n"
            f"使用方法: 在上述目录中放置 .py 文件即可扩展 Keeper 的能力。\n"
            f"详见: keeper/agent/plugins.py 中的文档和示例。"
        )

    lines = [f"[Plugin] 已加载 {len(plugins)} 个插件:"]
    lines.append("━" * 50)
    for p in plugins:
        lines.append(f"  • {p['name']}: {p['description']}")
    lines.append("━" * 50)
    lines.append(f"插件目录: {plugins_dir}")
    return "\n".join(lines)
