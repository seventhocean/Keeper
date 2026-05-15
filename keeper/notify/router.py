"""通知路由 — 按告警级别路由到不同渠道

配置示例（~/.keeper/config.yaml）：
    notifications:
      routes:
        - level: critical
          channels: [feishu, dingtalk]
        - level: warning
          channels: [feishu]
        - level: info
          channels: []
      feishu_webhook: "https://..."
      dingtalk_webhook: "https://..."
      wecom_webhook: "https://..."
"""
from typing import Dict, List, Optional
from .base import BaseNotifier
from .dingtalk import DingTalkNotifier
from .wecom import WeComNotifier


class NotifyRouter:
    """通知路由器"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 通知配置字典（从 AppConfig.notifications 获取）
        """
        self.config = config
        self._channels: Dict[str, BaseNotifier] = {}
        self._routes: List[Dict] = config.get("routes", [
            {"level": "critical", "channels": ["feishu", "dingtalk", "wecom"]},
            {"level": "warning", "channels": ["feishu"]},
            {"level": "info", "channels": []},
        ])
        self._init_channels()

    def _init_channels(self):
        """初始化各渠道"""
        # 飞书（复用现有实现）
        feishu_webhook = self.config.get("feishu_webhook")
        if feishu_webhook:
            try:
                from keeper.tools.notify import FeishuNotifier
                self._channels["feishu"] = FeishuNotifierWrapper(
                    FeishuNotifier(feishu_webhook, self.config.get("feishu_secret"))
                )
            except ImportError:
                pass

        # 钉钉
        dingtalk_webhook = self.config.get("dingtalk_webhook")
        if dingtalk_webhook:
            self._channels["dingtalk"] = DingTalkNotifier(
                dingtalk_webhook, self.config.get("dingtalk_secret")
            )

        # 企业微信
        wecom_webhook = self.config.get("wecom_webhook")
        if wecom_webhook:
            self._channels["wecom"] = WeComNotifier(wecom_webhook)

    def send(self, title: str, content: str, level: str = "info") -> Dict[str, bool]:
        """按级别路由发送通知

        Args:
            title: 通知标题
            content: 通知内容
            level: 级别 (critical/warning/info)

        Returns:
            各渠道发送结果 {"feishu": True, "dingtalk": False}
        """
        # 找到对应级别的路由规则
        target_channels = []
        for route in self._routes:
            if route.get("level") == level:
                target_channels = route.get("channels", [])
                break

        # 如果没找到匹配规则，critical 默认发所有
        if not target_channels and level == "critical":
            target_channels = list(self._channels.keys())

        # 发送
        results = {}
        for ch_name in target_channels:
            notifier = self._channels.get(ch_name)
            if notifier:
                try:
                    ok = notifier.send_rich(title, content, level)
                    results[ch_name] = ok
                except Exception:
                    results[ch_name] = False

        return results

    def send_text(self, text: str, channels: Optional[List[str]] = None) -> Dict[str, bool]:
        """发送纯文本到指定渠道"""
        if channels is None:
            channels = list(self._channels.keys())

        results = {}
        for ch_name in channels:
            notifier = self._channels.get(ch_name)
            if notifier:
                try:
                    results[ch_name] = notifier.send_text(text)
                except Exception:
                    results[ch_name] = False

        return results

    def test_all(self) -> Dict[str, bool]:
        """测试所有渠道连通性"""
        results = {}
        for name, notifier in self._channels.items():
            try:
                results[name] = notifier.test_connection()
            except Exception:
                results[name] = False
        return results

    def list_channels(self) -> List[str]:
        """列出已配置的渠道"""
        return list(self._channels.keys())

    def format_status(self) -> str:
        """格式化通知状态"""
        lines = ["[通知渠道状态]", "━" * 40]
        if not self._channels:
            lines.append("  (未配置任何通知渠道)")
        else:
            for name, notifier in self._channels.items():
                lines.append(f"  • {notifier.channel_name} ({name}): ✓ 已配置")
        lines.append("━" * 40)
        lines.append(f"  路由规则: {len(self._routes)} 条")
        return "\n".join(lines)


class FeishuNotifierWrapper(BaseNotifier):
    """飞书 Notifier 包装（适配 BaseNotifier 接口）"""

    def __init__(self, feishu_notifier):
        self._notifier = feishu_notifier

    @property
    def channel_name(self) -> str:
        return "飞书"

    def send_text(self, text: str) -> bool:
        return self._notifier.send_text(text)

    def send_rich(self, title: str, content: str, level: str = "info") -> bool:
        # 飞书富文本用 send_rich 方法
        sections = [[{"tag": "text", "text": content}]]
        return self._notifier.send_rich(title, sections)

    def test_connection(self) -> bool:
        return self.send_text("🔔 Keeper 飞书通知测试 — 连接正常")
