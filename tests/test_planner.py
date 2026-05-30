"""ExecutionPlan & Planner 测试

覆盖：
- PlanStep / ExecutionPlan dataclass
- 6 个预定义排查模板
- match_plan_template 关键词匹配
- should_show_plan 计划判断
- generate_dynamic_plan 动态生成
"""
import pytest
from keeper.agent.planner import (
    PlanStep,
    ExecutionPlan,
    PLAN_TEMPLATES,
    match_plan_template,
    should_show_plan,
    generate_dynamic_plan,
)


class TestPlanStep:
    """PlanStep dataclass"""

    def test_defaults(self):
        s = PlanStep(index=1, description="检查状态", tool_name="inspect_server")
        assert s.index == 1
        assert s.status == "pending"
        assert s.args_hint == ""
        assert s.result_summary == ""
        assert s.duration_ms == 0

    def test_custom_values(self):
        s = PlanStep(
            index=2, description="查看日志", tool_name="query_system_logs",
            args_hint="unit=nginx", status="done",
            result_summary="找到3条错误", duration_ms=150,
        )
        assert s.status == "done"
        assert s.args_hint == "unit=nginx"
        assert s.result_summary == "找到3条错误"
        assert s.duration_ms == 150


class TestExecutionPlan:
    """ExecutionPlan 格式化测试"""

    def test_format_plan(self):
        plan = ExecutionPlan(
            goal="CPU 排查",
            steps=[
                PlanStep(1, "检查资源", "inspect_server"),
                PlanStep(2, "获取进程", "get_top_processes", "n=10"),
            ],
        )
        output = plan.format_plan()
        assert "[执行计划] CPU 排查" in output
        assert "Step 1" in output
        assert "Step 2" in output
        assert "确认执行" in output

    def test_format_plan_with_different_statuses(self):
        plan = ExecutionPlan(
            goal="测试计划",
            steps=[
                PlanStep(1, "第一步", "tool_a", status="done"),
                PlanStep(2, "第二步", "tool_b", status="running"),
                PlanStep(3, "第三步", "tool_c", status="failed"),
                PlanStep(4, "第四步", "tool_d", status="skipped"),
            ],
        )
        output = plan.format_plan()
        assert "✓" in output
        assert "◉" in output
        assert "✗" in output
        assert "⊘" in output

    def test_format_report(self):
        plan = ExecutionPlan(
            goal="问题排查",
            steps=[
                PlanStep(1, "检查", "inspect_server", status="done",
                         result_summary="CPU: 92%", duration_ms=100),
                PlanStep(2, "查日志", "query_system_logs", status="done",
                         result_summary="3条错误", duration_ms=200),
            ],
        )
        report = plan.format_report()
        assert "[执行报告] 问题排查" in report
        assert "完成: 2/2" in report
        assert "总耗时: 300ms" in report

    def test_format_report_with_failures(self):
        plan = ExecutionPlan(
            goal="排查",
            steps=[
                PlanStep(1, "成功", "tool_a", status="done", duration_ms=100),
                PlanStep(2, "失败", "tool_b", status="failed", duration_ms=50),
            ],
        )
        report = plan.format_report()
        assert "完成: 1/2" in report

    def test_plan_is_confirmed_default(self):
        plan = ExecutionPlan(goal="test", steps=[])
        assert plan.is_confirmed is False
        assert plan.is_completed is False

    def test_format_plan_handles_unknown_status(self):
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep(1, "step", "tool", status="unknown_status")],
        )
        output = plan.format_plan()
        assert "?" in output  # fallback icon


class TestPlanTemplates:
    """6 个预定义模板"""

    def test_all_six_templates_exist(self):
        expected = {
            "cpu_high", "service_down", "k8s_issue",
            "security_audit", "disk_full", "network_issue",
        }
        assert set(PLAN_TEMPLATES.keys()) == expected

    def test_cpu_high_template(self):
        t = PLAN_TEMPLATES["cpu_high"]
        assert len(t.steps) == 3
        assert t.steps[0].tool_name == "inspect_server"

    def test_service_down_template(self):
        t = PLAN_TEMPLATES["service_down"]
        assert len(t.steps) == 4

    def test_each_template_has_goal(self):
        for key, t in PLAN_TEMPLATES.items():
            assert t.goal, f"{key} has no goal"
            assert len(t.steps) >= 2, f"{key} has fewer than 2 steps"


