"""钉钉群机器人 Webhook 通知

支持：
- 纯文本消息
- Markdown 富文本
- ActionCard 卡片
- HmacSHA256 签名验证
"""
import time
import hmac
import hashlib
import base64
import json
import urllib.request
import urllib.error
from typing import Optional
from urllib.parse import quote_plus

from .base import BaseNotifier


class DingTalkNotifier(BaseNotifier):
    """钉钉群机器人通知"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        Args:
            webhook_url: 钉钉 Webhook URL
            secret: 签名密钥（可选，启用加签模式时需要）
        """
        self.webhook_url = webhook_url
        self.secret = secret

    @property
    def channel_name(self) -> str:
        return "钉钉"

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
        markdown_text = f"## {level_icon} {title}\n\n{content}"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown_text,
            },
        }
        return self._send(payload)

    def test_connection(self) -> bool:
        """测试连接"""
        return self.send_text("🔔 Keeper 钉钉通知测试 — 连接正常")

    def _get_signed_url(self) -> str:
        """获取带签名的 URL"""
        if not self.secret:
            return self.webhook_url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = quote_plus(base64.b64encode(hmac_code))
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

    def _send(self, payload: dict) -> bool:
        """发送请求"""
        url = self._get_signed_url()
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                return result.get("errcode", -1) == 0
        except (urllib.error.URLError, json.JSONDecodeError, Exception):
            return False
