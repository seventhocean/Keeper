"""Notify Handler — 通知推送相关处理"""
from typing import Dict, Any

from ...tools.notify import FeishuNotifier


def handle_send_notify(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理推送通知意图"""
    nc = config.get_notification_config()
    webhook = nc.get("feishu_webhook")
    if not webhook:
        return "[通知] 未配置飞书 Webhook\n\n请先配置: keeper notify config --feishu-webhook <url>"

    # 从审计日志获取最近一次成功的操作记录
    records = agent_ref.audit.get_history(limit=10)
    last_record = None
    for record in records:
        if record.intent == "send_notify":
            continue
        if record.result != "success" or not record.response:
            continue
        lines = record.response.split("\n")
        if len(lines) < 3 and len(record.response) < 30:
            continue
        if record.response.startswith("[通知]") or "[Docker] 未找到" in record.response:
            continue
        last_record = record
        break

    if not last_record:
        return "[通知] 暂无可推送的内容\n\n提示：短消息不会推送到飞书，请先执行巡检等操作。"

    notifier = FeishuNotifier(webhook, nc.get("feishu_secret"))

    icon = "🔴" if last_record.result == "error" else "🟢"
    title = f"{icon} Keeper {last_record.intent}"

    lines = last_record.response.split("\n")
    summary_lines = [{"tag": "text", "text": line} for line in lines[:30]]
    sections = [summary_lines]

    host = last_record.host or state.context.current_host
    if host:
        sections.append([{"tag": "text", "text": f"主机: {host}"}])

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections.append([{"tag": "text", "text": f"时间: {now}"}])

    ok = notifier.send_rich(title=title, sections=sections, footer="Keeper v1.0.0")
    if ok:
        return "[通知] 已将最近操作结果推送到飞书"
    return "[通知] 推送失败，请检查 Webhook 配置和网络连接"
