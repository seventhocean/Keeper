"""服务器工具 - 资源采集和监控"""
import psutil
import socket
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class ServerStatus:
    """服务器状态"""
    host: str
    timestamp: str
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    boot_time: str
    top_processes: List[Dict[str, Any]]
    ssh_failed: bool = False  # 标记 SSH 采集是否失败


class ServerTools:
    """服务器工具类"""

    @staticmethod
    def get_hostname() -> str:
        """获取主机名"""
        return socket.gethostname()

    @staticmethod
    def get_cpu_percent() -> float:
        """获取 CPU 使用率"""
        return psutil.cpu_percent(interval=0.5)

    @staticmethod
    def get_memory_info() -> Dict[str, float]:
        """获取内存信息"""
        mem = psutil.virtual_memory()
        return {
            "percent": mem.percent,
            "used_gb": mem.used / (1024 ** 3),
            "total_gb": mem.total / (1024 ** 3),
        }

    @staticmethod
    def get_disk_info(path: str = "/") -> Dict[str, float]:
        """获取磁盘信息"""
        disk = psutil.disk_usage(path)
        return {
            "percent": disk.percent,
            "used_gb": disk.used / (1024 ** 3),
            "total_gb": disk.total / (1024 ** 3),
        }

    @staticmethod
    def get_load_avg() -> Dict[str, float]:
        """获取系统负载"""
        try:
            load1, load5, load15 = psutil.getloadavg()
        except (AttributeError, OSError):
            # Windows 不支持
            load1 = load5 = load15 = psutil.cpu_percent() / 100.0
        return {
            "1m": load1,
            "5m": load5,
            "15m": load15,
        }

    @staticmethod
    def get_top_processes(n: int = 5) -> List[Dict[str, Any]]:
        """获取资源占用 Top N 进程"""
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                processes.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_percent": info["cpu_percent"] or 0,
                    "memory_percent": info["memory_percent"] or 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 按内存占用排序
        processes.sort(key=lambda x: x["memory_percent"], reverse=True)
        return processes[:n]

    @staticmethod
    def get_boot_time() -> str:
        """获取开机时间"""
        boot_timestamp = psutil.boot_time()
        return datetime.fromtimestamp(boot_timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def inspect_server(cls, host: Optional[str] = None) -> ServerStatus:
        """巡检服务器状态

        Args:
            host: 主机名或 IP，None 表示本地

        Returns:
            ServerStatus: 服务器状态
        """
        target_host = host or cls.get_hostname()

        # 如果是本地，直接采集
        if host in (None, "localhost", "127.0.0.1", cls.get_hostname()):
            mem_info = cls.get_memory_info()
            disk_info = cls.get_disk_info()
            load_avg = cls.get_load_avg()
            return ServerStatus(
                host=target_host,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cpu_percent=cls.get_cpu_percent(),
                memory_percent=mem_info["percent"],
                memory_used_gb=mem_info["used_gb"],
                memory_total_gb=mem_info["total_gb"],
                disk_percent=disk_info["percent"],
                disk_used_gb=disk_info["used_gb"],
                disk_total_gb=disk_info["total_gb"],
                load_avg_1m=load_avg["1m"],
                load_avg_5m=load_avg["5m"],
                load_avg_15m=load_avg["15m"],
                boot_time=cls.get_boot_time(),
                top_processes=cls.get_top_processes(5),
            )
        else:
            # 远程主机采集（通过 SSH）
            from .ssh import SSHTools, SSHConfig
            ssh_config = SSHConfig(host=host)
            success, status_dict = SSHTools.collect_server_status(ssh_config)

            if success and status_dict:
                return ServerStatus(
                    host=status_dict.get("host", host),
                    timestamp=status_dict.get("timestamp", ""),
                    cpu_percent=status_dict.get("cpu_percent", 0),
                    memory_percent=status_dict.get("memory_percent", 0),
                    memory_used_gb=status_dict.get("memory_used_gb", 0),
                    memory_total_gb=status_dict.get("memory_total_gb", 0),
                    disk_percent=status_dict.get("disk_percent", 0),
                    disk_used_gb=status_dict.get("disk_used_gb", 0),
                    disk_total_gb=status_dict.get("disk_total_gb", 0),
                    load_avg_1m=status_dict.get("load_avg_1m", 0),
                    load_avg_5m=status_dict.get("load_avg_5m", 0),
                    load_avg_15m=status_dict.get("load_avg_15m", 0),
                    boot_time=status_dict.get("boot_time", ""),
                    top_processes=status_dict.get("top_processes", []),
                )
            else:
                # SSH 采集失败，返回标记状态
                return ServerStatus(
                    host=host,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    cpu_percent=0,
                    memory_percent=0,
                    memory_used_gb=0,
                    memory_total_gb=0,
                    disk_percent=0,
                    disk_used_gb=0,
                    disk_total_gb=0,
                    load_avg_1m=0,
                    load_avg_5m=0,
                    load_avg_15m=0,
                    boot_time="",
                    top_processes=[],
                    ssh_failed=True,
                )

    @classmethod
    def inspect_multiple_hosts(cls, hosts: List[str], max_workers: int = 10) -> List[ServerStatus]:
        """批量巡检多台主机

        Args:
            hosts: 主机 IP 列表
            max_workers: 最大并发数

        Returns:
            服务器状态列表
        """
        results = []

        def inspect_host(host: str) -> ServerStatus:
            """单个主机采集函数"""
            return cls.inspect_server(host)

        # 使用线程池并行采集
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_host = {executor.submit(inspect_host, host): host for host in hosts}

            # 收集结果
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    status = future.result()
                    results.append(status)
                except Exception as e:
                    # 异常情况，返回失败状态
                    results.append(ServerStatus(
                        host=host,
                        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        cpu_percent=0,
                        memory_percent=0,
                        memory_used_gb=0,
                        memory_total_gb=0,
                        disk_percent=0,
                        disk_used_gb=0,
                        disk_total_gb=0,
                        load_avg_1m=0,
                        load_avg_5m=0,
                        load_avg_15m=0,
                        boot_time="",
                        top_processes=[],
                        ssh_failed=True,
                    ))

        return results


def format_status_report(status: ServerStatus, thresholds: Dict[str, int]) -> str:
    """格式化状态报告

    Args:
        status: 服务器状态
        thresholds: 阈值配置 {"cpu": 80, "memory": 85, "disk": 90}

    Returns:
        str: 格式化的报告文本
    """
    # SSH 失败情况
    if status.ssh_failed:
        return f"[✗] 无法连接到 {status.host} - SSH 采集失败\n\n可能原因:\n  1. SSH 未配置或连接失败\n  2. 远程主机未安装 psutil\n  3. 防火墙阻止连接"

    lines = []
    lines.append(f"[✓] 服务器健康检查 - {status.host}")
    lines.append("━" * 40)

    # CPU
    cpu_ok = status.cpu_percent < thresholds.get("cpu", 80)
    cpu_icon = "✓" if cpu_ok else "⚠️"
    lines.append(f"  CPU:     {status.cpu_percent:.1f}%  (阈值：{thresholds.get('cpu', 80)}%)  {cpu_icon}")

    # 内存
    mem_ok = status.memory_percent < thresholds.get("memory", 85)
    mem_icon = "✓" if mem_ok else "⚠️"
    lines.append(f"  内存：   {status.memory_percent:.1f}%  (阈值：{thresholds.get('memory', 85)}%)  {mem_icon}")
    lines.append(f"         已用：{status.memory_used_gb:.2f}GB / {status.memory_total_gb:.2f}GB")

    # 磁盘
    disk_ok = status.disk_percent < thresholds.get("disk", 90)
    disk_icon = "✓" if disk_ok else "⚠️"
    lines.append(f"  磁盘：   {status.disk_percent:.1f}%  (阈值：{thresholds.get('disk', 90)}%)  {disk_icon}")
    lines.append(f"         已用：{status.disk_used_gb:.2f}GB / {status.disk_total_gb:.2f}GB")

    # 负载
    cpu_cores = psutil.cpu_count() or 1
    load_threshold = cpu_cores * 2
    load_ok = status.load_avg_1m < load_threshold
    load_icon = "✓" if load_ok else "⚠️"
    lines.append(f"  负载：   {status.load_avg_1m:.2f}  (阈值：{load_threshold})  {load_icon}")
    lines.append(f"         1 分钟:{status.load_avg_1m:.2f} | 5 分钟:{status.load_avg_5m:.2f} | 15 分钟:{status.load_avg_15m:.2f}")

    # 开机时间
    lines.append(f"  开机时间：{status.boot_time}")

    # Top 进程
    lines.append("\n  资源占用 Top 进程:")
    for i, proc in enumerate(status.top_processes, 1):
        lines.append(f"    {i}. {proc['name']} (PID:{proc['pid']}) - 内存:{proc['memory_percent']:.1f}%")

    # 健康评分
    issues = sum([
        0 if cpu_ok else 1,
        0 if mem_ok else 1,
        0 if disk_ok else 1,
        0 if load_ok else 1,
    ])
    score = max(0, 100 - issues * 15)
    lines.append(f"\n健康评分：{score}/100")

    if issues == 0:
        lines.append("状态：✅ 所有指标正常")
    else:
        lines.append(f"状态：⚠️ 发现 {issues} 项异常")

    return "\n".join(lines)


def format_batch_report(statuses: List[ServerStatus], thresholds: Dict[str, int]) -> str:
    """格式化批量巡检报告

    Args:
        statuses: 服务器状态列表
        thresholds: 阈值配置

    Returns:
        str: 格式化的批量报告文本
    """
    lines = []
    lines.append("┌" + "─" * 68 + "┐")
    lines.append("│" + " " * 20 + "批量服务器健康检查" + " " * 26 + "│")
    lines.append("└" + "─" * 68 + "┘")
    lines.append("")

    # 汇总表格
    lines.append("汇总:")
    lines.append("━" * 70)
    lines.append(f"{'主机':<20} {'CPU%':<8} {'内存%':<8} {'磁盘%':<8} {'负载':<10} {'状态':<8}")
    lines.append("━" * 70)

    success_count = 0
    failed_count = 0

    for status in statuses:
        if status.ssh_failed:
            lines.append(f"{status.host:<20} {'-':<8} {'-':<8} {'-':<8} {'-':<10} {'❌ 失败':<8}")
            failed_count += 1
        else:
            # 判断是否健康
            cpu_ok = status.cpu_percent < thresholds.get("cpu", 80)
            mem_ok = status.memory_percent < thresholds.get("memory", 85)
            disk_ok = status.disk_percent < thresholds.get("disk", 90)
            health_icon = "✅" if (cpu_ok and mem_ok and disk_ok) else "⚠️"

            lines.append(f"{status.host:<20} {status.cpu_percent:<8.1f} {status.memory_percent:<8.1f} "
                        f"{status.disk_percent:<8.1f} {status.load_avg_1m:<10.2f} {health_icon:<8}")
            success_count += 1

    lines.append("━" * 70)
    lines.append(f"总计：{len(statuses)} 台主机 | ✅ 成功：{success_count} 台 | ❌ 失败：{failed_count} 台")
    lines.append("")

    # 失败主机详情
    if failed_count > 0:
        lines.append("⚠️  失败主机提醒:")
        lines.append("   以下主机无法通过 SSH 采集，请检查 SSH 免密登录配置：")
        for status in statuses:
            if status.ssh_failed:
                lines.append(f"   - {status.host}")
        lines.append("")
        lines.append("   配置步骤:")
        lines.append("   1. 生成密钥：ssh-keygen -t rsa")
        lines.append("   2. 分发密钥：ssh-copy-id root@<IP>")
        lines.append("   3. 确保远程主机已安装 psutil: pip install psutil")
        lines.append("")

    # 只显示成功主机的详情（前 3 台）
    success_statuses = [s for s in statuses if not s.ssh_failed]
    if success_statuses:
        lines.append("详细报告 (前 3 台):")
        lines.append("")
        for status in success_statuses[:3]:
            report = format_status_report(status, thresholds)
            lines.append(report)
            lines.append("")

    # 如果全部失败
    if not success_statuses:
        lines.append("🔍 建议:")
        lines.append("   所有主机采集失败，正在仅巡检本机...")
        lines.append("")
        local_status = ServerTools.inspect_server("localhost")
        report = format_status_report(local_status, thresholds)
        lines.append(report)

    return "\n".join(lines)
