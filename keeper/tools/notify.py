"""IM 通知推送 — 飞书群机器人 Webhook"""
import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any
from datetime import datetime


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

    def send_report(
        self,
        statuses: List[Any],
        thresholds: Dict[str, int],
        title: str = "Keeper 服务器巡检报告",
    ) -> bool:
        """发送 Markdown 格式巡检报告到飞书群

        生成与导出报告一致的 Markdown 内容，通过交互式卡片发送。

        Args:
            statuses: ServerStatus 列表
            thresholds: 阈值配置 {"cpu": 80, "memory": 85, "disk": 90}
            title: 卡片标题

        Returns:
            是否发送成功
        """
        total = len(statuses)
        healthy = 0
        warning = 0
        failed = 0

        for s in statuses:
            if s.ssh_failed:
                failed += 1
            elif (s.cpu_percent < thresholds.get("cpu", 80) and
                  s.memory_percent < thresholds.get("memory", 85) and
                  s.disk_percent < thresholds.get("disk", 90)):
                healthy += 1
            else:
                warning += 1

        # 根据结果确定卡片颜色
        if failed > 0:
            header_color = "red"
        elif warning > 0:
            header_color = "orange"
        else:
            header_color = "green"

        # 生成完整的 Markdown 内容
        md_lines = []

        # 汇总
        md_lines.append(f"**巡检时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md_lines.append(f"**巡检主机**：{total} 台")
        md_lines.append("")
        md_lines.append(f"**汇总**：🟢 健康 **{healthy}** 台 | 🟡 警告 **{warning}** 台 | 🔴 失败 **{failed}** 台")
        md_lines.append("")

        # 主机列表表格
        md_lines.append("| 主机 | CPU% | 内存% | 磁盘% | 负载 | 状态 |")
        md_lines.append("|------|------|-------|-------|------|------|")

        for s in statuses:
            if s.ssh_failed:
                md_lines.append(f"| {s.host} | - | - | - | - | ❌ 失败 |")
            else:
                cpu_ok = s.cpu_percent < thresholds.get("cpu", 80)
                mem_ok = s.memory_percent < thresholds.get("memory", 85)
                disk_ok = s.disk_percent < thresholds.get("disk", 90)

                cpu_tag = f"{s.cpu_percent:.1f}%"
                mem_tag = f"{s.memory_percent:.1f}%"
                disk_tag = f"{s.disk_percent:.1f}%"

                if not cpu_ok:
                    cpu_tag = f"**{s.cpu_percent:.1f}%** ⚠️"
                if not mem_ok:
                    mem_tag = f"**{s.memory_percent:.1f}%** ⚠️"
                if not disk_ok:
                    disk_tag = f"**{s.disk_percent:.1f}%** ⚠️"

                health_tag = "✅" if (cpu_ok and mem_ok and disk_ok) else "⚠️"
                md_lines.append(
                    f"| {s.host} | {cpu_tag} | {mem_tag} | {disk_tag} | {s.load_avg_1m:.2f} | {health_tag} |"
                )

        md_lines.append("")

        # 详细信息（前 3 台）
        success_statuses = [s for s in statuses if not s.ssh_failed]
        if success_statuses:
            md_lines.append("---")
            md_lines.append("")

            for s in success_statuses[:3]:
                cpu_ok = s.cpu_percent < thresholds.get("cpu", 80)
                mem_ok = s.memory_percent < thresholds.get("memory", 85)
                disk_ok = s.disk_percent < thresholds.get("disk", 90)

                md_lines.append(f"**{s.host}**")
                md_lines.append("")
                md_lines.append(f"  CPU:  {s.cpu_percent:.1f}%  {'✅' if cpu_ok else '⚠️'}")
                md_lines.append(f"  内存：{s.memory_percent:.1f}% ({s.memory_used_gb:.1f}/{s.memory_total_gb:.1f} GB)  {'✅' if mem_ok else '⚠️'}")
                md_lines.append(f"  磁盘：{s.disk_percent:.1f}% ({s.disk_used_gb:.1f}/{s.disk_total_gb:.1f} GB)  {'✅' if disk_ok else '⚠️'}")
                md_lines.append(f"  负载：{s.load_avg_1m:.2f}")
                md_lines.append(f"  开机：{s.boot_time}")
                if s.top_processes:
                    top3 = ", ".join(f"{p['name']}({p['memory_percent']:.1f}%)" for p in s.top_processes[:3])
                    md_lines.append(f"  Top：{top3}")
                md_lines.append("")

        # 失败主机
        if failed:
            md_lines.append("---")
            md_lines.append("")
            md_lines.append("**❌ 采集失败主机：**")
            for s in statuses:
                if s.ssh_failed:
                    md_lines.append(f"  • {s.host}")
            md_lines.append("")

        # 异常提醒
        warning_hosts = [s for s in statuses if not s.ssh_failed and (
            s.cpu_percent >= thresholds.get("cpu", 80) or
            s.memory_percent >= thresholds.get("memory", 85) or
            s.disk_percent >= thresholds.get("disk", 90)
        )]
        if warning_hosts:
            md_lines.append("**⚠️ 异常提醒：**")
            for s in warning_hosts:
                issues = []
                if s.cpu_percent >= thresholds.get("cpu", 80):
                    issues.append(f"CPU {s.cpu_percent:.1f}% (阈值 {thresholds.get('cpu', 80)}%)")
                if s.memory_percent >= thresholds.get("memory", 85):
                    issues.append(f"内存 {s.memory_percent:.1f}% (阈值 {thresholds.get('memory', 85)}%)")
                if s.disk_percent >= thresholds.get("disk", 90):
                    issues.append(f"磁盘 {s.disk_percent:.1f}% (阈值 {thresholds.get('disk', 90)}%)")
                md_lines.append(f"  • **{s.host}**：{'；'.join(issues)}")
            md_lines.append("")

        # 发送为 Markdown 卡片
        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md_lines)}},
        ]

        footer = f"Keeper 智能运维 · Generated by Keeper v0.4.0-dev"

        return self.send_card(
            title=title,
            elements=elements,
            footer=footer,
            header_color=header_color,
        )

    def send_card(
        self,
        title: str,
        elements: List[Dict],
        footer: Optional[str] = None,
        header_color: str = "blue",
    ) -> bool:
        """发送通用交互式卡片

        Args:
            title: 卡片标题
            elements: 卡片元素列表（div, hr, note, image 等）
            footer: 底部备注文字
            header_color: 卡片头部颜色 (red/orange/green/blue/yellow/purple)

        Returns:
            是否发送成功
        """
        content = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": header_color,
                },
                "elements": elements,
            },
        }

        if footer:
            content["card"]["elements"].append({"tag": "hr"})
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
