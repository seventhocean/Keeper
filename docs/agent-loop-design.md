# Keeper Agent Loop 设计方案

> 目标：从"路由器模式"升级为"Agent Loop 模式"，实现类 Claude Code 的智能工具编排

## 一、当前模式 vs 目标模式

### 当前：路由器模式（Intent → Handler 一对一）

```
用户: "服务器 CPU 高，帮我分析一下"
  → NLU: intent=RCA_ANALYSIS
  → _dispatch() → _handle_rca()
  → 只调用一个工具，返回固定格式结果
```

**问题：**
- 一个意图只能调用一个固定工具
- 无法自动组合多个工具
- 无法根据中间结果调整策略
- 用户说复杂需求时只能执行第一步

### 目标：Agent Loop 模式（LLM 自主规划 + 多步执行）

```
用户: "服务器 CPU 高，帮我分析一下"
  → LLM 规划: [检查服务器状态, 查看 Top 进程, 查看系统日志, 综合分析]
  → Step 1: call inspect_server("localhost") → 结果: CPU 92%
  → Step 2: call get_top_processes() → 结果: mysql 占 85%
  → Step 3: call query_logs(keyword="mysql", since="1h") → 结果: slow query 大量出现
  → Step 4: LLM 综合分析 → "MySQL 慢查询导致 CPU 飙高，建议..."
```

---

## 二、核心设计：Tool Use + ReAct Loop

### 2.1 Tool 抽象层

把所有现有工具注册为 LangChain Tool 格式：

