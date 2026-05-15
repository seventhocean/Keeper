"""通知渠道抽象接口

所有通知渠道实现此基类，支持统一调用。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class BaseNotifier(ABC):
    """通知渠道基类"""

    @abstractmethod
    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        pass

    @abstractmethod
    def send_rich(self, title: str, content: str, level: str = "info") -> bool:
        """发送富文本/卡片消息

        Args:
            title: 标题
            content: 正文（Markdown 格式）
            level: 消息级别 info/warning/critical
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否正常"""
        pass

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """渠道名称（用于日志和展示）"""
        pass
