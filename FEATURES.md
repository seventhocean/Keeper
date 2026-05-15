# Keeper 功能清单与测试方法

> 版本: v0.5.0-dev | 更新: 2026-05-15

---

## 一、Agent 模式（默认交互入口）

### 1.1 混合 Agent（Fast Path + Agent Loop）

```
keeper                    # 启动 Agent 模式
keeper agent              # 显式启动 Agent 模式
keeper --classic           # 经典路由器模式
```

**测试方法：**

```bash
# 确保已配置 LLM
keeper config show

# 进入交互模式
keeper

# 输入以下自然语言指令：
#   "检查本机服务器状态"
#   "测试 8.8.8.8 的延迟"
#   "查看 Docker 容器状态"
#   "帮我分析一下为什么 CPU 高"
#   "检查系统有没有安全风险"

# 退出
输入: exit 或 退出 或 Ctrl+D
```

```bash
# 单命令模式（走经典路由器）
keeper run 检查本机
keeper run 测试 8.8.8.8 的延迟
```

### 1.2 Agent Loop 工具调用（18 个工具）

| # | 工具名 | 功能 | 安全等级 |
|---|--------|------|----------|
| 1 | `inspect_server` | 服务器资源巡检 (CPU/内存/磁盘/负载) | 只读 |
| 2 | `get_top_processes` | Top N 进程列表 | 只读 |
| 3 | `query_system_logs` | journalctl 系统日志查询 | 只读 |
| 4 | `read_log_file` | 读取日志文件 | 只读 |
| 5 | `ping_host` | ICMP Ping 测试 | 只读 |
| 6 | `check_port` | 端口连通性检测 | 只读 |
| 7 | `dns_lookup` | DNS 解析查询 | 只读 |
| 8 | `k8s_cluster_inspect` | K8s 集群全面巡检 | 只读 |
| 9 | `k8s_pod_logs` | Pod 日志查询 | 只读 |
| 10 | `k8s_scale_deployment` | Deployment 扩缩容 | 写入 |
| 11 | `k8s_restart_deployment` | Deployment 滚动重启 | 写入 |
| 12 | `docker_list_containers` | Docker 容器列表 | 只读 |
| 13 | `docker_container_logs` | Docker 容器日志 | 只读 |
| 14 | `scan_ports` | 端口扫描 (nmap) | 只读 |
| 15 | `check_ssl_cert` | SSL/TLS 证书检查 | 只读 |
| 16 | `manage_systemd_service` | systemd 服务管理 | 写入 |
| 17 | `inspect_remote_server` | SSH 远程服务器巡检 | 只读 |
| 18 | `execute_shell_command` | 安全 Shell 执行 | 写入 |

**测试方法：**

```bash
# 进入 Agent 模式
keeper

# 触发工具调用（LLM 自主选择工具）
输入: "检查本机"                          → 触发 inspect_server + get_top_processes
输入: "测试连接到 baidu.com"                → 触发 ping_host + dns_lookup
输入: "看一下 nginx 的错误日志"             → 触发 query_system_logs
输入: "端口 22 和 80 通不通"               → 触发 check_port
输入: "Docker 容器什么状态"                 → 触发 docker_list_containers
输入: "检查 baidu.com 的 SSL 证书"          → 触发 check_ssl_cert
输入: "安全审计这台机器"                    → 触发 scan_ports + check_ssl_cert

# 查看执行记录
输入: /history
输入: /memory
```

### 1.3 Fast Path（免 LLM 快速响应）

```
输入: 帮助 / help          → 显示能力列表
输入: 退出 / exit / quit   → 退出
```

**测试方法：**

```bash
keepr            # 进入 Agent 模式
输入: 帮助      → 应立即显示（不等待 LLM）
输入: /clear    → 清空历史
输入: /tools    → 列出所有工具
输入: /mode     → 显示当前模式
输入: /memory   → 显示历史记忆
输入: /history  → 显示上次执行详情
```

---

## 二、CLI 命令（经典模式）

### 2.1 服务器巡检

```bash
keeper run 检查本机
keeper run 检查 192.168.1.100
keeper run 批量巡检所有主机
keeper exec -- df -h /
keeper exec -- ps aux --sort=-%mem
```

**测试方法：**

```bash
keeper run 检查本机
# 应输出: CPU、内存、磁盘、负载、Top 进程、健康评分
```

### 2.2 K8s 集群管理

