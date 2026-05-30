# Keeper 项目代码审查报告

> 审查时间: 2026-05-30 | 版本: v1.1.0 | 分支: dev

---

## 一、项目功能全景（从使用角度）

### 1. 两种运行模式

| 模式 | 启动方式 | 原理 | 适用场景 |
|------|---------|------|---------|
| **Agent 模式**（默认） | `keeper` | LLM 自主决策 + 多步工具调用（ReAct Loop） | 复杂排查、自由操作 |
| **经典模式** | `keeper --classic` | 正则/LLM 意图识别 + 单步路由分发 | 确定性指令、无 LLM 环境 |

### 2. 核心功能模块

#### A. 服务器巡检
- 本地巡检：`keeper run 检查本机` - 采集 CPU/内存/磁盘/负载/Top 进程
- 远程巡检：`keeper run 检查 192.168.1.100` - 通过 SSH 采集
- 批量巡检：`keeper run 批量巡检` - 从 `/etc/hosts` 读取主机列表，并行采集

#### B. K8s 集群管理
- 集群巡检、Pod 日志、扩缩容、滚动重启、Pod 内执行命令

#### C. Docker 管理
- 容器列表/状态、容器日志、镜像管理、清理无用镜像

#### D. 网络诊断
- Ping、端口检测、DNS 查询、HTTP 检查

#### E. 安全扫描
- nmap 端口扫描、SSL/TLS 证书检查

#### F. 自动修复
- 根因分析(RCA) + 修复建议生成 + 用户确认后执行

#### G. Runbook 标准化运维
- 3 个内置 Runbook（磁盘清理、服务重启、日志轮转）
- 用户可自定义 YAML Runbook，动态注册为 LLM 工具

#### H. 定时任务
- Cron 表达式调度，支持定期巡检

#### I. 通知
- 飞书/钉钉/企业微信 Webhook 推送巡检结果

#### J. 记忆系统
- 短期记忆（对话内上下文）
- 长期记忆（JSON 持久化，跨会话回溯）
- 巡检历史（SQLite，支持趋势分析/容量预测）

---

## 二、端到端流程分析

### 流程一：Agent 模式启动 → 用户对话 → 工具调用 → 返回结果

```
用户执行 `keeper`
  → cli.py:cli() → 无子命令 → start_agent_chat()
  → AppConfig.from_env() → 加载 ~/.keeper/config.yaml
  → 检查 LLM 配置 → 未配置则进入交互式引导
  → HybridAgent(config) 创建
  → REPL 循环：prompt_toolkit 读取输入
  → agent.process(user_input)
    → 退出检测
    → 斜杠命令检测 (/clear, /tools, /memory...)
    → Fast Path: _try_fast_match() 正则匹配
    → Agent Loop: AgentLoop.run(augmented_input)
      → LangGraph create_react_agent 或 手动 ReAct
      → LLM 决策调用哪个工具
      → 执行工具 → 返回结果 → LLM 分析 → 是否需要更多信息
      → 循环直到给出最终答案
    → 记录审计日志
    → 保存到长期记忆
    → 返回给用户
```

**端到端可行性：** ✅ 流程完整可走通，前提是 LLM API 配置正确。

### 流程二：经典模式启动 → 意图解析 → Handler 分发

```
用户执行 `keeper --classic`
  → cli.py:cli(classic=True) → start_chat()
  → LangChainEngine 创建（延迟加载 LLM）
  → Agent(nlu_engine, config) 经典 Agent 创建
  → REPL 循环
  → agent.process(user_input)
    → nlu.parse(user_input) → 快速路径 / LLM 解析
    → 返回 ParsedIntent(intent, entities)
    → _dispatch(parsed) → handlers 映射表路由
    → handle_inspect / handle_scan / handle_k8s_inspect / ...
    → 记录审计 + 记忆 + 自动通知
```

**端到端可行性：** ✅ 流程完整。快速路径（正则匹配）不依赖 LLM，可以离线工作。

### 流程三：单命令执行

```
用户执行 `keeper run 检查 192.168.1.100`
  → cli.py:run(command=("检查", "192.168.1.100"))
  → 构建 user_input = "检查 192.168.1.100"
  → HybridAgent.process(user_input)
  → 直接输出结果并退出
```

**端到端可行性：** ✅ 可走通。

