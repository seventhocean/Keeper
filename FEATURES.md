# Keeper 功能清单与测试方法

> 版本: v0.5.0-dev | 更新: 2026-05-16 | 测试: 374 passed

---

## 一、Agent 模式（默认）

### 1.1 启动方式

```bash
keeper                      # Agent 交互模式（默认，LLM 多步推理）
keeper agent                # 显式 Agent 模式
keeper --classic            # 经典路由器模式
keeper run <命令>           # 单命令执行（Agent 模式）
keeper run --classic <命令> # 单命令（经典模式）
```

### 1.2 Hybrid Agent 执行流程

```
用户输入
  → [Fast Path] 正则匹配确定性指令（帮助/退出）→ 直接返回
  → [Agent Loop] LLM 自主规划 + 多步工具调用
  → [降级] 经典路由器模式兜底
```

**测试方法：**

```bash
keeper
# 输入自然语言，观察 Agent 是否自主选择工具、多步执行
输入: 检查本机服务器状态
输入: 测试 8.8.8.8 的延迟和 baidu.com 的 DNS
输入: 分析一下为什么 CPU 高
输入: 安全审计这台机器
输入: 退出
```

### 1.3 流式执行

Agent Loop 使用 LangGraph `stream(stream_mode="updates")`，工具调用和结果实时展示。

```
🤔 Agent 分析中...
🔧 inspect_server(localhost)  ✓ (123ms)
🔧 ping_host(8.8.8.8)         ✓ (34ms)
```

**测试方法：**

```bash
keeper
输入: 检查本机，还要 ping 一下 8.8.8.8
# 应看到工具调用逐个实时出现，而非执行完一次性显示
```

### 1.4 错误恢复

- 同一工具连续 3 次 → ⚠️ 警告 + 提示换工具
- 工具执行异常 → LLM 看到错误后自主选择其他工具
- LangGraph 流式异常 → 自动降级到阻塞模式
- MAX_LOOPS 硬限制（手动 ReAct: 10 / LangGraph: recursion_limit=50）

**测试方法：**

```bash
# 模拟错误恢复（LLM 应自主换工具）
keeper
输入: 检查 192.0.2.1 能不能连通，端口 9999 通不通
# 应看到 ping + check_port 两个不同工具被调用
```

### 1.5 自服务引导

遇到缺失依赖或配置时，Agent 主动引导用户解决：

| 场景 | 引导内容 |
|------|---------|
| SSH 连接失败 | 询问用户名/密钥路径/密码/端口 |
| K8s 无 kubeconfig | 引导配置 kubeconfig 或用 kubectl 替代 |
| nmap 未安装 | 提供跨平台安装命令，询问是否帮装 |
| kubernetes SDK 未安装 | 建议 pip install 或用 kubectl CLI |
| 首次启动无 API Key | 交互式配置向导，不退出 |

**测试方法：**

```bash
# 测试 K8s 引导（未安装 SDK）
keeper run 检查 K8s 集群
# 应看到: "你可以帮用户安装: pip install kubernetes 或用 kubectl 替代"

# 测试 SSH 引导（连接不可达主机）
keeper
输入: 检查 192.168.1.100 的服务器状态
# Agent 应询问 SSH 凭据而不是只报错
```

### 1.6 特殊命令

```
帮助 / help     → 显示能力列表
退出 / exit     → 结束会话
/clear          → 清空对话历史
/history        → 查看上次执行详情
/tools          → 列出所有可用工具
/mode           → 查看当前运行模式
/memory         → 查看历史操作记忆
```

**测试方法：**

```bash
keeper
输入: /tools    # 应显示 21 个工具
输入: /mode     # 应显示 Agent Loop (langgraph)
输入: /memory   # 应先显示记忆（如有历史操作）
输入: /clear    # 应清空对话
```

---

## 二、21 个 Agent 工具

### 结构化工具（16 个）

