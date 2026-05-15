"""工具注册中心 — 将所有运维工具注册为 LLM 可调用的 Tool

设计理念：
- 每个 @tool 装饰的函数就是一个 LLM 可以自主调用的能力
- LLM 根据 docstring 理解工具用途，自动决定何时调用
- 类似 Claude Code 的 Tool Use 机制

兼容性：
- 有 langchain_core 时：使用 @tool 装饰器（完整 Tool Use 支持）
- 无 langchain_core 时：使用 fallback 装饰器（保持函数可调用，但无 LLM 绑定）
"""
import subprocess
from typing import Optional, Callable, Any

# ─── 兼容层：langchain_core 可选 ─────────────────────────────────
try:
    from langchain_core.tools import tool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

    # Fallback：无 langchain 时用简单装饰器保持函数签名不变
    def tool(func: Callable) -> Callable:
        """Fallback @tool decorator when langchain is not installed."""
        func.name = func.__name__
        func.description = (func.__doc__ or "").split("\n")[0]
        func.is_tool = True

        def invoke(args: dict) -> str:
            return func(**args)

        func.invoke = invoke
        return func


# ═══════════════════════════════════════════════════════════════
# 服务器监控类工具
# ═══════════════════════════════════════════════════════════════

@tool
def inspect_server(host: str = "localhost") -> str:
    """检查服务器资源状态，包括 CPU、内存、磁盘使用率、系统负载和 Top 进程。

    Args:
        host: 目标主机 IP 或 hostname，默认检查本机 (localhost)

    Returns:
        格式化的服务器状态报告
    """
    from keeper.tools.server import ServerTools, format_status_report
    from keeper.tools.alert import AlertEngine
    try:
        status = ServerTools.inspect_server(host)
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        report = format_status_report(status, thresholds)

        # 自动写入巡检历史（SQLite）
        if not status.ssh_failed:
            try:
                from keeper.storage.history import InspectionHistory
                history = InspectionHistory()
                history.save(
                    host=status.host,
                    cpu=status.cpu_percent,
                    memory=status.memory_percent,
                    disk=status.disk_percent,
                    load=status.load_avg_1m,
                    raw_data={
                        "memory_used_gb": status.memory_used_gb,
                        "memory_total_gb": status.memory_total_gb,
                        "disk_used_gb": status.disk_used_gb,
                        "disk_total_gb": status.disk_total_gb,
                        "load_avg_5m": status.load_avg_5m,
                        "load_avg_15m": status.load_avg_15m,
                        "boot_time": status.boot_time,
                        "top_processes": status.top_processes[:5],
                    },
                )
            except Exception:
                pass  # 历史写入失败不影响巡检结果

        # 自动触发告警检查
        try:
            data = {
                "cpu_percent": status.cpu_percent,
                "memory_percent": status.memory_percent,
                "disk_percent": status.disk_percent,
                "load_avg": {"1m": status.load_avg_1m, "5m": status.load_avg_5m, "15m": status.load_avg_15m},
                "failed_services": [],
                "swap_percent": getattr(status, "swap_percent", 0),
            }
            alerts = AlertEngine.check_server(data, thresholds)
            if alerts:
                report += "\n\n⚠️ 告警：\n"
                for a in alerts:
                    report += f"  [{a.severity}] {a.name}: {a.message}\n"
        except Exception:
            pass  # 告警失败不影响巡检结果

        # 自动追加与上次对比信息（如有历史数据）
        try:
            from keeper.tools.comparator import InspectionComparator
            comparator = InspectionComparator()
            comp_report = comparator.compare_with_last(host)
            if comp_report and any(d.warning for d in comp_report.diffs):
                report += f"\n\n📊 与上次对比: {comp_report.summary}"
        except Exception:
            pass

        return report
    except Exception as e:
        return f"[错误] 服务器巡检失败 ({host}): {str(e)}"