### 流程四：K8s 命令行操作

```
用户执行 `keeper k8s inspect -n kube-system`
  → cli.py:k8s_inspect(namespace="kube-system")
  → _get_k8s_modules() → 导入 K8s SDK
  → K8sClient(config).connect()
  → K8sInspector.inspect_cluster()
  → format_cluster_report()
```

**端到端可行性：** ✅ 前提是 `kubernetes` SDK 已安装且 kubeconfig 可用。

### 流程五：Runbook 执行

```
Agent 模式中用户说 "磁盘满了帮我清理"
  → LLM 选择调用 runbook_disk_cleanup 工具
  → RunbookExecutor.load_from_yaml("disk_cleanup.yaml")
  → executor.execute(runbook, variables)
    → 遍历 steps → _safety_check → _render_variables → _execute_command
    → 确认步骤等待 confirm_callback
    → 检查 expect 表达式
    → 生成执行摘要
```

**端到端可行性：** ⚠️ 部分可行。Agent 模式下 `RunbookExecutor` 的 `confirm_callback` 使用默认值 `lambda _: True`（自动确认），需要确认的步骤会被自动执行，安全依赖于 `_safety_check` 黑名单。

---

## 三、端到端不通的关键问题

### 问题 1: LangGraph 模式下 WRITE 级别工具缺乏确认机制 ❌

**现象：** 在手动 ReAct 模式中，`is_tool_auto_allowed()` 会检查工具安全等级，WRITE 级别工具会返回"需用户确认"消息。但在 LangGraph 模式（`_run_langgraph`）中，没有这层检查。`create_react_agent` 会直接执行所有绑定的工具。

**对比：**

| | 手动 ReAct 模式 | LangGraph 模式 |
|---|---|---|
| `is_tool_auto_allowed` 检查 | ✅ 有 | ❌ 无 |
| `CommandSafetyChecker` (run_bash 内部) | ✅ 有 | ✅ 有 |
| `FixSuggester` (execute_shell_command 内部) | ✅ 有 | ✅ 有 |
| 工具级权限过滤 (permission_mode) | ✅ 有 | ✅ 有 |

**影响：** `write_file`、`manage_systemd_service(action=restart)` 等在 LangGraph 模式下无确认即执行。`run_bash` 和 `execute_shell_command` 有内部黑名单所以影响较小。

**建议修复：** 在 LangGraph 的工具绑定层添加安全 wrapper，或使用 LangGraph 的 interrupt 机制实现确认流。

---

### 问题 2: `install_runbook` 工具未注册到 ALL_TOOLS ❌

**现象：** `tools_registry.py` 中定义了 `@tool def install_runbook(...)`，但未将其加入 `ALL_TOOLS` 列表。

**影响：** LLM 在 Agent 模式下看不到这个工具，无法通过对话安装自定义 Runbook。README 中宣传的"Agent 对话中安装 Runbook"功能实际不可用。

**建议修复：** 在 `ALL_TOOLS` 列表末尾添加 `install_runbook`。

---

### 问题 3: Agent 模式无定时任务能力 ❌

**现象：** `TaskScheduler` 仅在经典模式的 `Agent.__init__()` 中创建和启动。`HybridAgent` 中没有调度器，也没有对应的 LLM 工具。

**影响：** Agent 模式下用户说"帮我设个定时任务"，LLM 没有工具可调用来实现此功能。

**建议修复：** 将 `TaskScheduler` 集成到 `HybridAgent`，或创建一个 `schedule_task` 工具注册到 `ALL_TOOLS`。

---

### 问题 4: 上下文注入 5 分钟 TTL 导致多轮对话内上下文过期

**现象：** `ContextInjector` 使用 5 分钟缓存 TTL。LangGraph Agent 的 system prompt 在创建时固化。只有 `is_stale()` 返回 True（5 分钟后）且有新请求时才重建 Agent。

**影响：** 5 分钟内的多轮对话中，LLM 看到的主机上下文和记忆摘要是第一轮时的快照，不会随对话推进而更新。

**建议：** 可接受的设计取舍。如需改进，可在每轮对话时将上下文作为用户消息注入而非 system prompt。

---

### 问题 5: 首次对话记忆双重注入

