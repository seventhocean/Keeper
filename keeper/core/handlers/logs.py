"""Logs Handler — 日志查询相关处理"""
import re
import subprocess
from typing import Dict, Any, List, Optional


def handle_logs(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理日志查询意图"""
    log_source = entities.get("log_source")
    query = entities.get("query")

    # 判断是否是"问题排查"意图
    raw_input = entities.get("_raw_input", "")
    is_troubleshoot = any(
        w in raw_input for w in ["问题", "异常", "错误", "故障", "告警", "报警", "有没有什么", "健康"]
    )

    # 系统日志查询
    if log_source in ("system", "journal"):
        from ...tools.logs import LogTools

        unit = entities.get("unit")
        lines_count = int(entities.get("lines", 50))
        since = entities.get("since")

        if is_troubleshoot and not unit:
            return _system_troubleshoot(since)

        keyword = query
        if keyword and all(ord(c) < 128 for c in keyword):
            success, output = LogTools.query_journal(
                lines=lines_count, unit=unit, since=since, keyword=keyword
            )
        else:
            success, output = LogTools.query_journal(
                lines=lines_count, unit=unit, since=since
            )

        if not success:
            return f"[系统日志] {output}"
        if not output.strip():
            return "[系统日志] 未找到匹配的日志"

        max_lines = 200
        output_lines = output.split("\n")
        if len(output_lines) > max_lines:
            output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"

        return f"[系统日志] (journalctl -n {lines_count}):\n\n{output}"

    # Docker 日志查询
    if log_source in ("docker", "container"):
        from ...tools.logs import LogTools

        container = entities.get("container") or entities.get("host")
        lines_count = int(entities.get("lines", 50))
        keyword = entities.get("query")

        if not container:
            return "[日志] 请指定容器名称，例如：查看 nginx 容器日志"

        success, output = LogTools.query_docker_logs(
            container_name=container, lines=lines_count, keyword=keyword
        )

        if not success:
            return f"[Docker 日志] {output}"
        if not output.strip():
            return f"[Docker 日志] 容器 {container} 无日志输出"

        return f"[Docker 日志] ({container}):\n\n{output}"

    # 文件日志查询
    if log_source in ("file",):
        from ...tools.logs import LogTools

        path = entities.get("path")
        lines_count = int(entities.get("lines", 50))
        keyword = entities.get("query")

        if not path:
            return "[日志] 请指定日志文件路径，例如：查看 /var/log/nginx/access.log"

        success, output = LogTools.query_file(path=path, lines=lines_count, keyword=keyword)

        if not success:
            return f"[文件日志] {output}"
        if not output.strip():
            return f"[文件日志] 文件 {path} 无匹配内容"

        return f"[文件日志] ({path}):\n\n{output}"

    # 审计日志（Keeper 操作记录）
    host = entities.get("host")
    hours = entities.get("hours")
    intent_filter = entities.get("intent_type")

    if query or host or hours or intent_filter:
        hours_int = int(hours) if hours else 24
        records = agent_ref.audit.get_history(
            hours=hours_int, limit=20, host=host, intent=intent_filter,
        )

        if not records:
            return f"[日志] 过去 {hours_int} 小时内没有找到 Keeper 操作记录"

        lines = [f"[日志] 过去 {hours_int} 小时的 Keeper 操作记录:"]
        for i, record in enumerate(records, 1):
            time_str = record.timestamp[11:19]
            result_icon = "✓" if record.result == "success" else "✗"
            host_str = f" ({record.host})" if record.host else ""
            lines.append(f"  {i}. [{time_str}] {result_icon} {record.intent}{host_str}")

        return "\n".join(lines)

    # 默认显示最近对话记忆
    recent_turns = state.memory.get_recent_turns(5)
    if not recent_turns:
        return "[日志] 暂无历史记录"

    lines = ["[日志] 最近操作记录:"]
    for i, turn in enumerate(recent_turns, 1):
        lines.append(f"  {i}. {turn.user_input} → {turn.intent}")

    return "\n".join(lines)


def _system_troubleshoot(since: Optional[str] = None) -> str:
    """系统问题排查 — 自动查询错误级别日志和常见问题模式"""
    lines = []

    # 1. 查询错误级别日志
    try:
        cmd = ["journalctl", "--no-pager", "-n", "100", "-p", "err"]
        if since:
            cmd.extend(["--since", since])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        err_output = result.stdout.strip() if result.returncode == 0 else ""

        harmless_patterns = ["Failed to parse bus name", "Cannot find device"]
        err_lines = [
            l for l in err_output.split("\n")
            if not any(p in l for p in harmless_patterns)
        ]
        err_output = "\n".join(err_lines)

        if err_output.strip():
            max_lines = 50
            err_out = err_output.split("\n")
            if len(err_out) > max_lines:
                err_output = "\n".join(err_out[:max_lines]) + f"\n\n... (截断，共 {len(err_out)} 行)"
            lines.append("━━━ 错误级别日志 (最近 100 条) ━━━")
            lines.append(err_output)
            lines.append("")

            issues_found = _analyze_error_logs(err_output)
            if issues_found:
                lines.append("━━━ 发现的问题 ━━━")
                for issue in issues_found:
                    lines.append(f"  ⚠ {issue}")
                lines.append("")
        else:
            lines.append("✓ 未发现错误级别日志")
            lines.append("")
    except Exception as e:
        lines.append(f"[错误日志] 查询失败：{e}")
        lines.append("")

    # 2. 常见问题模式检测
    issues = []

    # SSH 暴力破解检测
    try:
        cmd = ["journalctl", "--no-pager", "-n", "20", "--since", since or "24 hours ago", "-t", "sshd"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        sshd_output = result.stdout.strip() if result.returncode == 0 else ""
        failed_count = sshd_output.lower().count("failed password")
        if failed_count > 10:
            ips = re.findall(r"Failed password for .*? from (\d+\.\d+\.\d+\.\d+)", sshd_output)
            ip_list = ", ".join(list(set(ips))[:10])
            issues.append(f"SSH 暴力破解检测：过去 24 小时内有 {failed_count} 次失败登录尝试，来源 IP: {ip_list}")
        elif failed_count > 0:
            ips = re.findall(r"Failed password for .*? from (\d+\.\d+\.\d+\.\d+)", sshd_output)
            ip_list = ", ".join(list(set(ips))[:10])
            issues.append(f"SSH 失败登录：{failed_count} 次，来源 IP: {ip_list}")
    except Exception:
        pass

    # OOM Killer 检测
    try:
        cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "7 days ago", "-k", "--grep", "Out of memory"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.stdout.strip():
            issues.append("OOM Killer 被触发，存在内存溢出问题")
    except Exception:
        pass

    # 磁盘错误检测
    try:
        cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "24 hours ago", "--grep", "I/O error"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.stdout.strip():
            issues.append("检测到磁盘 I/O 错误")
    except Exception:
        pass

    # 系统服务失败
    try:
        cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "24 hours ago", "--grep", "Failed to start"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.stdout.strip():
            issues.append(f"有服务启动失败:\n{result.stdout.strip()[:300]}")
    except Exception:
        pass

    if issues:
        lines.append("━━━ 自动检测到的问题 ━━━")
        for i, issue in enumerate(issues, 1):
            lines.append(f"  {i}. {issue}")
    else:
        lines.append("✓ 未检测到常见问题模式")

    return "\n".join(lines)


def _analyze_error_logs(output: str) -> List[str]:
    """分析错误日志，提取关键问题"""
    issues = []

    auth_fails = len(re.findall(r"authentication failure", output))
    if auth_fails > 0:
        issues.append(f"认证失败 {auth_fails} 次")

    conn_refused = len(re.findall(r"Connection refused", output))
    if conn_refused > 0:
        issues.append(f"连接拒绝 {conn_refused} 次")

    timeouts = len(re.findall(r"[Tt]imeout", output))
    if timeouts > 0:
        issues.append(f"超时错误 {timeouts} 次")

    if "No space left on device" in output:
        issues.append("磁盘空间不足")

    perm_denied = len(re.findall(r"[Pp]ermission denied", output))
    if perm_denied > 0:
        issues.append(f"权限拒绝 {perm_denied} 次")

    return issues
