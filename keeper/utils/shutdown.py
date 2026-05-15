"""Graceful Shutdown — 优雅停机机制

确保 Agent 在收到中断信号时：
1. 记录当前正在执行的操作状态
2. 保存未持久化的记忆和审计日志
3. 停止定时任务调度器
4. 安全退出，不留下半完成状态

使用方式：
    from keeper.utils.shutdown import ShutdownManager

    shutdown = ShutdownManager()
    shutdown.register(cleanup_func)  # 注册清理函数
    shutdown.install()  # 安装信号处理器

    # 在工具执行前标记
    with shutdown.running_task("inspect_server"):
        ... # 执行工具

    # 检查是否收到中断
    if shutdown.is_shutting_down:
        return "[中断] 操作已安全取消"
"""
import signal
import threading
import sys
from typing import Callable, List, Optional
from contextlib import contextmanager


class ShutdownManager:
    """优雅停机管理器"""

    def __init__(self):
        self._shutting_down = False
        self._current_task: Optional[str] = None
        self._cleanup_funcs: List[Callable] = []
        self._lock = threading.Lock()
        self._installed = False

    @property
    def is_shutting_down(self) -> bool:
        """是否正在关闭"""
        return self._shutting_down

    @property
    def current_task(self) -> Optional[str]:
        """当前正在执行的任务名"""
        return self._current_task

    def register(self, func: Callable) -> None:
        """注册清理函数（先注册的后执行 — LIFO）"""
        with self._lock:
            self._cleanup_funcs.append(func)

    def unregister(self, func: Callable) -> None:
        """取消注册清理函数"""
        with self._lock:
            try:
                self._cleanup_funcs.remove(func)
            except ValueError:
                pass

    @contextmanager
    def running_task(self, task_name: str):
        """标记当前正在执行的任务（上下文管理器）

        用于信号处理器中判断是否需要等待任务完成。
        """
        self._current_task = task_name
        try:
            yield
        finally:
            self._current_task = None

    def install(self) -> None:
        """安装信号处理器

        处理 SIGINT (Ctrl+C) 和 SIGTERM (kill)。
        仅在主线程中安装。
        """
        if self._installed:
            return

        # 只在主线程中安装信号处理器
        if threading.current_thread() is not threading.main_thread():
            return

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self._installed = True

    def _handle_signal(self, signum: int, frame) -> None:
        """信号处理器"""
        if self._shutting_down:
            # 第二次中断 — 强制退出
            sys.stderr.write("\n[强制退出]\n")
            sys.exit(1)

        self._shutting_down = True

        task_info = ""
        if self._current_task:
            task_info = f" (正在执行: {self._current_task}，等待完成...)"

        sys.stderr.write(f"\n[优雅退出] 收到中断信号{task_info}，正在清理...\n")

        # 执行清理（LIFO 顺序）
        self._run_cleanup()

    def _run_cleanup(self) -> None:
        """执行所有注册的清理函数"""
        with self._lock:
            funcs = list(reversed(self._cleanup_funcs))

        for func in funcs:
            try:
                func()
            except Exception as e:
                sys.stderr.write(f"[清理警告] {func.__name__}: {e}\n")

    def shutdown(self) -> None:
        """手动触发优雅关闭（非信号触发）"""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._run_cleanup()


# ─── 全局单例 ─────────────────────────────────────────────────

_global_shutdown: Optional[ShutdownManager] = None


def get_shutdown_manager() -> ShutdownManager:
    """获取全局 ShutdownManager 单例"""
    global _global_shutdown
    if _global_shutdown is None:
        _global_shutdown = ShutdownManager()
    return _global_shutdown
