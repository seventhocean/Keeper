# Keeper 项目完善任务规划

> **目标：** 将 Keeper 从"功能演示"级别提升为"生产就绪"的智能运维 Agent
>
> **时间规划：** 4 个阶段，共 6-8 周
>
> **分支：** `feature/project-improvement-plan`

---

## 总体策略

```
阶段 1：工程化基础加固    （第 1 周）    — 必做，否则面试减分
阶段 2：功能闭环补全      （第 2-3 周）  — 核心差异化
阶段 3：智能化升级        （第 4-5 周）  — 亮点展示
阶段 4：生产级特性        （第 6-8 周）  — 加分项
```

---

## 阶段 1：工程化基础加固（第 1 周）

> **目标：** 让项目看起来像"生产级项目"而不是"课程作业"

### 1.1 安全加固

- [ ] **API Key 安全存储**
  - 新增文件：`keeper/security.py`
  - 集成 Python `keyring` 库，优先从系统密钥链读取
  - 配置文件自动设置 0600 权限
  - 支持 `keeper config set --api-key` 时自动存入 keyring
  - 保留环境变量兜底方式

- [ ] **输入参数校验**
  - 新增文件：`keeper/validators.py`
  - IP 地址格式校验（IPv4/IPv6）
  - hostname 白名单字符校验（防止命令注入）
  - command 参数黑名单检查（`; | & $() \`\`` 等）
  - port 范围校验 (1-65535)
  - 在 Agent 层统一调用校验

- [ ] **操作确认机制增强**
  - 修改文件：`keeper/core/agent.py`
  - 危险操作（DESTRUCTIVE 级别）强制二次确认
  - 确认超时 30s 自动取消
  - 记录用户确认/拒绝到审计日志

### 1.2 错误处理与容错

- [ ] **统一异常体系**
  - 新增文件：`keeper/exceptions.py`
  - 定义异常层次：
    ```
    KeeperError (基类)
    ├── ConfigError          — 配置错误
    ├── ConnectionError      — 连接失败 (SSH/K8s/LLM)
    ├── TimeoutError         — 操作超时
    ├── PermissionError      — 权限不足
    ├── ValidationError      — 输入校验失败
    ├── ToolExecutionError   — 工具执行失败
    └── NLUError             — NLU 解析异常
    ```

- [ ] **统一重试机制**
  - 新增文件：`keeper/utils/retry.py`
  - 基于 `tenacity` 实现装饰器
  - 默认策略：指数退避，最多 3 次，间隔 1s/2s/4s
  - 可配置：重试次数、间隔、异常白名单
  - 应用于：LLM 调用、SSH 连接、K8s API

- [ ] **LLM 降级模式**
  - 修改文件：`keeper/nlu/langchain_engine.py`
  - LLM 调用失败时自动切换纯正则模式
  - 在回复中提示用户"[降级模式] LLM 不可用，使用规则引擎"
  - 记录降级事件到日志

- [ ] **超时配置统一化**
  - 修改文件：`keeper/config.py`
  - 新增 `timeouts` 配置节：
    ```yaml
    timeouts:
      ssh: 30
      k8s: 30
      llm: 60
      network: 10
    ```
  - 各工具从配置读取超时值

### 1.3 测试与 CI

- [ ] **NLU 正则路径测试**
  - 新增文件：`tests/test_nlu_fast_path.py`
  - 覆盖所有 30+ 正则模式的正例测试
  - 反例测试（不应该匹配的输入）
  - 边界情况测试（空输入、超长输入、特殊字符）
  - 目标：正则路径 100% 覆盖

- [ ] **Agent 调度逻辑测试**
  - 新增文件：`tests/test_agent_dispatch.py`
  - Mock NLU 引擎，验证各意图正确路由到 handler
  - 测试上下文传递（host 指代解析）
  - 测试确认流程（pending_task 状态机）
  - 测试错误处理路径

