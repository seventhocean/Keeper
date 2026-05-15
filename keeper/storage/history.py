"""巡检历史持久化 — SQLite 存储

每次巡检自动写入，支持：
- 按主机查询历史
- 按时间范围查询
- 获取最近 N 次巡检
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class InspectionRecord:
    """巡检记录"""
    id: int
    host: str
    timestamp: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    load_avg_1m: float
    raw_json: str  # 完整 ServerStatus JSON


class InspectionHistory:
    """巡检历史存储"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else Path.home() / ".keeper" / "history.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    cpu_percent REAL,
                    memory_percent REAL,
                    disk_percent REAL,
                    load_avg_1m REAL,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_host_time
                ON inspections(host, timestamp)
            """)

    def save(self, host: str, cpu: float, memory: float, disk: float,
             load: float, raw_data: Optional[Dict] = None) -> int:
        """保存一条巡检记录

        Returns:
            记录 ID
        """
        timestamp = datetime.now().isoformat()
        raw_json = json.dumps(raw_data, ensure_ascii=False) if raw_data else "{}"

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "INSERT INTO inspections (host, timestamp, cpu_percent, memory_percent, disk_percent, load_avg_1m, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (host, timestamp, cpu, memory, disk, load, raw_json),
            )
            return cursor.lastrowid

    def get_latest(self, host: str, n: int = 1) -> List[InspectionRecord]:
        """获取某主机最近 N 条巡检记录"""
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT id, host, timestamp, cpu_percent, memory_percent, disk_percent, load_avg_1m, raw_json FROM inspections WHERE host = ? ORDER BY timestamp DESC LIMIT ?",
                (host, n),
            ).fetchall()
        return [InspectionRecord(*row) for row in rows]

    def get_by_time_range(self, host: str, hours: int = 24) -> List[InspectionRecord]:
        """获取某主机指定时间范围内的记录"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT id, host, timestamp, cpu_percent, memory_percent, disk_percent, load_avg_1m, raw_json FROM inspections WHERE host = ? AND timestamp >= ? ORDER BY timestamp",
                (host, since),
            ).fetchall()
        return [InspectionRecord(*row) for row in rows]

    def get_all_hosts(self) -> List[str]:
        """获取所有有记录的主机列表"""
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT host FROM inspections ORDER BY host"
            ).fetchall()
        return [row[0] for row in rows]

    def count(self, host: Optional[str] = None) -> int:
        """获取记录总数"""
        with sqlite3.connect(str(self.db_path)) as conn:
            if host:
                row = conn.execute("SELECT COUNT(*) FROM inspections WHERE host = ?", (host,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM inspections").fetchone()
        return row[0] if row else 0

    def cleanup(self, days: int = 90):
        """清理指定天数前的旧记录"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM inspections WHERE timestamp < ?", (cutoff,))
