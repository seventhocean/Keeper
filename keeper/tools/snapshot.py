"""执行前状态快照 — 修复操作前自动备份关键状态

功能：
- 自动备份：iptables 规则、systemd 服务状态、关键配置文件 hash、网络连接
- 存储位置：~/.keeper/snapshots/<timestamp>/
- 保留最近 10 次快照
- 支持回滚时恢复
"""
import os
import json
import hashlib
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class SnapshotData:
    """快照数据"""
    timestamp: str
    host: str
    iptables_rules: str = ""
    services_status: Dict[str, str] = field(default_factory=dict)
    config_hashes: Dict[str, str] = field(default_factory=dict)
    network_connections: str = ""
    disk_usage: str = ""
    process_list: str = ""


class SnapshotManager:
    """状态快照管理器"""

    MAX_SNAPSHOTS = 10
    CRITICAL_CONFIG_FILES = [
        "/etc/nginx/nginx.conf",
        "/etc/ssh/sshd_config",
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/fstab",
        "/etc/crontab",
    ]

    def __init__(self, snapshot_dir: Optional[Path] = None):
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else Path.home() / ".keeper" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def take_snapshot(self, host: str = "localhost") -> SnapshotData:
        """创建当前状态快照

        Args:
            host: 主机标识

        Returns:
            SnapshotData 快照数据
        """
        snapshot = SnapshotData(
            timestamp=datetime.now().isoformat(),
            host=host,
        )

        # 1. iptables 规则
        snapshot.iptables_rules = self._capture_iptables()

        # 2. 关键服务状态
        snapshot.services_status = self._capture_services()

        # 3. 配置文件 hash
        snapshot.config_hashes = self._capture_config_hashes()

        # 4. 网络连接
        snapshot.network_connections = self._capture_network()

        # 5. 磁盘使用
        snapshot.disk_usage = self._run_cmd("df -h")

        # 6. 进程列表
        snapshot.process_list = self._run_cmd("ps aux --sort=-%mem | head -20")

        # 持久化
        self._save_snapshot(snapshot)

        # 清理旧快照
        self._cleanup_old_snapshots()

        return snapshot

    def get_latest(self) -> Optional[SnapshotData]:
        """获取最新快照"""
        snapshots = self._list_snapshot_dirs()
        if not snapshots:
            return None
        return self._load_snapshot(snapshots[-1])

    def list_snapshots(self) -> List[Dict[str, str]]:
        """列出所有快照摘要"""
        result = []
        for d in self._list_snapshot_dirs():
            info_file = d / "info.json"
            if info_file.exists():
                try:
                    with open(info_file) as f:
                        data = json.load(f)
                    result.append({
                        "timestamp": data.get("timestamp", ""),
                        "host": data.get("host", ""),
                        "path": str(d),
                    })
                except (json.JSONDecodeError, KeyError):
                    pass
        return result

    def compare_with_current(self, snapshot: Optional[SnapshotData] = None) -> Dict[str, Any]:
        """将快照与当前状态对比

        Returns:
            变化项列表
        """
        if snapshot is None:
            snapshot = self.get_latest()
        if snapshot is None:
            return {"changes": [], "message": "无可用快照"}

        changes = []

        # 对比配置文件 hash
        current_hashes = self._capture_config_hashes()
        for path, old_hash in snapshot.config_hashes.items():
            new_hash = current_hashes.get(path, "missing")
            if new_hash != old_hash:
                changes.append({
                    "type": "config_changed",
                    "file": path,
                    "old_hash": old_hash[:8],
                    "new_hash": new_hash[:8],
                })

        # 对比服务状态
        current_services = self._capture_services()
        for svc, old_status in snapshot.services_status.items():
            new_status = current_services.get(svc, "unknown")
            if new_status != old_status:
                changes.append({
                    "type": "service_changed",
                    "service": svc,
                    "old_status": old_status,
                    "new_status": new_status,
                })

        return {"changes": changes, "message": f"发现 {len(changes)} 项变化"}

    def _capture_iptables(self) -> str:
        """捕获 iptables 规则"""
        return self._run_cmd("iptables-save 2>/dev/null || echo 'iptables not available'")

    def _capture_services(self) -> Dict[str, str]:
        """捕获关键服务状态"""
        services = ["nginx", "mysql", "docker", "sshd", "redis", "postgresql"]
        result = {}
        for svc in services:
            status = self._run_cmd(f"systemctl is-active {svc} 2>/dev/null")
            if status:
                result[svc] = status.strip()
        return result

    def _capture_config_hashes(self) -> Dict[str, str]:
        """计算关键配置文件的 hash"""
        hashes = {}
        for path in self.CRITICAL_CONFIG_FILES:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        hashes[path] = hashlib.md5(f.read()).hexdigest()
                except (PermissionError, IOError):
                    hashes[path] = "no_permission"
            else:
                hashes[path] = "not_found"
        return hashes

    def _capture_network(self) -> str:
        """捕获网络连接状态"""
        return self._run_cmd("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || echo 'no tool'")

    def _run_cmd(self, cmd: str, timeout: int = 10) -> str:
        """执行命令并返回输出"""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, Exception):
            return ""

    def _save_snapshot(self, snapshot: SnapshotData):
        """保存快照到磁盘"""
        ts = snapshot.timestamp.replace(":", "-").replace(".", "-")[:19]
        snap_dir = self.snapshot_dir / ts
        snap_dir.mkdir(parents=True, exist_ok=True)

        with open(snap_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(asdict(snapshot), f, ensure_ascii=False, indent=2)

    def _load_snapshot(self, snap_dir: Path) -> Optional[SnapshotData]:
        """从磁盘加载快照"""
        info_file = snap_dir / "info.json"
        if not info_file.exists():
            return None
        try:
            with open(info_file) as f:
                data = json.load(f)
            return SnapshotData(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def _list_snapshot_dirs(self) -> List[Path]:
        """列出快照目录（按时间排序）"""
        if not self.snapshot_dir.exists():
            return []
        dirs = [d for d in self.snapshot_dir.iterdir() if d.is_dir()]
        return sorted(dirs)

    def _cleanup_old_snapshots(self):
        """清理超过 MAX_SNAPSHOTS 的旧快照"""
        dirs = self._list_snapshot_dirs()
        while len(dirs) > self.MAX_SNAPSHOTS:
            old_dir = dirs.pop(0)
            shutil.rmtree(old_dir, ignore_errors=True)