| # | 工具 | 说明 | 分类 |
|---|------|------|------|
| 1 | inspect_server | 服务器巡检 + 自动告警 | 采集 |
| 2 | get_top_processes | Top N 进程 | 采集 |
| 3 | query_system_logs | journalctl 查询 | 日志 |
| 4 | read_log_file | 文件读取 | 日志 |
| 5 | ping_host | Ping 测试 | 网络 |
| 6 | check_port | 端口检测 | 网络 |
| 7 | dns_lookup | DNS 解析 | 网络 |
| 8 | k8s_cluster_inspect | 集群巡检 | K8s |
| 9 | k8s_pod_logs | Pod 日志 | K8s |
| 10 | k8s_scale_deployment | 扩缩容 | K8s |
| 11 | k8s_restart_deployment | 滚动重启 | K8s |
| 12 | docker_list_containers | 容器列表 | Docker |
| 13 | docker_container_logs | 容器日志 | Docker |
| 14 | scan_ports | nmap 端口扫描 | 安全 |
| 15 | check_ssl_cert | SSL 证书检查 | 安全 |
| 16 | manage_systemd_service | 服务管理 | 运维 |

### Runbook 工具（3 个）

| # | 工具 | 说明 | 来源 |
|---|------|------|------|
| 17 | runbook_disk_cleanup | 6 步磁盘清理流程 | disk_cleanup.yaml |
| 18 | runbook_service_restart | 4 步服务重启（含验证回滚） | service_restart.yaml |
| 19 | runbook_log_rotate | 3 步日志轮转 | log_rotate.yaml |

### 自由工具（5 个 — 仅 tool_mode=free/all 时可用）

| # | 工具 | 说明 |
|---|------|------|
| 20 | run_bash | 任意 Bash |
| 21 | read_file | 读文件 |
| - | write_file | 写文件 |
| - | list_directory | 列目录 |
| - | search_files | 搜索文件 |

**测试方法：**

```bash
# 查看完整列表
keeper
输入: /tools

# 验证结构化工具被优先使用（而非纯 run_bash）
keeper
输入: 检查本机服务器
# 应看到 inspect_server + get_top_processes（结构化）
# 仅在无合适工具时降级到 run_bash
```

---

## 三、CLI 命令（经典模式）

### 3.1 服务器巡检

```bash
keeper run 检查本机
keeper exec -- df -h /
keeper exec -- ps aux --sort=-%mem
```

### 3.2 K8s 集群管理

```bash
keeper k8s inspect
keeper k8s inspect -n kube-system
keeper k8s logs <pod> -n default -l 200
keeper k8s events
keeper k8s exec <pod> -- ls /
keeper k8s scale <deploy> -r 5
keeper k8s restart <deploy>
```

**测试方法：** 未安装 kubernetes SDK 时应有友好提示（无 Python traceback）。

### 3.3 Docker 管理

```bash
keeper docker ls
keeper docker stats
keeper docker images
keeper docker prune
```

### 3.4 网络诊断

```bash
keeper network ping 8.8.8.8 -c 4
keeper network port baidu.com 443
keeper network dns baidu.com
keeper network http https://baidu.com
```

### 3.5 安全扫描

```bash
keeper run 扫描漏洞 --host localhost
keeper cert scan
keeper cert check-domain baidu.com
```

**测试方法：** nmap 已安装时可正常扫描。未安装时 Agent 应提供安装引导。

### 3.6 定时任务

```bash
keeper schedule list
keeper schedule add --cron "*/30 * * * *" --description "K8s巡检" --type k8s_inspect
keeper schedule remove <task_id>
```

### 3.7 自动修复

```bash
keeper fix suggest
keeper fix verify
```

### 3.8 通知推送

```bash
keeper notify config --feishu-webhook "https://open.feishu.cn/..."
keeper notify test
keeper notify status
```

### 3.9 配置管理

```bash
keeper init
keeper config set --api-key sk-xxx --model claude-sonnet-4-6
keeper config set --threshold 80 --metric cpu
keeper config set --profile production
keeper config show
keeper status
```

### 3.10 审计日志

```bash
keeper logs --hours 24
keeper logs --host 192.168.1.100
keeper logs --intent inspect
keeper logs --json
```

---

## 四、安全模块

### 4.1 四级安全检查

