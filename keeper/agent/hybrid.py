"""混合模式 Agent — Fast Path + Agent Loop

┌──────────────────────────────────────────────────────────────┐
│ 用户输入                                                      │
│   ↓                                                          │
│ [Fast Path] — 正则匹配简单/确定性指令（帮助/退出/清空）       │
│   ↓ 命中         ↓ 未命中                                    │
│ 直接返回       [Agent Loop] — LLM 自主规划 + 多步工具调用     │
│ (<1ms)         (数秒，取决于工具调用次数)                     │
│                  ↓ 失败                                       │
│                [降级] — 旧路由器模式 / 友好错误提示            │
└──────────────────────────────────────────────────────────────┘
"""
import time
from typing import Optional, Callable

from keeper.config import AppConfig
from keeper.core.audit import AuditLogger
from keeper.core.context import AgentState
from keeper.nlu.langchain_engine import _try_fast_match
from keeper.nlu.base import IntentType
from .loop import AgentLoop, LANGCHAIN_AVAILABLE
from .planner import match_plan_template, should_show_plan, generate_dynamic_plan
from .memory import AgentMemory
from .state import AgentStateStore
from .ask_user import ask_user_parser


def _classify_input(user_input: str) -> str:
    """根据输入关键词分类任务类型（优先匹配具体类别，通用关键词最后检查）"""
    input_lower = user_input.lower()
    # 具体类别优先
    if any(kw in input_lower for kw in ("k8s", "kubernetes", "pod", "deployment")):
        return "k8s"
    if any(kw in input_lower for kw in ("网络", "ping", "端口", "dns", "延迟")):
        return "network"
    if any(kw in input_lower for kw in ("安全", "扫描", "漏洞", "证书", "ssl", "tls")):
        return "security"
    if any(kw in input_lower for kw in ("docker", "容器", "镜像")):
        return "docker"
    if any(kw in input_lower for kw in ("修复", "清理", "重启", "扩容", "缩容")):
        return "fix"
    # 通用巡视关键词放最后
    if any(kw in input_lower for kw in ("cpu", "内存", "磁盘", "检查", "服务器", "负载")):
        return "inspect"
    return "general"