```python
# keeper/agent/tools_registry.py
"""工具注册中心 — 将所有运维工具注册为 LLM 可调用的 Tool"""

from langchain_core.tools import tool
from typing import Optional


@tool
def inspect_server(host: str = "localhost") -> str:
    """检查服务器资源状态（CPU/内存/磁盘/负载/Top进程）
    
    Args:
        host: 目标主机 IP 或 hostname，默认 localhost
    
    Returns:
        服务器状态报告文本
    """
    from ..tools.server import ServerTools, format_status_report
    status = ServerTools.inspect_server(host)
    thresholds = {"cpu": 80, "memory": 85, "disk": 90}
    return format_status_report(status, thresholds)


@tool
def scan_ports(host: str, ports: str = "1-1024") -> str:
    """扫描目标主机的开放端口和服务
    
    Args:
        host: 目标主机 IP
        ports: 端口范围，如 "1-1024" 或 "22,80,443"
    
    Returns:
        端口扫描结果和风险评估
    """
    from ..tools.scanner import ScannerTools, format_scan_result
    result = ScannerTools.scan(host)
    return format_scan_result(result)


@tool
def query_system_logs(
    lines: int = 50,
    unit: Optional[str] = None,
    since: Optional[str] = None,
    keyword: Optional[str] = None,
    priority: Optional[str] = None,
) -> str:
    """查询系统日志（journalctl）
    
    Args:
        lines: 返回行数
        unit: systemd 服务名称 (如 nginx, mysql, docker)
        since: 时间范围 (如 "1 hour ago", "2024-01-01")
        keyword: 关键词过滤
        priority: 日志级别 (emerg/alert/crit/err/warning/notice/info/debug)
    
    Returns:
        日志内容
    """
    from ..tools.logs import LogTools
    success, output = LogTools.query_journal(
        lines=lines, unit=unit, since=since, keyword=keyword, priority=priority
    )
    return output if success else f"查询失败: {output}"


@tool
def check_network(host: str, action: str = "ping") -> str:
    """网络诊断工具
    
    Args:
        host: 目标主机或域名
        action: 诊断类型 - ping/port_check/dns/http_check
    
    Returns:
        网络诊断结果
    """
    from ..tools.network import NetworkTools, format_ping_result
    if action == "ping":
        result = NetworkTools.ping(host)
        return format_ping_result(result)
    # ... 其他 action


@tool
def k8s_cluster_inspect(namespace: Optional[str] = None) -> str:
    """检查 K8s 集群整体状态（节点/Pod/工作负载/服务）
    
    Args:
        namespace: 指定 namespace 过滤，为空则检查所有
    
    Returns:
        K8s 集群巡检报告
    """
    from ..tools.k8s.client import K8sClient
    from ..tools.k8s.inspector import K8sInspector
    from ..tools.k8s.formatter import format_cluster_report
    
    client = K8sClient()
    success, msg = client.connect()
    if not success:
        return f"K8s 连接失败: {msg}"
    
    inspector = K8sInspector(client)
    report = inspector.full_inspect(namespace=namespace)
    return format_cluster_report(report, namespace=namespace)


@tool
def k8s_pod_logs(pod_name: str, namespace: str = "default", lines: int = 50, keyword: Optional[str] = None) -> str:
    """查看 K8s Pod 日志
    
    Args:
        pod_name: Pod 名称（支持前缀模糊匹配）
        namespace: 命名空间
        lines: 返回行数
        keyword: 关键词过滤
    
    Returns:
        Pod 日志内容
    """
    from ..tools.k8s.client import K8sClient
    from ..tools.k8s.logs import K8sLogTools
    
    client = K8sClient()
    success, msg = client.connect()
    if not success:
        return f"K8s 连接失败: {msg}"
    
    success, output = K8sLogTools.get_pod_logs(client, pod_name, namespace, lines, keyword)
    return output


@tool
def docker_list_containers(all_containers: bool = True, filter_name: Optional[str] = None) -> str:
    """列出 Docker 容器状态
    
    Args:
        all_containers: 是否包含已停止容器
        filter_name: 按名称过滤
    
    Returns:
        容器列表
    """
    from ..tools.docker_tools import DockerTools, format_docker_containers
    containers = DockerTools.list_containers(all_containers, filter_name)
    return format_docker_containers(containers)


@tool
def check_ssl_cert(target: str) -> str:
    """检查 SSL/TLS 证书状态
    
    Args:
        target: 域名或文件路径
    
    Returns:
        证书状态信息（过期时间、剩余天数等）
    """
    from ..tools.cert_monitor import CertMonitor, format_cert_report
    monitor = CertMonitor()
    certs = monitor.check_domain(target)
    return format_cert_report(certs)


@tool
def execute_shell_command(command: str) -> str:
    """在本地执行 Shell 命令（只允许安全的只读命令）
    
    Args:
        command: 要执行的命令（会进行安全检查，拒绝危险命令）
    
    Returns:
        命令输出
    """
    import subprocess
    from ..tools.fixer import FixSuggester, SafetyLevel
    
    # 安全检查
    safety = FixSuggester.classify_command_safety(command)
    if safety == SafetyLevel.DANGEROUS:
        return f"[安全拦截] 命令被拒绝执行: {command}"
    if safety == SafetyLevel.DESTRUCTIVE:
        return f"[需要确认] 该命令为破坏性操作，请用户确认后执行: {command}"
    
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        return output[:2000] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "[超时] 命令执行超过 30s"
    except Exception as e:
        return f"[错误] {str(e)}"


# ─── 工具注册表 ──────────────────────────────────────────────
ALL_TOOLS = [
    inspect_server,
    scan_ports,
    query_system_logs,
    check_network,
    k8s_cluster_inspect,
    k8s_pod_logs,
    docker_list_containers,
    check_ssl_cert,
    execute_shell_command,
]
```

### 2.2 Agent Loop 核心