| 级别 | 说明 | 示例 |
|------|------|------|
| READ_ONLY | 只读，直接执行 | ps, df, ping, grep |
| WRITE | 需确认 | systemctl restart, kill |
| DESTRUCTIVE | 强制确认+警告 | docker prune, truncate |
| DANGEROUS | 绝对拒绝 | rm -rf /, dd, mkfs |

**测试方法：**

```bash
keeper
输入: 帮我执行 rm -rf /
# 应被安全拦截，提示危险操作

输入: 执行 df -h
# 应正常执行（安全命令）
```

### 4.2 工具权限表

14 个只读工具（auto_allow=True）+ 4 个写入工具（需确认）。

---

## 五、Runbook 运维手册

### 5.1 内置模板

| 模板 | 步骤 | 说明 |
|------|------|------|
| disk_cleanup.yaml | 6 步 | 检查→找大文件→清旧日志→清缓存→验证 |
| service_restart.yaml | 4 步 | 检查→重启→等待→验证（含回滚） |
| log_rotate.yaml | 3 步 | 检查→执行 logrotate→验证 |

**测试方法：**

```bash
keeper
输入: 磁盘空间不足，帮我清理
# Agent 应调用 runbook_disk_cleanup 执行标准化流程

输入: 重启 nginx 服务
# Agent 应调用 runbook_service_restart 而非裸 systemctl restart
```

---

## 六、其他模块

### 6.1 API 服务

```bash
python -m keeper.api.server &
curl http://localhost:8000/health
```

### 6.2 Compliance 合规

```python
from keeper.compliance.cis.linux_basic import CISLinuxBasic
# CIS Benchmark 安全检查
```

### 6.3 Prometheus 集成

```python
from keeper.integrations.prometheus import PrometheusClient
```

### 6.4 通知推送

支持飞书、钉钉、企业微信三通道。

### 6.5 Knowledge 知识库

`keeper/knowledge/fault_patterns.yaml` — 故障模式匹配。

### 6.6 Snapshot 快照

```python
from keeper.tools.snapshot import SnapshotManager
# 系统状态快照，支持前后对比
```

### 6.7 LogAnalyzer 日志分析

```python
from keeper.tools.log_analyzer import LogAnalyzer
# 错误聚合 + 异常检测
```

### 6.8 Capacity + Comparator

```python
from keeper.tools.capacity import CapacityPredictor
from keeper.tools.comparator import InspectionComparator
# 容量预测 + 趋势对比
```

---

## 七、部署模式

| 模式 | 命令 | 说明 |
|------|------|------|
| CLI | `curl ... \| bash && keeper` | 默认 |
| Docker | `docker compose up -d` | API + CLI |
| K8s | `kubectl apply -f deploy/` | 集群部署 |
| 开发 | `pip install -e ".[dev]"` | 源码修改 |

---

## 八、完整测试套件

```bash
source venv/bin/activate

# 全部测试
pytest tests/ -v                          # 374 tests

# 分模块测试
pytest tests/test_agent_loop.py -v        # Agent Loop
pytest tests/test_agent_safety.py -v      # 安全检查
pytest tests/test_agent_tools.py -v       # 工具注册
pytest tests/test_agent_e2e.py -v         # Agent E2E
pytest tests/test_integration.py -v       # 集成测试
pytest tests/test_tools_extended.py -v    # 工具扩展
pytest tests/test_nlu_fast_path.py -v     # NLU Fast Path
pytest tests/test_phase2.py -v            # Phase 2
pytest tests/test_validators.py -v        # 输入验证
pytest tests/test_notify.py -v            # 通知
pytest tests/test_fixer_cert.py -v        # 修复/证书
pytest tests/test_keeper.py -v            # 核心
pytest tests/test_logs.py -v              # 日志
pytest tests/test_reporter.py -v          # 报告
pytest tests/test_audit.py -v             # 审计

# 覆盖率
pytest tests/ --cov=keeper --cov-report=term-missing
```

### 快速冒烟测试

```bash
keeper status
keeper run 检查本机
keeper docker ls
keeper network ping 8.8.8.8
keeper cert check-domain baidu.com
keeper logs --hours 1
```
