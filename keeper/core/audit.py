"""审计日志模块 - 操作记录持久化"""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict


@dataclass
class AuditRecord:
    """审计记录"""
    timestamp: str
    user: str
    intent: str
    entities: Dict[str, Any]
    result: str  # "success", "error", "cancelled"
    response_time_ms: int
    host: Optional[str] = None
    error_message: Optional[str] = None


class AuditLogger:
    """审计日志记录器"""

    def __init__(self, log_path: Optional[str] = None):
        """初始化审计日志

        Args:
            log_path: 日志文件路径，默认 ~/.keeper/audit.log
        """
        if log_path:
            self.log_file = Path(log_path)
        else:
            self.log_file = Path.home() / ".keeper" / "audit.log"

        # 确保目录存在
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_turn(
        self,
        intent: str,
        entities: Dict[str, Any],
        result: str,
        response_time_ms: int,
        host: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """记录一次操作

        Args:
            intent: 意图类型
            entities: 实体参数
            result: 执行结果 (success/error/cancelled)
            response_time_ms: 响应时间 (毫秒)
            host: 目标主机（可选）
            error_message: 错误信息（可选）
        """
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            user=os.getenv("USER", "unknown"),
            intent=intent,
            entities=entities,
            result=result,
            response_time_ms=response_time_ms,
            host=host,
            error_message=error_message,
        )

        # 以 JSON Lines 格式追加写入
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def get_history(
        self,
        hours: int = 24,
        limit: int = 100,
        host: Optional[str] = None,
        intent: Optional[str] = None,
    ) -> List[AuditRecord]:
        """获取历史操作记录

        Args:
            hours: 查询最近 N 小时的记录
            limit: 最多返回多少条记录
            host: 按主机过滤
            intent: 按意图类型过滤

        Returns:
            List[AuditRecord]: 审计记录列表
        """
        records = []
        cutoff_time = datetime.now() - timedelta(hours=hours)

        if not self.log_file.exists():
            return records

        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    record_time = datetime.fromisoformat(data["timestamp"])

                    # 时间过滤
                    if record_time < cutoff_time:
                        continue

                    # 主机过滤
                    if host and data.get("host") != host:
                        continue

                    # 意图过滤
                    if intent and data.get("intent") != intent:
                        continue

                    records.append(AuditRecord(**data))

                    # 数量限制
                    if len(records) >= limit:
                        break

                except (json.JSONDecodeError, KeyError):
                    # 跳过无效行
                    continue

        # 按时间倒序（最新的在前）
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records

    def search(
        self,
        query: str,
        host: Optional[str] = None,
        intent: Optional[str] = None,
        hours: int = 168,  # 默认 7 天
        limit: int = 50,
    ) -> List[AuditRecord]:
        """搜索历史记录

        Args:
            query: 搜索关键词（匹配实体或错误信息）
            host: 按主机过滤
            intent: 按意图类型过滤
            hours: 查询最近 N 小时的记录
            limit: 最多返回多少条记录

        Returns:
            List[AuditRecord]: 审计记录列表
        """
        records = self.get_history(hours=hours, limit=limit * 2, host=host, intent=intent)

        # 关键词匹配
        if query:
            query_lower = query.lower()
            filtered = []
            for record in records:
                # 匹配实体
                entities_str = json.dumps(record.entities).lower()
                # 匹配错误信息
                error_msg = (record.error_message or "").lower()
                # 匹配主机
                host_str = (record.host or "").lower()

                if query_lower in entities_str or query_lower in error_msg or query_lower in host_str:
                    filtered.append(record)
            records = filtered

        return records[:limit]

    def clear(self) -> None:
        """清空审计日志"""
        if self.log_file.exists():
            self.log_file.unlink()

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """获取统计信息

        Args:
            hours: 统计最近 N 小时

        Returns:
            Dict: 统计数据
        """
        records = self.get_history(hours=hours, limit=10000)

        if not records:
            return {
                "total": 0,
                "success": 0,
                "error": 0,
                "by_intent": {},
                "avg_response_time_ms": 0,
            }

        # 统计
        success_count = sum(1 for r in records if r.result == "success")
        error_count = sum(1 for r in records if r.result == "error")

        # 按意图统计
        intent_counts = {}
        for record in records:
            intent = record.intent
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # 平均响应时间
        avg_time = sum(r.response_time_ms for r in records) / len(records)

        return {
            "total": len(records),
            "success": success_count,
            "error": error_count,
            "by_intent": intent_counts,
            "avg_response_time_ms": int(avg_time),
        }
