# Keeper Agent 模式改造任务计划

> **目标：** 将 Keeper 从"路由器模式"（Intent → Handler 一对一映射）改造为"Agent 模式"（LLM 自主决策 + 多步工具调用），实现类 Claude Code 的智能运维体验。
>
> **分支：** `feature/project-improvement-plan`
>
> **预计工期：** 2-3 周

---

## 当前进度

已完成的原型代码：
- [x] `keeper/agent/__init__.py` — 模块定义
- [x] `keeper/agent/tools_registry.py` — 14 个工具注册（@tool 装饰器）
- [x] `keeper/agent/loop.py` — ReAct Agent Loop（LangGraph + 手动双模式）
- [x] `keeper/agent/hybrid.py` — 混合模式入口（Fast Path + Agent Loop）
- [x] `keeper/cli.py` — CLI 集成（`keeper` 默认 Agent，`--classic` 回退）
- [x] `docs/agent-loop-design.md` — 设计文档

---

## 第 1 步：工具层完善与测试（Day 1-2）

> **目标：** 确保所有 14 个注册工具能正确执行、错误处理健全

### 1.1 修复工具适配问题

- [ ] **检查每个 @tool 函数的 import 路径**
  - 确认 `..tools.server` / `..tools.logs` 等相对导入在 agent 模块内正确工作
  - 如有问题，改为绝对导入 `keeper.tools.xxx`

- [ ] **验证工具函数签名与 LLM Tool Use 兼容性**
  - 所有参数必须有类型注解
  - Optional 参数必须有默认值
  - 复杂类型（List/Dict）需简化为 str（LLM 不擅长构造复杂 JSON）

- [ ] **为每个工具添加错误兜底**
  - 所有工具函数 catch Exception 后返回可读错误信息
  - 不抛异常到 Agent Loop（否则循环会中断）

### 1.2 补充缺失工具

- [ ] **补充 SSH 远程巡检工具**
  ```python
  @tool
  def inspect_remote_server(host: str, username: str = "root") -> str:
      """通过 SSH 检查远程服务器状态"""
  ```

- [ ] **补充 K8s 操作工具**
  ```python
  @tool
  def k8s_scale_deployment(name: str, replicas: int, namespace: str = "default") -> str:
      """扩缩容 K8s Deployment"""

  @tool
  def k8s_restart_deployment(name: str, namespace: str = "default") -> str:
      """滚动重启 K8s Deployment"""
  ```

- [ ] **补充服务管理工具**
  ```python
  @tool
  def manage_systemd_service(service: str, action: str = "status") -> str:
      """管理 systemd 服务 (status/restart/stop/start)"""
  ```

### 1.3 工具单元测试

- [ ] **新增测试文件：`tests/test_tools_registry.py`**
  - 测试每个工具函数能正常调用（mock 外部依赖）
  - 测试错误输入时返回友好错误信息而非异常
  - 测试 `ALL_TOOLS` 列表完整性
  - 测试 `get_tools_description()` 输出格式

### 验收标准
- [ ] 所有工具函数可独立执行不报错
- [ ] `python -c "from keeper.agent.tools_registry import ALL_TOOLS; print(len(ALL_TOOLS))"` 输出工具数量
- [ ] 测试通过率 100%

---

## 第 2 步：Agent Loop 引擎完善（Day 3-4）

> **目标：** 让 ReAct 循环稳定运行，处理各种边界情况

### 2.1 LangGraph 模式完善

- [ ] **验证 LangGraph create_react_agent 能正常工作**
  - 安装 langgraph：`pip install langgraph`
  - 编写最小 smoke test 验证循环正常
  - 确认 tool_calls 正确解析和执行

- [ ] **对话历史管理优化**
  - 限制传入 LLM 的历史长度（按 token 估算，不超过 4000 token）
  - 工具调用结果过长时自动截断（>2000 字符截断 + 提示）
  - 清理敏感信息（API Key 等不要出现在历史中）

### 2.2 手动 ReAct 模式完善

- [ ] **完善循环终止条件**
  - 最大循环次数限制（10 次）
  - 单次工具调用超时控制（30s）
  - 连续调用同一工具 3 次时提示 LLM 换策略

- [ ] **添加循环状态跟踪**
  - 记录每步：工具名、参数、结果摘要、耗时
  - 在 `AgentTurn` 中保存完整执行轨迹
  - 支持通过 `get_last_tool_calls()` 查看上轮执行详情

### 2.3 降级与容错

- [ ] **LangGraph 不可用时自动降级到手动模式**
  - ImportError 时打印提示并切换
  - 手动模式不可用时（LLM 连接失败），降级到正则模式

- [ ] **工具执行失败处理**
  - 单个工具失败不中断整个循环
  - 将错误信息作为 ToolMessage 反馈给 LLM
  - LLM 可以根据错误决定换工具或放弃

