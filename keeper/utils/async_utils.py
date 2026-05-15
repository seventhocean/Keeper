"""异步工具集 — 为网络密集型操作提供并发支持

提供：
- async_ping_hosts: 并发 ping 多台主机
- async_check_ports: 并发端口检测
- async_batch_inspect: 异步批量巡检
- run_in_thread: 将同步函数包装为异步
- AsyncBatchExecutor: 通用异步批量执行器

使用场景：
- API Server 中的异步接口
- 批量巡检时替代纯 ThreadPoolExecutor
- 多主机并发网络诊断
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, List, Dict, TypeVar, Optional, Coroutine
from functools import partial

T = TypeVar("T")

# 默认线程池（复用，避免频繁创建/销毁）
_default_executor: Optional[ThreadPoolExecutor] = None


def get_executor(max_workers: int = 20) -> ThreadPoolExecutor:
    """获取全局复用的线程池"""
    global _default_executor
    if _default_executor is None or _default_executor._shutdown:
        _default_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="keeper-async")
    return _default_executor


async def run_in_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """在线程池中运行同步函数

    Args:
        func: 同步函数
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        函数返回值

    Example:
        result = await run_in_thread(ServerTools.inspect_server, "localhost")
    """
    loop = asyncio.get_event_loop()
    executor = get_executor()
    if kwargs:
        fn = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, fn)
    else:
        return await loop.run_in_executor(executor, func, *args)


async def async_ping_hosts(hosts: List[str], count: int = 4, max_concurrency: int = 20) -> List[Dict[str, Any]]:
    """并发 ping 多台主机

    Args:
        hosts: 主机列表
        count: 每个 ping 的包数
        max_concurrency: 最大并发数

    Returns:
        各主机的 ping 结果列表（顺序与 hosts 一致）
    """
    from ..tools.network import NetworkTools

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _ping_one(host: str) -> Dict[str, Any]:
        async with semaphore:
            return await run_in_thread(NetworkTools.ping, host, count)

    tasks = [_ping_one(h) for h in hosts]
    return await asyncio.gather(*tasks, return_exceptions=False)


async def async_check_ports(targets: List[Dict[str, Any]], max_concurrency: int = 50) -> List[Dict[str, Any]]:
    """并发端口检测

    Args:
        targets: [{"host": "...", "port": 80}, ...]
        max_concurrency: 最大并发数

    Returns:
        各目标的检测结果列表
    """
    from ..tools.network import NetworkTools

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _check_one(target: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await run_in_thread(
                NetworkTools.check_port,
                target["host"],
                target["port"],
                target.get("timeout", 5),
            )

    tasks = [_check_one(t) for t in targets]
    return await asyncio.gather(*tasks, return_exceptions=False)


async def async_batch_inspect(hosts: List[str], max_concurrency: int = 10) -> List[Any]:
    """异步批量服务器巡检

    与 ServerTools.inspect_multiple_hosts 功能相同，但使用 asyncio 并发。
    适合在 API Server 的 async 接口中调用。

    Args:
        hosts: 主机 IP 列表
        max_concurrency: 最大并发数

    Returns:
        ServerStatus 列表
    """
    from ..tools.server import ServerTools

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _inspect_one(host: str):
        async with semaphore:
            return await run_in_thread(ServerTools.inspect_server, host)

    tasks = [_inspect_one(h) for h in hosts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常结果
    from ..tools.server import ServerStatus
    from datetime import datetime

    clean_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            clean_results.append(ServerStatus(
                host=hosts[i],
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cpu_percent=0, memory_percent=0, memory_used_gb=0, memory_total_gb=0,
                disk_percent=0, disk_used_gb=0, disk_total_gb=0,
                load_avg_1m=0, load_avg_5m=0, load_avg_15m=0,
                boot_time="", top_processes=[], ssh_failed=True,
            ))
        else:
            clean_results.append(result)

    return clean_results


class AsyncBatchExecutor:
    """通用异步批量执行器

    将多个同步任务包装为并发异步执行。

    Example:
        executor = AsyncBatchExecutor(max_concurrency=10)
        results = await executor.run(
            func=NetworkTools.ping,
            args_list=[("8.8.8.8",), ("1.1.1.1",), ("baidu.com",)],
        )
    """

    def __init__(self, max_concurrency: int = 10):
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def run(self, func: Callable, args_list: List[tuple], kwargs_list: Optional[List[dict]] = None) -> List[Any]:
        """批量执行

        Args:
            func: 同步函数
            args_list: 每次调用的参数 [(arg1, arg2), ...]
            kwargs_list: 每次调用的关键字参数 [{"k": "v"}, ...]

        Returns:
            结果列表（顺序与输入一致）
        """
        if kwargs_list is None:
            kwargs_list = [{}] * len(args_list)

        async def _execute_one(args: tuple, kwargs: dict):
            async with self.semaphore:
                return await run_in_thread(func, *args, **kwargs)

        tasks = [_execute_one(args, kwargs) for args, kwargs in zip(args_list, kwargs_list)]
        return await asyncio.gather(*tasks, return_exceptions=True)
