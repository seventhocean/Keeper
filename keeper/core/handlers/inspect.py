"""巡检 Handler — 服务器巡检相关处理"""
from typing import Dict, Any, List, Optional

from ...tools.server import ServerTools, format_status_report, format_batch_report
from ...tools.ssh import SSHTools
from ...storage.history import InspectionHistory


def _save_to_history(status) -> None:
    """将巡检结果写入 SQLite 历史（静默失败）"""
    if status.ssh_failed:
        return
    try:
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
        pass


def handle_inspect(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理服务器巡检意图"""
    host = entities.get("host")
    all_hosts = entities.get("all_hosts", False)
    profile = entities.get("profile") or state.context.current_profile

    # 获取阈值配置
    thresholds = {
        "cpu": config.get_threshold("cpu", profile),
        "memory": config.get_threshold("memory", profile),
        "disk": config.get_threshold("disk", profile),
    }

    # 多主机批量巡检
    if all_hosts:
        hosts = SSHTools.get_hosts_from_file("/etc/hosts")

        if not hosts:
            return (
                "[巡检] /etc/hosts 中没有找到可巡检的主机\n\n"
                "请确保 /etc/hosts 中配置了待巡检主机的 IP 地址，或指定具体主机 IP 进行巡检。"
            )

        try:
            statuses = ServerTools.inspect_multiple_hosts(hosts)
            agent_ref._last_inspect_statuses = statuses
            report = format_batch_report(statuses, thresholds)
            state.context.current_host = "batch"
            # 写入巡检历史
            for s in statuses:
                _save_to_history(s)
            return report
        except Exception as e:
            return f"[巡检] 批量巡检失败：{str(e)}"

    # 单主机巡检
    target_host = host or state.context.current_host or "localhost"

    try:
        status = ServerTools.inspect_server(target_host)
        agent_ref._last_inspect_statuses = [status]
        report = format_status_report(status, thresholds)
        state.context.current_host = target_host
        # 写入巡检历史
        _save_to_history(status)
        return report
    except NotImplementedError as e:
        return f"[巡检] {str(e)}"
    except Exception as e:
        return f"[巡检] 检查失败：{str(e)}"