- [ ] **Token 成本控制**
  - 每轮对话 token 上限（可配置，默认 8000）
  - 超限时自动截断工具输出 + 提示 LLM 总结

### 2.4 Agent Loop 测试

- [ ] **新增测试文件：`tests/test_agent_loop.py`**
  - Mock LLM 返回预设 tool_calls，验证循环正确执行
  - 测试最大循环次数限制
  - 测试工具执行失败后的恢复
  - 测试降级逻辑

### 验收标准
- [ ] 手动模式在无 langgraph 环境下正常工作
- [ ] LLM 能连续调用 3+ 个工具完成复杂任务
- [ ] 工具失败不会导致整个 Agent 崩溃
- [ ] 测试覆盖率 ≥ 80%

---

## 第 3 步：HybridAgent 集成与 CLI 完善（Day 5-6）

> **目标：** 让用户在终端中获得流畅的 Agent 体验

### 3.1 HybridAgent 完善

- [ ] **Fast Path 策略优化**
  - 明确哪些意图走 Fast Path（help/exit/confirm/clear）
  - 其他所有输入进入 Agent Loop
  - Fast Path 命中时不需要 LLM，<1ms 响应

- [ ] **降级链路完善**
  - Agent Loop 失败 → 尝试旧路由器模式 → 完全失败给友好提示
  - 记录降级原因到审计日志
  - 降级时提示用户"当前使用降级模式，功能受限"

- [ ] **审计日志集成**
  - 记录每次 Agent Loop 执行：
    - 用户输入
    - 调用了哪些工具（名称列表）
    - 总耗时
    - 最终结果（成功/失败/降级）

### 3.2 CLI 交互体验优化

- [ ] **流式输出工具调用过程**
  - 调用工具时实时显示：`🔧 调用 inspect_server(host="localhost")...`
  - 工具返回后显示耗时：`✓ 完成 (230ms)`
  - 最终答案与中间过程视觉区分

- [ ] **添加 `keeper agent --verbose` 模式**
  - 显示 LLM 完整思考过程（调试用）
  - 显示每个 tool_call 的参数和返回值

- [ ] **清空对话历史命令**
  - 在 Agent 模式中支持 `/clear` 清空上下文
  - 支持 `/history` 查看本轮工具调用记录
  - 支持 `/tools` 列出可用工具

### 3.3 与旧代码兼容

- [ ] **保留所有 CLI 子命令**
  - `keeper k8s inspect`、`keeper docker ls` 等命令不变
  - 只有交互模式（无子命令时）切换为 Agent 模式
  - `keeper --classic` 完全回退到旧行为

- [ ] **配置文件兼容**
  - 新增 `agent` 配置节（可选）：
    ```yaml
    agent:
      mode: auto          # auto / agent / classic
      max_loops: 10       # 最大循环次数
      max_tokens: 8000    # 每轮 token 上限
      verbose: false      # 是否显示详细过程
    ```

### 验收标准
- [ ] `keeper` 默认进入 Agent 模式，能正常对话
- [ ] `keeper --classic` 行为与改造前完全一致
- [ ] 工具调用过程有实时显示
- [ ] 所有旧 CLI 子命令仍可正常工作

---

## 第 4 步：System Prompt 工程与调优（Day 7-8）

> **目标：** 让 LLM 像运维专家一样思考和行动

### 4.1 System Prompt 迭代

- [ ] **基础 Prompt 完善**
  - 角色设定：资深 Linux 运维工程师
  - 工作方式：先收集数据 → 分析关联 → 给出结论
  - 安全原则：永不执行危险命令、永远先观察后行动
  - 输出格式：结构化、中文、重点标记

- [ ] **排查模式 Prompt**
  - 定义常见排查路径：
    - CPU 高 → 查进程 → 查对应服务日志 → 分析原因
    - 网络不通 → ping → DNS → 端口 → 防火墙 → 路由
    - 服务不可用 → 进程存活 → 端口监听 → 日志报错
  - 让 LLM 遵循这些路径而非乱猜

- [ ] **安全指令 Prompt**
  - 明确禁止事项：不执行 rm、不修改系统配置、不重启核心服务
  - 需要确认的事项：重启应用、清理文件、修改配置
  - 允许的事项：查看状态、读日志、网络诊断

### 4.2 Prompt 测试集

- [ ] **新增文件：`tests/test_agent_prompts.py`**
  - 10 个典型场景的输入输出验证（mock LLM）
  - 验证 LLM 不会调用危险命令
  - 验证 LLM 在信息不足时会主动调工具补充

### 4.3 Few-shot 示例

