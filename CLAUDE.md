# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**Keeper** - 智能运维 Agent，类似 Claude Code 的对话式 CLI 工具

**版本：** v1.0.0 (2026-05-16)

## 快速命令

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行测试
pytest tests/ -v
pytest tests/test_agent_loop.py -v  # 单文件测试

# 启动 Agent 模式（默认，LLM 自主决策 + 多步工具调用）
keeper

# 启动经典路由器模式
keeper --classic

# 单命令执行
keeper run 检查 192.168.1.100

# 执行 Shell 命令
keeper exec -- df -h /

# 配置管理
keeper config set --api-key YOUR_API_KEY --model claude-sonnet-4-6
keeper config set --threshold 80 --metric cpu
keeper config show

# 审计日志
keeper logs --hours 24
keeper logs --host 192.168.1.100
```

## 核心架构：Hybrid Agent (Fast Path + Agent Loop)

默认模式 `keeper` 使用 `keeper/agent/hybrid.py:HybridAgent`，输入流程如下：

```
用户输入
  → [Fast Path] — 正则匹配确定性指令（帮助/退出/清空等）
  → 未命中 → [Agent Loop] — LLM 自主规划 + 多步工具调用（ReAct Loop）
  → Agent Loop 失败 → [降级] — 经典路由器模式兜底
```

### Agent Loop 双模式（`keeper/agent/loop.py`）

`AgentLoop` 支持自动降级的运行模式：
1. **LangGraph ReAct Agent**（推荐，`langgraph>=0.2`）：使用 `create_react_agent`
2. **手动 ReAct 循环**（兼容，仅需 `langchain`）：LLM bind_tools + 手动消息循环
3. **不可用**：抛出明确错误提示安装 langchain/langgraph

关键参数：`MAX_LOOPS=10`, `MAX_OUTPUT_LEN=2000`（工具输出截断）, `MAX_HISTORY_TURNS=5`

### 工具注册中心（`keeper/agent/tools_registry.py`）

所有运维工具使用 `@tool` 装饰器注册为 LLM 可调用的函数。LLM 根据 docstring 理解工具用途并自主决定调用时机。支持两种模式：
- 有 `langchain_core`：使用 LangChain `@tool` 装饰器
- 无 `langchain_core`：fallback 装饰器保持函数可调用

`ALL_TOOLS` 列表包含 18 个工具（服务器监控、日志查询、网络诊断、K8s 管理、Docker、安全、SSH 远程、Shell 执行）。

### 模块结构

```
keeper/
├── agent/                    ← Agent Loop 引擎（新增）
│   ├── loop.py              ← ReAct Agent Loop（LangGraph / 手动两种模式）
│   ├── hybrid.py            ← HybridAgent — Fast Path + Agent Loop 混合入口
│   ├── planner.py           ← 执行计划生成器 + 6 个预定义排查模板
│   ├── memory.py            ← AgentMemory 长期记忆（持久化到 ~/.keeper/agent_memory.json）
│   ├── safety.py            ← CommandSafetyChecker 四级安全审查 + TOOL_PERMISSIONS 表
│   └── tools_registry.py    ← 18 个 @tool 注册 + ALL_TOOLS + get_tools_description()
├── core/
│   ├── agent.py             ← 经典路由器模式（降级兜底，保留）
│   ├── audit.py             ← 审计日志
│   └── context.py           ← AgentState
├── nlu/
│   ├── base.py              ← IntentType 枚举
│   └── langchain_engine.py  ← LangChain LLM 引擎 + _try_fast_match
├── tools/                   ← 底层工具实现
│   ├── server.py, docker_tools.py, scanner.py, network.py
│   ├── rca.py, fixer.py, cert_monitor.py, notify.py, scheduler.py
│   ├── logs.py, reporter.py, ssh.py, alert.py
│   └── k8s/                 ← K8s 子模块（client, inspector, formatter, logs, ops）
├── cli.py                   ← Click + Prompt Toolkit 入口
└── config.py                ← AppConfig（环境变量 + YAML）
```

### 安全控制（`keeper/agent/safety.py`）

四级安全检查：`READ_ONLY`（直接执行）→ `WRITE`（需确认）→ `DESTRUCTIVE`（强制确认+警告）→ `DANGEROUS`（绝对拒绝）。

每个工具在 `TOOL_PERMISSIONS` 表中预定义安全等级。`execute_shell_command` 内部有额外正则检查。

### 计划模式（`keeper/agent/planner.py`）

6 个预定义排查模板：`cpu_high`, `service_down`, `k8s_issue`, `security_audit`, `disk_full`, `network_issue`。简单任务直接执行，复杂任务（匹配 `为什么/排查/分析/全面` 等关键词）先展示计划，用户确认后执行。

### 记忆系统（`keeper/agent/memory.py`）

- 短期记忆：`AgentLoop.conversation_history`（当前会话）
- 长期记忆：`AgentMemory` 持久化到 `~/.keeper/agent_memory.json`（最近 100 条），支持按关键词搜索和主机历史查询

### CLI 入口

```bash
keeper              # 默认 Agent 模式（HybridAgent）
keeper --classic     # 经典路由器模式
keeper agent        # 显式启动 Agent 模式
keeper chat         # 显式启动经典模式
```

特殊命令：`/clear`, `/history`, `/tools`, `/mode`

## 依赖

| 依赖 | 用途 |
|------|------|
| langchain >= 0.3 | LLM 框架 |
| langgraph >= 0.2 | Agent Loop（ReAct 引擎） |
| langchain-openai >= 0.2 | OpenAI 兼容 API |
| langchain-anthropic >= 0.2 | Anthropic API |
| click + prompt-toolkit | CLI 交互 |
| kubernetes >= 28.1 | K8s SDK (可选) |

## 配置

配置文件：`~/.keeper/config.yaml`

```yaml
current_profile: dev
profiles:
  dev:
    hosts: [localhost]
    thresholds: {cpu: 90, memory: 90, disk: 95}
llm:
  provider: openai_compatible  # 或 anthropic
  api_key: sk-xxx
  base_url: https://api.qnaigc.com/v1
  model: doubao-seed-2.0-mini
k8s:
  kubeconfig: ""  # 留空自动检测
  context: ""
  cluster_type: k8s  # k8s/k3s
notifications:
  feishu_webhook: ""
  feishu_secret: ""
```

## 开发注意事项

- 所有命令需先激活 `venv/bin/activate`
- LLM 依赖：需要有效的 API Key 才能测试 Agent/ NLU 功能
- 漏洞扫描需要系统安装 `nmap`
- `ServerTools.inspect_server("localhost")` 无需远程连接，可用于本地测试
- K8s 客户端自动检测 kubeconfig（K3s/标准 K8s/in-cluster），无需手动配置