- [ ] **输入校验测试**
  - 新增文件：`tests/test_validators.py`
  - 合法 IP/hostname 测试
  - 命令注入 payload 拦截测试
  - 边界值测试

- [ ] **GitHub Actions CI**
  - 新增文件：`.github/workflows/ci.yml`
  - 触发条件：push + PR
  - 步骤：lint (flake8) → test (pytest) → coverage report
  - Python 版本矩阵：3.9, 3.10, 3.11, 3.12
  - 覆盖率门槛：≥ 70%

### 1.4 可观测性

- [ ] **结构化日志**
  - 新增文件：`keeper/utils/logger.py`
  - 集成 `structlog` 或标准 `logging` + JSON formatter
  - 统一日志格式：`{timestamp, level, module, message, context}`
  - 日志级别可通过配置 / 环境变量控制
  - 各模块替换 print → logger

- [ ] **审计日志轮转**
  - 修改文件：`keeper/core/audit.py`
  - 按天轮转：`audit-2026-05-15.log`
  - 自动压缩 7 天前的日志（gzip）
  - 可配置保留天数（默认 90 天）
  - 启动时自动清理过期日志

- [ ] **keeper status 自检增强**
  - 修改文件：`keeper/cli.py`
  - 检查项：
    - Python 版本
    - 配置文件是否存在且可读
    - LLM API 连通性（发送 ping 请求）
    - SSH 密钥是否配置
    - K8s 集群是否可达
    - 磁盘空间（~/.keeper/ 目录）
  - 输出格式：`[OK] / [WARN] / [FAIL]` 彩色状态

### 阶段 1 验收标准

- [ ] `pytest tests/ -v` 全绿，覆盖率 ≥ 70%
- [ ] GitHub Actions CI 配置完成并通过
- [ ] API Key 不再明文出现在配置文件中
- [ ] LLM 不可用时不会崩溃，自动降级到正则模式
- [ ] 输入 `; rm -rf /` 等注入 payload 被拦截

---


## 阶段 2：功能闭环补全（第 2-3 周）

> **目标：** 从"数据查看器"升级为"发现 → 分析 → 修复 → 验证"完整闭环

### 2.1 巡检历史与趋势对比

- [ ] **巡检数据持久化**
  - 新增文件：`keeper/storage/__init__.py`
  - 新增文件：`keeper/storage/history.py`
  - 使用 SQLite 存储巡检快照（零依赖）
  - 表结构：`inspections(id, host, timestamp, cpu, memory, disk, load, raw_json)`
  - 每次巡检自动写入
  - 提供查询接口：按时间范围、按主机

- [ ] **历史对比分析**
  - 新增文件：`keeper/tools/comparator.py`
  - 功能：
    - 与上次巡检对比（逐指标 diff + 箭头标识）
    - 与 N 天前对比
    - 过去 7 天趋势摘要（均值/峰值/增长率）
  - 异常检测：指标单日涨幅超过阈值时告警
  - NLU 集成："对比昨天" / "最近一周趋势" 触发

- [ ] **容量预测**
  - 新增文件：`keeper/tools/capacity.py`
  - 基于最近 N 天数据做线性回归
  - 预测磁盘/内存何时达到阈值
  - 输出："按当前增速，磁盘将在 X 天后达到 90%"
  - 自动在巡检报告中附加预测结果

- [ ] **对比测试**
  - 新增文件：`tests/test_comparator.py`
  - 测试对比逻辑正确性
  - 测试边界情况（无历史数据、单条记录）

### 2.2 Runbook 引擎

