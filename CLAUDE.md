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
pytest tests/test_agent_loop.py -v         # 单文件测试
pytest tests/ -m "not integration"          # 仅单元测试（跳过集成测试）
pytest tests/ -m "not requires_llm"         # 跳过需要 LLM 的测试
pytest tests/ --cov=keeper --cov-report=term-missing

# 代码检查
flake8 keeper/ --max-line-length=120

# 锁定精确依赖版本
bash scripts/lock-deps.sh

# 离线演示（无需 API Key）
python demo.py

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

`ALL_TOOLS` 列表包含 23 个工具：16 个结构化运维工具（服务器监控、日志查询、网络诊断、K8s 管理、Docker、安全扫描、SSL 证书、systemd 服务管理、SSH 远程）+ 3 个 Runbook 标准化流程（磁盘清理、服务重启、日志轮转）+ 2 个分析工具（`compare_inspection` 巡检对比、`predict_capacity` 容量预测）+ `execute_shell_command`。另有 5 个自由工具（`run_bash`, `read_file`, `write_file`, `list_directory`, `search_files`）在 `free_tools.py`，仅在 `tool_mode=free/all` 时暴露给 LLM。启动时自动加载 `~/.keeper/plugins/` 中的用户自定义工具。

### 模块结构

```
keeper/
├── agent/                    ← Agent Loop 引擎
│   ├── loop.py              ← ReAct Agent Loop（LangGraph / 手动两种模式）
│   ├── hybrid.py            ← HybridAgent — Fast Path + Agent Loop 混合入口
│   ├── planner.py           ← 执行计划生成器 + 6 个预定义排查模板
│   ├── memory.py            ← AgentMemory 长期记忆（持久化到 ~/.keeper/agent_memory.json）
│   ├── safety.py            ← CommandSafetyChecker 四级安全审查 + TOOL_PERMISSIONS 表
│   ├── tools_registry.py    ← 21 个 @tool 注册 + ALL_TOOLS + get_tools_description()
│   ├── free_tools.py        ← 5 个自由工具（run_bash/read_file/write_file/list_directory/search_files）
│   └── plugins.py           ← 用户自定义工具插件系统（~/.keeper/plugins/ 自动发现）
├── api/
│   └── server.py            ← FastAPI REST 服务（/health, /api/v1/query, /api/v1/tools 等端点）
├── core/
│   ├── agent.py             ← 经典路由器模式（降级兜底），主逻辑已拆分到 handlers/
│   ├── handlers/            ← 按功能域拆分的意图处理器
│   │   ├── inspect.py, k8s.py, docker.py, network.py, security.py
│   │   ├── fix.py, logs.py, notify.py, schedule.py, misc.py
│   ├── audit.py             ← 审计日志（JSON Lines + 自动轮转 + 大小限制）
│   └── context.py           ← ContextManager + MemoryManager + AgentState
├── nlu/
│   ├── base.py              ← IntentType 枚举（23 种意图）+ ParsedIntent
│   └── langchain_engine.py  ← LangChain LLM 引擎 + 62 个 Fast Path 正则
├── i18n/                     ← 国际化支持
│   ├── __init__.py           ← t() 翻译函数 + set_language()（KEEPER_LANG 环境变量）
│   └── packs/                ← 语言包（zh.py / en.py）
├── runbook/                  ← YAML 运维手册引擎
│   ├── executor.py          ← 加载/渲染变量/执行步骤/安全检查
│   ├── models.py            ← Runbook/RunbookStep 数据模型
│   └── templates/           ← 3 个内置模板（disk_cleanup/service_restart/log_rotate）
├── notify/                   ← 多通道通知路由
│   ├── router.py            ← NotifyRouter 按级别路由
│   ├── dingtalk.py          ← 钉钉 webhook（HMAC-SHA256 签名）
│   └── wecom.py             ← 企业微信 webhook
├── compliance/               ← CIS Benchmark 安全合规
│   ├── baseline.py          ← DriftDetector 配置基线漂移检测
│   └── cis/linux_basic.py   ← 15 项 CIS Level 1 检查
├── integrations/
│   └── prometheus.py        ← Alertmanager 客户端（查询/静默/告警摘要）
├── knowledge/
│   └── fault_patterns.yaml  ← 7 种故障模式（memory_leak/cpu_spike/disk_full 等）
├── storage/
│   └── history.py           ← SQLite 巡检历史持久化
├── tools/                   ← 底层工具实现（20 个文件）
│   ├── server.py, docker_tools.py, scanner.py, network.py
│   ├── rca.py, fixer.py, cert_monitor.py, notify.py, scheduler.py
│   ├── logs.py, reporter.py, ssh.py, alert.py
│   ├── capacity.py, comparator.py, snapshot.py, log_analyzer.py, timeline.py
│   └── k8s/                 ← K8s 子模块（client, inspector, formatter, logs, ops）
├── utils/
│   ├── logger.py            ← ContextLogger（结构化 JSON/文本日志）
│   ├── retry.py             ← with_retry 装饰器（指数退避，预定义策略）
│   ├── async_utils.py       ← 异步批量执行器（并发 ping/端口/巡检）
│   └── shutdown.py          ← ShutdownManager 优雅停机（SIGINT/SIGTERM）
├── cli.py                   ← Click + Prompt Toolkit 入口
└── config.py                ← AppConfig（环境变量 + YAML + 文件锁防并发）
```

