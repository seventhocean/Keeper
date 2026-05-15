"""结构化日志模块

提供统一的日志接口：
- JSON 格式输出（便于日志聚合）
- 统一字段：timestamp, level, module, message, context
- 日志级别通过配置/环境变量控制
- 各模块使用 get_logger(__name__) 获取实例

用法：
    from keeper.utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("巡检完成", host="192.168.1.100", duration_ms=320)
    logger.error("SSH 连接失败", host="10.0.0.1", error="timeout")
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON 格式日志 Formatter"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        # 添加额外字段（通过 extra 传入）
        if hasattr(record, "context") and record.context:
            log_entry["context"] = record.context

        # 异常信息
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, ensure_ascii=False)


class ContextLogger:
    """带上下文的 Logger 封装

    支持在日志中附加结构化 context 字段：
        logger.info("操作完成", host="xxx", duration=100)
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._setup()

    def _setup(self):
        """初始化 handler（避免重复添加）"""
        if self._logger.handlers:
            return

        # 日志级别从环境变量读取
        level = os.getenv("KEEPER_LOG_LEVEL", "INFO").upper()
        self._logger.setLevel(getattr(logging, level, logging.INFO))

        # 根据环境选择格式
        log_format = os.getenv("KEEPER_LOG_FORMAT", "text")  # text / json

        handler = logging.StreamHandler(sys.stderr)

        if log_format == "json":
            handler.setFormatter(JSONFormatter())
        else:
            # 人类可读格式
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            ))

        self._logger.addHandler(handler)
        self._logger.propagate = False

    def _log(self, level: int, message: str, **kwargs):
        """内部日志方法"""
        if kwargs:
            # 将 kwargs 作为 context 附加
            extra = {"context": kwargs}
            self._logger.log(level, message, extra=extra)
        else:
            self._logger.log(level, message)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs):
        """记录异常（自动附加 traceback）"""
        if kwargs:
            extra = {"context": kwargs}
            self._logger.exception(message, extra=extra)
        else:
            self._logger.exception(message)


def get_logger(name: str) -> ContextLogger:
    """获取模块 Logger

    Args:
        name: 模块名称（通常传 __name__）

    Returns:
        ContextLogger 实例

    Example:
        logger = get_logger(__name__)
        logger.info("服务器巡检完成", host="192.168.1.1", cpu=45.2)
    """
    return ContextLogger(name)