- [ ] **Runbook 数据模型**
  - 新增文件：`keeper/runbook/__init__.py`
  - 新增文件：`keeper/runbook/models.py`
  - 数据结构：
    ```python
    @dataclass
    class RunbookStep:
        name: str
        action: str          # shell / k8s / check
        command: str
        type: SafetyLevel    # safe / caution / destructive
        confirm: bool        # 是否需要人工确认
        timeout: int         # 超时秒数
        expect: str          # 预期结果表达式
        on_fail: str         # notify / abort / rollback
        rollback: str        # 回滚命令

    @dataclass
    class Runbook:
        name: str
        description: str
        trigger: str         # 触发条件表达式
        variables: Dict
        steps: List[RunbookStep]
    ```

- [ ] **Runbook 执行引擎**
  - 新增文件：`keeper/runbook/executor.py`
  - 功能：
    - YAML 文件加载与校验
    - 变量模板渲染 (`{{variable}}`)
    - 顺序执行各步骤
    - 确认步骤暂停等待用户输入
    - 预期检查（expect 表达式匹配）
    - 失败时按 on_fail 策略处理
    - 执行结果记录（每步耗时、输出、状态）
  - 安全控制：
    - 执行前整体安全审查
    - DANGEROUS 级别命令直接拒绝
    - DESTRUCTIVE 级别强制确认

- [ ] **内置 Runbook 模板**
  - 新增目录：`keeper/runbook/templates/`
  - 模板列表：
    - `disk_cleanup.yaml` — 磁盘空间清理
    - `service_restart.yaml` — 服务安全重启（检查→重启→验证）
    - `log_rotate.yaml` — 日志轮转
    - `k8s_pod_restart.yaml` — K8s Pod 重启
    - `memory_leak_check.yaml` — 内存泄漏排查

- [ ] **CLI 集成**
  - 修改文件：`keeper/cli.py`
  - 新增子命令：
    - `keeper runbook list` — 列出可用 Runbook
    - `keeper runbook run <name>` — 执行指定 Runbook
    - `keeper runbook show <name>` — 查看 Runbook 详情
    - `keeper runbook create` — 交互式创建 Runbook
  - NLU 集成：
    - 新增意图 `RUNBOOK` 
    - "执行磁盘清理流程" / "运行 disk_cleanup"

- [ ] **Runbook 测试**
  - 新增文件：`tests/test_runbook.py`
  - 测试 YAML 解析
  - 测试执行引擎（mock shell 命令）
  - 测试失败回滚逻辑
  - 测试安全拦截

### 2.3 修复闭环完善

- [ ] **执行前状态快照**
  - 新增文件：`keeper/tools/snapshot.py`
  - 自动备份项目：
    - iptables 规则 (`iptables-save`)
    - systemd 服务状态
    - 关键配置文件 hash
    - 网络连接状态 (`ss -tlnp`)
  - 存储位置：`~/.keeper/snapshots/<timestamp>/`
  - 保留最近 10 次快照

- [ ] **修复后自动验证**
  - 修改文件：`keeper/tools/fixer.py`
  - 每个 FixSuggestion 增加 `verify_command` 字段
  - 执行修复后自动运行验证命令
  - 验证通过 → 标记成功
  - 验证失败 → 提示用户是否执行回滚

- [ ] **自动回滚触发**
  - 修改文件：`keeper/tools/fixer.py`
  - 验证失败时：
    1. 自动恢复快照中的配置
    2. 执行 rollback 命令
    3. 再次验证恢复是否成功
  - 记录回滚事件到审计日志

- [ ] **修复历史记录**
  - 新增文件：`keeper/storage/fix_history.py`
  - 记录：时间、问题描述、修复命令、执行结果、验证结果
  - 重复问题检测："此问题在过去 N 天内出现过 X 次"
  - 建议根本性修复方案

### 2.4 日志智能分析

- [ ] **错误日志聚合**
  - 新增文件：`keeper/tools/log_analyzer.py`
  - 功能：
    - 按错误模式分组（正则提取错误签名）
    - 统计各模式出现频次
    - 排序输出 Top N
    - 时间分布分析（错误集中在哪个时段）

