"""自由模式通用工具 — 让 Agent 像 Claude Code 一样自由

这组工具不限定运维场景，而是提供通用能力：
1. run_bash: 执行任意 bash 命令（用户确认后）
2. read_file: 读取服务器上任意文件
3. write_file: 写入/创建文件（需确认）
4. list_directory: 列出目录内容
5. search_files: 搜索文件内容（grep）

安全策略：
- 读操作（read_file, list_directory, search_files）→ 直接执行
- 执行操作（run_bash）→ 安全命令直接执行，危险命令拦截
- 写操作（write_file）→ 需用户确认

与经典工具的区别：
- 经典工具：每个工具有特定用途（inspect_server, k8s_inspect...）
- 自由工具：通用能力，LLM 自己决定怎么用组合
"""
import os
import subprocess
from typing import Optional

try:
    from langchain_core.tools import tool
except ImportError:
    from .tools_registry import tool  # fallback


# ═══════════════════════════════════════════════════════════════
# 核心能力 1：执行任意 Bash 命令
# ═══════════════════════════════════════════════════════════════

@tool
def run_bash(command: str, timeout: int = 30) -> str:
    """在服务器上执行 bash 命令并返回输出。

    你可以执行任何 Linux 命令来收集信息、诊断问题或执行操作。
    常用命令示例：
    - 系统信息: uname -a, uptime, free -h, df -h, top -bn1
    - 进程: ps aux, pidof nginx, kill <pid>
    - 网络: ss -tlnp, ip addr, ping, curl, dig
    - 文件: ls, cat, head, tail, find, du, stat
    - 日志: journalctl, tail -f, grep
    - 服务: systemctl status/restart/stop
    - Docker: docker ps, docker logs, docker exec
    - K8s: kubectl get, kubectl describe, kubectl logs

    注意：rm -rf、dd、mkfs 等高危命令会被安全系统拦截。

    Args:
        command: 要执行的 bash 命令
        timeout: 超时时间（秒），默认 30

    Returns:
        命令的 stdout + stderr 输出
    """
    from .safety import CommandSafetyChecker, SafetyLevel

    # 安全检查
    verdict = CommandSafetyChecker.check(command)
    if verdict.level == SafetyLevel.DANGEROUS:
        return f"[安全拦截] 该命令被判定为高危操作，拒绝执行。\n原因: {verdict.reason}\n命令: {command}"
    if verdict.level == SafetyLevel.DESTRUCTIVE:
        return f"[需用户确认] 该命令为破坏性操作:\n  命令: {command}\n  风险: {verdict.reason}\n请让用户确认后再执行。"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/",
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        if not output.strip():
            return "(命令执行成功，无输出)"

        # 限制输出长度
        if len(output) > 5000:
            output = output[:5000] + f"\n\n... (输出过长，已截断，共 {len(output)} 字符)"

        return output
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout}s: {command}"
    except Exception as e:
        return f"[错误] {type(e).__name__}: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 核心能力 2：读取任意文件
# ═══════════════════════════════════════════════════════════════

