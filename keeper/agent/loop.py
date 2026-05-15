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

def _emit(callback, event):
    """安全调用回调 — 兼容旧格式 (str) 和新格式 (dict)"""
    if callback is None:
        return
    try:
        callback(event)
    except TypeError:
        # 旧格式: callback(str)
        if isinstance(event, dict):
            msg = event.get("message") or event.get("content") or event.get("tool") or ""
            if event.get("type") == "tool_call":
                args_str = ", ".join(f"{k}={repr(v)}" for k, v in (event.get("args") or {}).items())
                msg = f"  🔧 {event['tool']}({args_str})\n"
            elif event.get("type") == "tool_result":
                icon = "✓" if event.get("success") else "✗"
                msg = f" {icon} ({event.get('duration_ms', 0)}ms)\n"
            elif event.get("type") == "thinking":
                msg = f"  🤔 {event.get('message', '')}\n"
            elif event.get("type") == "warning":
                msg = f"  {event.get('message', '')}\n"
            elif event.get("type") == "text":
                msg = event.get("content", "")
            callback(msg)


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

## 自主服务原则（重要）
当工具返回的是一段引导文字（而非错误）时，这意味着你需要帮用户解决问题：
- **缺少依赖**: 工具提示缺少 nmap/kubernetes SDK → 主动询问用户是否帮你安装
- **SSH 连接失败**: 工具返回了引导信息 → 把引导信息展示给用户，等待用户提供凭据
- **K8s 连接失败**: 工具返回了 kubeconfig 配置引导 → 帮助用户找到或配置 kubeconfig
- **缺少配置**: 需要 API key/webhook 等 → 指引用户去配置
- **不要直接放弃**: 遇到配置问题不是报错了事，而是引导用户一步步解决

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
        """LangGraph 流式执行 — 逐步展示 + 错误恢复"""
        from langchain_core.messages import HumanMessage, AIMessage

        messages = []
        for h in self.conversation_history[-self.MAX_HISTORY_TURNS:]:
            messages.append(HumanMessage(content=h["user"]))
            messages.append(AIMessage(content=h["assistant"]))
        messages.append(HumanMessage(content=user_input))

        _emit(callback, {"type": "thinking", "message": "Agent 分析中..."})

        last_tool_name = ""
        consecutive_same = 0
        all_raw_messages = []

        try:
            for chunk in self.agent.stream(
                {"messages": messages},
                stream_mode="updates",
                config={"recursion_limit": 50},
            ):
                turn.loop_count += 1

                # Agent 节点: LLM 决策
                if "agent" in chunk:
                    agent_out = chunk["agent"]
                    # LangGraph 1.x: chunk = {"agent": {"messages": [...]}}
                    inner = agent_out.get("messages", []) if isinstance(agent_out, dict) else []
                    items = inner if isinstance(inner, list) else [inner] if inner else [agent_out]
                    if not items:
                        items = [agent_out]

                    for msg in items:
                        all_raw_messages.append(msg)
                        # 兼容 dict 和 Message 对象
                        if isinstance(msg, dict):
                            tool_calls = msg.get("tool_calls")
                            content = msg.get("content", "")
                            msg_type = msg.get("type", "")
                        else:
                            tool_calls = getattr(msg, "tool_calls", None)
                            content = getattr(msg, "content", "") or ""
                            msg_type = getattr(msg, "type", "")

                        # 跳过 ToolMessage（它们由 tools 节点处理）
                        if msg_type == "tool" or (isinstance(msg, dict) and msg.get("type") == "tool"):
                            continue

                        if tool_calls:
                            for tc in tool_calls:
                                if isinstance(tc, dict):
                                    tname = tc.get("name", "")
                                    targs = tc.get("args", {})
                                else:
                                    tname = getattr(tc, "name", "")
                                    targs = getattr(tc, "args", {})

                                if tname == last_tool_name:
                                    consecutive_same += 1
                                else:
                                    consecutive_same = 0
                                last_tool_name = tname

                                if consecutive_same >= 3:
                                    _emit(callback, {
                                        "type": "warning",
                                        "message": f"{tname} 连续调用 {consecutive_same} 次，建议换工具"
                                    })

                                _emit(callback, {
                                    "type": "tool_call",
                                    "tool": tname,
                                    "args": targs,
                                })

                                turn.tool_calls.append(ToolCall(
                                    tool_name=tname, args=targs,
                                    result="", duration_ms=0,
                                ))

                # Tools 节点: 工具执行结果
                elif "tools" in chunk:
                    tools_out = chunk["tools"]
                    inner = tools_out.get("messages", []) if isinstance(tools_out, dict) else []
                    tms = inner if isinstance(inner, list) else [inner] if inner else [tools_out]
                    for tm in tms:
                        all_raw_messages.append(tm)
                        if isinstance(tm, dict):
                            tc = tm.get("content", "")
                            tn = tm.get("name", "")
                        else:
                            tc = getattr(tm, "content", "")
                            tn = getattr(tm, "name", "")

                        if not tn:
                            continue

                        success = not (isinstance(tc, str) and ("[错误]" in tc or "Error" in tc or "[工具执行错误]" in tc))
                        for prev in reversed(turn.tool_calls):
                            if prev.tool_name == tn:
                                prev.result = tc[:500] if isinstance(tc, str) else str(tc)[:500]
                                prev.success = success
                                break
                        _emit(callback, {
                            "type": "tool_result",
                            "tool": tn,
                            "duration_ms": 0,
                            "success": success,
                        })

        except Exception as e:
            _emit(callback, {
                "type": "warning",
                "message": f"流式异常: {type(e).__name__}，降级到阻塞模式",
            })
            try:
                final = self.agent.invoke({"messages": messages})
                all_raw_messages = final["messages"]
            except Exception:
                raise e

        # 提取最终回复
        response = ""
        for msg in reversed(all_raw_messages):
            ct = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            tc = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            if ct and isinstance(ct, str) and ct.strip():
                if not tc or len(ct.strip()) > 20:
                    response = ct
                    break

        if not response:
            response = "[Agent] 已完成数据收集。"
            if turn.tool_calls:
                response += "\n"
                for tc in turn.tool_calls[-3:]:
                    response += f"  • {tc.tool_name}: {tc.result[:150]}\n"

        self._add_history(user_input, response)
        _emit(callback, {"type": "done"})
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

        _emit(callback, {"type": "thinking", "message": "Agent 分析中..."})

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
                        _emit(callback, {
                            "type": "warning",
                            "message": f"{tool_name} 连续调用 {consecutive_same_tool} 次，请尝试其他工具",
                        })
                    else:
                        _emit(callback, {
                            "type": "tool_call",
                            "tool": tool_name,
                            "args": tool_args,
                        })

                        # 安全检查
                        from .safety import is_tool_auto_allowed, get_tool_permission
                        if not is_tool_auto_allowed(tool_name):
                            level = get_tool_permission(tool_name)
                            _emit(callback, {
                                "type": "warning",
                                "message": f"需确认 [{level.value}]",
                            })

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

                        _emit(callback, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "duration_ms": t_duration,
                            "success": not result.startswith("[错误]") and not result.startswith("[工具执行错误]"),
                        })

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