- [ ] **异常模式检测**
  - 修改文件：`keeper/tools/log_analyzer.py`
  - 检测项：
    - 日志量突增（与基线对比 >3 倍）
    - 新错误类型出现（之前从未见过的错误）
    - 错误率突升（ERROR 占比变化）
  - 输出告警建议

- [ ] **NLU 意图扩展**
  - 修改文件：`keeper/nlu/base.py` — 新增 `LOG_ANALYSIS` 意图
  - 修改文件：`keeper/nlu/langchain_engine.py` — 新增正则模式
  - 修改文件：`keeper/core/agent.py` — 新增 `_handle_log_analysis` handler
  - 触发语句："分析错误日志" / "最近有什么异常日志" / "日志分析"

### 阶段 2 验收标准

- [ ] 巡检结果自动持久化到 SQLite
- [ ] 支持 "对比昨天" 自然语言查询，输出指标对比
- [ ] 至少 3 个内置 Runbook 可加载并模拟执行
- [ ] 修复操作有完整的"快照 → 执行 → 验证 → 回滚"链路
- [ ] 日志分析能输出 Top N 错误模式 + 异常检测

---


## 阶段 3：智能化升级（第 4-5 周）

> **目标：** 展示"AI + 运维"的真正价值，面试核心亮点

### 3.1 RCA 增强 — 事件时间线

- [ ] **事件时间线构建**
  - 新增文件：`keeper/tools/timeline.py`
  - 数据源采集：
    - K8s Events (Warning/Normal)
    - Deployment 变更历史 (rollout history)
    - 系统日志中的关键事件 (OOM/重启/崩溃)
    - 告警触发记录
    - 配置变更记录（文件修改时间）
  - 统一时间轴输出：按时间排列所有事件
  - 支持时间范围过滤："最近 1 小时" / "今天"

- [ ] **因果关系推理**
  - 修改文件：`keeper/tools/rca.py`
  - 构建关联规则：
    - 时间邻近性（事件 A 发生后 N 分钟内事件 B 发生）
    - 因果模板（部署 → OOM → 扩容 → 资源不足）
    - 资源竞争关系（CPU 高 + 负载高 → 进程争抢）
  - LLM 增强：将时间线 + 关联规则输入 LLM 生成诊断报告
  - 输出结构：根因 → 影响链 → 修复建议

- [ ] **故障知识库**
  - 新增文件：`keeper/knowledge/__init__.py`
  - 新增文件：`keeper/knowledge/fault_patterns.yaml`
  - 格式：
    ```yaml
    patterns:
      - name: memory_leak
        symptoms:
          - "内存使用率持续增长"
          - "OOM Killed"
          - "RSS 单调递增"
        possible_causes:
          - "应用未释放连接/缓存"
          - "Go routine 泄漏"
          - "Java 堆外内存泄漏"
        fix_suggestions:
          - "重启服务（临时）"
          - "分析 heap dump"
          - "检查连接池配置"
    ```
  - RCA 引擎自动匹配知识库模式
  - 支持用户自定义追加模式

- [ ] **RCA 测试**
  - 新增文件：`tests/test_rca_timeline.py`
  - 测试时间线排序
  - 测试因果关联匹配
  - 测试知识库模式匹配

### 3.2 Prometheus 告警集成

- [ ] **Alertmanager 客户端**
  - 新增文件：`keeper/integrations/__init__.py`
  - 新增文件：`keeper/integrations/prometheus.py`
  - 功能：
    - 查询活跃告警 (`/api/v2/alerts`)
    - 查询告警历史
    - 创建/删除静默规则 (`/api/v2/silences`)
    - 告警分组统计
  - 配置：
    ```yaml
    integrations:
      prometheus:
        alertmanager_url: "http://localhost:9093"
        username: ""
        password: ""
    ```

- [ ] **告警聚合分析**
  - 修改文件：`keeper/integrations/prometheus.py`
  - 分析功能：
    - Top N 最频繁告警
    - 告警风暴检测（短时间大量触发）
    - 告警趋势（今天 vs 昨天）
    - 长期未解决告警标记

