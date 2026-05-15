"""Agent Loop — 类 Claude Code 的多步推理执行引擎

核心机制：
1. 用户输入一个需求
2. LLM 分析需求，决定调用哪些工具
3. 执行工具，获取结果
4. LLM 根据结果决定是否需要更多信息
5. 循环直到 LLM 给出最终答案

兼容性：
- 有 langgraph：使用 create_react_agent（推荐）
- 有 langchain 无 langgraph：手动 ReAct 循环
- 都没有：抛出明确错误提示安装
"""
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

from .tools_registry import ALL_TOOLS, LANGCHAIN_AVAILABLE


# ─── 检测可用的 Agent 框架 ─────────────────────────────────────
LANGGRAPH_AVAILABLE = False
if LANGCHAIN_AVAILABLE:
    try:
        from langgraph.prebuilt import create_react_agent
        LANGGRAPH_AVAILABLE = True
    except ImportError:
        pass


# ─── System Prompt ───────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """你是 Keeper，一个专业的智能运维 Agent。

## 你的工作方式
你通过调用工具来收集信息、诊断问题、执行操作。面对用户的问题：
1. 先分析需要什么信息
2. 调用合适的工具获取数据
3. 根据数据分析问题
4. 如果需要更多信息，继续调用工具
5. 最终给出完整的分析和建议

## 重要原则
- **先观察再判断**：不要没收集数据就下结论
- **逐步排查**：从大方向缩小到具体问题
- **关联分析**：结合多个数据源交叉验证
- **安全优先**：不执行破坏性操作，除非用户明确确认
- **简洁清晰**：使用结构化格式输出，重要信息高亮

## 排查模式参考
- CPU 高 → inspect_server → get_top_processes → query_system_logs(unit=异常进程)
- 服务不可达 → ping_host → check_port → query_system_logs(unit=服务名)
- K8s Pod 异常 → k8s_cluster_inspect → k8s_pod_logs
- 网络问题 → ping_host → dns_lookup → check_port
- 安全审计 → scan_ports → check_ssl_cert → query_system_logs(keyword="failed")

