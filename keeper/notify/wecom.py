"""企业微信群机器人 Webhook 通知

支持：
- 纯文本消息
- Markdown 富文本
"""
import json
import urllib.request
import urllib.error
from typing import Optional

from .base import BaseNotifier


class WeComNotifier(BaseNotifier):
    """企业微信群机器人通知"""

    def __init__(self, webhook_url: str):
        """
        Args:
            webhook_url: 企微 Webhook URL (https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx)
        """
        self.webhook_url = webhook_url

    @property
    def channel_name(self) -> str:
        return "企业微信"

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": text},
        }
        return self._send(payload)

    def send_rich(self, title: str, content: str, level: str = "info") -> bool:
        """发送 Markdown 消息"""
        level_icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}.get(level, "")
        markdown_content = f"## {level_icon} {title}\n\n{content}"

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": markdown_content},
        }
        return self._send(payload)

    def test_connection(self) -> bool:
        """测试连接"""
        return self.send_text("🔔 Keeper 企微通知测试 — 连接正常")

    def _send(self, payload: dict) -> bool:
        """发送请求"""
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                return result.get("errcode", -1) == 0
        except (urllib.error.URLError, json.JSONDecodeError, Exception):
            return False