- [ ] **告警 → RCA 联动**
  - 修改文件：`keeper/core/agent.py`
  - 逻辑：收到告警查询后，自动建议执行 RCA
  - 示例："有 3 个活跃告警 → 是否进行根因分析？"

- [ ] **NLU 意图扩展**
  - 修改文件：`keeper/nlu/base.py` — 新增 `ALERT_QUERY` 意图
  - 触发语句："查看告警" / "有什么告警" / "静默 xxx 告警"

### 3.3 配置漂移检测

- [ ] **配置基线定义**
  - 新增文件：`keeper/compliance/__init__.py`
  - 新增文件：`keeper/compliance/baseline.py`
  - 基线格式 (YAML)：
    ```yaml
    baselines:
      nginx:
        files:
          - path: /etc/nginx/nginx.conf
            checks:
              - type: contains
                value: "worker_processes auto"
              - type: not_contains
                value: "server_tokens on"
        services:
          - name: nginx
            state: running
            enabled: true
      sshd:
        files:
          - path: /etc/ssh/sshd_config
            checks:
              - type: contains
                value: "PermitRootLogin no"
              - type: contains
                value: "PasswordAuthentication no"
    ```

- [ ] **漂移检测引擎**
  - 新增文件：`keeper/compliance/drift.py`
  - 功能：
    - 加载基线定义
    - 检查实际文件内容 vs 基线期望
    - 检查服务状态 vs 基线期望
    - 输出漂移报告（哪些项不符合基线）
  - 支持本地 + SSH 远程检测

- [ ] **多机一致性检查**
  - 修改文件：`keeper/compliance/drift.py`
  - 功能：对比 N 台机器的同一配置文件
  - 输出：哪些机器与"多数"不一致
  - 示例："3 台 nginx 中，node-2 的 worker_connections 不同"

- [ ] **CIS Benchmark 基础**
  - 新增目录：`keeper/compliance/cis/`
  - 新增文件：`keeper/compliance/cis/linux_basic.py`
  - 实现 10-15 项基础安全检查：
    - SSH 配置安全性
    - 文件权限 (/etc/passwd, /etc/shadow)
    - 不必要的服务检测
    - 防火墙状态
    - 密码策略

### 3.4 通知渠道扩展

- [ ] **Notifier 抽象接口**
  - 新增文件：`keeper/notify/__init__.py`
  - 新增文件：`keeper/notify/base.py`
  - 统一接口：
    ```python
    class BaseNotifier(ABC):
        @abstractmethod
        def send_text(self, text: str) -> bool: ...
        @abstractmethod
        def send_rich(self, title: str, sections: List) -> bool: ...
        @abstractmethod
        def test_connection(self) -> bool: ...
    ```

- [ ] **飞书通知重构**
  - 新增文件：`keeper/notify/feishu.py`
  - 从 `keeper/tools/notify.py` 迁移，实现 `BaseNotifier`
  - 保持向后兼容

- [ ] **钉钉通知**
  - 新增文件：`keeper/notify/dingtalk.py`
  - 钉钉群机器人 Webhook
  - 支持签名验证 (HmacSHA256)
  - 支持 text / markdown / actionCard 消息

- [ ] **企业微信通知**
  - 新增文件：`keeper/notify/wecom.py`
  - 企微群机器人 Webhook
  - 支持 text / markdown / image 消息

- [ ] **通知路由**
  - 新增文件：`keeper/notify/router.py`
  - 按告警级别路由到不同渠道
  - 配置：
    ```yaml
    notifications:
      routes:
        - level: critical
          channels: [feishu, dingtalk]
        - level: warning
          channels: [feishu]
        - level: info
          channels: []  # 不推送
    ```

### 阶段 3 验收标准

