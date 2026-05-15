"""巡检历史对比分析

功能：
- 与上次巡检对比（逐指标 diff + 箭头标识）
- 与 N 天前对比
- 过去 7 天趋势摘要（均值/峰值/增长率）
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from ..storage.history import InspectionHistory, InspectionRecord


@dataclass
class MetricDiff:
    """指标变化"""
    name: str
    current: float
    previous: float
    delta: float          # 绝对差
    delta_percent: float  # 变化百分比
    direction: str        # "up" / "down" / "stable"
    warning: bool = False # 是否异常涨幅


@dataclass
class ComparisonReport:
    """对比报告"""
    host: str
    current_time: str
    previous_time: str
    diffs: List[MetricDiff]
    summary: str


class InspectionComparator:
    """巡检对比分析器"""

    # 单日涨幅超过此值视为异常
    ABNORMAL_THRESHOLD = 10.0  # 百分比

    def __init__(self, history: Optional[InspectionHistory] = None):
        self.history = history or InspectionHistory()

    def compare_with_last(self, host: str, current: Optional[Dict[str, float]] = None) -> Optional[ComparisonReport]:
        """与上次巡检对比

        Args:
            host: 主机地址
            current: 当前指标 {cpu, memory, disk, load}，为空则从历史取最新

        Returns:
            ComparisonReport 或 None（无历史数据时）
        """
        records = self.history.get_latest(host, n=2)
        if len(records) < 2:
            return None

        latest = records[0]
        previous = records[1]

        if current is None:
            current = {
                "cpu": latest.cpu_percent,
                "memory": latest.memory_percent,
                "disk": latest.disk_percent,
                "load": latest.load_avg_1m,
            }

        diffs = self._compute_diffs(current, {
            "cpu": previous.cpu_percent,
            "memory": previous.memory_percent,
            "disk": previous.disk_percent,
            "load": previous.load_avg_1m,
        })

        summary = self._generate_summary(diffs)

        return ComparisonReport(
            host=host,
            current_time=latest.timestamp,
            previous_time=previous.timestamp,
            diffs=diffs,
            summary=summary,
        )

    def get_trend(self, host: str, hours: int = 168) -> Dict[str, Any]:
        """获取趋势摘要（默认 7 天）

        Returns:
            {metric: {avg, max, min, trend}}
        """
        records = self.history.get_by_time_range(host, hours=hours)
        if not records:
            return {}

        metrics = {"cpu": [], "memory": [], "disk": [], "load": []}
        for r in records:
            metrics["cpu"].append(r.cpu_percent)
            metrics["memory"].append(r.memory_percent)
            metrics["disk"].append(r.disk_percent)
            metrics["load"].append(r.load_avg_1m)

        result = {}
        for name, values in metrics.items():
            if not values:
                continue
            avg = sum(values) / len(values)
            result[name] = {
                "avg": round(avg, 1),
                "max": round(max(values), 1),
                "min": round(min(values), 1),
                "current": round(values[-1], 1),
                "samples": len(values),
                "trend": "up" if len(values) > 1 and values[-1] > values[0] else "down",
            }

        return result

    def _compute_diffs(self, current: Dict[str, float], previous: Dict[str, float]) -> List[MetricDiff]:
        """计算指标差异"""
        names = {"cpu": "CPU", "memory": "内存", "disk": "磁盘", "load": "负载"}
        diffs = []
        for key, display_name in names.items():
            cur = current.get(key, 0)
            prev = previous.get(key, 0)
            delta = cur - prev
            delta_pct = ((cur - prev) / prev * 100) if prev != 0 else 0

            if abs(delta) < 0.5:
                direction = "stable"
            elif delta > 0:
                direction = "up"
            else:
                direction = "down"

            diffs.append(MetricDiff(
                name=display_name,
                current=round(cur, 1),
                previous=round(prev, 1),
                delta=round(delta, 1),
                delta_percent=round(delta_pct, 1),
                direction=direction,
                warning=abs(delta) > self.ABNORMAL_THRESHOLD,
            ))

        return diffs

    def _generate_summary(self, diffs: List[MetricDiff]) -> str:
        """生成对比摘要"""
        warnings = [d for d in diffs if d.warning]
        if not warnings:
            return "各项指标变化正常"

        parts = []
        for d in warnings:
            arrow = "↑" if d.direction == "up" else "↓"
            parts.append(f"{d.name} {arrow}{abs(d.delta):.1f}%")
        return "异常变化: " + ", ".join(parts)

    def format_comparison(self, report: ComparisonReport) -> str:
        """格式化对比报告"""
        lines = [
            f"[巡检对比] {report.host}",
            f"  当前: {report.current_time[:16]}",
            f"  对比: {report.previous_time[:16]}",
            "━" * 40,
        ]
        for d in report.diffs:
            arrow = {"up": "↑", "down": "↓", "stable": "→"}[d.direction]
            warn = " ⚠️" if d.warning else ""
            lines.append(
                f"  {d.name:<6} {d.previous:>6.1f}% → {d.current:>6.1f}% ({arrow}{abs(d.delta):.1f}%){warn}"
            )
        lines.append("━" * 40)
        lines.append(f"  {report.summary}")
        return "\n".join(lines)