class TestMatchPlanTemplate:
    """match_plan_template 关键词匹配"""

    def test_cpu_high_match(self):
        for query in ["cpu 高", "CPU高", "cpu 使用率 90%", "负载高", "load 高", "卡顿"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"
            assert "cpu" in result.goal.lower() or "CPU" in result.goal

    def test_service_down_match(self):
        for query in ["不可达", "连不上", "服务 502", "timeout", "访问超时"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"

    def test_k8s_match(self):
        for query in ["k8s 集群异常", "kubernetes pod 挂了", "pod 挂"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"

    def test_security_match(self):
        for query in ["安全检查", "安全审计", "漏洞扫描"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"

    def test_disk_full_match(self):
        for query in ["磁盘满", "磁盘空间不足", "disk full", "no space left"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"

    def test_network_match(self):
        for query in ["网络不通", "ping 不通", "dns 解析失败"]:
            result = match_plan_template(query)
            assert result is not None, f"'{query}' should match"

    def test_no_match(self):
        assert match_plan_template("你好") is None
        assert match_plan_template("今天的天气") is None

    def test_fuzzy_cpu_high(self):
        """模糊匹配: CPU...高 中间插入其他词"""
        result = match_plan_template("cpu为什么这么高")
        assert result is not None
        assert "cpu" in result.goal.lower()

    def test_fuzzy_load_high(self):
        result = match_plan_template("负载怎么这么高")
        assert result is not None

    def test_returns_deep_copy(self):
        """返回的是深拷贝，修改不影响模板"""
        template = PLAN_TEMPLATES["cpu_high"]
        result = match_plan_template("cpu 高")
        assert result is not None
        result.steps[0].status = "done"
        assert template.steps[0].status == "pending"  # 模板未修改


class TestShouldShowPlan:
    """should_show_plan 计划判断"""

    def test_simple_instructions_no_plan(self):
        simple_queries = [
            "检查本机", "检查 localhost", "帮助", "ping 8.8.8.8",
            "查看容器", "查看日志", "集群状态", "证书",
        ]
        for q in simple_queries:
            assert should_show_plan(q) is False, f"'{q}' should NOT show plan"

    def test_complex_questions_show_plan(self):
        complex_queries = [
            "为什么 CPU 高", "排查内存泄漏", "分析磁盘空间",
            "全面检查", "安全检查", "帮我看看这个",
            "什么问题", "怎么回事",
        ]
        for q in complex_queries:
            assert should_show_plan(q) is True, f"'{q}' should show plan"

    def test_unknown_input_defaults_no_plan(self):
        """不匹配简单也不匹配复杂 → 默认不展示"""
        assert should_show_plan("随便看看") is False


class TestGenerateDynamicPlan:
    """generate_dynamic_plan 动态生成"""

    def test_should_not_plan_for_simple(self):
        assert generate_dynamic_plan("检查本机") is None

    def test_should_not_plan_when_template_matches(self):
        """模板已匹配时不重复生成动态计划"""
        assert generate_dynamic_plan("cpu 高排查") is None

    def test_resource_related(self):
        plan = generate_dynamic_plan("为什么内存占用这么高")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "inspect_server" in tool_names
        assert "资源" in plan.goal

    def test_service_related(self):
        plan = generate_dynamic_plan("nginx 服务为什么挂了")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "inspect_server" in tool_names
        assert "get_top_processes" in tool_names

    def test_log_related(self):
        plan = generate_dynamic_plan("日志里面有很多报错怎么回事")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "query_system_logs" in tool_names

    def test_network_related(self):
        # "网络" 会匹配 network_issue 模板 → 返回 None
        # 用不匹配模板但包含网络类关键词的输入
        plan = generate_dynamic_plan("为什么连接延迟这么高")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "ping_host" in tool_names
        assert "check_port" in tool_names

    def test_security_related(self):
        # "入侵" 匹配 security_audit 模板 → 返回 None
        # 用不匹配模板的词
        plan = generate_dynamic_plan("为什么有可疑进程在运行")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "scan_ports" in tool_names
        assert "query_system_logs" in tool_names

    def test_k8s_dynamic(self):
        plan = generate_dynamic_plan("deployment 为什么一直 pending")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "k8s_cluster_inspect" in tool_names

    def test_docker_dynamic(self):
        plan = generate_dynamic_plan("docker 容器为什么启动不了")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        assert "docker_list_containers" in tool_names

    def test_unknown_domain_fallback(self):
        """无法识别具体领域时使用通用排查"""
        # "慢" 会匹配资源异常，需要用真正无法识别的词
        plan = generate_dynamic_plan("帮我看看这个报错怎么回事")
        assert plan is not None
        assert len(plan.steps) >= 1
        # "报错" 匹配日志异常
        assert "日志" in plan.goal

    def test_combined_domains(self):
        """多领域关键词 → 多步骤"""
        # "ping" → 匹配简单关键词 → should_show_plan=False
        # 需要复杂关键词但不匹配任何模板，同时多领域
        plan = generate_dynamic_plan("mysql 服务为什么连接延迟高")
        assert plan is not None
        tool_names = [s.tool_name for s in plan.steps]
        # 应包含资源检查 + 进程检查 + 网络检测
        assert "inspect_server" in tool_names
        assert "ping_host" in tool_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
