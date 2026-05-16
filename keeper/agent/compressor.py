"""工具输出压缩管线 — 参考 Claude Code 的分级压缩设计

设计理念：
- 能局部处理就不做全局摘要
- 能折叠视图就不合并成摘要
- 尽量延后信息损失，最后才牺牲细节

四级管线（层层升级）：
1. 裁剪（Trim）— 替换过大的原始输出
2. 结构化摘要 — 保留关键信息（错误/告警行），丢弃噪音
3. 折叠 — 长内容用占位符替代，只保留首尾
4. 极限压缩 — 超长内容只保留统计信息
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class CompressedResult:
    """压缩后的工具结果"""
    content: str           # 最终内容
    original_len: int      # 原始长度
    compressed_len: int    # 压缩后长度
    strategy: str          # 使用的策略：none / trim / summarize / fold / stats_only


class OutputCompressor:
    """工具输出压缩器

    根据工具类型和输出长度，智能选择压缩策略。
    """

    # 各级阈值
    TRIM_THRESHOLD = 3000      # 超过此长度触发裁剪
    SUMMARIZE_THRESHOLD = 1500 # 超过此长度触发结构化摘要
    FOLD_THRESHOLD = 800       # 超过此长度触发折叠
    STATS_THRESHOLD = 400      # 超过此长度只保留统计

    def compress(
        self,
        tool_name: str,
        content: str,
        max_len: int = TRIM_THRESHOLD,
    ) -> CompressedResult:
        """执行压缩

        Args:
            tool_name: 工具名称（用于选择压缩策略）
            content: 原始输出
            max_len: 最大允许长度

        Returns:
            CompressedResult 压缩结果
        """
        original_len = len(content)

        # 不需要压缩
        if original_len <= max_len:
            return CompressedResult(content, original_len, original_len, "none")

        # 策略 1: 结构化摘要（日志/巡检类工具）
        if tool_name in (
            "query_system_logs", "read_log_file", "k8s_pod_logs",
            "docker_container_logs", "inspect_server", "inspect_remote_server",
        ):
            result = self._summarize(tool_name, content)
            if result:
                return result

        # 策略 2: 折叠（保留首尾，中间用占位符）
        if original_len > max_len * 1.5:
            result = self._fold(content, max_len)
            return CompressedResult(
                result, original_len, len(result), "fold"
            )

        # 策略 3: 直接裁剪
        result = content[:max_len] + f"\n\n... (输出 {original_len} 字符，已截断)"
        return CompressedResult(result, original_len, len(result), "trim")

    def _summarize(self, tool_name: str, content: str) -> Optional[CompressedResult]:
        """结构化摘要 — 保留关键信息行

        策略：
        - 日志类：保留 error/warning/crit/alert 行
        - 巡检类：保留指标数据和告警
        - 其余：折叠
        """
        lines = content.split("\n")

        if "log" in tool_name:
            # 日志类：保留错误/警告行 + 首尾各 5 行
            important = []
            for i, line in enumerate(lines):
                lower = line.lower()
                if any(kw in lower for kw in ("error", "fail", "crit", "alert", "warning", "exception")):
                    important.append((i, line))

            if important:
                header = f"[日志摘要] 共 {len(lines)} 行，其中 {len(important)} 条重要记录:"
                kept = []
                # 首 3 行
                for line in lines[:3]:
                    kept.append(line)
                # 重要行
                for idx, line in important:
                    # 截断单行长度
                    truncated = line[:200] + "..." if len(line) > 200 else line
                    kept.append(f"  [行 {idx}] {truncated}")
                # 尾 2 行
                kept.append("...")
                for line in lines[-2:]:
                    kept.append(line)

                summary = "\n".join(kept)
                return CompressedResult(summary, len(content), len(summary), "summarize")

        # 非日志类：不做结构化摘要，交给折叠
        return None

    def _fold(self, content: str, max_len: int) -> str:
        """折叠 — 保留首尾，中间用占位符"""
        head_len = max_len // 3
        tail_len = max_len // 3
        original_len = len(content)

        head = content[:head_len]
        tail = content[-tail_len:] if len(content) > tail_len else ""

        # 找完整行边界
        if "\n" in head:
            head = content[:head.rfind("\n") + 1]
        if "\n" in tail:
            first_newline = tail.find("\n")
            if first_newline >= 0:
                tail = tail[first_newline + 1:]

        total_lines = content.count("\n") + 1
        folded = f"{head}... ({total_lines} 行中的中间部分已折叠，共 {original_len} 字符) ...\n{tail}"
        return folded

    def compress_for_history(self, content: str, max_len: int = 500) -> str:
        """历史存储用压缩 — 只保留摘要

        用于 conversation_history 中保存时截断过长内容。
        """
        if len(content) <= max_len:
            return content

        lines = content.split("\n")
        total_lines = len(lines)

        # 如果只有一行（超长），直接截断
        if total_lines == 1:
            return content[:max_len - 30] + f"\n... ({len(content)} 字符)"

        # 保留首 2 行 + 统计
        kept = lines[:2]
        kept.append(f"... (共 {total_lines} 行，{len(content)} 字符)")
        result = "\n".join(kept)

        # 如果结果仍然超长，进一步截断
        if len(result) > max_len:
            result = result[:max_len - 30] + f"\n... ({len(content)} 字符)"

        return result


# 全局实例
output_compressor = OutputCompressor()
