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

    @property
    def agent_loop(self) -> AgentLoop:
        """延迟初始化 Agent Loop"""
        if self._agent_loop is None:
            self._agent_loop = AgentLoop(self.config.llm, mode="auto", tool_mode="free")
        return self._agent_loop

    def set_stream_callback(self, callback: Callable):
        """设置流式输出回调（显示工具调用过程）"""
        self._stream_callback = callback

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
            response = self.agent_loop.run(user_input, stream_callback=self._stream_callback)

            # 记录审计
            tool_calls = self.agent_loop.get_last_tool_calls()
            self._log_audit(
                "agent_loop",
                "multi_step",
                {"tools": [tc.tool_name for tc in tool_calls], "loops": self.agent_loop.last_turn.loop_count if self.agent_loop.last_turn else 0},
                response,
                start_time,
            )
            return response

        except Exception as e:
            return self._handle_agent_error(user_input, fast_result, e, start_time)

    def _handle_slash_command(self, cmd: str) -> str:
        """处理斜杠命令"""
        cmd = cmd.strip().lower()

        if cmd in ("/clear", "/reset"):
            if self._agent_loop:
                self._agent_loop.clear_history()
            return "[系统] 对话历史已清空。"

        if cmd in ("/history", "/last"):
            if self._agent_loop:
                return self._agent_loop.get_execution_summary()
            return "(无执行记录)"

        if cmd in ("/tools", "/能力"):
            from .free_tools import get_free_tools_description
            from .tools_registry import get_tools_description
            return get_free_tools_description() + "\n" + get_tools_description()

        if cmd in ("/mode", "/状态"):
            mode = self._agent_loop.active_mode if self._agent_loop else "未初始化"
            return f"[系统] 当前模式: Agent Loop ({mode})"

        return f"[系统] 未知命令: {cmd}\n可用: /clear /history /tools /mode"

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

    def _log_audit(self, mode: str, intent: str, entities: dict, response: str, start_time: float):
        """记录审计日志"""
        response_time = int((time.time() - start_time) * 1000)
        try:
            self.audit.log_turn(
                intent=f"{mode}:{intent}",
                entities=entities,
                result="success" if not response.startswith("[错误]") and not response.startswith("[Agent 错误]") else "error",
                response_time_ms=response_time,
                response=response[:500],
            )
        except Exception:
            pass  # 审计失败不影响主流程
