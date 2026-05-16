"""执行计划生成器 — 复杂任务先展示计划再执行

设计理念：
- 简单任务（1-2 步）直接执行
- 复杂任务（3+ 步）先展示计划，用户确认后执行
- 执行完成后生成结构化报告
"""
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class PlanStep:
    """执行计划中的一步"""
    index: int
    description: str
    tool_name: str
    args_hint: str = ""
    status: str = "pending"  # pending / running / done / failed / skipped
    result_summary: str = ""
    duration_ms: int = 0


@dataclass
class ExecutionPlan:
    """执行计划"""
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    is_confirmed: bool = False
    is_completed: bool = False

    def format_plan(self) -> str:
        """格式化展示计划"""
        lines = [
            f"[执行计划] {self.goal}",
            "━" * 50,
        ]
        for step in self.steps:
            icon = {
                "pending": "○",
                "running": "◉",
                "done": "✓",
                "failed": "✗",
                "skipped": "⊘",
            }.get(step.status, "?")
            lines.append(f"  {icon} Step {step.index}: {step.description}")
            if step.args_hint:
                lines.append(f"      → {step.tool_name}({step.args_hint})")
        lines.append("━" * 50)
        lines.append(f"共 {len(self.steps)} 步，确认执行？[Y/n]")
        return "\n".join(lines)

    def format_report(self) -> str:
        """格式化执行报告"""
        lines = [
            f"[执行报告] {self.goal}",
            "━" * 50,
        ]
        total_time = 0
        success_count = 0
        for step in self.steps:
            icon = "✓" if step.status == "done" else "✗"
            if step.status == "done":
                success_count += 1
            total_time += step.duration_ms
            lines.append(f"  {icon} Step {step.index}: {step.description} ({step.duration_ms}ms)")
            if step.result_summary:
                # 缩进显示结果摘要（最多 2 行）
                summary_lines = step.result_summary.split("\n")[:2]
                for sl in summary_lines:
                    lines.append(f"      {sl[:80]}")
        lines.append("━" * 50)
        lines.append(f"完成: {success_count}/{len(self.steps)} | 总耗时: {total_time}ms")
        return "\n".join(lines)


# ─── 常见排查模板 ──────────────────────────────────────────────

PLAN_TEMPLATES = {
    "cpu_high": ExecutionPlan(
        goal="CPU 使用率高排查",
        steps=[
            PlanStep(1, "检查服务器整体资源状态", "inspect_server"),
            PlanStep(2, "获取 CPU 占用最高的进程", "get_top_processes", "n=10"),
            PlanStep(3, "查看异常进程对应的服务日志", "query_system_logs", "unit=<进程名>"),
        ],
    ),
    "service_down": ExecutionPlan(
        goal="服务不可达排查",
        steps=[
            PlanStep(1, "Ping 测试网络连通性", "ping_host"),
            PlanStep(2, "检查服务端口是否开放", "check_port"),
            PlanStep(3, "查看服务运行状态", "manage_systemd_service", "action=status"),
            PlanStep(4, "查看服务错误日志", "query_system_logs", "priority=err"),
        ],
    ),
    "k8s_issue": ExecutionPlan(
        goal="K8s 集群问题排查",
        steps=[
            PlanStep(1, "K8s 集群全面巡检", "k8s_cluster_inspect"),
            PlanStep(2, "查看异常 Pod 日志", "k8s_pod_logs"),
        ],
    ),
    "security_audit": ExecutionPlan(
        goal="安全审计",
        steps=[
            PlanStep(1, "扫描开放端口", "scan_ports"),
            PlanStep(2, "检查 SSL 证书", "check_ssl_cert"),
            PlanStep(3, "查看登录失败日志", "query_system_logs", "keyword=failed"),
            PlanStep(4, "检查最近登录记录", "execute_shell_command", "command=last -20"),
        ],
    ),
    "disk_full": ExecutionPlan(
        goal="磁盘空间排查",
        steps=[
            PlanStep(1, "检查磁盘使用率", "inspect_server"),
            PlanStep(2, "查找大文件", "execute_shell_command", "command=du -sh /* 2>/dev/null | sort -rh | head -10"),
            PlanStep(3, "检查日志目录大小", "execute_shell_command", "command=du -sh /var/log/* | sort -rh | head -10"),
        ],
    ),
    "network_issue": ExecutionPlan(
        goal="网络问题排查",
        steps=[
            PlanStep(1, "Ping 测试连通性", "ping_host"),
            PlanStep(2, "DNS 解析检查", "dns_lookup"),
            PlanStep(3, "端口连通性检查", "check_port"),
        ],
    ),
}


