"""报告生成工具 - JSON/HTML 导出"""
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .server import ServerStatus, format_status_report


class ReportExporter:
    """报告导出工具"""

    @staticmethod
    def export_json(
        statuses: List[ServerStatus],
        thresholds: Dict[str, int],
        output_path: str,
    ) -> str:
        """导出 JSON 格式报告

        Args:
            statuses: 服务器状态列表
            thresholds: 阈值配置
            output_path: 输出文件路径

        Returns:
            str: 成功/失败信息
        """
        hosts = []
        healthy_count = 0
        warning_count = 0
        failed_count = 0

        for status in statuses:
            # 判断健康状态
            if status.ssh_failed:
                health = "failed"
                failed_count += 1
                issues = ["SSH 采集失败"]
            else:
                issues = []
                if status.cpu_percent >= thresholds.get("cpu", 80):
                    issues.append(f"CPU 使用率过高: {status.cpu_percent:.1f}%")
                if status.memory_percent >= thresholds.get("memory", 85):
                    issues.append(f"内存使用率过高: {status.memory_percent:.1f}%")
                if status.disk_percent >= thresholds.get("disk", 90):
                    issues.append(f"磁盘使用率过高: {status.disk_percent:.1f}%")

                cpu_cores = status.load_avg_1m / 8  # 估算
                if status.load_avg_1m >= (cpu_cores * 2):
                    issues.append(f"系统负载过高: {status.load_avg_1m:.2f}")

                health = "healthy" if not issues else "warning"
                if health == "healthy":
                    healthy_count += 1
                else:
                    warning_count += 1

            hosts.append({
                "host": status.host,
                "timestamp": status.timestamp,
                "health_status": health,
                "metrics": {
                    "cpu_percent": status.cpu_percent,
                    "memory_percent": status.memory_percent,
                    "memory_used_gb": status.memory_used_gb,
                    "memory_total_gb": status.memory_total_gb,
                    "disk_percent": status.disk_percent,
                    "disk_used_gb": status.disk_used_gb,
                    "disk_total_gb": status.disk_total_gb,
                    "load_avg_1m": status.load_avg_1m,
                    "load_avg_5m": status.load_avg_5m,
                    "load_avg_15m": status.load_avg_15m,
                    "boot_time": status.boot_time,
                    "top_processes": status.top_processes,
                },
                "issues": issues,
            })

        report = {
            "report_type": "server_inspect",
            "generated_at": datetime.now().isoformat(),
            "hosts": hosts,
            "summary": {
                "total_hosts": len(statuses),
                "healthy": healthy_count,
                "warning": warning_count,
                "failed": failed_count,
                "thresholds": thresholds,
            }
        }

        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            return f"[报告] JSON 报告已保存至: {output_path}"
        except Exception as e:
            return f"[报告] 导出失败：{str(e)}"

    @staticmethod
    def export_html(
        statuses: List[ServerStatus],
        thresholds: Dict[str, int],
        output_path: str,
    ) -> str:
        """导出 HTML 格式报告

        Args:
            statuses: 服务器状态列表
            thresholds: 阈值配置
            output_path: 输出文件路径

        Returns:
            str: 成功/失败信息
        """
        html = ReportExporter._generate_html(statuses, thresholds)

        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            return f"[报告] HTML 报告已保存至: {output_path}"
        except Exception as e:
            return f"[报告] 导出失败：{str(e)}"

    @staticmethod
    def export_markdown(
        statuses: List[ServerStatus],
        thresholds: Dict[str, int],
        output_path: str,
    ) -> str:
        """导出 Markdown 格式报告

        Args:
            statuses: 服务器状态列表
            thresholds: 阈值配置
            output_path: 输出文件路径

        Returns:
            str: 成功/失败信息
        """
        lines = []
        lines.append("# Keeper 服务器巡检报告")
        lines.append("")
        lines.append(f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**巡检主机：** {len(statuses)} 台")
        lines.append("")

        # 汇总表格
        lines.append("## 汇总")
        lines.append("")
        lines.append("| 主机 | CPU% | 内存% | 磁盘% | 负载 | 状态 |")
        lines.append("|------|------|-------|-------|------|------|")

        for status in statuses:
            if status.ssh_failed:
                lines.append(f"| {status.host} | - | - | - | - | ❌ 失败 |")
            else:
                cpu_ok = status.cpu_percent < thresholds.get("cpu", 80)
                mem_ok = status.memory_percent < thresholds.get("memory", 85)
                disk_ok = status.disk_percent < thresholds.get("disk", 90)
                health = "✅" if (cpu_ok and mem_ok and disk_ok) else "⚠️"

                lines.append(
                    f"| {status.host} | {status.cpu_percent:.1f} "
                    f"| {status.memory_percent:.1f}% | {status.disk_percent:.1f}% "
                    f"| {status.load_avg_1m:.2f} | {health} |"
                )

        # 详情
        lines.append("")
        lines.append("## 详细报告")
        lines.append("")

        for status in statuses:
            if not status.ssh_failed:
                report = format_status_report(status, thresholds)
                lines.append(f"### {status.host}")
                lines.append("")
                lines.append("```")
                lines.append(report)
                lines.append("```")
                lines.append("")

        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return f"[报告] Markdown 报告已保存至: {output_path}"
        except Exception as e:
            return f"[报告] 导出失败：{str(e)}"

    @staticmethod
    def _generate_html(statuses: List[ServerStatus], thresholds: Dict[str, int]) -> str:
        """生成 HTML 内容"""
        generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 汇总行
        healthy = sum(1 for s in statuses if not s.ssh_failed and
                      s.cpu_percent < thresholds.get("cpu", 80) and
                      s.memory_percent < thresholds.get("memory", 85) and
                      s.disk_percent < thresholds.get("disk", 90))
        warning = sum(1 for s in statuses if not s.ssh_failed and
                      (s.cpu_percent >= thresholds.get("cpu", 80) or
                       s.memory_percent >= thresholds.get("memory", 85) or
                       s.disk_percent >= thresholds.get("disk", 90)))
        failed = sum(1 for s in statuses if s.ssh_failed)

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="zh-CN"><head>',
            '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">',
            '<title>Keeper 巡检报告</title>',
            '<style>',
            'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:20px;background:#f5f5f5;color:#333}',
            '.container{max-width:1200px;margin:0 auto}',
            'h1{color:#1a1a1a;border-bottom:2px solid #e0e0e0;padding-bottom:10px}',
            '.summary{display:flex;gap:20px;margin:20px 0}',
            '.summary-card{flex:1;background:#fff;border-radius:8px;padding:20px;text-align:center;box-shadow:0 2px 4px rgba(0,0,0,0.1)}',
            '.summary-card h3{margin:0 0 10px 0;font-size:14px;color:#666}',
            '.summary-card .value{font-size:36px;font-weight:bold}',
            '.summary-card.healthy .value{color:#22c55e}',
            '.summary-card.warning .value{color:#f59e0b}',
            '.summary-card.failed .value{color:#ef4444}',
            'table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 4px rgba(0,0,0,0.1)}',
            'th{background:#f8f9fa;padding:12px 16px;text-align:left;font-weight:600;color:#495057}',
            'td{padding:12px 16px;border-top:1px solid #e9ecef}',
            '.badge{display:inline-block;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:500}',
            '.badge-healthy{background:#dcfce7;color:#166534}',
            '.badge-warning{background:#fef3c7;color:#92400e}',
            '.badge-failed{background:#fee2e2;color:#991b1b}',
            '.details{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:20px;margin-top:20px}',
            '.card{background:#fff;border-radius:8px;padding:20px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}',
            '.card h3{margin:0 0 15px 0;color:#1a1a1a}',
            '.metric{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f0f0f0}',
            '.metric:last-child{border-bottom:none}',
            '.metric .label{color:#666}',
            '.metric .value{font-weight:600}',
            '.metric .value.ok{color:#22c55e}',
            '.metric .value.warn{color:#f59e0b}',
            '.metric .value.fail{color:#ef4444}',
            '.progress{height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden;margin-top:4px}',
            '.progress .bar{height:100%;border-radius:3px;transition:width 0.3s}',
            '.progress .bar.ok{background:#22c55e}',
            '.progress .bar.warn{background:#f59e0b}',
            '.progress .bar.fail{background:#ef4444}',
            '.footer{text-align:center;margin-top:30px;color:#999;font-size:12px}',
            '</style></head><body>',
            '<div class="container">',
            f'<h1>Keeper 服务器巡检报告</h1>',
            f'<p>生成时间：{generated_time}</p>',
            '<div class="summary">',
            f'<div class="summary-card healthy"><h3>健康</h3><div class="value">{healthy}</div></div>',
            f'<div class="summary-card warning"><h3>警告</h3><div class="value">{warning}</div></div>',
            f'<div class="summary-card failed"><h3>失败</h3><div class="value">{failed}</div></div>',
            '</div>',
        ]

        # 汇总表格
        html_parts.append('<h2>主机列表</h2>')
        html_parts.append('<table>')
        html_parts.append('<tr><th>主机</th><th>CPU%</th><th>内存%</th><th>磁盘%</th><th>负载</th><th>状态</th></tr>')

        for status in statuses:
            if status.ssh_failed:
                html_parts.append(
                    f'<tr><td>{status.host}</td><td>-</td><td>-</td><td>-</td><td>-</td>'
                    f'<td><span class="badge badge-failed">失败</span></td></tr>'
                )
            else:
                cpu_ok = status.cpu_percent < thresholds.get("cpu", 80)
                mem_ok = status.memory_percent < thresholds.get("memory", 85)
                disk_ok = status.disk_percent < thresholds.get("disk", 90)

                cpu_cls = "ok" if cpu_ok else ("warn" if status.cpu_percent < thresholds.get("cpu", 80) * 1.1 else "fail")
                mem_cls = "ok" if mem_ok else "warn" if status.memory_percent < thresholds.get("memory", 85) * 1.1 else "fail"
                disk_cls = "ok" if disk_ok else "warn" if status.disk_percent < thresholds.get("disk", 90) * 1.1 else "fail"

                health_cls = "healthy" if (cpu_ok and mem_ok and disk_ok) else "warning"

                html_parts.append(
                    f'<tr><td>{status.host}</td>'
                    f'<td><span class="value {cpu_cls}">{status.cpu_percent:.1f}%</span></td>'
                    f'<td><span class="value {mem_cls}">{status.memory_percent:.1f}%</span></td>'
                    f'<td><span class="value {disk_cls}">{status.disk_percent:.1f}%</span></td>'
                    f'<td>{status.load_avg_1m:.2f}</td>'
                    f'<td><span class="badge badge-{health_cls}">{"健康" if health_cls == "healthy" else "警告"}</span></td></tr>'
                )

        html_parts.append('</table>')

        # 详细卡片
        success_statuses = [s for s in statuses if not s.ssh_failed]
        if success_statuses:
            html_parts.append('<h2>详细信息</h2>')
            html_parts.append('<div class="details">')

            for status in success_statuses:
                cpu_ok = status.cpu_percent < thresholds.get("cpu", 80)
                mem_ok = status.memory_percent < thresholds.get("memory", 85)
                disk_ok = status.disk_percent < thresholds.get("disk", 90)

                def metric_row(label, value, threshold, ok):
                    cls = "ok" if ok else "warn"
                    pct = min(value / threshold * 100, 100)
                    return (
                        f'<div class="metric">'
                        f'<div><span class="label">{label}</span>'
                        f'<div class="progress"><div class="bar {cls}" style="width:{pct:.0f}%"></div></div></div>'
                        f'<span class="value {cls}">{value:.1f}% / {threshold}%</span>'
                        f'</div>'
                    )

                html_parts.append(f'<div class="card"><h3>{status.host}</h3>')
                html_parts.append(metric_row("CPU", status.cpu_percent, thresholds.get("cpu", 80), cpu_ok))
                html_parts.append(metric_row("内存", status.memory_percent, thresholds.get("memory", 85), mem_ok))
                html_parts.append(metric_row("磁盘", status.disk_percent, thresholds.get("disk", 90), disk_ok))

                load_ok = status.load_avg_1m < 8
                html_parts.append(
                    f'<div class="metric"><span class="label">负载 (1m)</span>'
                    f'<span class="value {"ok" if load_ok else "warn"}">{status.load_avg_1m:.2f}</span></div>'
                )
                html_parts.append(
                    f'<div class="metric"><span class="label">开机时间</span>'
                    f'<span class="value">{status.boot_time}</span></div>'
                )

                if status.top_processes:
                    html_parts.append('<div class="metric"><span class="label">Top 进程</span><span class="value">')
                    for proc in status.top_processes[:3]:
                        html_parts.append(f'<br>{proc["name"]} ({proc["memory_percent"]:.1f}%)')
                    html_parts.append('</span></div>')

                html_parts.append('</div>')

            html_parts.append('</div>')

        html_parts.extend([
            '</div>',
            '<div class="footer">Generated by Keeper - 智能运维 Agent</div>',
            '</body></html>',
        ])

        return "\n".join(html_parts)