- [ ] RCA 能自动构建事件时间线并输出因果分析
- [ ] 支持查询 Prometheus Alertmanager 告警（mock 或真实）
- [ ] 配置漂移检测至少支持 nginx + sshd 基线
- [ ] CIS Benchmark 至少实现 10 项安全检查
- [ ] 通知渠道支持飞书 + 钉钉 + 企微（≥ 3 种）

---


## 阶段 4：生产级特性（第 6-8 周）

> **目标：** 展示系统设计能力和产品思维

### 4.1 多集群 / 资产管理

- [ ] **CMDB 轻量版**
  - 新增文件：`keeper/cmdb/__init__.py`
  - 新增文件：`keeper/cmdb/models.py`
  - 资产类型：Host、K8sCluster、Service
  - SQLite 持久化
  - CLI：`keeper asset add/list/remove/tag`

- [ ] **资产自动发现**
  - 新增文件：`keeper/cmdb/discovery.py`
  - 功能：
    - 网段扫描发现存活主机 (nmap -sn)
    - K8s 集群枚举（多 kubeconfig）
    - 服务端口指纹识别
  - 发现结果自动注册到 CMDB

- [ ] **多集群统一视图**
  - 新增文件：`keeper/tools/k8s/multi_cluster.py`
  - 功能：
    - 并行连接多个集群
    - 跨集群异常 Pod 汇总
    - 跨集群资源使用率对比
  - 触发："所有集群状态" / "哪个集群有问题"

### 4.2 变更管理

- [ ] **变更工单模型**
  - 新增文件：`keeper/change/__init__.py`
  - 新增文件：`keeper/change/models.py`
  - 字段：变更类型、描述、影响范围、执行窗口、审批状态、执行人
  - 变更类型：standard（标准）、normal（普通）、emergency（紧急）

- [ ] **变更执行引擎**
  - 新增文件：`keeper/change/executor.py`
  - 流程：
    1. pre-check（前置检查：服务健康、备份完成）
    2. 灰度执行（先 1 台 → 确认 → 全量）
    3. post-check（后置验证：服务正常、指标无异常）
    4. 完成/回滚决策
  - 灰度策略：canary (1台) → batch (25%) → full (100%)

- [ ] **变更回滚**
  - 新增文件：`keeper/change/rollback.py`
  - 支持：
    - 配置回滚（从快照恢复）
    - K8s 回滚（rollout undo）
    - 服务版本回滚
  - 回滚触发条件：post-check 失败自动触发

- [ ] **变更审批**
  - 修改文件：`keeper/change/models.py`
  - normal/emergency 变更需要审批
  - 审批方式：CLI 确认 / 飞书消息确认
  - 超时未审批自动取消

### 4.3 异步与性能

- [ ] **asyncio 批量巡检**
  - 新增文件：`keeper/tools/async_server.py`
  - 基于 `asyncio` + `asyncssh` 实现
  - 支持 100+ 主机并发巡检
  - 并发控制：信号量限制最大并发数（默认 20）
  - 进度显示：`[23/100] 巡检中...`

- [ ] **连接池管理**
  - 新增文件：`keeper/utils/pool.py`
  - SSH 连接池：复用连接，避免重复握手
  - K8s 客户端池：多集群客户端缓存
  - 连接过期/健康检查机制

- [ ] **性能基准测试**
  - 新增文件：`tests/benchmark/test_performance.py`
  - 测试项：
    - NLU 正则路径延迟 (目标 <1ms)
    - 单机巡检延迟 (目标 <3s)
    - 10/50/100 主机并发巡检耗时
  - 结果输出：表格 + 是否达标

### 4.4 容器化与部署

- [ ] **Dockerfile**
  - 新增文件：`Dockerfile`
  - 多阶段构建：
    - builder 阶段：安装依赖
    - runtime 阶段：最小基础镜像 (python:3.11-slim)
  - 包含必要工具：nmap、ssh-client、kubectl
  - 非 root 用户运行