```bash
keeper k8s inspect                        # 集群巡检
keeper k8s inspect -n kube-system         # 指定命名空间
keeper k8s logs <pod-name>                # Pod 日志
keeper k8s logs nginx -n default -l 200   # 指定行数
keeper k8s events                         # Warning 事件
keeper k8s events -n kube-system          # 指定命名空间
keeper k8s exec <pod> -- ls /             # Pod 内执行命令
keeper k8s scale <deploy> -r 5            # 扩缩容
keeper k8s restart <deploy> -n production # 滚动重启
```

**测试方法：**

```bash
# 需要 kubernetes SDK 和有效的 kubeconfig
pip install kubernetes
keeper k8s inspect
keeper k8s events
```

### 2.3 Docker 管理

```bash
keeper docker ls         # 容器列表
keeper docker stats      # 资源统计
keeper docker images     # 镜像列表
keeper docker prune      # 清理无用镜像
```

**测试方法：**

```bash
keeper docker ls
# 应输出: 运行中/已停止容器数、镜像数、磁盘使用、健康评分
```

### 2.4 网络诊断

```bash
keeper network ping 8.8.8.8
keeper network ping 8.8.8.8 -c 10
keeper network port baidu.com 443
keeper network dns baidu.com
keeper network http https://baidu.com
```

**测试方法：**

```bash
keeper network ping 8.8.8.8
# 应输出: 丢包率、最小/平均/最大延迟

keeper network port localhost 22
# 应输出: 端口开放/关闭状态
```

### 2.5 安全扫描

```bash
keeper run 扫描漏洞
keeper run 扫描 192.168.1.100 --full
```

**测试方法：**

```bash
# 需要系统安装 nmap
sudo apt install nmap
keeper run 扫描localhost
# 应输出: 开放端口列表、风险检测
```

### 2.6 SSL/TLS 证书

```bash
keeper cert scan                              # 扫描本地证书
keeper cert check-domain baidu.com            # 检查域名证书
keeper cert check-domain baidu.com -p 8443    # 指定端口
```

**测试方法：**

```bash
keeper cert check-domain baidu.com
# 应输出: 证书状态（有效/即将过期/已过期）、剩余天数、颁发者
```

### 2.7 定时任务

```bash
keeper schedule list
keeper schedule add --cron "*/30 * * * *" --description "每30分钟检查K8s" --type k8s_inspect
keeper schedule add --cron "0 9 * * *" --description "每天9点巡检" --type batch_inspect
keeper schedule remove <task_id>
```

**测试方法：**

```bash
keeper schedule list
keeper schedule add --cron "*/30 * * * *" --description "测试任务" --type inspect
keeper schedule list
keeper schedule remove <返回的task_id>
```

### 2.8 自动修复

```bash
keeper fix suggest          # 生成修复建议
keeper fix verify           # 验证当前状态
```

**测试方法：**

```bash
keeper fix suggest
# 应输出: 基于规则的修复建议列表（或"未发现需要修复的问题"）
keeper fix verify
# 应输出: CPU、内存、磁盘、负载当前值
```

### 2.9 报告导出

```bash
keeper run 导出为 JSON
keeper run 生成 HTML 报告
keeper run 保存为 Markdown
```

**测试方法：**

```bash
keeper run 导出为 JSON
# 应输出: 报告文件路径
```

### 2.10 配置管理

```bash
keeper init
keeper config set --api-key sk-xxx --model claude-sonnet-4-6
keeper config set --threshold 80 --metric cpu
keeper config set --threshold 80            # 设置所有阈值
keeper config set --profile production
keeper config show
keeper config clear                         # 清除所有配置（需确认）
keeper status
```

**测试方法：**

```bash
keeper status
# 应输出: 配置文件路径、当前环境、LLM Provider、Model
```

### 2.11 审计日志

```bash
keeper logs --hours 24
keeper logs --host 192.168.1.100
keeper logs --intent inspect
keeper logs --json
```

**测试方法：**

```bash
keeper run 检查本机
keeper logs --hours 1
# 应输出: 刚才的操作记录
```

### 2.12 飞书通知

```bash
keeper notify config --feishu-webhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
keeper notify test
keeper notify status
```

**测试方法：**

```bash
keeper notify status
# 应输出: 当前通知配置状态
```

---

## 三、Runbook 运维手册

### 3.1 内置模板

| 模板 | 文件 | 步骤 |
|------|------|------|
| 磁盘清理 | `disk_cleanup.yaml` | 6 步（检查→查找大文件→清理旧日志→清理缓存→验证） |
| 日志轮转 | `log_rotate.yaml` | 3 步（检查→执行 logrotate→验证） |
| 服务重启 | `service_restart.yaml` | 4 步（检查→重启→等待→验证） |

