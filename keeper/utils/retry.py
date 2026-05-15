"""统一重试机制 — 指数退避重试装饰器

用法：
    from keeper.utils.retry import with_retry, RetryConfig

    # 默认策略（3次，指数退避）
    @with_retry()
    def call_llm():
        ...

    # 自定义策略
    @with_retry(RetryConfig(max_attempts=5, base_delay=2.0))
    def ssh_connect():
        ...

    # 指定只重试某些异常
    @with_retry(RetryConfig(retry_on=(ConnectionError, TimeoutError)))
    def api_call():
        ...
"""
import time
import functools
import logging
from typing import Tuple, Type, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3                    # 最大尝试次数（含首次）
    base_delay: float = 1.0                  # 基础延迟（秒）
    max_delay: float = 30.0                  # 最大延迟（秒）
    exponential_base: float = 2.0            # 指数基数
    retry_on: Tuple[Type[Exception], ...] = (Exception,)  # 重试的异常类型
    on_retry: Optional[Callable] = None      # 重试时的回调


def with_retry(config: Optional[RetryConfig] = None):
    """重试装饰器

    Args:
        config: 重试配置，默认 3 次指数退避

    Example:
        @with_retry()
        def unstable_operation():
            ...

        @with_retry(RetryConfig(max_attempts=5))
        def important_operation():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except config.retry_on as e:
                    last_exception = e

                    if attempt == config.max_attempts:
                        # 最后一次，不再重试
                        break

                    # 计算延迟
                    delay = min(
                        config.base_delay * (config.exponential_base ** (attempt - 1)),
                        config.max_delay,
                    )

                    logger.warning(
                        f"[重试] {func.__name__} 第 {attempt}/{config.max_attempts} 次失败: "
                        f"{type(e).__name__}: {str(e)[:100]}，{delay:.1f}s 后重试"
                    )

                    # 回调
                    if config.on_retry:
                        config.on_retry(func.__name__, attempt, e)

                    time.sleep(delay)

            # 所有重试都失败
            raise last_exception

        return wrapper
    return decorator


# ─── 预定义策略 ─────────────────────────────────────────────────

LLM_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    retry_on=(Exception,),  # LLM 调用可能抛各种异常
)

SSH_RETRY = RetryConfig(
    max_attempts=2,
    base_delay=2.0,
    max_delay=5.0,
    retry_on=(OSError, IOError),
)

K8S_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    retry_on=(Exception,),
)

NETWORK_RETRY = RetryConfig(
    max_attempts=2,
    base_delay=0.5,
    max_delay=3.0,
    retry_on=(OSError, IOError),
)
