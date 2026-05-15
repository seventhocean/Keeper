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
from .free_tools import FREE_TOOLS


# ─── 检测可用的 Agent 框架 ─────────────────────────────────────
LANGGRAPH_AVAILABLE = False
if LANGCHAIN_AVAILABLE:
    try:
        from langgraph.prebuilt import create_react_agent
        LANGGRAPH_AVAILABLE = True
    except ImportError:
        pass


# ─── System Prompt ───────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """你是 Keeper，一个专业的智能运维 Agent。你拥有和资深 Linux 运维工程师一样的能力。

## 你的核心能力
你可以通过工具直接操作服务器：
- **run_bash**: 执行任意 bash 命令（ps, df, cat, grep, systemctl, docker, kubectl...）
- **read_file**: 读取任何文件（配置文件、日志、代码）
- **write_file**: 修改或创建文件（修改配置、写脚本）
- **list_directory**: 浏览文件系统
- **search_files**: 在文件中搜索内容

## 工作方式
像一个真正的运维工程师一样工作：
1. 用户描述问题 → 你分析需要什么信息
2. 执行命令收集数据 → 查看输出结果
3. 如果信息不够 → 继续执行更多命令
4. 分析所有数据 → 给出结论和建议
5. 如果需要修复 → 提出具体操作方案

## 重要原则
- **先诊断再操作**：收集足够信息后才下结论
- **逐步排查**：从宽到窄缩小问题范围
- **解释你的思路**：让用户知道你在做什么、为什么
- **安全优先**：破坏性操作前说明风险
- **给出完整方案**：不只是发现问题，还要给修复建议

## 排查思路参考
- CPU 高 → `top -bn1` → 找到进程 → 查对应日志
- 服务异常 → `systemctl status xxx` → 查日志 `journalctl -u xxx`
- 磁盘满 → `df -h` → `du -sh /*` → 找大文件
- 网络不通 → `ping` → `ss -tlnp` → `iptables -L`
- 容器问题 → `docker ps` → `docker logs xxx`

## 输出格式
- 使用中文回复
- 结构化展示（标题、列表）
- 异常用 ⚠️ 标记
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

    def __init__(self, llm_config, mode: str = "auto", tool_mode: str = "all"):
        """初始化 Agent Loop

        Args:
            llm_config: LLM 配置 (api_key, base_url, model)
            mode: 执行模式
                - "auto": 自动选择最佳模式
                - "langgraph": 强制 LangGraph
                - "manual": 强制手动 ReAct
            tool_mode: 工具集模式
                - "free": 自由模式（run_bash + read_file + write_file，像 Claude Code）
                - "routed": 路由模式（18 个预注册运维工具）
                - "all": 全部工具（自由 + 路由）
        """
        self.llm_config = llm_config
        self.requested_mode = mode
        self.tool_mode = tool_mode
        self.active_mode: Optional[str] = None
        self._agent = None
        self._llm = None
        self.conversation_history: List[Dict[str, str]] = []
        self.last_turn: Optional[AgentTurn] = None

    def _get_tools(self):
        """根据 tool_mode 获取工具列表"""
        if self.tool_mode == "free":
            return FREE_TOOLS
        elif self.tool_mode == "routed":
            return ALL_TOOLS
        elif self.tool_mode == "all":
            return FREE_TOOLS + ALL_TOOLS
        else:
            return FREE_TOOLS

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
            tools=self._get_tools(),
            prompt=AGENT_SYSTEM_PROMPT,
        )

    def _create_manual_agent(self):
        """方式 2：手动 ReAct（LLM + bind_tools）"""
        return self.llm.bind_tools(self._get_tools())

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

        # 提取最终回复 — 从后往前找第一条有文本内容的消息
        response = ""
        for msg in reversed(result["messages"]):
            content = getattr(msg, "content", None)
            if content and isinstance(content, str) and content.strip():
                # 跳过只有 tool_calls 没有实质内容的消息
                has_tool_calls = getattr(msg, "tool_calls", None)
                if not has_tool_calls or len(content.strip()) > 20:
                    response = content
                    break

        if not response:
            # 无可用的文本回复，基于工具调用生成摘要
            response = "[Agent] 已完成数据收集，但未生成最终回复。以下为执行摘要：\n"
            for tc in turn.tool_calls[-5:]:
                response += f"  • {tc.tool_name}: {tc.result[:150]}\n"

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
        tool_map = {t.name: t for t in self._get_tools()}

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

                    t_duration = 0

                    if consecutive_same_tool >= 3:
                        result = f"[提示] 你已连续调用 {tool_name} 3次，请尝试其他工具或给出结论。"
                    else:
                        # 通知用户
                        if callback:
                            args_str = ", ".join(f"{k}={repr(v)}" for k, v in tool_args.items())
                            callback(f"  🔧 调用 {tool_name}({args_str})...")

                        # 安全检查
                        from .safety import is_tool_auto_allowed, get_tool_permission
                        if not is_tool_auto_allowed(tool_name):
                            level = get_tool_permission(tool_name)
                            if callback:
                                callback(f" ⚠️ 需确认 [{level.value}]\n")

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
                        duration_ms=t_duration,
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