@tool
def read_file(path: str, start_line: int = 0, max_lines: int = 200) -> str:
    """读取服务器上的文件内容。

    可以读取任何文本文件：配置文件、日志、代码、数据等。

    Args:
        path: 文件绝对路径（如 /etc/nginx/nginx.conf）
        start_line: 从第几行开始读（0-indexed），用于读取大文件的特定部分
        max_lines: 最多返回的行数，默认 200

    Returns:
        文件内容（带行号）
    """
    path = path.strip()
    if not path:
        return "[错误] 请提供文件路径"

    if not os.path.exists(path):
        return f"[错误] 文件不存在: {path}"

    if os.path.isdir(path):
        return f"[错误] {path} 是目录，请使用 list_directory 工具"

    try:
        file_size = os.path.getsize(path)
        if file_size > 10 * 1024 * 1024:  # 10MB
            return f"[错误] 文件过大 ({file_size / 1024 / 1024:.1f}MB)，请用 run_bash 的 head/tail 命令读取部分内容"

        with open(path, "r", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        selected = all_lines[start_line:start_line + max_lines]

        # 带行号输出
        output_lines = []
        for i, line in enumerate(selected, start=start_line + 1):
            output_lines.append(f"{i:4d} | {line.rstrip()}")

        header = f"[文件] {path} ({total_lines} 行, 显示 {start_line + 1}-{start_line + len(selected)})"
        return header + "\n" + "\n".join(output_lines)

    except PermissionError:
        return f"[错误] 无权限读取: {path}"
    except UnicodeDecodeError:
        return f"[错误] 非文本文件（二进制）: {path}"
    except Exception as e:
        return f"[错误] 读取失败: {type(e).__name__}: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 核心能力 3：写入文件
# ═══════════════════════════════════════════════════════════════

@tool
def write_file(path: str, content: str, mode: str = "overwrite") -> str:
    """写入或创建文件。（⚠️ 写操作，会修改服务器文件）

    用途：修改配置文件、创建脚本、写入数据等。

    Args:
        path: 文件绝对路径
        content: 要写入的内容
        mode: 写入模式
            - "overwrite": 覆盖整个文件（默认）
            - "append": 追加到文件末尾

    Returns:
        操作结果
    """
    path = path.strip()
    if not path:
        return "[错误] 请提供文件路径"

    # 安全检查：不允许写入关键系统文件
    protected_paths = [
        "/etc/passwd", "/etc/shadow", "/etc/sudoers",
        "/boot/", "/dev/", "/proc/", "/sys/",
    ]
    for p in protected_paths:
        if path.startswith(p):
            return f"[安全拦截] 不允许写入系统关键文件: {path}"

    try:
        # 确保目录存在
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        write_mode = "a" if mode == "append" else "w"
        with open(path, write_mode, encoding="utf-8") as f:
            f.write(content)

        file_size = os.path.getsize(path)
        return f"[成功] 文件已{'追加' if mode == 'append' else '写入'}: {path} ({file_size} bytes)"

    except PermissionError:
        return f"[错误] 无权限写入: {path}"
    except Exception as e:
        return f"[错误] 写入失败: {type(e).__name__}: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 核心能力 4：列出目录
# ═══════════════════════════════════════════════════════════════

@tool
def list_directory(path: str = "/", show_hidden: bool = False) -> str:
    """列出目录内容（文件和子目录）。

    Args:
        path: 目录路径，默认 /
        show_hidden: 是否显示隐藏文件（以 . 开头的）

    Returns:
        目录内容列表（类型、大小、名称）
    """
    path = path.strip() or "/"
    if not os.path.exists(path):
        return f"[错误] 目录不存在: {path}"
    if not os.path.isdir(path):
        return f"[错误] {path} 不是目录"

    try:
        entries = os.listdir(path)
        if not show_hidden:
            entries = [e for e in entries if not e.startswith(".")]
        entries.sort()

        lines = [f"[目录] {path} ({len(entries)} 项)"]
        for entry in entries[:100]:  # 最多显示 100 项
            full_path = os.path.join(path, entry)
            try:
                stat = os.stat(full_path)
                if os.path.isdir(full_path):
                    lines.append(f"  📁 {entry}/")
                else:
                    size = stat.st_size
                    if size > 1024 * 1024:
                        size_str = f"{size / 1024 / 1024:.1f}M"
                    elif size > 1024:
                        size_str = f"{size / 1024:.1f}K"
                    else:
                        size_str = f"{size}B"
                    lines.append(f"  📄 {entry} ({size_str})")
            except (PermissionError, OSError):
                lines.append(f"  ❓ {entry} (无法读取)")

        if len(entries) > 100:
            lines.append(f"  ... 还有 {len(entries) - 100} 项")

        return "\n".join(lines)
    except PermissionError:
        return f"[错误] 无权限访问: {path}"
    except Exception as e:
        return f"[错误] {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 核心能力 5：搜索文件内容
# ═══════════════════════════════════════════════════════════════

@tool
def search_files(pattern: str, path: str = "/var/log", file_pattern: str = "*", max_results: int = 30) -> str:
    """在文件中搜索文本内容（类似 grep -r）。

    用于快速查找错误信息、配置项、特定日志等。

    Args:
        pattern: 搜索的文本/正则模式
        path: 搜索的目录路径，默认 /var/log
        file_pattern: 文件名过滤（如 *.log, *.conf）
        max_results: 最大返回结果数

    Returns:
        匹配的行（含文件名和行号）
    """
    try:
        cmd = [
            "grep", "-rn", "--include", file_pattern,
            "-m", str(max_results),
            pattern, path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if not output:
            return f"[搜索] 在 {path} 中未找到匹配 '{pattern}' 的内容"

        lines = output.split("\n")
        header = f"[搜索] '{pattern}' in {path} — 找到 {len(lines)} 条匹配"
        # 截断每行长度
        truncated = [l[:200] for l in lines[:max_results]]
        return header + "\n" + "\n".join(truncated)

    except subprocess.TimeoutExpired:
        return f"[超时] 搜索超时，请缩小搜索范围"
    except FileNotFoundError:
        return "[错误] grep 命令不可用"
    except Exception as e:
        return f"[错误] 搜索失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 工具注册表 — 自由模式使用此列表
# ═══════════════════════════════════════════════════════════════

FREE_TOOLS = [
    run_bash,
    read_file,
    write_file,
    list_directory,
    search_files,
]


def get_free_tools_description() -> str:
    """获取自由模式工具描述"""
    return """
🚀 Agent 自由模式 — 通用能力工具:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • run_bash: 执行任意 bash 命令
  • read_file: 读取任意文件
  • write_file: 写入/创建文件
  • list_directory: 浏览目录结构
  • search_files: 搜索文件内容 (grep)

我可以像运维工程师一样自由操作这台服务器。
直接告诉我你想做什么，我会自己规划步骤并执行。
"""