```python
# keeper/agent/loop.py
"""Agent Loop — 类 Claude Code 的多步执行引擎"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import create_react_agent
# 或手动实现 ReAct 循环

from .tools_registry import ALL_TOOLS


SYSTEM_PROMPT = """你是 Keeper，一个智能运维 Agent。你有多个工具可以使用，请根据用户的问题：

1. 分析用户需要什么信息或操作
2. 选择合适的工具调用（可以调用多个）
3. 根据工具返回的结果，决定是否需要进一步操作
4. 最终给出完整的分析结论和建议

## 你的工具能力：
- inspect_server: 检查服务器资源（CPU/内存/磁盘）
- scan_ports: 端口和漏洞扫描
- query_system_logs: 查询系统/服务日志
- check_network: 网络诊断（ping/端口/DNS）
- k8s_cluster_inspect: K8s 集群巡检
- k8s_pod_logs: 查看 Pod 日志
- docker_list_containers: Docker 容器状态
- check_ssl_cert: SSL 证书检查
- execute_shell_command: 执行安全的 Shell 命令

## 工作原则：
- 先收集信息，再做分析判断
- 发现异常时，主动用其他工具深入排查
- 给出具体、可操作的建议
- 对危险操作必须警告用户

## 输出格式：
- 使用中文回复
- 结构化展示信息（标题、列表、表格）
- 最后给出总结和建议
"""


class AgentLoop:
    """Agent Loop 引擎 — 多步推理执行"""

    def __init__(self, llm_config):
        self.llm = ChatOpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )
        # 使用 LangGraph 的 ReAct Agent
        self.agent = create_react_agent(
            model=self.llm,
            tools=ALL_TOOLS,
            state_modifier=SYSTEM_PROMPT,
        )
        self.conversation_history = []

    def run(self, user_input: str) -> str:
        """执行一轮对话
        
        LLM 会自动：
        1. 分析用户意图
        2. 决定调用哪些工具
        3. 根据结果决定下一步
        4. 循环执行直到给出最终答案
        """
        # 构建消息
        messages = self.conversation_history + [
            HumanMessage(content=user_input)
        ]
        
        # Agent Loop 执行（LLM 自主循环）
        result = self.agent.invoke({"messages": messages})
        
        # 提取最终回复
        final_message = result["messages"][-1]
        response = final_message.content
        
        # 更新对话历史
        self.conversation_history.append(HumanMessage(content=user_input))
        self.conversation_history.append(AIMessage(content=response))
        
        # 保持历史长度
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
        
        return response
```

### 2.3 混合架构：Fast Path + Agent Loop

```python
# keeper/agent/hybrid_agent.py
"""混合 Agent — 简单任务快速响应，复杂任务进入 Agent Loop"""

from ..nlu.langchain_engine import _try_fast_match
from .loop import AgentLoop
from ..config import AppConfig


class HybridAgent:
    """混合模式 Agent
    
    设计理念：
    - 简单明确的指令 → Fast Path（正则匹配 + 直接执行，<100ms）
    - 复杂/模糊的需求 → Agent Loop（LLM 自主规划，多步执行）
    
    这样兼顾了：
    - 性能（常见操作不需要调 LLM）
    - 智能（复杂场景 LLM 自主决策）
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._agent_loop = None  # 延迟初始化
        
        # 简单任务的快速 handler（保持现有逻辑）
        self._fast_handlers = {
            "help": self._quick_help,
            "confirm": self._quick_confirm,
            # ... 确定性操作
        }

    @property
    def agent_loop(self) -> AgentLoop:
        """延迟初始化 Agent Loop（需要时才加载 LLM）"""
        if self._agent_loop is None:
            self._agent_loop = AgentLoop(self.config.llm)
        return self._agent_loop

    def process(self, user_input: str) -> str:
        """处理用户输入
        
        决策逻辑：
        1. 尝试 Fast Path（正则匹配简单意图）
        2. 如果是确定性操作（help/exit/confirm），直接执行
        3. 否则进入 Agent Loop，让 LLM 自主决策
        """
        # Step 1: 快速路径尝试
        fast_result = _try_fast_match(user_input)
        
        if fast_result and fast_result.intent.value in self._fast_handlers:
            # 确定性操作直接走 fast path
            return self._fast_handlers[fast_result.intent.value](fast_result.entities)
        
        # Step 2: 进入 Agent Loop（LLM 自主决策）
        return self.agent_loop.run(user_input)

    def _quick_help(self, entities) -> str:
        return "Keeper 支持：服务器巡检、K8s管理、Docker管理、网络诊断..."

    def _quick_confirm(self, entities) -> str:
        return "确认执行"
```

---

## 三、执行流程对比示例

### 示例 1：简单任务（Fast Path）

```
用户: "帮助"
  → Fast Path 匹配: intent=HELP
  → 直接返回帮助信息（无 LLM 调用，<1ms）
```