### 安全控制（`keeper/agent/safety.py`）

四级安全检查：`READ_ONLY`（直接执行）→ `WRITE`（需确认）→ `DESTRUCTIVE`（强制确认+警告）→ `DANGEROUS`（绝对拒绝）。

每个工具在 `TOOL_PERMISSIONS` 表中预定义安全等级。`execute_shell_command` 内部有额外正则检查。

### 计划模式（`keeper/agent/planner.py`）

6 个预定义排查模板：`cpu_high`, `service_down`, `k8s_issue`, `security_audit`, `disk_full`, `network_issue`。简单任务直接执行，复杂任务（匹配 `为什么/排查/分析/全面` 等关键词）先展示计划，用户确认后执行。

### 记忆系统（`keeper/agent/memory.py`）

- 短期记忆：`AgentLoop.conversation_history`（当前会话）
- 长期记忆：`AgentMemory` 持久化到 `~/.keeper/agent_memory.json`（最近 100 条），支持按关键词搜索和主机历史查询
- 会话启动时主动将最近记忆摘要注入 LLM system prompt，提供上下文连续性

### 插件系统（`keeper/agent/plugins.py`）

用户可在 `~/.keeper/plugins/` 目录放置 `.py` 文件扩展 Keeper 能力。每个插件使用 `@tool` 装饰器定义工具，导出 `TOOLS` 列表。启动时自动扫描并合并到 Agent Loop 可用工具集中，加载失败时仅警告不中断。

### 国际化（`keeper/i18n/`）

支持中英文切换，通过 `KEEPER_LANG` 环境变量或 `set_language()` 函数设置。使用 `t("key")` 获取当前语言文本，键支持点分隔嵌套路径和模板变量替换。

### 优雅停机（`keeper/utils/shutdown.py`）

`ShutdownManager` 处理 SIGINT/SIGTERM 信号：标记正在执行的任务、保存未持久化记忆和审计日志、停止调度器。支持注册自定义清理函数。按 Ctrl+C 两次强制退出。

### 异步工具（`keeper/utils/async_utils.py`）

`AsyncBatchExecutor` + 全局复用线程池，为 API Server 和多主机批量操作提供并发支持。封装了 `async_ping_hosts`、`async_check_ports`、`async_batch_inspect`。

### 测试标记（`pytest.ini` + `tests/conftest.py`）

```bash
pytest tests/ -m "not integration"    # 仅单元测试
pytest tests/ -m integral             # 仅集成测试（依赖真实 psutil/网络/Docker）
pytest tests/ -m "not requires_llm"   # 跳过需要 LLM API Key 的测试
```

3 个自定义标记：`integration`（依赖真实系统环境）、`slow`（>5s）、`requires_llm`（需要 LLM API Key）。`conftest.py` 提供 `tmp_config_dir`、`mock_llm` 等统一 fixture。

### CLI 入口

```bash
keeper              # 默认 Agent 模式（HybridAgent）
keeper --classic     # 经典路由器模式
keeper agent        # 显式启动 Agent 模式
keeper chat         # 显式启动经典模式
```

特殊命令（交互模式内）：`/clear`, `/history`, `/tools`, `/mode`, `/memory`

其他 CLI 子命令：

```bash
keeper k8s inspect                 # K8s 集群巡检
keeper k8s logs <pod>              # Pod 日志
keeper k8s events                  # Warning 事件
keeper k8s scale <deploy> -r 5     # 扩缩容
keeper docker ls|stats|images      # Docker 管理
keeper network ping|port|dns|http  # 网络诊断
keeper cert scan|check-domain      # SSL 证书
keeper schedule list|add|remove    # 定时任务
keeper fix suggest|verify          # 自动修复
keeper notify config|test|status   # 通知推送
keeper init                        # 交互式初始化
keeper status                      # 系统状态
```

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
- LLM 依赖：需要有效的 API Key 才能测试 Agent/ NLU 功能；无 API Key 时可用 `python demo.py` 进行离线功能验证
- 漏洞扫描需要系统安装 `nmap`
- `ServerTools.inspect_server("localhost")` 无需远程连接，可用于本地测试
- K8s 客户端自动检测 kubeconfig（K3s/标准 K8s/in-cluster），无需手动配置
- Docker Compose 开发环境：`docker compose up -d` 启动 API + Prometheus + Alertmanager
- 详细功能测试说明见 `FEATURES.md`，测试报告见 `TEST_REPORT.md`
