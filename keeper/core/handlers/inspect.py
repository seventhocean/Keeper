"""巡检 Handler — 服务器巡检相关处理"""
from typing import Dict, Any, List, Optional

from ...tools.server import ServerTools, format_status_report, format_batch_report
from ...tools.ssh import SSHTools


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
        return report
    except NotImplementedError as e:
        return f"[巡检] {str(e)}"
    except Exception as e:
        return f"[巡检] 检查失败：{str(e)}"