class HybridAgent:
    """混合模式 Agent

    对外暴露 process(user_input) 方法，内部自动决定走哪条路径。
    """

    # 这些意图走 Fast Path 直接处理
    FAST_PATH_INTENTS = {
        IntentType.HELP,
        IntentType.CONFIRM,
    }

    def __init__(self, config: AppConfig):
        self.config = config
        self.state = AgentState()
        self.state.is_running = True
        self.audit = AuditLogger()
        self._agent_loop: Optional[AgentLoop] = None
        self._stream_callback: Optional[Callable] = None
        self.memory = AgentMemory()
        self._first_turn = True  # 首次对话标志，用于注入记忆摘要
        self.state_store = AgentStateStore()
        self.state_store.is_running = True

    @property
    def agent_loop(self) -> AgentLoop:
        """延迟初始化 Agent Loop"""
        if self._agent_loop is None:
            self._agent_loop = AgentLoop(
                self.config.llm, mode="auto", tool_mode="all", memory=self.memory,
            )
        return self._agent_loop

    def set_stream_callback(self, callback: Callable):
        """设置流式输出回调（显示工具调用过程）"""
        self._stream_callback = callback

    def get_last_tool_names(self) -> list:
        """获取上一轮执行中调用的工具名称列表"""
        try:
            loop = self.agent_loop
            return loop.get_last_tool_names()
        except Exception:
            return []

    def process(self, user_input: str) -> str:
        """处理用户输入

        Returns:
            Agent 回复文本
        """
        start_time = time.time()
        user_input = user_input.strip()

        if not user_input:
            return ""

        # ─── 退出检测 ───
        if user_input.lower() in ("exit", "quit", "bye", "退出", "再见"):
            self.state.is_running = False
            return "[系统] 再见！"

        # ─── 特殊命令 ───
        if user_input.startswith("/"):
            return self._handle_slash_command(user_input)

        # ─── Fast Path ───
        fast_result = _try_fast_match(user_input)
        if fast_result and fast_result.intent in self.FAST_PATH_INTENTS:
            response = self._handle_fast_path(fast_result.intent, fast_result.entities)
            self._log_audit("fast_path", fast_result.intent.value, {}, response, start_time)
            return response

        # ─── Agent Loop ───
        if not self.config.is_llm_configured():
            return self._handle_no_llm(user_input, fast_result)

        try:
            # 注入排查计划（模板优先，动态生成兜底）
            plan = match_plan_template(user_input)
            if not plan and should_show_plan(user_input):
                # 模板未匹配但输入暗示复杂任务 → 动态生成
                plan = generate_dynamic_plan(user_input)

            augmented_input = user_input
            if plan:
                steps_desc = " → ".join(s.description for s in plan.steps)
                augmented_input = f"{user_input}\n\n[排查路线: {steps_desc}]"

            # 上下文注入：由 ContextInjector 统一处理
            # 首次对话：注入最近记忆摘要 + 主机上下文
            # 后续对话：仅在关键词匹配时注入相关记忆
            if self._first_turn:
                self._first_turn = False
                self.agent_loop.context_injector.collect(augmented_input)
            else:
                # 后续对话：通过 ContextInjector 获取相关记忆
                self.agent_loop.context_injector.collect(augmented_input)
                history_context = self.memory.get_context_for_prompt(user_input)
                if history_context:
                    augmented_input = f"{history_context}\n[当前问题]\n{augmented_input}"

            response = self.agent_loop.run(augmented_input, stream_callback=self._stream_callback)

            # 检测是否需要结构化提问
            # 如果 Agent 的回复中包含工具返回的引导信息，格式化为结构化提问
            last_tool_calls = self.agent_loop.get_last_tool_calls()
            for tc in last_tool_calls:
                parsed = ask_user_parser.parse(tc.tool_name, tc.result)
                if parsed.needs_user_input:
                    # 尝试使用交互式选择
                    if parsed.questions and parsed.questions[0].options:
                        try:
                            from keeper.agent.confirm import select_option
                            question = parsed.questions[0]
                            selected = select_option(question.question, list(question.options))
                            response = response.rstrip() + f"\n[用户选择] {selected}"
                        except Exception:
                            formatted = ask_user_parser.format_for_display(parsed)
                            response = response.rstrip() + "\n" + formatted
                    else:
                        formatted = ask_user_parser.format_for_display(parsed)
                        # 在回复末尾追加结构化提问
                        response = response.rstrip() + "\n" + formatted
                    break

            # 同步状态到状态总线
            self.state_store.active_loop_mode = self.agent_loop.active_mode
            self.state_store.last_tool_calls = self.agent_loop.get_last_tool_calls()

            # 记录审计
            tool_calls = self.agent_loop.get_last_tool_calls()
            audit_tool_names = [tc.tool_name for tc in tool_calls]
            # 从工具调用中提取目标主机
            audit_host = ""
            for tc in tool_calls:
                if tc.tool_name in ("inspect_server", "inspect_remote_server", "ping_host", "check_port", "scan_ports"):
                    audit_host = tc.args.get("host", "") if tc.args else ""
                    if audit_host:
                        break
            self._log_audit(
                "agent_loop",
                "multi_step",
                {"tools": audit_tool_names, "loops": self.agent_loop.last_turn.loop_count if self.agent_loop.last_turn else 0},
                response,
                start_time,
                host=audit_host,
            )

            # 保存到长期记忆
            self.memory.add(
                user_input=user_input,
                tools_used=audit_tool_names,
                conclusion=response[:300],
                category=_classify_input(user_input),
            )
            return response

        except Exception as e:
            return self._handle_agent_error(user_input, fast_result, e, start_time)

    def _handle_slash_command(self, cmd: str) -> str:
        """处理斜杠命令 — 委托给命令系统"""
        from .commands import (
            CommandRegistry, create_default_registry,
            handle_memory_command,
        )

        cmd_raw = cmd.strip()
        cmd_lower = cmd_raw.lower()

        # /memory 需要解析参数，单独处理
        if cmd_lower == "/memory" or cmd_lower == "/记忆" or cmd_lower.startswith("/memory "):
            return handle_memory_command(cmd_raw, self.memory)

        # 其他命令：去掉 / 前缀后查找
        cmd_no_slash = cmd_lower.lstrip("/")
        if cmd_no_slash in ("clear", "清空", "reset"):
            from .commands import _clear
            return _clear(lambda: self._agent_loop)
        if cmd_no_slash in ("history", "上次", "last"):
            from .commands import _history
            return _history(lambda: self._agent_loop)
        if cmd_no_slash in ("tools", "能力"):
            from .commands import _tools
            return _tools()
        if cmd_no_slash in ("mode", "状态"):
            from .commands import _mode
            return _mode(lambda: self._agent_loop)
        if cmd_no_slash in ("plugins", "插件"):
            from .commands import _plugins
            return _plugins()
        if cmd_no_slash in ("status", "系统状态"):
            return self.state_store.format_status()

        return f"[系统] 未知命令: {cmd}\n可用: /clear /history /tools /mode /memory /plugins /status"

    def _handle_fast_path(self, intent: IntentType, entities: dict) -> str:
        """处理 Fast Path 意图"""
        if intent == IntentType.HELP:
            return self._get_help_text()
        if intent == IntentType.CONFIRM:
            return "[系统] 没有待确认的操作。"
        return "[系统] 未知指令"

    def _handle_no_llm(self, user_input: str, fast_result) -> str:
        """LLM 未配置时的降级处理"""
        msg = "[降级模式] LLM 未配置，Agent 模式不可用。\n\n"
        msg += "配置方法:\n"
        msg += "  keeper config set --api-key YOUR_KEY --base-url https://api.xxx.com/v1\n\n"
        msg += "或使用经典模式:\n"
        msg += "  keeper --classic\n"
        return msg

    def _handle_agent_error(self, user_input: str, fast_result, error: Exception, start_time) -> str:
        """Agent Loop 失败时的降级处理"""
        # 尝试用旧路由器模式兜底
        if fast_result and fast_result.intent != IntentType.UNKNOWN:
            try:
                from keeper.core.agent import Agent
                from keeper.nlu.langchain_engine import LangChainEngine, LLMProvider

                provider_map = {
                    "openai_compatible": LLMProvider.OPENAI_COMPATIBLE,
                    "anthropic": LLMProvider.ANTHROPIC,
                }
                provider = provider_map.get(self.config.llm.provider, LLMProvider.OPENAI_COMPATIBLE)

                engine = LangChainEngine(
                    provider=provider,
                    api_key=self.config.llm.api_key,
                    base_url=self.config.llm.base_url,
                    model=self.config.llm.model,
                )
                old_agent = Agent(nlu_engine=engine, config=self.config)
                response = old_agent.process(user_input)
                self._log_audit("fallback_classic", fast_result.intent.value, {}, response, start_time)
                return f"[降级到经典模式]\n{response}"
            except Exception:
                pass

        # 完全兜底
        error_msg = f"[Agent 错误] {type(error).__name__}: {str(error)}\n\n"
        error_msg += "建议:\n"
        error_msg += "  1. 检查 LLM API Key 和网络连接\n"
        error_msg += "  2. 尝试简化问题描述\n"
        error_msg += "  3. 使用 keeper --classic 经典模式\n"

        self._log_audit("error", "agent_loop_failed", {"error": str(error)}, error_msg, start_time)
        return error_msg

    def _get_help_text(self) -> str:
        """帮助信息"""
        try:
            from keeper.i18n import get_help_text
            help_text = get_help_text()
            if help_text and help_text != "agent.help":
                return help_text
        except Exception:
            pass

        from .free_tools import get_free_tools_description
        return f"""[Keeper Agent 模式 — 自由模式]

我是智能运维助手，拥有和运维工程师一样的服务器操作能力。

💬 你可以直接说：
  • "帮我看看 CPU 为什么高"
  • "查看 /etc/nginx/nginx.conf 的配置"
  • "找一下哪个日志文件有 error"
  • "重启一下 nginx 服务"
  • "磁盘满了，帮我清理一下"
  • "看看 docker 有什么容器在跑"

我会自己执行命令、读取文件、分析结果，直到解决问题。

{get_free_tools_description()}

⚡ 特殊命令：
  /clear   — 清空对话历史
  /history — 查看上次执行详情
  /tools   — 列出所有可用工具
  /mode    — 查看当前运行模式
"""

    def _log_audit(self, mode: str, intent: str, entities: dict, response: str, start_time: float, host: str = ""):
        """记录审计日志"""
        response_time = int((time.time() - start_time) * 1000)
        try:
            self.audit.log_turn(
                intent=f"{mode}:{intent}",
                entities=entities,
                result="success" if not response.startswith("[错误]") and not response.startswith("[Agent 错误]") else "error",
                response_time_ms=response_time,
                response=response[:500],
                host=host or None,
            )
        except Exception:
            pass  # 审计失败不影响主流程