- [ ] **docker-compose**
  - 新增文件：`docker-compose.yml`
  - 服务：keeper (CLI 模式)
  - 可选服务：prometheus + alertmanager（开发测试用）
  - volume 映射：~/.keeper/ 配置持久化

- [ ] **Server 模式（HTTP API）**
  - 新增文件：`keeper/api/__init__.py`
  - 新增文件：`keeper/api/server.py`
  - 基于 FastAPI 实现
  - 端点：
    - `POST /api/v1/query` — 自然语言查询
    - `GET /api/v1/status` — 系统状态
    - `GET /api/v1/history` — 巡检历史
    - `POST /api/v1/runbook/run` — 执行 Runbook
  - 认证：Bearer Token
  - 用途：多人共享、集成到其他平台

- [ ] **Helm Chart（可选）**
  - 新增目录：`deploy/helm/keeper/`
  - 支持部署到 K8s 集群内
  - ConfigMap 管理配置
  - Secret 管理 API Key

### 4.5 文档完善

- [ ] **架构文档**
  - 新增文件：`docs/architecture.md`
  - 内容：系统架构图、模块交互、数据流图

- [ ] **Runbook 编写指南**
  - 新增文件：`docs/runbook-guide.md`
  - 内容：YAML 格式说明、变量语法、安全等级、最佳实践

- [ ] **部署文档**
  - 新增文件：`docs/deployment.md`
  - 内容：Docker 部署、K8s 部署、配置说明

- [ ] **API 文档**
  - 新增文件：`docs/api.md`
  - 内容：Server 模式 API 说明、请求/响应示例

### 阶段 4 验收标准

- [ ] 支持 100+ 主机并发巡检，耗时 < 30s
- [ ] Docker 一键启动并可用
- [ ] 变更管理支持灰度 + 回滚
- [ ] Server 模式 API 可用
- [ ] 文档完整覆盖架构、部署、API

---

## 最终目录结构

```
Keeper/
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── TASKS.md                           ← 本文件
├── keeper/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── exceptions.py                  # 阶段 1
│   ├── validators.py                  # 阶段 1
│   ├── security.py                    # 阶段 1
│   ├── core/
│   │   ├── agent.py
│   │   ├── context.py
│   │   └── audit.py
│   ├── nlu/
│   │   ├── base.py
│   │   └── langchain_engine.py
│   ├── tools/
│   │   ├── server.py
│   │   ├── scanner.py
│   │   ├── ssh.py
│   │   ├── docker_tools.py
│   │   ├── network.py
│   │   ├── rca.py
│   │   ├── fixer.py
│   │   ├── logs.py
│   │   ├── log_analyzer.py           # 阶段 2
│   │   ├── comparator.py             # 阶段 2
│   │   ├── capacity.py               # 阶段 2
│   │   ├── snapshot.py               # 阶段 2
│   │   ├── timeline.py               # 阶段 3
│   │   ├── cert_monitor.py
│   │   ├── scheduler.py
│   │   ├── reporter.py
│   │   ├── alert.py
│   │   ├── async_server.py           # 阶段 4
│   │   └── k8s/
│   │       ├── client.py
│   │       ├── inspector.py
│   │       ├── formatter.py
│   │       ├── logs.py
│   │       ├── ops.py
│   │       └── multi_cluster.py      # 阶段 4
│   ├── runbook/                       # 阶段 2
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── executor.py
│   │   └── templates/
│   │       ├── disk_cleanup.yaml
│   │       ├── service_restart.yaml
│   │       ├── log_rotate.yaml
│   │       ├── k8s_pod_restart.yaml
│   │       └── memory_leak_check.yaml
│   ├── storage/                       # 阶段 2
│   │   ├── __init__.py
│   │   ├── history.py
│   │   └── fix_history.py
│   ├── compliance/                    # 阶段 3
│   │   ├── __init__.py
│   │   ├── baseline.py
│   │   ├── drift.py
│   │   └── cis/
│   │       └── linux_basic.py
│   ├── notify/                        # 阶段 3
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── feishu.py
│   │   ├── dingtalk.py
│   │   ├── wecom.py
│   │   └── router.py
│   ├── integrations/                  # 阶段 3
│   │   ├── __init__.py
│   │   └── prometheus.py
│   ├── knowledge/                     # 阶段 3
│   │   ├── __init__.py
│   │   └── fault_patterns.yaml
│   ├── cmdb/                          # 阶段 4
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── discovery.py
│   ├── change/                        # 阶段 4
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── executor.py
│   │   └── rollback.py
│   ├── api/                           # 阶段 4
│   │   ├── __init__.py
│   │   └── server.py
│   └── utils/                         # 阶段 1
│       ├── __init__.py
│       ├── retry.py
│       ├── logger.py
│       └── pool.py
├── tests/
│   ├── test_nlu_fast_path.py          # 阶段 1
│   ├── test_agent_dispatch.py         # 阶段 1
│   ├── test_validators.py            # 阶段 1
│   ├── test_comparator.py            # 阶段 2
│   ├── test_runbook.py               # 阶段 2
│   ├── test_rca_timeline.py          # 阶段 3
│   ├── test_audit.py
│   ├── test_fixer_cert.py
│   ├── test_keeper.py
│   ├── test_logs.py
│   ├── test_notify.py
│   ├── test_reporter.py
│   └── benchmark/
│       └── test_performance.py        # 阶段 4
├── deploy/
│   └── helm/keeper/                   # 阶段 4
└── docs/
    ├── architecture.md                # 阶段 4
    ├── runbook-guide.md               # 阶段 4
    ├── deployment.md                  # 阶段 4
    └── api.md                         # 阶段 4
```

