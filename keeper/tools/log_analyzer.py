"""日志智能分析 — 错误聚合 + 异常模式检测

功能：
- 按错误模式分组（正则提取错误签名）
- 统计各模式出现频次
- 排序输出 Top N
- 异常模式检测（日志量突增、新错误类型）
"""
import re
import subprocess
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime


@dataclass
class ErrorPattern:
    """错误模式"""
    signature: str       # 错误签名（去除变量后的模式）
    count: int           # 出现次数
    severity: str        # error / warning / critical
    examples: List[str] = field(default_factory=list)  # 原始日志示例（最多 3 条）
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class LogAnalysisReport:
    """日志分析报告"""
    source: str          # 日志来源
    time_range: str      # 时间范围
    total_lines: int     # 总行数
    error_count: int     # 错误行数
    warning_count: int   # 警告行数
    top_errors: List[ErrorPattern]   # Top N 错误模式
    anomalies: List[str]             # 异常检测结果


class LogAnalyzer:
    """日志分析器"""

    # 错误模式正则
    ERROR_PATTERNS = [
        (re.compile(r"\b(error|ERROR|Error)\b"), "error"),
        (re.compile(r"\b(FATAL|fatal|CRIT|crit|CRITICAL)\b"), "critical"),
        (re.compile(r"\b(WARN|warn|WARNING|warning)\b"), "warning"),
    ]

    # 用于提取错误签名的规则（去除变量部分）
    VARIABLE_PATTERNS = [
        (re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"), "<IP>"),
        (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "<TIMESTAMP>"),
        (re.compile(r"\b\d{5,}\b"), "<NUM>"),
        (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
        (re.compile(r"/[^\s:]+"), "<PATH>"),
    ]

    @classmethod
    def analyze_journal(
        cls,
        unit: Optional[str] = None,
        since: str = "1 hour ago",
        priority: str = "err",
        lines: int = 500,
    ) -> LogAnalysisReport:
        """分析 journalctl 日志

        Args:
            unit: systemd 服务名称
            since: 时间范围
            priority: 最低日志级别
            lines: 最大行数

        Returns:
            LogAnalysisReport
        """
        cmd = ["journalctl", "--no-pager", "-n", str(lines), "--since", since]
        if unit:
            cmd.extend(["-u", unit])
        if priority:
            cmd.extend(["-p", priority])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            log_content = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log_content = ""

        source = f"journalctl{' -u ' + unit if unit else ''}"
        return cls._analyze_content(log_content, source, since)

    @classmethod
    def analyze_file(
        cls,
        file_path: str,
        lines: int = 500,
    ) -> LogAnalysisReport:
        """分析日志文件

        Args:
            file_path: 日志文件路径
            lines: 最大行数

        Returns:
            LogAnalysisReport
        """
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), file_path],
                capture_output=True, text=True, timeout=10,
            )
            log_content = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log_content = ""

        return cls._analyze_content(log_content, file_path, f"最后 {lines} 行")

    @classmethod
    def _analyze_content(cls, content: str, source: str, time_range: str) -> LogAnalysisReport:
        """分析日志内容"""
        if not content.strip():
            return LogAnalysisReport(
                source=source, time_range=time_range,
                total_lines=0, error_count=0, warning_count=0,
                top_errors=[], anomalies=["日志为空或无法读取"],
            )

        lines = content.strip().split("\n")
        total_lines = len(lines)

        # 分类统计
        error_lines = []
        warning_lines = []
        error_count = 0
        warning_count = 0

        for line in lines:
            for pattern, severity in cls.ERROR_PATTERNS:
                if pattern.search(line):
                    if severity in ("error", "critical"):
                        error_lines.append(line)
                        error_count += 1
                    elif severity == "warning":
                        warning_lines.append(line)
                        warning_count += 1
                    break

        # 错误模式聚合
        signature_counter = Counter()
        signature_examples: Dict[str, List[str]] = {}

        for line in error_lines:
            sig = cls._extract_signature(line)
            signature_counter[sig] += 1
            if sig not in signature_examples:
                signature_examples[sig] = []
            if len(signature_examples[sig]) < 3:
                signature_examples[sig].append(line[:200])

        # Top N 错误
        top_errors = []
        for sig, count in signature_counter.most_common(10):
            top_errors.append(ErrorPattern(
                signature=sig[:100],
                count=count,
                severity="error",
                examples=signature_examples.get(sig, []),
            ))

        # 异常检测
        anomalies = cls._detect_anomalies(total_lines, error_count, warning_count, top_errors)

        return LogAnalysisReport(
            source=source,
            time_range=time_range,
            total_lines=total_lines,
            error_count=error_count,
            warning_count=warning_count,
            top_errors=top_errors,
            anomalies=anomalies,
        )

    @classmethod
    def _extract_signature(cls, line: str) -> str:
        """提取错误签名（去除变量部分，保留模式）"""
        sig = line
        # 去除时间戳前缀
        sig = re.sub(r"^\S+\s+\d{2}:\d{2}:\d{2}\s+\S+\s+", "", sig)
        # 替换变量
        for pattern, replacement in cls.VARIABLE_PATTERNS:
            sig = pattern.sub(replacement, sig)
        # 截断
        return sig[:100].strip()

    @classmethod
    def _detect_anomalies(cls, total: int, errors: int, warnings: int,
                          top_errors: List[ErrorPattern]) -> List[str]:
        """异常模式检测"""
        anomalies = []

        # 错误率过高
        if total > 0:
            error_rate = errors / total * 100
            if error_rate > 50:
                anomalies.append(f"错误率异常高: {error_rate:.0f}%（{errors}/{total}）")
            elif error_rate > 20:
                anomalies.append(f"错误率偏高: {error_rate:.0f}%")

        # 单一错误大量出现
        if top_errors and top_errors[0].count > 100:
            anomalies.append(
                f"高频错误: '{top_errors[0].signature[:50]}' 出现 {top_errors[0].count} 次"
            )

        # 错误种类多
        if len(top_errors) > 5:
            anomalies.append(f"错误种类较多: {len(top_errors)} 种不同错误模式")

        return anomalies

    @classmethod
    def format_report(cls, report: LogAnalysisReport) -> str:
        """格式化分析报告"""
        lines = [
            f"[日志分析] {report.source}",
            f"  时间范围: {report.time_range}",
            f"  总行数: {report.total_lines} | 错误: {report.error_count} | 警告: {report.warning_count}",
            "━" * 50,
        ]

        if report.top_errors:
            lines.append("Top 错误模式:")
            for i, err in enumerate(report.top_errors[:5], 1):
                lines.append(f"  {i}. [{err.count}次] {err.signature}")
                if err.examples:
                    lines.append(f"      例: {err.examples[0][:80]}")
        else:
            lines.append("  未发现错误")

        if report.anomalies:
            lines.append("")
            lines.append("⚠️ 异常检测:")
            for a in report.anomalies:
                lines.append(f"  • {a}")

        lines.append("━" * 50)
        return "\n".join(lines)
