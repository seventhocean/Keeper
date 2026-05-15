"""审计日志模块 - 操作记录持久化

增强：
- 文件大小限制（默认 10MB）
- 自动轮转（保留最近 5 个归档文件）
- 写入前检查大小，超限时自动轮转
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict


# ─── 默认配置 ────────────────────────────────────────────────
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_BACKUP_COUNT = 5                    # 保留 5 个归档文件


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
    response: Optional[str] = None  # Agent 响应内容


class AuditLogger:
    """审计日志记录器（带自动轮转）"""

    def __init__(
        self,
        log_path: Optional[str] = None,
        max_size_bytes: int = MAX_LOG_SIZE_BYTES,
        max_backups: int = MAX_BACKUP_COUNT,
    ):
        """初始化审计日志

        Args:
            log_path: 日志文件路径，默认 ~/.keeper/audit.log
            max_size_bytes: 单个日志文件最大字节数，默认 10MB
            max_backups: 保留的归档文件数量，默认 5
        """
        if log_path:
            self.log_file = Path(log_path)
        else:
            self.log_file = Path.home() / ".keeper" / "audit.log"

        self.max_size_bytes = max_size_bytes
        self.max_backups = max_backups

        # 确保目录存在
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _should_rotate(self) -> bool:
        """检查是否需要轮转"""
        if not self.log_file.exists():
            return False
        try:
            return self.log_file.stat().st_size >= self.max_size_bytes
        except OSError:
            return False

    def _rotate(self) -> None:
        """执行日志轮转

        轮转策略：
        - audit.log → audit.log.1
        - audit.log.1 → audit.log.2
        - ...
        - audit.log.{max_backups} → 删除
        """
        # 删除最旧的归档
        oldest = self.log_file.with_suffix(f".log.{self.max_backups}")
        if oldest.exists():
            oldest.unlink()

        # 依次重命名：N → N+1（从大到小）
        for i in range(self.max_backups - 1, 0, -1):
            src = self.log_file.with_suffix(f".log.{i}")
            dst = self.log_file.with_suffix(f".log.{i + 1}")
            if src.exists():
                shutil.move(str(src), str(dst))

        # 当前文件 → .1
        if self.log_file.exists():
            dst = self.log_file.with_suffix(".log.1")
            shutil.move(str(self.log_file), str(dst))

    def log_turn(
        self,
        intent: str,
        entities: Dict[str, Any],
        result: str,
        response_time_ms: int,
        host: Optional[str] = None,
        error_message: Optional[str] = None,
        response: Optional[str] = None,
    ) -> None:
        """记录一次操作

        Args:
            intent: 意图类型
            entities: 实体参数
            result: 执行结果 (success/error/cancelled)
            response_time_ms: 响应时间 (毫秒)
            host: 目标主机（可选）
            error_message: 错误信息（可选）
            response: Agent 响应内容（可选）
        """
        # 写入前检查是否需要轮转
        if self._should_rotate():
            try:
                self._rotate()
            except Exception:
                pass  # 轮转失败不影响写入

        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            user=os.getenv("USER", "unknown"),
            intent=intent,
            entities=entities,
            result=result,
            response_time_ms=response_time_ms,
            host=host,
            error_message=error_message,
            response=response,
        )

        # 以 JSON Lines 格式追加写入
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except OSError:
            pass  # 写入失败不抛异常

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

                except (json.JSONDecodeError, KeyError):
                    # 跳过无效行
                    continue

        # 按时间倒序（最新的在前）
        records.sort(key=lambda r: r.timestamp, reverse=True)

        # 应用限制
        if limit > 0:
            records = records[:limit]

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

    def get_log_info(self) -> Dict[str, Any]:
        """获取日志文件信息（大小、归档数量等）"""
        info = {
            "log_file": str(self.log_file),
            "max_size_mb": self.max_size_bytes / (1024 * 1024),
            "max_backups": self.max_backups,
            "current_size_bytes": 0,
            "current_size_mb": 0.0,
            "backup_count": 0,
            "total_size_mb": 0.0,
        }

        if self.log_file.exists():
            size = self.log_file.stat().st_size
            info["current_size_bytes"] = size
            info["current_size_mb"] = round(size / (1024 * 1024), 2)

        # 统计归档文件
        total_size = info["current_size_bytes"]
        for i in range(1, self.max_backups + 1):
            backup = self.log_file.with_suffix(f".log.{i}")
            if backup.exists():
                info["backup_count"] += 1
                total_size += backup.stat().st_size

        info["total_size_mb"] = round(total_size / (1024 * 1024), 2)
        return info