### 示例 2：复杂任务（Agent Loop）

```
用户: "服务器最近很慢，帮我看看什么问题"

→ Agent Loop 开始:

  LLM 思考: "用户说服务器慢，我需要检查资源状态和日志"
  
  Step 1: call inspect_server("localhost")
  结果: CPU 92%, 内存 78%, 磁盘 65%
  
  LLM 思考: "CPU 很高，我需要看看是什么进程"
  
  Step 2: call execute_shell_command("ps aux --sort=-%cpu | head -10")
  结果: mysql 占用 85% CPU
  
  LLM 思考: "MySQL 占用高，看看是不是慢查询导致的"
  
  Step 3: call query_system_logs(unit="mysql", since="1 hour ago", priority="err")
  结果: [大量 slow query 日志]
  
  LLM 思考: "确认是 MySQL 慢查询问题，我来总结"
  
  最终回复:
  ┌─────────────────────────────────────────┐
  │ 🔍 问题分析                              │
  ├─────────────────────────────────────────┤
  │ 根因：MySQL 慢查询导致 CPU 飙升          │
  │                                         │
  │ 证据：                                   │
  │ 1. CPU 使用率 92%，主要被 mysql 进程占用  │
  │ 2. 最近 1 小时出现大量 slow query 日志    │
  │                                         │
  │ 建议：                                   │
  │ 1. 检查慢查询日志定位具体 SQL            │
  │ 2. 考虑添加索引或优化查询               │
  │ 3. 临时方案：kill 长时间运行的查询       │
  └─────────────────────────────────────────┘
```

### 示例 3：多工具协作

```
用户: "全面检查一下系统安全状况"

→ Agent Loop:

  Step 1: call inspect_server("localhost")        — 系统资源
  Step 2: call scan_ports("localhost")            — 开放端口
  Step 3: call check_ssl_cert("example.com")     — 证书状态
  Step 4: call query_system_logs(keyword="failed login", since="24h")  — 登录失败
  Step 5: call execute_shell_command("last -10")  — 最近登录
  
  综合输出: 安全审计报告
```

---

## 四、关键依赖

```
langchain >= 0.3        (已有)
langgraph >= 0.2        (新增 — Agent Loop 框架)
langchain-openai >= 0.2 (已有)
```

LangGraph 是 LangChain 团队的 Agent 框架，专门用于构建 ReAct Loop。

---

## 五、实现优先级

```
Phase A（快速验证，1-2 天）:
├── 1. 安装 langgraph
├── 2. 创建 keeper/agent/tools_registry.py（注册 3-5 个核心工具）
├── 3. 创建 keeper/agent/loop.py（基于 create_react_agent）
└── 4. 在 CLI 中增加 --agent 模式开关测试

Phase B（完善，3-5 天）:
├── 5. 注册所有现有工具（15+ 个）
├── 6. 实现 HybridAgent（Fast Path + Agent Loop）
├── 7. 优化 System Prompt（增加运维领域知识）
├── 8. 增加工具调用安全拦截
└── 9. 对话历史管理

Phase C（高级特性，1 周）:
├── 10. 工具调用结果缓存（避免重复调用）
├── 11. 执行计划展示（先告诉用户要做什么，确认后执行）
├── 12. 流式输出（边执行边输出）
├── 13. Token 成本控制（限制最大循环次数）
└── 14. 降级模式（LLM 不可用时回退路由器模式）
```

---

## 六、与当前架构的兼容策略

```
keeper/
├── core/
│   └── agent.py              ← 保留原有路由器模式（作为降级方案）
├── agent/                    ← 新增 Agent Loop 模块
│   ├── __init__.py
│   ├── tools_registry.py    ← 工具注册
│   ├── loop.py              ← ReAct Agent Loop
│   └── hybrid_agent.py      ← 混合模式入口
└── cli.py                    ← 增加 --mode=agent/classic 切换
```

用户可以选择：
- `keeper` — 默认 hybrid 模式
- `keeper --classic` — 退回路由器模式（无需 LLM 即可用）