## 输出格式
- 使用中文回复
- 用标题分隔不同部分
- 异常/告警信息用 ⚠️ 标记
- 正常状态用 ✓ 标记
- 最后给出 [总结] 和 [建议]
"""


@dataclass
class ToolCall:
    """工具调用记录"""
    tool_name: str
    args: Dict[str, Any]
    result: str
    duration_ms: int
    success: bool = True


@dataclass
class AgentTurn:
    """一轮 Agent 执行记录"""
    user_input: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    final_response: str = ""
    total_duration_ms: int = 0
    loop_count: int = 0
    mode: str = ""  # "langgraph" / "manual" / "error"


class AgentLoop:
    """Agent Loop 引擎

    支持三种运行模式（自动降级）：
    1. LangGraph create_react_agent（最佳体验）
    2. 手动 ReAct 循环（兼容无 langgraph）
    3. 错误提示（无 langchain 时）
    """

    MAX_LOOPS = 10          # 最大循环次数，防止死循环
    MAX_OUTPUT_LEN = 2000   # 工具输出最大字符数（超出截断）
    MAX_HISTORY_TURNS = 5   # 保留的历史对话轮数

    def __init__(self, llm_config, mode: str = "auto"):
        """初始化 Agent Loop

        Args:
            llm_config: LLM 配置 (api_key, base_url, model)
            mode: 执行模式
                - "auto": 自动选择最佳模式
                - "langgraph": 强制 LangGraph
                - "manual": 强制手动 ReAct
        """
        self.llm_config = llm_config
        self.requested_mode = mode
        self.active_mode: Optional[str] = None
        self._agent = None
        self._llm = None
        self.conversation_history: List[Dict[str, str]] = []
        self.last_turn: Optional[AgentTurn] = None

    def _detect_mode(self) -> str:
        """自动检测可用模式"""
        if self.requested_mode == "langgraph" and LANGGRAPH_AVAILABLE:
            return "langgraph"
        if self.requested_mode == "manual" and LANGCHAIN_AVAILABLE:
            return "manual"
        if self.requested_mode == "auto":
            if LANGGRAPH_AVAILABLE:
                return "langgraph"
            if LANGCHAIN_AVAILABLE:
                return "manual"
        return "unavailable"

    @property
    def llm(self):
        """延迟初始化 LLM"""
        if self._llm is None:
            if not LANGCHAIN_AVAILABLE:
                raise RuntimeError(
                    "langchain 未安装，无法使用 Agent Loop。\n"
                    "请运行: pip install langchain-core langchain-openai langgraph"
                )
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=self.llm_config.api_key,
                base_url=self.llm_config.base_url,
                model=self.llm_config.model,
                temperature=0,
            )
        return self._llm

    @property
    def agent(self):
        """延迟初始化 Agent"""
        if self._agent is None:
            self.active_mode = self._detect_mode()
            if self.active_mode == "langgraph":
                self._agent = self._create_langgraph_agent()
            elif self.active_mode == "manual":
                self._agent = self._create_manual_agent()
            else:
                raise RuntimeError(
                    "无可用的 Agent 框架。\n"
                    "请安装: pip install langchain-core langchain-openai langgraph"
                )
        return self._agent

    def _create_langgraph_agent(self):
        """方式 1：LangGraph ReAct Agent"""
        from langgraph.prebuilt import create_react_agent
        return create_react_agent(
            model=self.llm,
            tools=ALL_TOOLS,
            state_modifier=AGENT_SYSTEM_PROMPT,
        )

    def _create_manual_agent(self):
        """方式 2：手动 ReAct（LLM + bind_tools）"""
        return self.llm.bind_tools(ALL_TOOLS)

    def run(self, user_input: str, stream_callback: Optional[Callable] = None) -> str:
        """执行一轮 Agent Loop

        Args:
            user_input: 用户输入
            stream_callback: 流式输出回调 (text) -> None

        Returns:
            Agent 最终回复
        """
        start_time = time.time()
        turn = AgentTurn(user_input=user_input)

        try:
            # 初始化 agent（触发模式检测）
            _ = self.agent
            turn.mode = self.active_mode

            if self.active_mode == "langgraph":
                response = self._run_langgraph(user_input, turn, stream_callback)
            else:
                response = self._run_manual(user_input, turn, stream_callback)

        except RuntimeError as e:
            # 框架不可用
            turn.mode = "error"
            response = str(e)
        except Exception as e:
            turn.mode = "error"
            response = f"[Agent 错误] 执行失败: {type(e).__name__}: {str(e)}"

        turn.final_response = response
        turn.total_duration_ms = int((time.time() - start_time) * 1000)
        self.last_turn = turn

        return response

    def _run_langgraph(
        self, user_input: str, turn: AgentTurn, callback: Optional[Callable]
    ) -> str:
        """LangGraph 模式执行"""
        from langchain_core.messages import HumanMessage, AIMessage

        # 构建消息（包含历史）
        messages = []
        for h in self.conversation_history[-self.MAX_HISTORY_TURNS:]:
            messages.append(HumanMessage(content=h["user"]))
            messages.append(AIMessage(content=h["assistant"]))
        messages.append(HumanMessage(content=user_input))

        if callback:
            callback("  🤔 Agent 分析中...\n")

        # 执行
        result = self.agent.invoke({"messages": messages})

        # 提取工具调用记录
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call = ToolCall(
                        tool_name=tc["name"],
                        args=tc["args"],
                        result="(见后续消息)",
                        duration_ms=0,
                    )
                    turn.tool_calls.append(tool_call)
                    if callback:
                        callback(f"  🔧 {tc['name']}({tc['args']})\n")
            turn.loop_count += 1

        # 提取最终回复
        final_msg = result["messages"][-1]
        response = final_msg.content

        # 更新历史
        self._add_history(user_input, response)

        return response

    def _run_manual(
        self, user_input: str, turn: AgentTurn, callback: Optional[Callable]
    ) -> str:
        """手动 ReAct 循环"""
        from langchain_core.messages import (
            HumanMessage, AIMessage, SystemMessage, ToolMessage,
        )

        # 构建初始消息
        messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT)]

        # 加入历史对话
        for h in self.conversation_history[-self.MAX_HISTORY_TURNS:]:
            messages.append(HumanMessage(content=h["user"]))
            messages.append(AIMessage(content=h["assistant"]))

        messages.append(HumanMessage(content=user_input))

        # 工具查找表
        tool_map = {t.name: t for t in ALL_TOOLS}

        if callback:
            callback("  🤔 Agent 分析中...\n")

        # ReAct 循环
        final_response = ""
        consecutive_same_tool = 0
        last_tool_name = ""

        for loop_i in range(self.MAX_LOOPS):
            turn.loop_count = loop_i + 1

            # 调用 LLM
            response = self.agent.invoke(messages)

            # 检查是否有 tool_calls
            if not response.tool_calls:
                # 无工具调用 → LLM 已给出最终答案
                final_response = response.content
                break
            else:
                # 有工具调用 → 执行并把结果喂回
                messages.append(response)

                for tc in response.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_id = tc["id"]

                    # 检测重复调用
                    if tool_name == last_tool_name:
                        consecutive_same_tool += 1
                    else:
                        consecutive_same_tool = 0
                    last_tool_name = tool_name

                    if consecutive_same_tool >= 3:
                        result = f"[提示] 你已连续调用 {tool_name} 3次，请尝试其他工具或给出结论。"
                    else:
                        # 通知用户
                        if callback:
                            args_str = ", ".join(f"{k}={repr(v)}" for k, v in tool_args.items())
                            callback(f"  🔧 调用 {tool_name}({args_str})...")

                        # 执行工具
                        t_start = time.time()
                        if tool_name in tool_map:
                            try:
                                result = tool_map[tool_name].invoke(tool_args)
                            except Exception as e:
                                result = f"[工具执行错误] {type(e).__name__}: {str(e)}"
                        else:
                            result = f"[错误] 未知工具: {tool_name}"
                        t_duration = int((time.time() - t_start) * 1000)

                        # 截断过长输出
                        if len(result) > self.MAX_OUTPUT_LEN:
                            result = result[:self.MAX_OUTPUT_LEN] + "\n... (输出已截断)"

                        if callback:
                            callback(f" ✓ ({t_duration}ms)\n")

                    # 记录
                    turn.tool_calls.append(ToolCall(
                        tool_name=tool_name,
                        args=tool_args,
                        result=result[:500],
                        duration_ms=t_duration if 't_duration' in dir() else 0,
                        success=not result.startswith("[错误]") and not result.startswith("[工具执行错误]"),
                    ))

                    # 把工具结果作为 ToolMessage 添加
                    messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_id,
                    ))
        else:
            # 超过最大循环次数
            final_response = "[Agent] 达到最大执行步骤 ({}次)，以下是目前收集到的信息摘要：\n\n".format(
                self.MAX_LOOPS
            )
            for tc in turn.tool_calls[-3:]:
                final_response += f"• {tc.tool_name}: {tc.result[:200]}\n"
            final_response += "\n请简化问题或指定更具体的方向。"

        # 更新历史
        self._add_history(user_input, final_response)

        return final_response

    def _add_history(self, user_input: str, response: str):
        """添加到对话历史（带长度控制）"""
        # 截断过长的回复（历史中只保留摘要）
        summary = response[:500] if len(response) > 500 else response
        self.conversation_history.append({
            "user": user_input,
            "assistant": summary,
        })
        # 保持历史长度
        if len(self.conversation_history) > self.MAX_HISTORY_TURNS * 2:
            self.conversation_history = self.conversation_history[-self.MAX_HISTORY_TURNS:]

    def get_last_tool_calls(self) -> List[ToolCall]:
        """获取上一轮的工具调用记录"""
        if self.last_turn:
            return self.last_turn.tool_calls
        return []

    def get_execution_summary(self) -> str:
        """获取上一轮执行摘要"""
        if not self.last_turn:
            return "(无执行记录)"

        turn = self.last_turn
        lines = [
            f"[执行摘要] 模式: {turn.mode} | 循环: {turn.loop_count}次 | 耗时: {turn.total_duration_ms}ms",
        ]
        if turn.tool_calls:
            lines.append("工具调用:")
            for i, tc in enumerate(turn.tool_calls, 1):
                status = "✓" if tc.success else "✗"
                lines.append(f"  {i}. {status} {tc.tool_name} ({tc.duration_ms}ms)")
        return "\n".join(lines)

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history.clear()
