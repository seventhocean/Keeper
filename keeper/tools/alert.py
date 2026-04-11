"""告警规则引擎 — 基于巡检结果自动触发告警"""
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class Alert:
    """单条告警"""
    name: str           # 告警名称
    severity: str       # "info", "warning", "critical"
    message: str        # 告警详情


class AlertEngine:
    """告警规则引擎"""

    @classmethod
    def check_server(cls, status: Dict[str, Any], thresholds: Dict[str, int]) -> List[Alert]:
        """检查服务器状态，返回触发的告警

        Args:
            status: ServerTools.inspect_server 返回的状态字典
            thresholds: 阈值配置 {"cpu": 80, "memory": 85, "disk": 90}

        Returns:
            触发的告警列表
        """
        alerts = []

        # CPU 告警
        cpu_pct = status.get("cpu_percent", 0)
        cpu_threshold = thresholds.get("cpu", 80)
        if cpu_pct > cpu_threshold:
            alerts.append(Alert(
                name="CPU 使用率过高",
                severity="critical" if cpu_pct > 95 else "warning",
                message=f"CPU 使用率 {cpu_pct}%，超过阈值 {cpu_threshold}%",
            ))

        # 内存告警
        mem_pct = status.get("memory_percent", 0)
        mem_threshold = thresholds.get("memory", 85)
        if mem_pct > mem_threshold:
            alerts.append(Alert(
                name="内存使用率过高",
                severity="critical" if mem_pct > 95 else "warning",
                message=f"内存使用率 {mem_pct}%，超过阈值 {mem_threshold}%",
            ))

        # 磁盘告警
        disk_pct = status.get("disk_percent", 0)
        disk_threshold = thresholds.get("disk", 90)
        if disk_pct > disk_threshold:
            alerts.append(Alert(
                name="磁盘使用率过高",
                severity="critical" if disk_pct > 95 else "warning",
                message=f"磁盘使用率 {disk_pct}%，超过阈值 {disk_threshold}%",
            ))

        # 负载告警
        load_avg = status.get("load_avg", {})
        load_per_cpu = status.get("load_per_cpu", 0)
        if load_per_cpu > 2.0:
            alerts.append(Alert(
                name="系统负载过高",
                severity="warning",
                message=f"每核心负载 {load_per_cpu:.1f}，远超正常值 1.0",
            ))

        # 服务失败告警
        failed_services = status.get("failed_services", [])
        if failed_services:
            alerts.append(Alert(
                name="系统服务异常",
                severity="critical",
                message=f"以下服务启动失败: {', '.join(failed_services[:5])}",
            ))

        # Swap 告警
        swap_pct = status.get("swap_percent", 0)
        if swap_pct > 50:
            alerts.append(Alert(
                name="Swap 使用过高",
                severity="warning",
                message=f"Swap 使用率 {swap_pct}%，可能影响性能",
            ))

        return alerts

    @classmethod
    def check_batch_report(cls, statuses: List[Dict[str, Any]], thresholds: Dict[str, int]) -> List[Alert]:
        """检查批量巡检报告，返回汇总告警

        Args:
            statuses: 多台服务器的状态列表
            thresholds: 阈值配置

        Returns:
            触发的告警列表
        """
        alerts = []

        for status in statuses:
            host = status.get("hostname", "unknown")
            host_alerts = cls.check_server(status, thresholds)
            for alert in host_alerts:
                alerts.append(Alert(
                    name=f"[{host}] {alert.name}",
                    severity=alert.severity,
                    message=alert.message,
                ))

        return alerts

    @classmethod
    def check_cert(cls, local_certs, k8s_certs, domain_certs=None) -> List[Alert]:
        """检查证书状态，返回触发的告警

        Args:
            local_certs: 本地证书列表
            k8s_certs: K8s 证书列表
            domain_certs: 域名证书列表

        Returns:
            触发的告警列表
        """
        alerts = []
        all_certs = list(local_certs) + list(k8s_certs) + list(domain_certs or [])

        expired = [c for c in all_certs if c.status == "expired"]
        expiring = [c for c in all_certs if c.status == "expiring_soon"]

        for cert in expired:
            alerts.append(Alert(
                name=f"SSL 证书已过期 [{cert.path}]",
                severity="critical",
                message=f"{cert.subject} 过期时间: {cert.not_after}，已过 {abs(cert.days_left)} 天",
            ))

        for cert in expiring:
            alerts.append(Alert(
                name=f"SSL 证书即将过期 [{cert.path}]",
                severity="warning",
                message=f"{cert.subject} 过期时间: {cert.not_after}，剩余 {cert.days_left} 天",
            ))

        return alerts