---

## 依赖新增计划

| 阶段 | 新增依赖 | 用途 |
|------|----------|------|
| 1 | `tenacity` | 重试机制 |
| 1 | `keyring` | 密钥安全存储 |
| 1 | `structlog` | 结构化日志 |
| 2 | (无新增) | SQLite 为 Python 内置 |
| 3 | `httpx` (已有) | Prometheus API 调用 |
| 4 | `asyncssh` | 异步 SSH |
| 4 | `fastapi` + `uvicorn` | HTTP API Server 模式 |

---

## 开发规范

### 分支策略

```
main                           ← 稳定版本
├── feature/phase1-security    ← 阶段 1 安全加固
├── feature/phase1-testing     ← 阶段 1 测试
├── feature/phase2-history     ← 阶段 2 巡检历史
├── feature/phase2-runbook     ← 阶段 2 Runbook
├── feature/phase3-rca         ← 阶段 3 RCA 增强
└── feature/phase4-async       ← 阶段 4 异步
```

### 提交规范

```
feat(security): add input validation for host parameters
fix(nlu): handle empty input in fast path matching
test(agent): add dispatch routing tests
docs(runbook): add runbook writing guide
refactor(notify): extract BaseNotifier interface
```

### 代码质量要求

- 所有新增代码必须有类型注解
- 公开方法必须有 docstring
- 复杂逻辑必须有注释
- 每个 PR 必须有对应的测试
- flake8 + black 格式化通过

---

## 里程碑 & 检查点

| 里程碑 | 时间 | 关键交付物 |
|--------|------|-----------|
| M1: 工程化就绪 | Week 1 末 | CI 绿灯 + 安全加固 + 70% 覆盖率 |
| M2: 闭环 MVP | Week 3 末 | 巡检对比 + Runbook + 修复验证 |
| M3: 智能化 | Week 5 末 | RCA 时间线 + 告警集成 + 合规检测 |
| M4: 生产就绪 | Week 8 末 | Docker 部署 + API + 并发巡检 |

---

*文档创建时间：2026-05-15*
*分支：feature/project-improvement-plan*