@tool
def get_top_processes(n: int = 10) -> str:
    """获取当前系统资源占用最高的进程列表（按 CPU + 内存排序）

    Args:
        n: 返回的进程数量，默认 10

    Returns:
        Top N 进程列表（PID、名称、CPU%、内存%）
    """
    from keeper.tools.server import ServerTools
    try:
        processes = ServerTools.get_top_processes(n)
        if not processes:
            return "未获取到进程信息"
        lines = [f"{'PID':<8} {'进程名':<20} {'CPU%':<8} {'MEM%':<8}"]
        lines.append("-" * 50)
        for p in processes:
            lines.append(
                f"{p['pid']:<8} {p['name']:<20} {p['cpu_percent']:<8.1f} {p['memory_percent']:<8.1f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[错误] 获取进程信息失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 日志查询类工具
# ═══════════════════════════════════════════════════════════════

@tool
def query_system_logs(
    lines: int = 50,
    unit: Optional[str] = None,
    since: Optional[str] = None,
    keyword: Optional[str] = None,
    priority: Optional[str] = None,
) -> str:
    """查询系统日志（基于 journalctl）

    Args:
        lines: 返回的日志行数，默认 50
        unit: systemd 服务名称过滤 (如 nginx, mysql, docker, sshd)
        since: 时间范围过滤 (如 "1 hour ago", "today", "2026-05-15")
        keyword: 关键词过滤（大小写不敏感）
        priority: 日志级别过滤 (emerg/alert/crit/err/warning/notice/info/debug)

    Returns:
        匹配的日志内容
    """
    from keeper.tools.logs import LogTools
    try:
        success, output = LogTools.query_journal(
            lines=lines, unit=unit, since=since,
            keyword=keyword, priority=priority,
        )
        if success:
            return output if output.strip() else "(日志为空，未找到匹配记录)"
        return f"日志查询失败: {output}"
    except Exception as e:
        return f"[错误] 日志查询异常: {str(e)}"


@tool
def read_log_file(file_path: str, lines: int = 50, keyword: Optional[str] = None) -> str:
    """读取指定日志文件的最后 N 行（支持关键词过滤）

    Args:
        file_path: 日志文件路径 (如 /var/log/nginx/error.log)
        lines: 读取的行数，默认最后 50 行
        keyword: 关键词过滤

    Returns:
        日志文件内容
    """
    from keeper.tools.logs import LogTools
    try:
        success, output = LogTools.query_file(path=file_path, lines=lines, keyword=keyword)
        return output if success else f"读取失败: {output}"
    except Exception as e:
        return f"[错误] 读取日志文件失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 网络诊断类工具
# ═══════════════════════════════════════════════════════════════

@tool
def ping_host(host: str, count: int = 4) -> str:
    """对目标主机执行 Ping 测试，检查网络连通性和延迟

    Args:
        host: 目标主机 IP 或域名
        count: 发送的 ICMP 包数量，默认 4

    Returns:
        Ping 测试结果（丢包率、延迟等）
    """
    from keeper.tools.network import NetworkTools, format_ping_result
    try:
        result = NetworkTools.ping(host, count=count)
        return format_ping_result(result)
    except Exception as e:
        return f"[错误] Ping 失败: {str(e)}"


@tool
def check_port(host: str, port: int) -> str:
    """检查目标主机的指定端口是否开放

    Args:
        host: 目标主机 IP 或域名
        port: 要检查的端口号

    Returns:
        端口状态（开放/关闭/超时）
    """
    from keeper.tools.network import NetworkTools, format_port_result
    try:
        result = NetworkTools.check_port(host, port)
        return format_port_result(result)
    except Exception as e:
        return f"[错误] 端口检测失败: {str(e)}"


@tool
def dns_lookup(domain: str) -> str:
    """查询域名的 DNS 解析记录

    Args:
        domain: 要查询的域名

    Returns:
        DNS 解析结果（A记录、CNAME等）
    """
    from keeper.tools.network import NetworkTools, format_dns_result
    try:
        result = NetworkTools.dns_lookup(domain)
        return format_dns_result(result)
    except Exception as e:
        return f"[错误] DNS 查询失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# K8s 集群管理类工具
# ═══════════════════════════════════════════════════════════════

@tool
def k8s_cluster_inspect(namespace: Optional[str] = None) -> str:
    """对 K8s 集群执行全面巡检，检查节点、Pod、工作负载、服务、存储等状态

    Args:
        namespace: 指定 namespace 过滤，为空则检查所有 namespace

    Returns:
        K8s 集群巡检报告（包含异常检测和健康评分）
    """
    try:
        from keeper.tools.k8s.client import K8sClient
        from keeper.tools.k8s.inspector import K8sInspector
        from keeper.tools.k8s.formatter import format_cluster_report

        client = K8sClient()
        success, msg = client.connect()
        if not success:
            return (
                f"K8s 连接失败: {msg}\n\n"
                f"请向用户确认：\n"
                f"  1. kubeconfig 路径（~/.kube/config 或 /etc/rancher/k3s/k3s.yaml）\n"
                f"  2. 集群类型（K8s / K3s）\n"
                f"  3. 是否需要指定 context\n\n"
                f"用户提供信息后，用 execute_shell_command 设置 KUBECONFIG 环境变量后重试。"
            )

        ok, report = K8sInspector.inspect_cluster(client, namespace=namespace)
        if not ok:
            return f"K8s 巡检失败: {report}"
        return format_cluster_report(report, namespace=namespace)
    except ImportError:
        return (
            "kubernetes Python SDK 未安装。\n"
            "你可以帮用户安装: pip install kubernetes\n"
            "或用 execute_shell_command 执行 kubectl 命令行替代。\n"
            "kubectl 命令不需要安装 Python SDK，功能和 SDK 一致。"
        )
    except Exception as e:
        return f"[错误] K8s 巡检失败: {str(e)}"


@tool
def k8s_pod_logs(
    pod_name: str,
    namespace: str = "default",
    lines: int = 50,
    keyword: Optional[str] = None,
) -> str:
    """查看 K8s Pod 的日志输出

    Args:
        pod_name: Pod 名称（支持前缀模糊匹配，如 "nginx" 可匹配 "nginx-xxx-abc"）
        namespace: 命名空间，默认 "default"
        lines: 返回的日志行数
        keyword: 关键词过滤

    Returns:
        Pod 日志内容
    """
    try:
        from keeper.tools.k8s.client import K8sClient
        from keeper.tools.k8s.logs import K8sLogTools

        client = K8sClient()
        success, msg = client.connect()
        if not success:
            return (
                f"K8s 连接失败: {msg}\n\n"
                f"请向用户确认：\n"
                f"  1. kubeconfig 路径（~/.kube/config 或 /etc/rancher/k3s/k3s.yaml）\n"
                f"  2. 集群类型（K8s / K3s）\n"
                f"  3. 是否需要指定 context\n\n"
                f"用户提供信息后，用 execute_shell_command 设置 KUBECONFIG 环境变量后重试。"
            )

        success, output = K8sLogTools.get_pod_logs(
            client, pod_name, namespace, lines, keyword
        )
        return output
    except ImportError:
        return "[错误] kubernetes SDK 未安装"
    except Exception as e:
        return f"[错误] 获取 Pod 日志失败: {str(e)}"


@tool
def k8s_scale_deployment(name: str, replicas: int, namespace: str = "default") -> str:
    """扩缩容 K8s Deployment 的副本数

    Args:
        name: Deployment 名称
        replicas: 目标副本数
        namespace: 命名空间，默认 "default"

    Returns:
        操作结果
    """
    try:
        from keeper.tools.k8s.client import K8sClient
        from keeper.tools.k8s.ops import K8sOps

        client = K8sClient()
        success, msg = client.connect()
        if not success:
            return (
                f"K8s 连接失败: {msg}\n\n"
                f"请向用户确认：\n"
                f"  1. kubeconfig 路径（~/.kube/config 或 /etc/rancher/k3s/k3s.yaml）\n"
                f"  2. 集群类型（K8s / K3s）\n"
                f"  3. 是否需要指定 context\n\n"
                f"用户提供信息后，用 execute_shell_command 设置 KUBECONFIG 环境变量后重试。"
            )

        success, output = K8sOps.scale_deployment(client, name, namespace, replicas)
        return output
    except ImportError:
        return "[错误] kubernetes SDK 未安装"
    except Exception as e:
        return f"[错误] 扩缩容失败: {str(e)}"


@tool
def k8s_restart_deployment(name: str, namespace: str = "default") -> str:
    """滚动重启 K8s Deployment

    Args:
        name: Deployment 名称
        namespace: 命名空间，默认 "default"

    Returns:
        操作结果
    """
    try:
        from keeper.tools.k8s.client import K8sClient
        from keeper.tools.k8s.ops import K8sOps

        client = K8sClient()
        success, msg = client.connect()
        if not success:
            return (
                f"K8s 连接失败: {msg}\n\n"
                f"请向用户确认：\n"
                f"  1. kubeconfig 路径（~/.kube/config 或 /etc/rancher/k3s/k3s.yaml）\n"
                f"  2. 集群类型（K8s / K3s）\n"
                f"  3. 是否需要指定 context\n\n"
                f"用户提供信息后，用 execute_shell_command 设置 KUBECONFIG 环境变量后重试。"
            )

        success, output = K8sOps.restart_deployment(client, name, namespace)
        return output
    except ImportError:
        return "[错误] kubernetes SDK 未安装"
    except Exception as e:
        return f"[错误] 重启失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# Docker 管理类工具
# ═══════════════════════════════════════════════════════════════

@tool
def docker_list_containers(all_containers: bool = True, filter_name: Optional[str] = None) -> str:
    """列出 Docker 容器状态

    Args:
        all_containers: 是否包含已停止的容器，默认 True
        filter_name: 按容器名称过滤

    Returns:
        容器列表（名称、状态、端口映射、运行时间）
    """
    from keeper.tools.docker_tools import DockerTools, format_docker_containers
    try:
        if not DockerTools.is_docker_available():
            return "[错误] Docker 不可用，请检查 Docker 服务是否运行"
        containers = DockerTools.list_containers(all_containers, filter_name)
        stats = DockerTools.get_container_stats()
        return format_docker_containers(containers, stats)
    except Exception as e:
        return f"[错误] Docker 查询失败: {str(e)}"


@tool
def docker_container_logs(container_name: str, lines: int = 50) -> str:
    """查看 Docker 容器日志

    Args:
        container_name: 容器名称或 ID
        lines: 返回的日志行数

    Returns:
        容器日志内容
    """
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        return output if output.strip() else f"容器 {container_name} 无日志输出"
    except subprocess.TimeoutExpired:
        return "[超时] 获取容器日志超时"
    except FileNotFoundError:
        return "[错误] docker 命令未找到"
    except Exception as e:
        return f"[错误] 获取容器日志失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 安全与证书类工具
# ═══════════════════════════════════════════════════════════════

@tool
def scan_ports(host: str) -> str:
    """扫描目标主机的开放端口，分析服务和安全风险

    Args:
        host: 目标主机 IP 地址

    Returns:
        端口扫描结果 + 风险评估
    """
    from keeper.tools.scanner import ScannerTools, format_scan_result, NmapNotInstalledError
    try:
        result = ScannerTools.scan_ports(host)
        return format_scan_result(result)
    except NmapNotInstalledError as e:
        cmd = NmapNotInstalledError.get_install_command()
        return (
            f"nmap 未安装，端口扫描功能不可用。\n\n"
            f"你可以帮用户安装 nmap：\n"
            f"  {cmd}\n\n"
            f"用 execute_shell_command 执行安装命令（需要 sudo 权限）。\n"
            f"安装完成后自动重试扫描。"
        )
    except Exception as e:
        return f"[错误] 端口扫描失败: {str(e)}"


@tool
def check_ssl_cert(target: str) -> str:
    """检查域名的 SSL/TLS 证书状态（过期时间、颁发者、有效性）

    Args:
        target: 要检查的域名 (如 example.com)

    Returns:
        证书信息（过期时间、剩余天数、状态）
    """
    from keeper.tools.cert_monitor import CertMonitor, format_cert_report
    try:
        monitor = CertMonitor()
        certs = monitor.check_domain_cert(target)
        return format_cert_report(certs)
    except Exception as e:
        return f"[错误] 证书检查失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 服务管理工具
# ═══════════════════════════════════════════════════════════════

@tool
def manage_systemd_service(service: str, action: str = "status") -> str:
    """管理 systemd 服务（查看状态/重启/停止/启动）

    Args:
        service: 服务名称 (如 nginx, mysql, docker, sshd)
        action: 操作类型，可选 status/restart/stop/start/enable/disable

    Returns:
        服务状态或操作结果
    """
    allowed_actions = {"status", "restart", "stop", "start", "enable", "disable"}
    if action not in allowed_actions:
        return f"[错误] 不支持的操作: {action}，可选: {', '.join(allowed_actions)}"

    try:
        result = subprocess.run(
            ["systemctl", action, service],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        return output.strip() if output.strip() else f"systemctl {action} {service} 执行完成"
    except subprocess.TimeoutExpired:
        return f"[超时] systemctl {action} {service} 超时"
    except FileNotFoundError:
        return "[错误] systemctl 命令不可用（非 systemd 系统）"
    except Exception as e:
        return f"[错误] 服务操作失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# SSH 远程巡检
# ═══════════════════════════════════════════════════════════════

@tool
def inspect_remote_server(host: str, username: str = "root") -> str:
    """通过 SSH 检查远程服务器的资源状态（CPU/内存/磁盘/负载）

    Args:
        host: 远程服务器 IP 地址
        username: SSH 用户名，默认 root

    Returns:
        远程服务器状态报告
    """
    from keeper.tools.ssh import SSHTools, SSHConfig
    from keeper.tools.server import format_status_report
    try:
        config = SSHConfig(host=host, username=username)
        status = SSHTools.collect_server_status(config)
        if status.ssh_failed:
            return (
                f"SSH 连接 {host} 失败（用户: {username}）。\n\n"
                f"请向用户询问以下信息后重试：\n"
                f"  1. SSH 用户名（默认 root，是否需要更换？）\n"
                f"  2. SSH 密钥路径（如 ~/.ssh/id_rsa）\n"
                f"  3. 或使用密码登录\n"
                f"  4. SSH 端口（非标准端口 22？）\n\n"
                f"用户提供凭据后，你可以用 execute_shell_command 通过 ssh 命令行重试。"
            )
        thresholds = {"cpu": 80, "memory": 85, "disk": 90}
        return format_status_report(status, thresholds)
    except Exception as e:
        return f"[错误] 远程巡检失败 ({host}): {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 通用 Shell 执行（带安全控制）
# ═══════════════════════════════════════════════════════════════

@tool
def execute_shell_command(command: str) -> str:
    """在服务器上执行 Shell 命令。仅允许安全的只读/诊断类命令，危险命令会被拦截。

    适合执行: ps, df, free, top -bn1, netstat, ss, lsof, cat, head, tail, grep, find, systemctl status 等

    Args:
        command: 要执行的 Shell 命令

    Returns:
        命令执行输出
    """
    from keeper.tools.fixer import FixSuggester, SafetyLevel

    # 安全等级检查
    safety = FixSuggester.classify_command_safety(command)
    if safety == SafetyLevel.DANGEROUS:
        return f"[安全拦截] 该命令被判定为高危操作，拒绝执行: {command}"
    if safety == SafetyLevel.DESTRUCTIVE:
        return f"[需确认] 该命令为破坏性操作，需要用户确认: {command}\n请用户输入 '确认' 后我再执行。"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr] " + result.stderr

        if not output.strip():
            return "(命令执行成功，无输出)"

        # 限制输出长度
        if len(output) > 3000:
            output = output[:3000] + "\n... (输出过长，已截断)"
        return output
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 30s: {command}"
    except Exception as e:
        return f"[错误] 命令执行失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# Runbook 运维手册工具
# ═══════════════════════════════════════════════════════════════

@tool
def runbook_disk_cleanup(threshold: int = 85, log_retention_days: int = 30) -> str:
    """执行磁盘清理 Runbook — 检查磁盘使用率、查找大文件、清理旧日志和缓存。

    当用户说"磁盘满了"、"清理磁盘空间"、"磁盘空间不足"时使用此工具。

    Args:
        threshold: 磁盘使用率阈值（百分比），默认 85
        log_retention_days: 日志保留天数，默认 30

    Returns:
        执行结果和清理后的磁盘状态
    """
    from keeper.runbook.executor import RunbookExecutor
    template_dir = __import__('pathlib').Path(__file__).parent.parent / "runbook" / "templates"
    executor = RunbookExecutor()
    try:
        runbook = executor.load_from_yaml(str(template_dir / "disk_cleanup.yaml"))
        ok, summary = executor.execute(runbook, {"threshold": str(threshold), "log_retention_days": str(log_retention_days)})
        return summary
    except FileNotFoundError:
        return "[错误] disk_cleanup runbook 模板未找到"
    except Exception as e:
        return f"[错误] Runbook 执行失败: {type(e).__name__}: {str(e)}"


@tool
def runbook_service_restart(service_name: str = "nginx", wait_seconds: int = 5) -> str:
    """执行服务重启 Runbook — 检查服务状态、安全重启、等待、验证服务恢复。

    当用户说"重启 nginx"、"重启 mysql"、"重启某个服务"时使用此工具。
    比直接执行 systemctl restart 更安全，包含健康检查和回滚能力。

    Args:
        service_name: 要重启的服务名称（如 nginx, mysql, docker）
        wait_seconds: 重启后等待验证的秒数，默认 5

    Returns:
        重启过程和验证结果
    """
    from keeper.runbook.executor import RunbookExecutor
    template_dir = __import__('pathlib').Path(__file__).parent.parent / "runbook" / "templates"
    executor = RunbookExecutor()
    try:
        runbook = executor.load_from_yaml(str(template_dir / "service_restart.yaml"))
        ok, summary = executor.execute(runbook, {"service_name": service_name, "wait_seconds": str(wait_seconds)})
        return summary
    except FileNotFoundError:
        return "[错误] service_restart runbook 模板未找到"
    except Exception as e:
        return f"[错误] Runbook 执行失败: {type(e).__name__}: {str(e)}"


@tool
def runbook_log_rotate(log_path: str = "/var/log") -> str:
    """执行日志轮转 Runbook — 检查日志目录大小、执行 logrotate、验证结果。

    当用户说"日志太多了"、"轮转日志"、"清理日志"时使用此工具。

    Args:
        log_path: 日志目录路径，默认 /var/log

    Returns:
        轮转前后的日志目录状态
    """
    from keeper.runbook.executor import RunbookExecutor
    template_dir = __import__('pathlib').Path(__file__).parent.parent / "runbook" / "templates"
    executor = RunbookExecutor()
    try:
        runbook = executor.load_from_yaml(str(template_dir / "log_rotate.yaml"))
        ok, summary = executor.execute(runbook, {"log_path": log_path})
        return summary
    except FileNotFoundError:
        return "[错误] log_rotate runbook 模板未找到"
    except Exception as e:
        return f"[错误] Runbook 执行失败: {type(e).__name__}: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 巡检对比 & 容量预测
# ═══════════════════════════════════════════════════════════════

@tool
def compare_inspection(host: str = "localhost") -> str:
    """对比当前巡检结果与上次巡检的差异，显示各指标变化趋势。

    当用户问"和上次对比变化大吗"、"最近趋势怎样"、"CPU 是不是涨了"时使用此工具。

    Args:
        host: 主机地址，默认 localhost

    Returns:
        巡检对比报告（包含 CPU/内存/磁盘/负载的变化）
    """
    try:
        from keeper.tools.comparator import InspectionComparator
        comparator = InspectionComparator()

        report = comparator.compare_with_last(host)
        if report is None:
            return f"[巡检对比] {host} 历史数据不足（需要至少 2 次巡检记录）。\n请先执行一次 inspect_server 采集数据。"

        formatted = comparator.format_comparison(report)

        # 追加 7 天趋势
        trend = comparator.get_trend(host, hours=168)
        if trend:
            formatted += "\n\n[7 天趋势]\n"
            for metric, info in trend.items():
                arrow = "↑" if info["trend"] == "up" else "↓"
                formatted += f"  {metric}: 均值 {info['avg']}% | 峰值 {info['max']}% | 趋势 {arrow}\n"

        return formatted
    except Exception as e:
        return f"[错误] 巡检对比失败: {str(e)}"


@tool
def predict_capacity(host: str = "localhost") -> str:
    """基于历史数据预测磁盘/内存何时达到阈值，给出容量规划建议。

    当用户问"磁盘还能用多久"、"容量预测"、"什么时候会满"时使用此工具。

    Args:
        host: 主机地址，默认 localhost

    Returns:
        各指标的容量预测报告（含预计达到阈值的天数）
    """
    try:
        from keeper.tools.capacity import CapacityPredictor
        predictor = CapacityPredictor()
        predictions = predictor.predict(host)

        if not predictions:
            return f"[容量预测] {host} 历史数据不足（需要至少 7 天的巡检记录）。\n请持续使用 inspect_server 采集数据。"

        return predictor.format_predictions(predictions)
    except Exception as e:
        return f"[错误] 容量预测失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# 工具注册表 — Agent Loop 使用此列表
# ═══════════════════════════════════════════════════════════════

ALL_TOOLS = [
    # 服务器监控
    inspect_server,
    get_top_processes,
    # 日志查询
    query_system_logs,
    read_log_file,
    # 网络诊断
    ping_host,
    check_port,
    dns_lookup,
    # K8s
    k8s_cluster_inspect,
    k8s_pod_logs,
    k8s_scale_deployment,
    k8s_restart_deployment,
    # Docker
    docker_list_containers,
    docker_container_logs,
    # 安全
    scan_ports,
    check_ssl_cert,
    # 服务管理
    manage_systemd_service,
    # SSH 远程
    inspect_remote_server,
    # Runbook
    runbook_disk_cleanup,
    runbook_service_restart,
    runbook_log_rotate,
    # 巡检对比 & 容量预测
    compare_inspection,
    predict_capacity,
    # 通用
    execute_shell_command,
]

# ─── 加载用户自定义插件工具 ──────────────────────────────────────
try:
    from .plugins import discover_plugins
    _plugin_tools = discover_plugins()
    if _plugin_tools:
        ALL_TOOLS.extend(_plugin_tools)
except Exception:
    pass  # 插件加载失败不影响主流程


def get_tools_description() -> str:
    """获取所有工具的描述（用于展示能力列表）"""
    lines = ["\n🔧 可用工具列表：", "=" * 40]
    for t in ALL_TOOLS:
        name = t.name if hasattr(t, 'name') else t.__name__
        doc = (t.description if hasattr(t, 'description') else t.__doc__) or ""
        first_line = doc.split("\n")[0]
        lines.append(f"  • {name}: {first_line}")
    lines.append(f"\n共 {len(ALL_TOOLS)} 个工具可用")
    return "\n".join(lines)