- [ ] **在 System Prompt 中加入 2-3 个示例**
  - 示例 1：CPU 高 → 展示完整排查链路
  - 示例 2：服务不可达 → 展示网络诊断链路
  - 示例 3：K8s Pod 异常 → 展示 K8s 排查链路

### 验收标准
- [ ] LLM 面对"服务器很慢"时能自主调用 3+ 个工具逐步排查
- [ ] LLM 不会生成任何危险 shell 命令
- [ ] 输出格式清晰、结构化、有总结和建议

---

## 第 5 步：Planning 能力（Day 9-10）

> **目标：** 复杂任务先展示计划 → 用户确认 → 再执行

### 5.1 执行计划生成

- [ ] **新增文件：`keeper/agent/planner.py`**
  - 功能：LLM 先生成"我打算做什么"计划
  - 格式：
    ```
    [执行计划]
    1. 检查服务器 CPU 和内存使用率
    2. 查看 Top 进程找出资源消耗大户
    3. 检查对应服务的日志
    4. 综合分析给出结论和建议

    确认执行？[Y/n]
    ```
  - 用户确认后才开始工具调用

- [ ] **计划模式开关**
  - 配置项：`agent.show_plan: true/false`
  - 简单问题（1-2 步）直接执行不展示计划
  - 复杂问题（3+ 步）先展示计划

### 5.2 执行报告

- [ ] **执行完成后生成摘要**
  - 格式：
    ```
    [执行报告]
    ✓ Step 1: inspect_server → CPU 92%, 内存 78%
    ✓ Step 2: get_top_processes → mysql 占用 85% CPU
    ✓ Step 3: query_system_logs → 发现慢查询日志
    
    [总结] MySQL 慢查询导致 CPU 飙高
    [建议] 1. 优化慢查询 SQL  2. 添加索引
    ```

### 验收标准
- [ ] 复杂问题能先展示计划再执行
- [ ] 执行完成后有结构化报告
- [ ] 用户可以拒绝计划（输入 n）

---

## 第 6 步：安全控制层（Day 11-12）

> **目标：** 确保 Agent 不会执行危险操作

### 6.1 命令安全审查

- [ ] **新增文件：`keeper/agent/safety.py`**
  - 在 `execute_shell_command` 工具中增强安全检查
  - 白名单模式：只允许已知安全命令（ps, df, free, cat, grep, journalctl...）
  - 黑名单模式：拒绝所有破坏性命令（rm, dd, mkfs, >, kill -9 1...）
  - 灰名单模式：需要用户确认的命令（systemctl restart, docker stop...）

- [ ] **操作确认机制**
  - LLM 想执行灰名单命令时，暂停循环询问用户
  - 用户确认后继续，拒绝后告知 LLM "用户拒绝了此操作"
  - 超时 30s 未确认自动取消

- [ ] **安全审计**
  - 所有被拦截的命令记录到审计日志
  - 所有执行的命令记录到审计日志
  - 支持查看"Agent 历史执行过的所有命令"

### 6.2 工具权限分级

- [ ] **为每个工具标记权限等级**
  ```python
  TOOL_SAFETY = {
      "inspect_server": "read_only",      # 只读，无需确认
      "query_system_logs": "read_only",
      "execute_shell_command": "elevated", # 提升权限，需审查
      "k8s_scale_deployment": "write",     # 写操作，需确认
  }
  ```

- [ ] **write 级别工具自动触发确认**
  - Agent 调用 write 工具前暂停
  - 显示：`⚠️ Agent 想要执行写操作：k8s_scale_deployment(replicas=5)，确认？[y/N]`

### 验收标准
- [ ] `rm -rf /` 等命令 100% 被拦截
- [ ] 写操作需要用户确认
- [ ] 审计日志记录所有命令执行

---

## 第 7 步：记忆与上下文增强（Day 13-14）

> **目标：** Agent 能记住对话上下文和历史操作

### 7.1 对话内记忆

- [ ] **优化对话历史传递**
  - 只保留最近 5 轮对话的摘要（而非完整内容）
  - 工具调用结果摘要化（而非全文）
  - 总 token 控制在 4000 以内

- [ ] **指代解析**
  - "它" → 上次提到的主机/服务
  - "再查一下" → 重复上次的工具调用
  - "那台机器" → 上下文中的 host

### 7.2 跨会话记忆

- [ ] **新增文件：`keeper/agent/memory.py`**
  - 持久化最近 N 次 Agent 执行的摘要
  - 格式：`{timestamp, user_input, tools_used, conclusion}`
  - 存储位置：`~/.keeper/agent_memory.json`
  - LLM 可通过"之前的操作记录"获取历史

### 验收标准
- [ ] 连续对话中"它"/"那台机器"等指代能正确解析
- [ ] Agent 能参考历史操作（"上次也是这个问题"）

