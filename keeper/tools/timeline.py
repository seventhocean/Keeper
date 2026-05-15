"""事件时间线构建 — RCA 增强

从多个数据源采集事件，按时间排列，辅助根因分析：
- K8s Events
- 系统日志关键事件（OOM/重启/崩溃）
- 告警触发记录
- 配置变更（文件修改时间）
"""
import subprocess
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class TimelineEvent:
    """时间线事件"""
    timestamp: str
    source: str       # k8s / system / alert / config / deploy
    severity: str     # info / warning / critical
    title: str
    detail: str = ""
    related_resource: str = ""  # 相关资源（Pod/Service/Host）


@dataclass
class EventTimeline:
    """事件时间线"""
    host: str
    time_range: str
    events: List[TimelineEvent] = field(default_factory=list)
    summary: str = ""


class TimelineBuilder:
    """事件时间线构建器"""

    def build(self, host: str = "localhost", hours: int = 1) -> EventTimeline:
        """构建指定时间范围的事件时间线

        Args:
            host: 目标主机
            hours: 回溯小时数

        Returns:
            EventTimeline
        """
        timeline = EventTimeline(
            host=host,
            time_range=f"最近 {hours} 小时",
        )

        # 采集各数据源
        timeline.events.extend(self._collect_system_events(hours))
        timeline.events.extend(self._collect_config_changes(hours))

        # 按时间排序
        timeline.events.sort(key=lambda e: e.timestamp)

        # 生成摘要
        timeline.summary = self._generate_summary(timeline)

        return timeline

    def _collect_system_events(self, hours: int) -> List[TimelineEvent]:
        """从 journalctl 采集关键系统事件"""
        events = []
        since = f"{hours} hour ago"

        # OOM 事件
        oom_events = self._query_journal(since, keyword="oom", priority="err")
        for line in oom_events:
            events.append(TimelineEvent(
                timestamp=self._extract_timestamp(line),
                source="system",
                severity="critical",
                title="OOM Killed",
                detail=line[:200],
            ))

        # 服务重启事件
        restart_events = self._query_journal(since, keyword="Started|Stopped|Failed", priority="info")
        for line in restart_events[:20]:  # 限制数量
            severity = "critical" if "Failed" in line else "info"
            events.append(TimelineEvent(
                timestamp=self._extract_timestamp(line),
                source="system",
                severity=severity,
                title=self._extract_service_event(line),
                detail=line[:200],
            ))

        # 错误日志突增
        error_events = self._query_journal(since, priority="err")
        if len(error_events) > 50:
            events.append(TimelineEvent(
                timestamp=datetime.now().isoformat()[:19],
                source="system",
                severity="warning",
                title=f"错误日志突增: {len(error_events)} 条",
                detail=f"最近 {hours}h 内有 {len(error_events)} 条错误日志",
            ))

        return events

    def _collect_config_changes(self, hours: int) -> List[TimelineEvent]:
        """检测配置文件变更"""
        events = []
        config_files = [
            "/etc/nginx/nginx.conf",
            "/etc/ssh/sshd_config",
            "/etc/hosts",
            "/etc/resolv.conf",
        ]

        cutoff = datetime.now() - timedelta(hours=hours)

        for f in config_files:
            try:
                result = subprocess.run(
                    ["stat", "-c", "%Y %n", f],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split(" ", 1)
                    mtime = datetime.fromtimestamp(int(parts[0]))
                    if mtime > cutoff:
                        events.append(TimelineEvent(
                            timestamp=mtime.isoformat()[:19],
                            source="config",
                            severity="warning",
                            title=f"配置变更: {f}",
                            detail=f"文件修改时间: {mtime.strftime('%H:%M:%S')}",
                            related_resource=f,
                        ))
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                pass

        return events

    def _query_journal(self, since: str, keyword: str = "", priority: str = "") -> List[str]:
        """查询 journalctl"""
        cmd = ["journalctl", "--no-pager", "-n", "100", "--since", since]
        if priority:
            cmd.extend(["-p", priority])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().split("\n") if result.stdout else []
            if keyword:
                pattern = re.compile(keyword, re.IGNORECASE)
                lines = [l for l in lines if pattern.search(l)]
            return lines
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _extract_timestamp(self, line: str) -> str:
        """从日志行提取时间戳"""
        # 尝试 ISO 格式
        match = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", line)
        if match:
            return match.group(0)
        # 尝试 syslog 格式 (May 15 10:00:00)
        match = re.search(r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}", line)
        if match:
            return datetime.now().strftime("%Y-") + match.group(0)
        return datetime.now().isoformat()[:19]

    def _extract_service_event(self, line: str) -> str:
        """提取服务事件标题"""
        if "Started" in line:
            match = re.search(r"Started (.+?)(\.|$)", line)
            return f"服务启动: {match.group(1)[:50]}" if match else "服务启动"
        if "Stopped" in line:
            match = re.search(r"Stopped (.+?)(\.|$)", line)
            return f"服务停止: {match.group(1)[:50]}" if match else "服务停止"
        if "Failed" in line:
            match = re.search(r"Failed (.+?)(\.|$)", line)
            return f"服务失败: {match.group(1)[:50]}" if match else "服务失败"
        return line[:60]

    def _generate_summary(self, timeline: EventTimeline) -> str:
        """生成时间线摘要"""
        total = len(timeline.events)
        critical = sum(1 for e in timeline.events if e.severity == "critical")
        warning = sum(1 for e in timeline.events if e.severity == "warning")

        if critical > 0:
            return f"发现 {critical} 个严重事件，{warning} 个警告，共 {total} 条"
        elif warning > 0:
            return f"发现 {warning} 个警告事件，共 {total} 条"
        else:
            return f"共 {total} 条事件，无异常"

    def format_timeline(self, timeline: EventTimeline) -> str:
        """格式化时间线输出"""
        lines = [
            f"[事件时间线] {timeline.host} ({timeline.time_range})",
            "━" * 50,
        ]

        if not timeline.events:
            lines.append("  (无事件)")
        else:
            for event in timeline.events[-20:]:  # 最多显示 20 条
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[event.severity]
                lines.append(f"  {event.timestamp[11:19]} {icon} [{event.source}] {event.title}")
                if event.detail and event.severity != "info":
                    lines.append(f"           {event.detail[:80]}")

        lines.append("━" * 50)
        lines.append(f"  {timeline.summary}")
        return "\n".join(lines)