**现象：** `HybridAgent.process()` 首次对话时：
1. 调用 `context_injector.collect()` 收集上下文（内部有 `_collect_memory_summary()`）
2. 又手动从 `memory.get_recent(3)` 构建记忆摘要注入到 `augmented_input`

**影响：** 记忆信息被重复注入（一次在 system prompt 中，一次在用户消息中），增加 token 消耗，可能造成 LLM 混淆。

**建议修复：** 去掉 `hybrid.py` 中的手动记忆注入，完全依赖 `ContextInjector`。

---

### 问题 6: `execute_shell_command` 和 `run_bash` 功能重复

**现象：** 两个工具功能几乎相同（执行 Shell 命令），但安全检查机制不同：
- `execute_shell_command` 使用 `FixSuggester.classify_command_safety`
- `run_bash` 使用 `CommandSafetyChecker.check`

**影响：** `tool_mode="all"` 时 LLM 看到两个相似工具，可能选择困难或行为不一致。

**建议：** 文档化两者区别（`execute_shell_command` 面向结构化工具场景，`run_bash` 面向自由模式），或合并为一个统一实现。

---

## 四、可以正常走通的流程 ✅

1. **本地服务器巡检** - 不依赖外部，psutil 采集 → 格式化报告
2. **网络诊断（ping/port/dns）** - subprocess 调用系统命令
3. **审计日志查询** - 本地 JSON Lines 文件读取
4. **巡检历史存储和查询** - SQLite 读写
5. **配置管理** - YAML 文件读写
6. **Fast Path 正则匹配** - 帮助/退出等确定性指令
7. **Agent 模式基本对话** - LLM API 可用时完整 ReAct 循环
8. **Runbook 执行（内置）** - YAML 加载 + Shell 执行
9. **优雅停机** - 信号处理 + 清理回调
10. **记忆系统** - 跨会话 JSON 持久化 + 加载

---

## 五、存在问题需注意的流程 ⚠️

1. **LangGraph 模式安全层缺失** - WRITE 级别工具无确认即执行
2. **`install_runbook` 不可调用** - 未注册到 ALL_TOOLS
3. **Agent 模式无定时任务** - 调度器仅在经典模式中初始化
4. **上下文注入 5 分钟 TTL** - 多轮对话内上下文可能过期
5. **首次对话记忆双重注入** - ContextInjector 和 HybridAgent 各注入一次
6. **远程 SSH 巡检** - 需要预配置免密登录，失败时走引导流程

---

## 六、完全不通的流程 ❌

1. **Agent 对话中安装 Runbook** - `install_runbook` 未暴露给 LLM
2. **Agent 模式设置定时任务** - 无工具/无调度器
3. **LangGraph 模式下的写操作确认** - 绕过了安全层

---

## 七、已修复的问题（本次 PR）

| 优先级 | 问题 | 修复方式 |
|--------|------|---------|
| P0 | `keeper --version` 输出 `1.0.0`（应为 `1.1.0`） | 修正 `cli.py` 版本号 |
| P0 | CLAUDE.md 中 `MAX_OUTPUT_LEN=3000` 与代码不符 | 修正为 2000 |
| P1 | `keeper logs` 命令强制要求 API Key | 移除检查，直接使用 `AuditLogger()` |
| P1 | `ToolMeta.tags` 类型注解 `list` 与实际使用 `tuple` 不一致 | 修正为 `tuple` |
| P1 | README/CLAUDE.md 工具数量过时 | 更新为 28+ |
| P1 | memory-roadmap.md 中 InspectionHistory 状态标记错误 | 标记为已实现 |

---

## 八、后续建议修复优先级

### P0（安全相关，应尽快修复）
- [ ] LangGraph 模式添加工具安全 wrapper
- [ ] `install_runbook` 注册到 `ALL_TOOLS`

### P1（功能完整性）
- [ ] Agent 模式集成定时任务调度器
- [ ] 去除首次对话记忆双重注入
- [ ] Runbook 执行器在 Agent 模式下添加真实确认机制

### P2（代码质量）
- [ ] 统一 `execute_shell_command` 和 `run_bash` 的安全检查机制
- [ ] `AskUserQuestion.options` 和 `AskUserResult.questions` 类型注解修正
- [ ] LangGraph 模式 `duration_ms` 计时
- [ ] `HybridAgent._handle_slash_command` 清理未使用的 CommandRegistry 导入
