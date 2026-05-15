"""Misc Handler — 帮助/导出/配置/安装/未知等通用处理"""
import subprocess
from typing import Dict, Any, List, Optional

from ...tools.server import ServerTools, format_batch_report
from ...tools.ssh import SSHTools, SSHConfig
from ...tools.scanner import NmapNotInstalledError
from ...tools.notify import FeishuNotifier


def handle_help(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理帮助请求"""
    return """📖 Keeper 完整能力一览

🖥️  **服务器巡检** — "检查本机" / "检查 192.168.1.100" / "服务器状态"
🔍  **批量巡检** — "批量巡检所有主机" / "检查所有机器"
🛡️  **漏洞扫描** — "扫描漏洞" / "扫描 192.168.1.100" / "全面扫描"
📊  **报告导出** — "导出为 JSON" / "生成 HTML 报告" / "保存为 Markdown"
📝  **日志查询** — "查看最近的操作记录" / "查看系统日志" / "查看 nginx 容器日志"
☸️  **K8s 管理** — "检查 K8s 集群状态" / "查看 Pod 的日志" / "重启 my-app deployment" / "把 frontend 扩到 5 个副本"
🐳  **Docker 管理** — "查看 Docker 容器状态" / "查看镜像占用" / "清理无用镜像" / "重启 xxx 容器"
🔧  **根因分析** — "分析一下为什么 CPU 高" / "帮我排查生产环境问题" / "对比 spring 和 autumn 的差异"
🌐  **网络诊断** — "测试 8.8.8.8 的延迟" / "检查 3306 端口通不通" / "DNS 解析正常吗"
⏰  **定时任务** — "每 30 分钟检查一次" / "每天早上 9 点巡检" / "查看定时任务"
🩹  **自动修复** — "帮我修复服务器问题" / "帮我清理一下磁盘" / "一键修复" / "验证修复效果"
🔒  **证书监控** — "检查 SSL 证书" / "看看证书有没有过期" / "检查 baidu.com 的证书"
📢  **飞书通知** — "发送到飞书" / "推送巡检结果"
💻  **软件安装** — "安装 nmap" / "在 192.168.1.100 上安装 xxx"
🔎  **问题排查** — "有没有什么问题" / "系统健康吗" / "有什么故障吗"
⚙️  **配置管理** — "把 CPU 阈值设为 80%" / "切换到 production 环境" / "显示配置"

输入 '退出' 或 Ctrl+D 结束会话
"""


def handle_chat(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理闲聊意图"""
    return """👋 你好！我是 Keeper，你的智能运维助手。

🖥️  "检查本机" — 服务器巡检
🛡️  "扫描漏洞" — 安全扫描
☸️  "检查 K8s 集群状态" — K8s 巡检
🐳  "查看 Docker 容器状态" — 容器管理
🔧  "分析一下为什么 CPU 高" — 根因分析
🌐  "测试 8.8.8.8 的延迟" — 网络诊断
💬  "帮助" — 查看完整能力列表

有什么需要帮忙的吗？"""


def handle_unknown(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理未知意图"""
    return """抱歉，我没有理解您的意思。您可以尝试以下方式：

  🖥️  "检查本机" — 服务器巡检
  🔍  "批量巡检所有主机" — 多主机巡检
  🛡️  "扫描漏洞" — 安全扫描
  ☸️  "检查 K8s 集群状态" — K8s 巡检
  🐳  "查看 Docker 容器状态" — 容器管理
  🔧  "分析一下为什么 CPU 高" — 根因分析
  🌐  "测试 8.8.8.8 的延迟" — 网络诊断
  🔎  "有没有什么问题" — 问题排查
  💬  "帮助" — 查看完整能力列表
"""


def handle_config(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理配置管理意图"""
    action = entities.get("action")
    profile = entities.get("profile")
    metric = entities.get("metric")
    threshold = entities.get("threshold")

    # 切换环境
    if profile and not action:
        state.context.current_profile = profile
        config.current_profile = profile
        return f"[配置] 已切换到环境：{profile}"

    # 修改阈值
    if action in ("set", "update") and threshold is not None:
        current_profile = config.current_profile
        profile_config = config.get_profile(current_profile)

        if "thresholds" not in profile_config:
            profile_config["thresholds"] = {}

        if metric:
            profile_config["thresholds"][metric] = int(threshold)
            config.set_profile(current_profile, profile_config)
            metric_name = {"cpu": "CPU", "memory": "内存", "disk": "磁盘"}.get(metric, metric)
            return f"[配置] 已将 {metric_name} 阈值设置为 {threshold}%"
        else:
            profile_config["thresholds"]["cpu"] = int(threshold)
            profile_config["thresholds"]["memory"] = int(threshold)
            profile_config["thresholds"]["disk"] = int(threshold)
            config.set_profile(current_profile, profile_config)
            return f"[配置] 已将所有阈值设置为 {threshold}%"

    # 显示配置
    current_profile = config.get_profile()
    lines = [f"[配置] 当前环境：{config.current_profile}"]

    if current_profile:
        lines.append("\n配置详情:")
        hosts = current_profile.get("hosts", [])
        thresholds = current_profile.get("thresholds", {})
        if hosts:
            lines.append(f"  主机列表：{', '.join(hosts)}")
        if thresholds:
            lines.append(
                f"  阈值配置：CPU={thresholds.get('cpu', 80)}%, "
                f"内存={thresholds.get('memory', 85)}%, "
                f"磁盘={thresholds.get('disk', 90)}%"
            )

    return "\n".join(lines)


def handle_export(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理报告导出意图"""
    from ...tools.reporter import ReportExporter
    from datetime import datetime

    fmt = (entities.get("format") or "html").lower()

    host = entities.get("host") or state.context.current_host
    if not host:
        mentioned_hosts = state.memory.get_hosts_mentioned()
        if mentioned_hosts:
            host = mentioned_hosts[-1]

    profile = entities.get("profile") or state.context.current_profile
    thresholds = {
        "cpu": config.get_threshold("cpu", profile),
        "memory": config.get_threshold("memory", profile),
        "disk": config.get_threshold("disk", profile),
    }

    if fmt in ("json",):
        export_fmt = "json"
    elif fmt in ("md", "markdown"):
        export_fmt = "markdown"
    else:
        export_fmt = "html"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_hosts = entities.get("all_hosts", False)
    if all_hosts:
        hosts = SSHTools.get_hosts_from_file("/etc/hosts")
        if not hosts:
            return "[报告] /etc/hosts 中没有找到可巡检的主机"
    elif host:
        hosts = [host]
    else:
        hosts = ["localhost"]

    try:
        statuses = ServerTools.inspect_multiple_hosts(hosts)
    except Exception as e:
        return f"[报告] 采集数据失败：{str(e)}"

    ext = {"json": "json", "html": "html", "markdown": "md"}[export_fmt]
    output_path = f"./keeper_report_{timestamp}.{ext}"

    if export_fmt == "json":
        result = ReportExporter.export_json(statuses, thresholds, output_path)
    elif export_fmt == "html":
        result = ReportExporter.export_html(statuses, thresholds, output_path)
    else:
        result = ReportExporter.export_markdown(statuses, thresholds, output_path)

    agent_ref._last_inspect_statuses = statuses

    # 飞书通知
    nc = config.get_notification_config()
    webhook = nc.get("feishu_webhook")
    if webhook:
        notifier = FeishuNotifier(webhook, nc.get("feishu_secret"))
        notifier.send_report(
            statuses=statuses,
            thresholds=thresholds,
            title=f"Keeper 巡检报告 ({export_fmt.upper()})",
        )

    return result


def handle_install(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理安装软件意图"""
    package = entities.get("package") or "nmap"
    host = entities.get("host")

    if not host:
        from ..agent import PendingTask
        cmd = NmapNotInstalledError.get_install_command()
        agent_ref.pending_task = PendingTask(
            task_type="install",
            package=package,
            host="localhost",
            message=(
                f"请在本地执行以下命令安装 {package}:\n\n  {cmd}\n\n"
                f"或者我可以帮你自动安装，输入 'yes' 或 '好的' 确认执行。"
            ),
        )
        return agent_ref.pending_task.message
    else:
        # 远程安装
        if not SSHTools.test_connection(host):
            return (
                f"[连接] 无法连接到 {host}\n\n"
                f"请检查:\n1. 主机是否在线\n2. SSH 服务是否运行\n"
                f"3. 防火墙设置\n4. SSH 密钥/密码配置"
            )

        success, output = SSHTools.execute(
            SSHConfig(host=host),
            f"sudo apt-get update && sudo apt-get install -y {package}",
        )
        if success:
            return f"[安装] ✓ {package} 已在 {host} 上成功安装\n\n{output[:500]}"
        else:
            return f"[安装] ✗ {package} 安装失败\n\n{output}"


def handle_confirm_no_task(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理确认但没有待办任务"""
    return (
        "[系统] 当前没有待确认的任务。您可以尝试：\n"
        "  - '扫描漏洞'\n"
        "  - '检查 192.168.1.100'\n"
        "  - '帮助'"
    )
