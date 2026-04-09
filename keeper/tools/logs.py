"""系统日志查询工具"""
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any


class LogTools:
    """系统日志查询工具类"""

    COMMON_LOG_PATHS = {
        "system": "/var/log/syslog",
        "messages": "/var/log/messages",
        "secure": "/var/log/secure",
        "auth": "/var/log/auth.log",
        "kern": "/var/log/kern.log",
        "nginx_access": "/var/log/nginx/access.log",
        "nginx_error": "/var/log/nginx/error.log",
        "mysql": "/var/log/mysql/error.log",
        "mysql_slow": "/var/log/mysql/slow-query.log",
        "docker": "/var/log/docker.log",
        "cron": "/var/log/cron",
    }

    @staticmethod
    def query_journal(
        lines: int = 100,
        unit: Optional[str] = None,
        since: Optional[str] = None,
        keyword: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> tuple[bool, str]:
        """查询 journalctl 日志

        Args:
            lines: 显示行数
            unit: systemd 服务名称 (如 nginx, docker)
            since: 时间范围 (如 "2026-04-08", "1 hour ago")
            keyword: 关键词过滤
            priority: 日志级别 (emerg, alert, crit, err, warning, notice, info, debug)

        Returns:
            (success, output)
        """
        cmd = ["journalctl", "--no-pager", "-n", str(lines)]

        if unit:
            cmd.extend(["-u", unit])
        if since:
            cmd.extend(["--since", since])
        if priority:
            cmd.extend(["-p", priority])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # journalctl 可能在某些系统上不可用
                return False, f"journalctl 不可用：{result.stderr}"

            output = result.stdout

            # 关键词过滤
            if keyword:
                filtered_lines = [
                    line for line in output.split("\n")
                    if keyword.lower() in line.lower()
                ]
                output = "\n".join(filtered_lines)

            return True, output

        except subprocess.TimeoutExpired:
            return False, "journalctl 查询超时"
        except FileNotFoundError:
            return False, "journalctl 未安装，请尝试使用 '日志文件' 命令查询文件日志"
        except Exception as e:
            return False, f"journalctl 查询失败：{str(e)}"

    @staticmethod
    def query_file(
        path: str,
        lines: int = 50,
        keyword: Optional[str] = None,
    ) -> tuple[bool, str]:
        """查询指定日志文件

        Args:
            path: 日志文件路径
            lines: 显示行数
            keyword: 关键词过滤

        Returns:
            (success, output)
        """
        log_path = Path(path)

        if not log_path.exists():
            return False, f"日志文件不存在：{path}"

        if not log_path.is_file():
            return False, f"路径不是文件：{path}"

        try:
            # 使用 tail 获取最后 N 行
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return False, f"读取日志文件失败：{result.stderr}"

            output = result.stdout

            # 关键词过滤
            if keyword:
                filtered_lines = [
                    line for line in output.split("\n")
                    if keyword.lower() in line.lower()
                ]
                output = "\n".join(filtered_lines)

            return True, output

        except subprocess.TimeoutExpired:
            return False, "读取日志文件超时"
        except PermissionError:
            return False, f"权限不足，无法读取日志文件：{path}"
        except Exception as e:
            return False, f"读取日志文件失败：{str(e)}"

    @staticmethod
    def list_log_files() -> tuple[bool, List[Dict[str, str]]]:
        """列出常见的日志文件路径及状态

        Returns:
            (success, log_files)
            log_files: [{"name": "系统日志", "path": "/var/log/syslog", "exists": True, "size": "1.2MB"}, ...]
        """
        log_files = []

        for name, path in LogTools.COMMON_LOG_PATHS.items():
            p = Path(path)
            exists = p.exists()
            size = ""
            if exists:
                size_bytes = p.stat().st_size
                if size_bytes < 1024:
                    size = f"{size_bytes}B"
                elif size_bytes < 1024 * 1024:
                    size = f"{size_bytes / 1024:.1f}KB"
                else:
                    size = f"{size_bytes / (1024 * 1024):.1f}MB"

            log_files.append({
                "name": name,
                "path": path,
                "exists": exists,
                "size": size,
            })

        return True, log_files

    @staticmethod
    def query_docker_logs(
        container_name: str,
        lines: int = 50,
        keyword: Optional[str] = None,
        since: Optional[str] = None,
    ) -> tuple[bool, str]:
        """查询 Docker 容器日志

        Args:
            container_name: 容器名称或 ID
            lines: 显示行数
            keyword: 关键词过滤
            since: 时间范围 (如 "2026-04-08", "1h")

        Returns:
            (success, output)
        """
        cmd = ["docker", "logs", "--tail", str(lines), container_name]

        if since:
            cmd.extend(["--since", since])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False, f"Docker 查询失败：{result.stderr}"

            # docker logs 输出在 stderr 中
            output = result.stderr or result.stdout

            # 关键词过滤
            if keyword:
                filtered_lines = [
                    line for line in output.split("\n")
                    if keyword.lower() in line.lower()
                ]
                output = "\n".join(filtered_lines)

            return True, output

        except subprocess.TimeoutExpired:
            return False, "Docker 日志查询超时"
        except FileNotFoundError:
            return False, "Docker 未安装或不在 PATH 中"
        except Exception as e:
            return False, f"Docker 日志查询失败：{str(e)}"

    @staticmethod
    def search_logs(
        keyword: str,
        log_type: Optional[str] = None,
        lines: int = 50,
    ) -> tuple[bool, str]:
        """智能搜索日志

        Args:
            keyword: 搜索关键词
            log_type: 日志类型 (journal, file, docker, all)
            lines: 显示行数

        Returns:
            (success, output)
        """
        results = []

        if log_type in (None, "journal", "all"):
            success, output = LogTools.query_journal(lines=lines, keyword=keyword)
            if success and output.strip():
                results.append(("Journal", output))

        if log_type in (None, "docker", "all"):
            # 尝试获取运行中的容器日志
            try:
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    containers = result.stdout.strip().split("\n")
                    for container in containers[:3]:  # 最多查询前 3 个容器
                        success, output = LogTools.query_docker_logs(
                            container, lines=lines, keyword=keyword
                        )
                        if success and output.strip():
                            results.append((f"Docker({container})", output))
            except Exception:
                pass

        if not results:
            return False, f"未在日志中找到关键词：{keyword}"

        output_lines = []
        for source, content in results:
            output_lines.append(f"=== {source} ===")
            output_lines.append(content)
            output_lines.append("")

        return True, "\n".join(output_lines)