def match_plan_template(user_input: str) -> Optional[ExecutionPlan]:
    """根据用户输入匹配预定义排查模板

    Returns:
        匹配的模板副本，或 None
    """
    import copy

    keywords_map = {
        "cpu_high": ["cpu 高", "cpu高", "cpu 使用率", "负载高", "load 高", "卡顿", "cpu高"],
        "service_down": ["不可达", "连不上", "无法访问", "502", "503", "504", "timeout", "超时"],
        "k8s_issue": ["k8s", "kubernetes", "pod", "集群异常", "pod 挂"],
        "security_audit": ["安全", "安全检查", "审计", "漏洞", "入侵"],
        "disk_full": ["磁盘满", "磁盘空间", "disk full", "no space", "空间不足"],
        "network_issue": ["网络", "ping 不通", "dns", "解析失败", "网络不通"],
    }

    input_lower = user_input.lower()
    for template_key, keywords in keywords_map.items():
        for kw in keywords:
            if kw in input_lower:
                return copy.deepcopy(PLAN_TEMPLATES[template_key])

    # 模糊匹配：处理 "cpu为什么高" 这种中间插入其他词的情况
    import re
    if re.search(r"cpu.*高", input_lower):
        return copy.deepcopy(PLAN_TEMPLATES["cpu_high"])
    if re.search(r"负载.*高", input_lower):
        return copy.deepcopy(PLAN_TEMPLATES["cpu_high"])

    return None


def should_show_plan(user_input: str) -> bool:
    """判断是否需要先展示计划

    简单问题（明确指令）不展示，复杂/模糊问题展示。
    """
    # 简单指令关键词 — 不需要展示计划
    simple_keywords = [
        "检查本机", "检查 localhost", "帮助", "ping", "查看容器",
        "查看日志", "集群状态", "证书",
    ]
    input_lower = user_input.lower()
    for kw in simple_keywords:
        if kw in input_lower:
            return False

    # 模糊/复杂问题 — 展示计划
    complex_keywords = [
        "为什么", "排查", "分析", "全面", "安全检查",
        "帮我看看", "什么问题", "怎么回事",
    ]
    for kw in complex_keywords:
        if kw in input_lower:
            return True

    return False


def generate_dynamic_plan(user_input: str) -> Optional[ExecutionPlan]:
    """动态生成排查计划 — 当模板未匹配但用户输入暗示复杂任务时

    基于关键词分析生成灵活的执行计划，
    弥补 6 个预定义模板未覆盖的场景。

    Returns:
        动态生成的 ExecutionPlan，或 None（无需计划）
    """
    input_lower = user_input.lower()

    # 检测是否需要计划
    if not should_show_plan(user_input):
        return None

    # 已有模板匹配的场景不需要动态生成
    if match_plan_template(user_input):
        return None

    # 根据关键词动态构建计划
    steps = []
    step_idx = 1
    goal_parts = []

    # 服务器资源相关
    if any(kw in input_lower for kw in ("cpu", "内存", "磁盘", "负载", "资源", "慢", "卡")):
        steps.append(PlanStep(step_idx, "检查服务器整体资源状态", "inspect_server"))
        step_idx += 1
        goal_parts.append("资源异常")

    # 服务相关
    if any(kw in input_lower for kw in ("nginx", "mysql", "redis", "docker", "服务", "进程")):
        if not steps:
            steps.append(PlanStep(step_idx, "检查服务器整体资源状态", "inspect_server"))
            step_idx += 1
        steps.append(PlanStep(step_idx, "查看相关进程/服务状态", "get_top_processes", "n=10"))
        step_idx += 1
        goal_parts.append("服务异常")

    # 日志排查
    if any(kw in input_lower for kw in ("日志", "error", "报错", "异常", "失败")):
        steps.append(PlanStep(step_idx, "查询系统和应用日志", "query_system_logs", "priority=err"))
        step_idx += 1
        goal_parts.append("日志异常")

    # 网络相关
    if any(kw in input_lower for kw in ("网络", "连接", "超时", "不通", "延迟")):
        steps.append(PlanStep(step_idx, "网络连通性检测", "ping_host"))
        step_idx += 1
        steps.append(PlanStep(step_idx, "端口连通性验证", "check_port"))
        step_idx += 1
        goal_parts.append("网络异常")

    # 安全相关
    if any(kw in input_lower for kw in ("安全", "入侵", "可疑", "未知")):
        steps.append(PlanStep(step_idx, "端口扫描和安全检查", "scan_ports"))
        step_idx += 1
        steps.append(PlanStep(step_idx, "检查登录日志", "query_system_logs", "keyword=failed"))
        step_idx += 1
        goal_parts.append("安全排查")

    # K8s 相关
    if any(kw in input_lower for kw in ("k8s", "kubernetes", "pod", "deployment", "集群")):
        steps.append(PlanStep(step_idx, "K8s 集群巡检", "k8s_cluster_inspect"))
        step_idx += 1
        goal_parts.append("K8s 异常")

    # Docker 相关
    if any(kw in input_lower for kw in ("docker", "容器", "镜像")):
        steps.append(PlanStep(step_idx, "Docker 容器状态检查", "docker_list_containers"))
        step_idx += 1
        goal_parts.append("Docker 异常")

    # 如果未能识别具体方向，使用通用排查路线
    if not steps:
        steps = [
            PlanStep(step_idx, "检查服务器整体状态", "inspect_server"),
        ]
        goal_parts.append("通用排查")

    goal = f"动态计划: {' + '.join(goal_parts)}"
    return ExecutionPlan(goal=goal, steps=steps)
