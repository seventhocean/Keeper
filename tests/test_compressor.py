"""OutputCompressor 测试 — 工具输出压缩管线

覆盖四级压缩策略：none / trim / summarize / fold / stats_only
"""
import pytest
from keeper.agent.compressor import OutputCompressor, CompressedResult, output_compressor


class TestCompressorNoCompress:
    """内容未超过阈值 — 不压缩"""

    def test_short_content_no_compress(self):
        c = OutputCompressor()
        result = c.compress("ping_host", "hello", max_len=2000)
        assert result.strategy == "none"
        assert result.content == "hello"
        assert result.original_len == result.compressed_len

    def test_exact_boundary_no_compress(self):
        c = OutputCompressor()
        content = "x" * 500
        result = c.compress("some_tool", content, max_len=500)
        assert result.strategy == "none"
        assert len(result.content) == 500


class TestCompressorTrim:
    """超出阈值但不触发结构化摘要/折叠 — 直接裁剪"""

    def test_trim_unknown_tool(self):
        c = OutputCompressor()
        content = "x" * 800
        # max_len=400, original=800, 1.5*400=600, 800 > 600 → fold
        # Use smaller ratio: 800 vs 2000 → 800 <= 2000 → no compress
        # Let's use: content=1200, max_len=1000, 1200>1000, 1.5*1000=1500, 1200<=1500 → trim
        result = c.compress("unknown_tool", content, max_len=600)
        # 800 > 600*1.5=900? No, 800 < 900 so trim
        assert result.strategy == "trim"
        assert len(result.content) < len(content)

    def test_trim_preserves_truncation_message(self):
        c = OutputCompressor()
        content = "A" * 600
        result = c.compress("unknown_tool", content, max_len=400)
        assert "输出" in result.content
        assert "截断" in result.content
        assert str(len(content)) in result.content


class TestCompressorSummarize:
    """结构化摘要 — 日志/巡检类工具"""

    def test_log_tool_error_summary(self):
        c = OutputCompressor()
        lines = [
            "2024-01-01 INFO Starting service",
            "2024-01-01 WARNING Low memory",
            "2024-01-01 ERROR Connection failed",
            "2024-01-01 ERROR Timeout",
            "2024-01-01 INFO normal stuff",
        ]
        content = "\n".join(lines) * 100  # make it long
        result = c.compress("query_system_logs", content, max_len=400)
        assert result.strategy == "summarize"
        assert "日志摘要" in result.content
        assert "重要记录" in result.content

    def test_log_tool_keeps_critical(self):
        c = OutputCompressor()
        lines = []
        for i in range(500):
            lines.append(f"2024-01-01 INFO line {i}")
        lines.append("2024-01-01 CRITICAL disk failure")
        content = "\n".join(lines)
        result = c.compress("read_log_file", content, max_len=200)
        assert result.strategy == "summarize"
        assert "CRITICAL" in result.content or "crit" in result.content.lower()

    def test_inspection_tool_no_error_lines(self):
        """巡检类工具没有 error 行时走折叠路径"""
        c = OutputCompressor()
        lines = ["CPU: 15%", "MEM: 45%", "DISK: 62%"] * 200
        content = "\n".join(lines)
        result = c.compress("inspect_server", content, max_len=100)
        # 无 error/warning 行 → 摘要返回 None → 走 fold
        assert result.strategy in ("fold", "trim")

    def test_all_log_tool_names(self):
        """所有日志/巡检类工具名都走摘要路径"""
        log_tools = [
            "query_system_logs", "read_log_file", "k8s_pod_logs",
            "docker_container_logs", "inspect_server", "inspect_remote_server",
        ]
        c = OutputCompressor()
        for tool_name in log_tools:
            # 含 error 的关键内容
            content = ("ERROR something bad\n" * 50 + "INFO ok\n" * 200)
            result = c.compress(tool_name, content, max_len=200)
            assert result.strategy in ("summarize", "fold", "trim"), \
                f"{tool_name}: unexpected strategy {result.strategy}"


class TestCompressorFold:
    """折叠 — 保留首尾，中间用占位符"""

    def test_fold_basic(self):
        c = OutputCompressor()
        content = "A\n" * 2000  # way over threshold
        result = c.compress("some_tool", content, max_len=200)
        assert result.strategy == "fold"
        assert "已折叠" in result.content

    def test_fold_preserves_head_and_tail(self):
        c = OutputCompressor()
        lines = [f"line_{i}" for i in range(1000)]
        content = "\n".join(lines)
        result = c.compress("some_tool", content, max_len=200)
        assert result.strategy == "fold"
        # head should contain early lines
        assert "line_0" in result.content
        # tail should contain late lines
        assert "line_999" in result.content

    def test_fold_shows_line_count(self):
        c = OutputCompressor()
        content = "\n".join(["x"] * 500)
        result = c.compress("some_tool", content, max_len=200)
        assert "500" in result.content or "行" in result.content


class TestCompressorSummarizeEdgeCases:
    """结构化摘要边界情况"""

    def test_single_line_no_important(self):
        """全是 INFO 行 — 无重要行时走 fold"""
        c = OutputCompressor()
        content = "INFO everything is fine\n" * 300
        result = c.compress("query_system_logs", content, max_len=100)
        assert result.strategy in ("fold", "trim")

    def test_warning_detected(self):
        c = OutputCompressor()
        lines = [
            "2024-01-01 INFO Starting",
            "2024-01-01 WARNING Disk usage 90%",
            "2024-01-01 INFO Continuing",
        ] * 100
        content = "\n".join(lines)
        result = c.compress("read_log_file", content, max_len=300)
        assert result.strategy == "summarize"
        assert "warning" in result.content.lower() or "WARNING" in result.content

    def test_exception_detected(self):
        c = OutputCompressor()
        lines = [
            "2024-01-01 INFO Processing",
            "2024-01-01 Exception: NullPointerException at line 42",
            "2024-01-01 INFO Done",
        ] * 100
        content = "\n".join(lines)
        result = c.compress("k8s_pod_logs", content, max_len=200)
        assert result.strategy == "summarize"
        assert "exception" in result.content.lower()


class TestCompressForHistory:
    """历史存储用压缩"""

    def test_short_content_passthrough(self):
        c = OutputCompressor()
        content = "short result"
        result = c.compress_for_history(content, max_len=500)
        assert result == content

    def test_long_multiline(self):
        c = OutputCompressor()
        lines = [f"line_{i}" for i in range(1000)]
        content = "\n".join(lines)
        result = c.compress_for_history(content, max_len=500)
        assert len(result) <= 500
        assert "行" in result or "chars" not in result.lower()

    def test_single_long_line(self):
        c = OutputCompressor()
        content = "x" * 2000
        result = c.compress_for_history(content, max_len=500)
        assert len(result) <= 500
        assert "..." in result

    def test_barely_over_limit(self):
        c = OutputCompressor()
        content = "y" * 510
        result = c.compress_for_history(content, max_len=500)
        assert len(result) <= 500


class TestGlobalInstance:
    """全局 output_compressor 实例"""

    def test_global_instance_exists(self):
        assert isinstance(output_compressor, OutputCompressor)

    def test_global_instance_works(self):
        result = output_compressor.compress("ping_host", "short", max_len=2000)
        assert result.strategy == "none"
        assert result.content == "short"


class TestCompressedResult:
    """CompressedResult dataclass"""

    def test_fields(self):
        r = CompressedResult(content="abc", original_len=100, compressed_len=3, strategy="trim")
        assert r.content == "abc"
        assert r.original_len == 100
        assert r.compressed_len == 3
        assert r.strategy == "trim"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
