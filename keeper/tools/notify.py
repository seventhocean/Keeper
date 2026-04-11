"""IM 通知推送 — 飞书群机器人 Webhook"""
import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.error
from typing import Optional, List, Dict


class FeishuNotifier:
    """飞书群机器人 Webhook 通知"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret

    def send_text(self, text: str, at_user_ids: Optional[List[str]] = None) -> bool:
        """发送纯文本消息

        Args:
            text: 消息内容
            at_user_ids: 要 @ 的 open_id 列表

        Returns:
            是否发送成功
        """
        content = {"msg_type": "text", "content": {"text": text}}

        if at_user_ids:
            at_list = " ".join(f'<at user_id="{uid}"></at>' for uid in at_user_ids)
            content["content"]["text"] = text + "\n" + at_list

        return self._send(content)

    def send_rich(
        self,
        title: str,
        sections: List[List[Dict[str, str]]],
        footer: Optional[str] = None,
    ) -> bool:
        """发送富文本卡片消息

        Args:
            title: 卡片标题
            sections: 内容区块列表，每个区块是元素列表
                元素格式: {"tag": "text", "text": "内容"}
                         {"tag": "a", "text": "链接文字", "href": "url"}
            footer: 底部文字

        Returns:
            是否发送成功
        """
        content = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": self._severity_to_color(title),
                },
                "elements": [],
            },
        }

        for section in sections:
            content["card"]["elements"].append(
                {"tag": "div", "fields": section}
            )

        if footer:
            content["card"]["elements"].append(
                {"tag": "hr"}
            )
            content["card"]["elements"].append(
                {"tag": "note", "elements": [{"tag": "plain_text", "content": footer}]}
            )

        return self._send(content)

    def _gen_sign(self, timestamp: int) -> str:
        """生成签名（HMAC-SHA256）"""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def _severity_to_color(self, title: str) -> str:
        """根据标题中的 emoji 确定卡片颜色"""
        if "\U0001f534" in title or "\U0001f6a8" in title:  # 🔴 or 🚨
            return "red"
        elif "\U0001f7e1" in title or "\u26a0" in title:  # 🟡 or ⚠
            return "orange"
        elif "\U0001f7e2" in title or "\u2705" in title:  # 🟢 or ✅
            return "green"
        return "blue"

    def _send(self, payload: Dict) -> bool:
        """发送 HTTP POST 到飞书 Webhook"""
        if self.secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = self._gen_sign(timestamp)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )

            for attempt in range(2):  # 重试 1 次
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                        code = result.get("code", -1)
                        if code == 0:
                            return True
                        # 重试
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        return False
                except (urllib.error.URLError, urllib.error.HTTPError, OSError):
                    if attempt == 0:
                        time.sleep(1)
                        continue
                    return False
        except Exception:
            return False

        return False
