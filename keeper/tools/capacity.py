"""容量预测 — 基于历史数据的线性回归预测

功能：
- 预测磁盘/内存何时达到阈值
- 输出："按当前增速，磁盘将在 X 天后达到 90%"
"""
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from ..storage.history import InspectionHistory


@dataclass
class CapacityPrediction:
    """容量预测结果"""
    metric: str           # cpu / memory / disk
    current_value: float
    threshold: float
    growth_rate: float    # 每天增长百分比
    days_to_threshold: Optional[int]  # 达到阈值的天数（None=不会达到）
    prediction: str       # 人类可读的预测文本
    confidence: str       # high / medium / low


class CapacityPredictor:
    """容量预测器"""

    def __init__(self, history: Optional[InspectionHistory] = None):
        self.history = history or InspectionHistory()

    def predict(self, host: str, thresholds: Optional[Dict[str, int]] = None) -> List[CapacityPrediction]:
        """对所有指标进行容量预测

        Args:
            host: 主机地址
            thresholds: 阈值配置 {cpu: 80, memory: 85, disk: 90}

        Returns:
            各指标的预测结果列表
        """
        if thresholds is None:
            thresholds = {"cpu": 80, "memory": 85, "disk": 90}

        records = self.history.get_by_time_range(host, hours=168)  # 7天
        if len(records) < 2:
            return []

        predictions = []

        # 磁盘预测（最有意义）
        disk_values = [(i, r.disk_percent) for i, r in enumerate(records)]
        predictions.append(self._predict_metric(
            "磁盘", disk_values, thresholds.get("disk", 90), len(records)
        ))

        # 内存预测
        mem_values = [(i, r.memory_percent) for i, r in enumerate(records)]
        predictions.append(self._predict_metric(
            "内存", mem_values, thresholds.get("memory", 85), len(records)
        ))

        # CPU 通常波动大，预测意义较小，但还是做
        cpu_values = [(i, r.cpu_percent) for i, r in enumerate(records)]
        predictions.append(self._predict_metric(
            "CPU", cpu_values, thresholds.get("cpu", 80), len(records)
        ))

        return predictions

    def _predict_metric(self, name: str, data: List[Tuple[int, float]],
                        threshold: float, total_samples: int) -> CapacityPrediction:
        """对单个指标进行线性回归预测"""
        if not data:
            return CapacityPrediction(
                metric=name, current_value=0, threshold=threshold,
                growth_rate=0, days_to_threshold=None,
                prediction=f"{name} 无历史数据", confidence="low"
            )

        current = data[-1][1]

        # 简单线性回归
        slope, _ = self._linear_regression(data)

        # 计算每天增长率（假设样本间隔相等）
        # 如果 7 天有 N 个样本，每样本间隔 = 7*24/N 小时
        hours_per_sample = (7 * 24) / max(total_samples, 1)
        daily_growth = slope * (24 / hours_per_sample) if hours_per_sample > 0 else 0

        # 预测天数
        if daily_growth <= 0 or current >= threshold:
            days = None
        else:
            remaining = threshold - current
            days = int(remaining / daily_growth) if daily_growth > 0 else None

        # 置信度
        if total_samples >= 20:
            confidence = "high"
        elif total_samples >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        # 生成预测文本
        if current >= threshold:
            prediction = f"{name} 当前已超过阈值 ({current:.1f}% >= {threshold}%)"
        elif days is None or days > 365:
            prediction = f"{name} 当前 {current:.1f}%，增长缓慢或下降，短期内不会达到阈值"
        elif days <= 7:
            prediction = f"⚠️ {name} 当前 {current:.1f}%，按当前增速约 {days} 天后达到 {threshold}%"
        elif days <= 30:
            prediction = f"{name} 当前 {current:.1f}%，预计 {days} 天后达到 {threshold}%"
        else:
            prediction = f"{name} 当前 {current:.1f}%，预计 {days} 天后达到 {threshold}%（较远）"

        return CapacityPrediction(
            metric=name,
            current_value=round(current, 1),
            threshold=threshold,
            growth_rate=round(daily_growth, 3),
            days_to_threshold=days,
            prediction=prediction,
            confidence=confidence,
        )

    def _linear_regression(self, data: List[Tuple[int, float]]) -> Tuple[float, float]:
        """简单线性回归 y = slope * x + intercept"""
        n = len(data)
        if n < 2:
            return 0.0, data[0][1] if data else 0.0

        sum_x = sum(d[0] for d in data)
        sum_y = sum(d[1] for d in data)
        sum_xy = sum(d[0] * d[1] for d in data)
        sum_x2 = sum(d[0] ** 2 for d in data)

        denominator = n * sum_x2 - sum_x ** 2
        if denominator == 0:
            return 0.0, sum_y / n

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        return slope, intercept

    def format_predictions(self, predictions: List[CapacityPrediction]) -> str:
        """格式化预测结果"""
        if not predictions:
            return "[容量预测] 历史数据不足，无法预测"

        lines = ["[容量预测]", "━" * 40]
        for p in predictions:
            lines.append(f"  {p.prediction} (置信度: {p.confidence})")
        lines.append("━" * 40)
        return "\n".join(lines)
