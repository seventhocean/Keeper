"""Network Handler — 网络诊断相关处理"""
from typing import Dict, Any

from ...tools.network import (
    NetworkTools, format_ping_result, format_port_result,
    format_dns_result, format_http_result,
)


def handle_network(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理网络诊断意图"""
    action = entities.get("network_action", "").lower()
    host = entities.get("host")
    port = entities.get("port")
    domain = entities.get("domain")
    url = entities.get("url")

    lines = []

    # 无明确 action — 做一组基础检测
    if not action:
        ping_result = NetworkTools.ping("8.8.8.8", count=4)
        lines.append(format_ping_result(ping_result))
        lines.append("")
        dns_result = NetworkTools.dns_lookup("baidu.com")
        lines.append(format_dns_result(dns_result))
        return "\n".join(lines)

    # Ping
    if action == "ping":
        target = host or "8.8.8.8"
        count = int(entities.get("lines", 4))
        result = NetworkTools.ping(target, count=count)
        return format_ping_result(result)

    # 端口检测
    if action == "port":
        if not host or not port:
            return "[网络诊断] 请指定主机和端口，例如：检查 192.168.1.100 的 3306 端口"
        result = NetworkTools.check_port(host, int(port))
        return format_port_result(result)

    # DNS
    if action == "dns":
        target = domain or "baidu.com"
        result = NetworkTools.dns_lookup(target)
        return format_dns_result(result)

    # HTTP
    if action == "http":
        target = url or "http://localhost"
        result = NetworkTools.http_check(target)
        return format_http_result(result)

    # Traceroute
    if action == "traceroute":
        target = host or "8.8.8.8"
        success, output = NetworkTools.traceroute(target)
        if not success:
            return f"[网络诊断] {output}"
        return f"[网络诊断] 路由追踪到 {target}:\n{output}"

    return "[网络诊断] 未识别的检测类型，请说清楚一些，如 'ping 8.8.8.8' 或 '检查 3306 端口'"
