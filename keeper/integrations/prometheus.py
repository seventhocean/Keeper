"""Prometheus Alertmanager 集成

功能：
- 查询活跃告警
- 告警聚合分析（Top N、风暴检测、趋势）
- 创建/删除静默规则
- 告警 → RCA 联动建议
"""
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


@dataclass
class Alert:
    """单条告警"""
    name: str
    severity: str        # critical / warning / info
    state: str           # firing / resolved
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    starts_at: str = ""
    ends_at: str = ""
    fingerprint: str = ""
    instance: str = ""
    summary: str = ""


@dataclass
class AlertSummary:
    """告警聚合摘要"""
    total_firing: int = 0
    total_resolved: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_name: Dict[str, int] = field(default_factory=dict)
    top_alerts: List[Alert] = field(default_factory=list)
    storm_detected: bool = False
    storm_message: str = ""


class PrometheusClient:
    """Prometheus Alertmanager 客户端"""

    def __init__(self, alertmanager_url: str, username: str = "", password: str = ""):
        """
        Args:
            alertmanager_url: Alertmanager API 地址 (如 http://localhost:9093)
            username: Basic Auth 用户名（可选）
            password: Basic Auth 密码（可选）
        """
        self.base_url = alertmanager_url.rstrip("/")
        self.username = username
        self.password = password
        self._client = None

    @property
    def client(self):
        """延迟初始化 HTTP 客户端"""
        if self._client is None:
            if not HTTPX_AVAILABLE:
                raise ImportError("httpx 未安装，请运行: pip install httpx")
            auth = (self.username, self.password) if self.username else None
            self._client = httpx.Client(
                base_url=self.base_url,
                auth=auth,
                timeout=10.0,
            )
        return self._client

    def get_alerts(self, active: bool = True, silenced: bool = False,
                   inhibited: bool = False) -> List[Alert]:
        """查询告警列表

        Args:
            active: 是否包含活跃告警
            silenced: 是否包含已静默告警
            inhibited: 是否包含已抑制告警

        Returns:
            告警列表
        """
        params = {
            "active": str(active).lower(),
            "silenced": str(silenced).lower(),
            "inhibited": str(inhibited).lower(),
        }

        try:
            resp = self.client.get("/api/v2/alerts", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return []

        alerts = []
        for item in data:
            labels = item.get("labels", {})
            annotations = item.get("annotations", {})
            alerts.append(Alert(
                name=labels.get("alertname", "unknown"),
                severity=labels.get("severity", "warning"),
                state=item.get("status", {}).get("state", "unknown"),
                labels=labels,
                annotations=annotations,
                starts_at=item.get("startsAt", ""),
                ends_at=item.get("endsAt", ""),
                fingerprint=item.get("fingerprint", ""),
                instance=labels.get("instance", ""),
                summary=annotations.get("summary", annotations.get("description", "")),
            ))

        return alerts

    def get_alert_summary(self) -> AlertSummary:
        """获取告警聚合摘要"""
        alerts = self.get_alerts(active=True)
        summary = AlertSummary()

        for alert in alerts:
            if alert.state == "firing":
                summary.total_firing += 1
            else:
                summary.total_resolved += 1

            # 按严重级别
            sev = alert.severity
            summary.by_severity[sev] = summary.by_severity.get(sev, 0) + 1

            # 按告警名称
            name = alert.name
            summary.by_name[name] = summary.by_name.get(name, 0) + 1

        # Top 告警（按出现次数排序）
        sorted_names = sorted(summary.by_name.items(), key=lambda x: -x[1])
        for name, count in sorted_names[:5]:
            matching = [a for a in alerts if a.name == name]
            if matching:
                summary.top_alerts.append(matching[0])

        # 告警风暴检测（5分钟内 >20 条）
        if summary.total_firing > 20:
            summary.storm_detected = True
            summary.storm_message = f"告警风暴: {summary.total_firing} 条活跃告警"

        return summary

    def create_silence(self, matchers: List[Dict[str, str]],
                       duration_hours: int = 2,
                       comment: str = "Silenced by Keeper") -> Tuple[bool, str]:
        """创建静默规则

        Args:
            matchers: 匹配规则列表 [{"name": "alertname", "value": "xxx", "isRegex": false}]
            duration_hours: 静默持续时间（小时）
            comment: 备注

        Returns:
            (success, silence_id_or_error)
        """
        now = datetime.utcnow()
        end = now + timedelta(hours=duration_hours)

        payload = {
            "matchers": matchers,
            "startsAt": now.isoformat() + "Z",
            "endsAt": end.isoformat() + "Z",
            "createdBy": "keeper",
            "comment": comment,
        }

        try:
            resp = self.client.post("/api/v2/silences", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return True, data.get("silenceID", "unknown")
        except Exception as e:
            return False, str(e)

    def delete_silence(self, silence_id: str) -> Tuple[bool, str]:
        """删除静默规则"""
        try:
            resp = self.client.delete(f"/api/v2/silence/{silence_id}")
            resp.raise_for_status()
            return True, "已删除"
        except Exception as e:
            return False, str(e)

    def format_alerts(self, alerts: Optional[List[Alert]] = None) -> str:
        """格式化告警列表"""
        if alerts is None:
            alerts = self.get_alerts()

        if not alerts:
            return "[Prometheus] 当前无活跃告警 ✓"

        lines = [f"[Prometheus] 活跃告警: {len(alerts)} 条", "━" * 50]

        for alert in alerts[:15]:
            icon = {"critical": "🔴", "warning": "🟡"}.get(alert.severity, "🔵")
            lines.append(f"  {icon} [{alert.severity}] {alert.name}")
            if alert.instance:
                lines.append(f"     实例: {alert.instance}")
            if alert.summary:
                lines.append(f"     摘要: {alert.summary[:80]}")
            lines.append(f"     触发: {alert.starts_at[:19]}")

        if len(alerts) > 15:
            lines.append(f"  ... 还有 {len(alerts) - 15} 条")

        lines.append("━" * 50)
        return "\n".join(lines)

    def format_summary(self, summary: Optional[AlertSummary] = None) -> str:
        """格式化告警摘要"""
        if summary is None:
            summary = self.get_alert_summary()

        lines = [
            "[Prometheus 告警摘要]",
            f"  活跃: {summary.total_firing} | 已恢复: {summary.total_resolved}",
            f"  严重级别: {summary.by_severity}",
        ]

        if summary.storm_detected:
            lines.append(f"  ⚠️ {summary.storm_message}")

        if summary.top_alerts:
            lines.append("  Top 告警:")
            for a in summary.top_alerts[:3]:
                count = summary.by_name.get(a.name, 0)
                lines.append(f"    • {a.name} × {count}")

        return "\n".join(lines)
