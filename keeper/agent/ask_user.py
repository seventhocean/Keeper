"""结构化提问能力 — 参考 Claude Code 的 AskUserQuestionTool

设计理念：
- 工具执行中需要补充信息时，不是返回纯文本，而是返回结构化提问
- HybridAgent 解析后，以结构化方式向用户展示
- 用户可以直接在 CLI 中输入答案或选择选项

两种模式：
1. 简单提问（open-ended）：直接输入文字回答
2. 选项提问（multiple choice）：从预设选项中选择一个
"""
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class AskUserQuestion:
    """结构化提问"""
    question: str          # 问题文本
    header: str = ""       # 短标签（如 "SSH", "K8s", "API"）
    options: List[str] = ()  # 可选答案（为空则为开放式问题）
    default: str = ""      # 默认答案


@dataclass
class AskUserResult:
    """提问解析结果"""
    needs_user_input: bool  # 是否需要用户输入
    questions: List[AskUserQuestion] = ()  # 问题列表
    raw_message: str = ""  # 原始消息（用于直接展示）
    context: str = ""      # 上下文说明


class AskUserParser:
    """提问解析器 — 从工具返回中识别结构化提问"""

    # 需要用户输入的关键词模式
    NEED_INPUT_PATTERNS = [
        ("请向用户", "需要确认"),
        ("请让用户", "需要确认"),
        ("请用户提供", "需要信息"),
        ("请向用户确认", "需要确认"),
        ("请让用户确认", "需要确认"),
        ("请用户提供以下信息", "需要信息"),
        ("请用户提供", "需要信息"),
        ("询问用户", "需要确认"),
        ("你可以帮用户", "引导操作"),
        ("你可以帮用户安装", "引导安装"),
    ]

    def parse(self, tool_name: str, content: str) -> AskUserResult:
        """解析工具返回，判断是否需要结构化提问

        Args:
            tool_name: 工具名称
            content: 工具返回内容

        Returns:
            AskUserResult
        """
        if not content:
            return AskUserResult(needs_user_input=False)

        # 检查是否需要用户输入
        needs_input = False
        context = ""
        for pattern, ctx in self.NEED_INPUT_PATTERNS:
            if pattern in content:
                needs_input = True
                context = ctx
                break

        if not needs_input:
            return AskUserResult(needs_user_input=False)

        # 提取问题
        questions = self._extract_questions(content, tool_name)
        if not questions:
            # 无法提取结构化问题，直接返回原文
            return AskUserResult(
                needs_user_input=False,
                raw_message=content,
            )

        return AskUserResult(
            needs_user_input=True,
            questions=questions,
            context=context,
            raw_message=content,
        )

    def _extract_questions(self, content: str, tool_name: str) -> List[AskUserQuestion]:
        """从内容中提取结构化问题"""
        questions = []

        # SSH 连接失败场景
        if tool_name in ("inspect_remote_server",):
            lines = content.split("\n")
            # 提取引导项
            items = []
            in_list = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("请向用户询问"):
                    in_list = True
                    continue
                if in_list and stripped.startswith(("1.", "2.", "3.", "4.")):
                    # 提取纯文本部分
                    text = stripped.lstrip("0123456789.").strip()
                    # 去掉括号中的说明
                    text = text.split("（")[0].split("(")[0].strip()
                    items.append(text)
                elif in_list and (stripped.startswith("用户") or not stripped):
                    if not stripped and items:
                        break

            if items:
                questions.append(AskUserQuestion(
                    question="SSH 连接失败，需要以下信息：",
                    header="SSH",
                    options=items,
                ))

        # K8s 连接失败场景
        elif tool_name in ("k8s_cluster_inspect", "k8s_pod_logs", "k8s_scale_deployment", "k8s_restart_deployment"):
            if "kubeconfig" in content:
                questions.append(AskUserQuestion(
                    question="K8s 连接失败，需要确认 kubeconfig 配置",
                    header="K8s",
                    options=[
                        "使用默认 kubeconfig (~/.kube/config)",
                        "使用 K3s 配置 (/etc/rancher/k3s/k3s.yaml)",
                        "指定自定义 kubeconfig 路径",
                    ],
                ))

        # 依赖未安装场景
        if "未安装" in content and "安装命令" in content:
            questions.append(AskUserQuestion(
                question="检测到依赖缺失，是否需要我帮你安装？",
                header="安装",
                options=["是，帮我安装", "否，我自己安装"],
            ))

        # 通用场景：如果有引导文字但无法提取具体问题
        if not questions:
            questions.append(AskUserQuestion(
                question=content[:200],
                header="引导",
            ))

        return questions

    def format_for_display(self, result: AskUserResult) -> str:
        """格式化提问为 CLI 可展示的文本"""
        if not result.needs_user_input:
            return result.raw_message

        lines = [f"\n[需要您的输入] ({result.context})"]
        lines.append("━" * 40)

        for i, q in enumerate(result.questions, 1):
            if q.header:
                lines.append(f"\n  [{q.header}] {q.question}")
            else:
                lines.append(f"\n  {i}. {q.question}")

            if q.options:
                lines.append("  可选：")
                for j, opt in enumerate(q.options, 1):
                    lines.append(f"    {j}. {opt}")

        lines.append("")
        lines.append("请回复所需信息，或输入 'skip' 跳过。")
        return "\n".join(lines)


# 全局实例
ask_user_parser = AskUserParser()
