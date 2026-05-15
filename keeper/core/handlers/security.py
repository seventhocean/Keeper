"""Security Handler — 安全扫描 & 证书监控相关处理"""
from typing import Dict, Any

from ...tools.scanner import ScannerTools, format_scan_result, NmapNotInstalledError
from ...tools.cert_monitor import CertMonitor


def handle_scan(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理漏洞扫描意图"""
    host = entities.get("host") or state.context.current_host or "localhost"

    try:
        scan_type = "quick" if not entities.get("full") else "full"

        if scan_type == "quick":
            result = ScannerTools.quick_scan(host)
        else:
            result = ScannerTools.full_scan(host)

        report = format_scan_result(result)
        state.context.current_host = host
        return report
    except NmapNotInstalledError:
        from ..agent import PendingTask
        agent_ref.pending_task = PendingTask(
            task_type="install",
            package="nmap",
            host="localhost",
        )
        return NmapNotInstalledError.get_help_message()
    except RuntimeError as e:
        return f"[扫描] {str(e)}"
    except TimeoutError as e:
        return f"[扫描] 扫描超时：{str(e)}"
    except Exception as e:
        return f"[扫描] 扫描失败：{str(e)}"


def handle_cert_check(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理证书监控意图"""
    domain = entities.get("domain")

    # 检查指定域名
    if domain:
        cert = CertMonitor.check_domain_cert(domain)
        if cert:
            status_icon = {"valid": "🟢", "expiring_soon": "🟡", "expired": "🔴"}[cert.status]
            days = (
                f"剩余 {cert.days_left} 天" if cert.status == "valid"
                else (f"已过 {abs(cert.days_left)} 天" if cert.status == "expired"
                      else f"剩余 {cert.days_left} 天")
            )
            lines = [f"[SSL/TLS] {domain}:"]
            lines.append(f"  状态: {status_icon} {days}")
            lines.append(f"  主体: {cert.subject}")
            lines.append(f"  过期: {cert.not_after}")
            if cert.domains:
                lines.append(f"  域名: {', '.join(cert.domains[:5])}")
            return "\n".join(lines)
        return f"[SSL/TLS] 无法获取 {domain} 的证书信息"

    # 全面扫描
    lines = []

    # 本地证书
    local_certs = CertMonitor.scan_local_certs()
    lines.append(f"[SSL/TLS] 本地证书扫描: 发现 {len(local_certs)} 个证书")
    for c in local_certs:
        if c.status != "valid":
            icon = "🔴" if c.status == "expired" else "🟡"
            lines.append(f"  {icon} {c.path} - 剩余 {c.days_left} 天 ({c.not_after})")

    # K8s 证书
    from .k8s import _get_k8s_client
    k8s_client, _, err = _get_k8s_client(config, auto_detect=True)
    k8s_certs = []
    if not err and k8s_client:
        try:
            k8s_certs = CertMonitor.check_k8s_certs(k8s_client)
            lines.append(f"\n[SSL/TLS] K8s 证书扫描: 发现 {len(k8s_certs)} 个证书")
            for c in k8s_certs:
                if c.status != "valid":
                    icon = "🔴" if c.status == "expired" else "🟡"
                    lines.append(f"  {icon} {c.path} - 剩余 {c.days_left} 天 ({c.not_after})")
        finally:
            k8s_client.close()

    # 域名证书
    domains = CertMonitor.detect_domains_from_config()
    domain_certs = []
    if domains:
        lines.append(f"\n[SSL/TLS] 检测到 {len(domains)} 个潜在域名，检查前 5 个:")
        for d in domains[:5]:
            cert = CertMonitor.check_domain_cert(d)
            if cert:
                domain_certs.append(cert)
                icon = "🔴" if cert.status == "expired" else ("🟡" if cert.status == "expiring_soon" else "🟢")
                lines.append(f"  {icon} {d} - 剩余 {cert.days_left} 天 ({cert.not_after})")
            else:
                lines.append(f"  ✗ {d} - 无法获取证书")

    if not lines:
        return "[SSL/TLS] 未发现任何证书"

    # 汇总
    all_certs = local_certs + k8s_certs + domain_certs
    expired = [c for c in all_certs if c.status == "expired"]
    expiring = [c for c in all_certs if c.status == "expiring_soon"]
    if expired or expiring:
        lines.append("")
        lines.append(f"⚠ 发现 {len(expired)} 个已过期、{len(expiring)} 个即将过期的证书")

    return "\n".join(lines)