---

## 第 8 步：端到端集成测试与文档（Day 15-16）

> **目标：** 确保改造后的系统稳定可用

### 8.1 集成测试

- [ ] **新增文件：`tests/test_agent_e2e.py`**
  - 模拟 5 个完整对话场景（mock LLM + mock 工具）
  - 场景 1：简单巡检（直接调一个工具）
  - 场景 2：多步排查（CPU 高 → 进程 → 日志）
  - 场景 3：降级场景（LLM 不可用）
  - 场景 4：安全拦截（尝试执行危险命令）
  - 场景 5：对话上下文（连续多轮）

### 8.2 性能测试

- [ ] **测量关键路径延迟**
  - Fast Path：目标 <5ms
  - Agent Loop（1 次工具调用）：目标 <5s
  - Agent Loop（3 次工具调用）：目标 <15s
  - 降级路径：目标 <100ms

### 8.3 文档更新

- [ ] **更新 README.md**
  - 新增 Agent 模式说明
  - 使用示例（复杂排查场景）
  - 配置说明

- [ ] **更新 CLAUDE.md**
  - 新增 Agent 模块说明
  - 开发指南（如何添加新工具）

- [ ] **新增 `docs/agent-guide.md`**
  - Agent 模式使用教程
  - 工具开发指南
  - Prompt 调优指南
  - 常见问题排查

### 验收标准
- [ ] 5 个 E2E 测试场景全部通过
- [ ] 文档完整覆盖新功能
- [ ] `keeper --help` 显示 Agent 模式说明

---

## 依赖变更

| 变更 | 包名 | 说明 |
|------|------|------|
| 新增 | `langgraph>=0.2.0` | Agent Loop 框架（可选，有手动兜底） |
| 已有 | `langchain>=0.3.0` | Tool Use 基础设施 |
| 已有 | `langchain-openai>=0.2.0` | LLM 调用 |

---

## 分支策略

```
feature/project-improvement-plan     ← 当前总分支
├── feature/agent-tools              ← 第 1 步：工具层
├── feature/agent-loop               ← 第 2 步：Loop 引擎
├── feature/agent-cli                ← 第 3 步：CLI 集成
├── feature/agent-prompt             ← 第 4 步：Prompt 工程
├── feature/agent-planning           ← 第 5 步：Planning
├── feature/agent-safety             ← 第 6 步：安全控制
├── feature/agent-memory             ← 第 7 步：记忆系统
└── feature/agent-testing            ← 第 8 步：测试文档
```

每步完成后合并到主分支。

---

## 里程碑

| 里程碑 | 时间 | 交付物 |
|--------|------|--------|
| M1: 工具可用 | Day 2 | 所有工具函数可独立测试通过 |
| M2: 循环可用 | Day 4 | Agent Loop 能完成多步执行 |
| M3: CLI 可用 | Day 6 | `keeper` 默认 Agent 模式可正常使用 |
| M4: 智能可用 | Day 8 | LLM 能自主排查问题 |
| M5: 安全可用 | Day 12 | 危险操作 100% 拦截 |
| M6: 发布就绪 | Day 16 | 测试通过 + 文档完整 |

---

## 使用方式预览

改造完成后的使用效果：

```bash
# 默认 Agent 模式
$ keeper
keeper🤖> 服务器最近很慢，帮我看看

🤔 分析中...
  🔧 调用 inspect_server(host="localhost")... ✓ (320ms)
  🔧 调用 get_top_processes(n=10)... ✓ (150ms)
  🔧 调用 query_system_logs(unit="mysql", since="1h", priority="err")... ✓ (280ms)

[分析报告]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
问题：MySQL 慢查询导致 CPU 飙升

证据：
  1. CPU 使用率 92%，主要被 mysqld 进程占用 (85%)
  2. 最近 1 小时 mysql 错误日志中出现 342 条 slow query
  3. 内存 78%，磁盘 65%，其他指标正常

建议：
  1. 立即：kill 长时间运行的查询 (SHOW PROCESSLIST)
  2. 短期：检查慢查询日志定位具体 SQL，添加索引
  3. 长期：考虑读写分离或查询缓存
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

keeper🤖> 帮我看看具体是哪个 SQL 慢

  🔧 调用 execute_shell_command(command="mysqladmin processlist")... ✓
  🔧 调用 read_log_file(file_path="/var/log/mysql/slow-query.log", lines=20)... ✓

[结果] 最慢的查询是: SELECT * FROM orders WHERE status='pending' (执行 45s)
[建议] 为 orders.status 字段添加索引

# 经典模式（回退）
$ keeper --classic
keeper> 检查本机
[✓] 服务器健康检查 - localhost ...
```

---

*文档创建时间：2026-05-15*
*当前状态：待执行*
