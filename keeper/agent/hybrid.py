"""混合模式 Agent — Fast Path + Agent Loop

设计理念：
┌──────────────────────────────────────────────────────────────┐
│ 用户输入                                                      │
│   ↓                                                          │
│ [Fast Path 尝试] — 正则匹配简单/确定性指令                    │
│   ↓ 命中         ↓ 未命中                                    │
│ 直接执行       [Agent Loop] — LLM 自主规划 + 多步工具调用     │
│ (<1ms)         (1-30s，取决于工具调用次数)                    │
└──────────────────────────────────────────────────────────────┘

为什么这样设计：
1. 简单指令（"帮助"/"退出"/"确认"）不需要调 LLM，正则即可
2. 复杂/模糊指令交给 LLM 自主决策，像 Claude Code 一样智能
3. LLM 不可用时可以完全降级到正则模式（只支持简单指令）
"""
import time
from typing import Optional, Callable

from ..config import AppConfig
from ..core.audit import AuditLogger
from ..core.context import AgentState
from ..nlu.langchain_engine import _try_fast_match
from ..nlu.base import IntentType
from .loop import AgentLoop


class HybridAgent:
    """混合模式 Agent

    对外暴露一个 process(user_input) 方法，内部自动决定走哪条路径。
    """

    # 这些意图走 Fast Path 直接处理，不需要 Agent Loop
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
            mode = "langgraph"  # 优先尝试 langgraph
            self._agent_loop = AgentLoop(self.config.llm, mode=mode)
        return self._agent_loop

    def set_stream_callback(self, callback: Callable):
        """设置流式输出回调（显示工具调用过程）"""
        self._stream_callback = callback

    def process(self, user_input: str) -> str:
        """处理用户输入

        决策逻辑：
        1. 尝试 Fast Path（正则匹配简单意图）
        2. 命中确定性操作 → 直接返回
        3. 否则 → 进入 Agent Loop（LLM 自主决策）
        4. Agent Loop 失败 → 降级处理

        Args:
            user_input: 用户输入文本

        Returns:
            Agent 回复
        """
        start_time = time.time()
        user_input = user_input.strip()

        if not user_input:
            return ""

        # ─── Step 1: 退出检测 ───
        if user_input.lower() in ("exit", "quit", "bye", "退出", "再见"):
            self.state.is_running = False
            return "[系统] 再见！"

        # ─── Step 2: Fast Path ───
        fast_result = _try_fast_match(user_input)
        if fast_result and fast_result.intent in self.FAST_PATH_INTENTS:
            response = self._handle_fast_path(fast_result.intent, fast_result.entities)
            self._log_audit("fast_path", fast_result.intent.value, {}, response, start_time)
            return response

        # ─── Step 3: Agent Loop ───
        if not self.config.is_llm_configured():
            return self._handle_no_llm(user_input, fast_result)

        try:
            # 显示"思考中"提示
            if self._stream_callback:
                self._stream_callback("🤔 分析中...\n")

            response = self.agent_loop.run(user_input, stream_callback=self._stream_callback)

            # 记录审计
            tool_calls = self.agent_loop.get_last_tool_calls()
            self._log_audit(
                "agent_loop",
                "multi_step",
                {"tool_calls": [tc.tool_name for tc in tool_calls]},
                response,
                start_time,
            )
            return response

        except Exception as e:
            # Agent Loop 失败，尝试降级
            return self._handle_agent_error(user_input, fast_result, e, start_time)

    def _handle_fast_path(self, intent: IntentType, entities: dict) -> str:
        """处理 Fast Path 意图"""
        if intent == IntentType.HELP:
            return self._get_help_text()
        if intent == IntentType.CONFIRM:
            return "[系统] 没有待确认的操作。"
        return "[系统] 未知指令"

    def _handle_no_llm(self, user_input: str, fast_result) -> str:
        """LLM 未配置时的降级处理"""
        msg = "[降级模式] LLM 未配置，仅支持简单指令。\n"
        msg += "请运行 `keeper config set --api-key YOUR_KEY` 配置后使用完整 Agent 模式。\n\n"

        # 如果正则匹配到了意图，给一个提示
        if fast_result:
            msg += f"检测到意图: {fast_result.intent.value}，但需要 LLM 才能执行复杂分析。"
        else:
            msg += "支持的简单指令: 帮助 / 退出"

        return msg

    def _handle_agent_error(self, user_input: str, fast_result, error: Exception, start_time) -> str:
        """Agent Loop 执行失败时的降级处理"""
        # 如果有 fast_result，尝试用旧模式兜底
        if fast_result and fast_result.intent != IntentType.UNKNOWN:
            from ..core.agent import Agent
            from ..nlu.langchain_engine import LangChainEngine

            try:
                # 尝试用旧路由器模式执行
                engine = LangChainEngine(
                    api_key=self.config.llm.api_key,
                    base_url=self.config.llm.base_url,
                    model=self.config.llm.model,
                )
                old_agent = Agent(nlu_engine=engine, config=self.config)
                return old_agent.process(user_input)
            except Exception:
                pass

        # 完全兜底
        error_msg = f"[Agent 错误] {str(error)}\n"
        error_msg += "提示：可以尝试更具体的指令，或使用 `keeper --classic` 模式。"

        self._log_audit("error", "agent_loop_failed", {"error": str(error)}, error_msg, start_time)
        return error_msg

    def _get_help_text(self) -> str:
        """帮助信息"""
        from .tools_registry import get_tools_description
        return f"""[Keeper Agent 模式]

我是智能运维助手，你可以用自然语言描述任何运维需求：

💬 示例：
  • "服务器最近很慢，帮我看看"
  • "检查 K8s 集群有没有问题"
  • "nginx 为什么返回 502？"
  • "全面检查一下系统安全"
  • "对比一下这台机器和昨天的状态"

我会自动选择合适的工具，逐步排查问题。

{get_tools_description()}

系统指令: 帮助 / 退出
"""

    def _log_audit(self, mode: str, intent: str, entities: dict, response: str, start_time: float):
        """记录审计日志"""
        response_time = int((time.time() - start_time) * 1000)
        try:
            self.audit.log_turn(
                intent=f"{mode}:{intent}",
                entities=entities,
                result="success" if not response.startswith("[错误]") else "error",
                response_time_ms=response_time,
                response=response[:500],
            )
        except Exception:
            pass  # 审计失败不影响主流程
