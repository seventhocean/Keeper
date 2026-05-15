"""Agent Loop — 类 Claude Code 的多步推理执行引擎

核心机制：
1. 用户输入一个需求
2. LLM 分析需求，决定调用哪些工具
3. 执行工具，获取结果
4. LLM 根据结果决定是否需要更多信息
5. 循环直到 LLM 给出最终答案

这就是 Claude Code 的 Tool Use + ReAct 模式。
"""
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

from .tools_registry import ALL_TOOLS


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


@dataclass
class AgentTurn:
    """一轮 Agent 执行记录"""
    user_input: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    final_response: str = ""
    total_duration_ms: int = 0
    loop_count: int = 0


class AgentLoop:
    """Agent Loop 引擎

    有两种实现方式：
    1. LangGraph create_react_agent（推荐，自动处理循环）
    2. 手动 ReAct 循环（更可控）

    这里提供两种实现。
    """

    MAX_LOOPS = 10  # 最大循环次数，防止死循环
    MAX_TOKENS_PER_TURN = 4000  # 每轮最大 token

    def __init__(self, llm_config, mode: str = "langgraph"):
        """初始化 Agent Loop

        Args:
            llm_config: LLM 配置 (api_key, base_url, model)
            mode: 执行模式
                - "langgraph": 使用 LangGraph ReAct Agent（推荐）
                - "manual": 手动 ReAct 循环
        """
        self.llm_config = llm_config
        self.mode = mode
        self._agent = None
        self._llm = None
        self.conversation_history: List[Dict] = []
        self.last_turn: Optional[AgentTurn] = None

    @property
    def llm(self):
        """延迟初始化 LLM"""
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=self.llm_config.api_key,
                base_url=self.llm_config.base_url,
                model=self.llm_config.model,
                temperature=0,
                max_tokens=self.MAX_TOKENS_PER_TURN,
            )
        return self._llm

    @property
    def agent(self):
        """延迟初始化 Agent"""
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent

    def _create_agent(self):
        """创建 Agent（根据 mode 选择实现方式）"""
        if self.mode == "langgraph":
            return self._create_langgraph_agent()
        else:
            return self._create_manual_agent()

    def _create_langgraph_agent(self):
        """方式 1：LangGraph ReAct Agent（推荐）

        LangGraph 自动处理：
        - Tool 调用解析
        - 循环执行逻辑
        - 消息历史管理
        - 终止条件判断
        """
        try:
            from langgraph.prebuilt import create_react_agent
            agent = create_react_agent(
                model=self.llm,
                tools=ALL_TOOLS,
                state_modifier=AGENT_SYSTEM_PROMPT,
            )
            return agent
        except ImportError:
            # langgraph 未安装，回退到手动模式
            print("[提示] langgraph 未安装，使用手动 ReAct 模式")
            self.mode = "manual"
            return self._create_manual_agent()

    def _create_manual_agent(self):
        """方式 2：手动 ReAct 循环（不依赖 langgraph）

        手动实现 Tool Use 循环，兼容性更好。
        """
        # 绑定 tools 到 LLM
        llm_with_tools = self.llm.bind_tools(ALL_TOOLS)
        return llm_with_tools

    def run(self, user_input: str, stream_callback: Optional[Callable] = None) -> str:
        """执行一轮 Agent Loop

        Args:
            user_input: 用户输入
            stream_callback: 流式输出回调 (可选)

        Returns:
            Agent 最终回复
        """
        start_time = time.time()
        turn = AgentTurn(user_input=user_input)

        try:
            if self.mode == "langgraph":
                response = self._run_langgraph(user_input, turn, stream_callback)
            else:
                response = self._run_manual(user_input, turn, stream_callback)
        except Exception as e:
            response = f"[Agent 错误] 执行失败: {str(e)}\n请尝试简化问题或使用 --classic 模式。"

        turn.final_response = response
        turn.total_duration_ms = int((time.time() - start_time) * 1000)
        self.last_turn = turn

        return response

    def _run_langgraph(
        self, user_input: str, turn: AgentTurn, callback: Optional[Callable]
    ) -> str:
        """LangGraph 模式执行"""
        from langchain_core.messages import HumanMessage

        # 构建消息（包含历史）
        messages = []
        for h in self.conversation_history[-10:]:  # 最近 5 轮对话
            messages.append(HumanMessage(content=h["user"]))
            from langchain_core.messages import AIMessage
            messages.append(AIMessage(content=h["assistant"]))
        messages.append(HumanMessage(content=user_input))

        # 执行 Agent
        result = self.agent.invoke({"messages": messages})

        # 提取工具调用记录
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    turn.tool_calls.append(ToolCall(
                        tool_name=tc["name"],
                        args=tc["args"],
                        result="(见后续消息)",
                        duration_ms=0,
                    ))
            turn.loop_count += 1

        # 提取最终回复
        final_msg = result["messages"][-1]
        response = final_msg.content

        # 更新历史
        self.conversation_history.append({
            "user": user_input,
            "assistant": response,
        })

        return response

    def _run_manual(
        self, user_input: str, turn: AgentTurn, callback: Optional[Callable]
    ) -> str:
        """手动 ReAct 循环（不依赖 langgraph）

        循环逻辑：
        1. 发送消息给 LLM（带 tool 定义）
        2. 如果 LLM 返回 tool_calls → 执行工具 → 把结果塞回消息 → 回到 1
        3. 如果 LLM 返回纯文本 → 结束循环
        """
        from langchain_core.messages import (
            HumanMessage, AIMessage, SystemMessage, ToolMessage,
        )

        # 构建初始消息
        messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT)]

        # 加入历史对话
        for h in self.conversation_history[-10:]:
            messages.append(HumanMessage(content=h["user"]))
            messages.append(AIMessage(content=h["assistant"]))

        messages.append(HumanMessage(content=user_input))

        # 构建工具查找表
        tool_map = {t.name: t for t in ALL_TOOLS}

        # ReAct 循环
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
                messages.append(response)  # AI 消息（含 tool_calls）

                for tc in response.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_id = tc["id"]

                    # 通知用户正在执行什么
                    if callback:
                        callback(f"  🔧 调用 {tool_name}({tool_args})...")

                    # 执行工具
                    t_start = time.time()
                    if tool_name in tool_map:
                        try:
                            result = tool_map[tool_name].invoke(tool_args)
                        except Exception as e:
                            result = f"[工具执行错误] {str(e)}"
                    else:
                        result = f"[错误] 未知工具: {tool_name}"
                    t_duration = int((time.time() - t_start) * 1000)

                    # 记录
                    turn.tool_calls.append(ToolCall(
                        tool_name=tool_name,
                        args=tool_args,
                        result=result[:500],  # 截断记录
                        duration_ms=t_duration,
                    ))

                    # 把工具结果作为 ToolMessage 添加到消息中
                    messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_id,
                    ))
        else:
            # 超过最大循环次数
            final_response = "[Agent] 达到最大执行步骤，请简化问题重试。"

        # 更新历史
        self.conversation_history.append({
            "user": user_input,
            "assistant": final_response,
        })

        return final_response

    def get_last_tool_calls(self) -> List[ToolCall]:
        """获取上一轮的工具调用记录（用于审计）"""
        if self.last_turn:
            return self.last_turn.tool_calls
        return []

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history.clear()