**测试方法：**

```python
from keeper.runbook.executor import RunbookExecutor, list_builtin_runbooks

# 列出所有内置模板
print(list_builtin_runbooks())

# 加载并执行
executor = RunbookExecutor()
runbook = executor.load_from_yaml("keeper/runbook/templates/disk_cleanup.yaml")
executor.execute(runbook, {"threshold": "85"})
```

---

## 四、Compliance 安全合规

### 4.1 CIS Benchmark

```python
from keeper.compliance.cis.linux_basic import CISLinuxBasic

checker = CISLinuxBasic()
results = checker.run_all()
for r in results:
    print(f"{r.status}: {r.title}")
```

**测试方法：**

```bash
pytest tests/ -v -k test_phase2
```

### 4.2 Prometheus 集成

```python
from keeper.integrations.prometheus import PrometheusClient

client = PrometheusClient("http://localhost:9090")
# 查询指标
result = client.query("node_cpu_seconds_total")
```

---

## 五、API 服务

```bash
# 启动 API 服务
python -m keeper.api.server

# 健康检查
curl http://localhost:8000/health

# 服务状态
curl http://localhost:8000/api/status -H "Authorization: Bearer <token>"

# 列出工具
curl http://localhost:8000/api/tools -H "Authorization: Bearer <token>"
```

**测试方法：**

```bash
# 启动服务（后台）
python -m keeper.api.server &
sleep 2
curl http://localhost:8000/health
# 应返回: {"status": "ok"}
kill %1
```

---

## 六、通知推送（多通道）

| 通道 | 文件 | 状态 |
|------|------|------|
| 飞书 | `keeper/tools/notify.py` | ✅ 已有 |
| 钉钉 | `keeper/notify/dingtalk.py` | ✅ 新增 |
| 企业微信 | `keeper/notify/wecom.py` | ✅ 新增 |
| 路由器 | `keeper/notify/router.py` | ✅ 新增 |

**测试方法：**

```bash
pytest tests/test_notify.py -v
```

---

## 七、完整测试套件

### 7.1 单元测试

```bash
source venv/bin/activate
pytest tests/ -v                          # 全部 304 个测试
pytest tests/test_agent_loop.py -v        # Agent Loop 测试
pytest tests/test_agent_safety.py -v      # 安全模块测试
pytest tests/test_agent_tools.py -v       # 工具注册测试
pytest tests/test_agent_e2e.py -v         # Agent E2E 测试
pytest tests/test_nlu_fast_path.py -v     # NLU Fast Path 测试
pytest tests/test_phase2.py -v            # Phase 2 功能测试
pytest tests/test_validators.py -v        # 输入验证测试
pytest tests/test_notify.py -v            # 通知推送测试
pytest tests/test_fixer_cert.py -v        # 修复/证书测试
pytest tests/test_keeper.py -v            # 核心模块测试
pytest tests/test_logs.py -v              # 日志工具测试
pytest tests/test_reporter.py -v          # 报告导出测试
pytest tests/test_audit.py -v             # 审计日志测试
```

### 7.2 覆盖率

```bash
pytest tests/ --cov=keeper --cov-report=term-missing
```

### 7.3 快速功能冒烟测试

```bash
# 经典模式
keeper run 检查本机
keeper run 测试 8.8.8.8 的延迟
keeper docker ls
keeper network ping 8.8.8.8
keeper cert check-domain baidu.com
keeper status
keeper logs --hours 1

# Agent 模式
keeper
输入: 检查本机服务器状态
输入: 测试网络连通性
输入: /tools
输入: /memory
输入: /history
输入: 退出
```

---

## 八、项目结构速查

```
keeper/
├── agent/          ← Agent Loop 引擎（HybridAgent + ReAct Loop + 工具注册）
├── api/            ← FastAPI REST 服务
├── cli.py          ← Click CLI 入口
├── compliance/     ← 安全合规（CIS Benchmark）
├── config.py       ← 配置管理
├── core/           ← 经典路由器（降级兜底）
├── exceptions.py   ← 异常层次结构
├── integrations/   ← Prometheus 集成
├── knowledge/      ← 故障模式知识库
├── nlu/            ← NLU 引擎（Fast Path + LLM）
├── notify/         ← 多通道通知推送（飞书/钉钉/企微）
├── runbook/        ← YAML 运维手册引擎
├── storage/        ← 数据持久化（SQLite）
├── tools/          ← 底层工具实现（20+ 个模块）
├── utils/          ← 工具函数（日志/重试）
└── validators.py   ← 输入验证
```
