# Keeper

智能运维 Agent — 类 Claude Code 的对话式 CLI 工具

用自然语言管理服务器：「检查 K8s 集群」「分析 CPU 为什么高」「磁盘满了帮我清理」。Keeper 通过 LLM 自主分析、选择工具、多步执行，像资深运维工程师一样工作。

**版本：** v1.0.0 | 测试：374 passed | 工具：21 个

---

## 快速开始

### 一键安装

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash
```

### 首次启动

```bash
keeper
```

首次启动时，Keeper 会自动检测 LLM 配置。如果未配置 API Key，会进入**交互式配置向导**，直接输入 API Key / Base URL / Model 即可，无需手动编辑配置文件。

```
⚡ 首次使用？需要配置 LLM API Key。

   快速开始（推荐）：
   1. 获取 API Key: https://platform.openai.com/api-keys
   2. 或使用国产模型（如 DeepSeek、豆包等）

   API Key (输入跳过): sk-xxx
   Base URL [https://api.qnaigc.com/v1]:
   Model [deepseek/deepseek-v3.2-251201]:

✓ LLM 配置已保存！
🤖 Keeper Agent 模式已启动
```

### 手动配置

```bash
keeper config set --api-key YOUR_API_KEY --model claude-sonnet-4-6
keeper config set --api-key YOUR_API_KEY --base-url https://api.qnaigc.com/v1
keeper status    # 查看当前配置
```

### Docker 部署

```bash
docker compose up -d             # 启动 Keeper + API 服务
docker compose run keeper-cli    # 进入 CLI 模式
```

---

## Agent 模式（默认）

Keeper 采用 **Hybrid Agent** 架构：Fast Path（正则匹配简单指令）+ Agent Loop（LLM 多步推理 + 工具调用）。

```
用户: "检查服务器状态，测试 8.8.8.8 延迟"
  🤔 Agent 分析中...
  🔧 inspect_server(localhost)  ✓ (123ms)
  🔧 ping_host(8.8.8.8)         ✓ (34ms)

[服务器状态报告]
  CPU: 15%  内存: 40%  磁盘: 62%
  健康评分: 100/100

[网络诊断]
  8.8.8.8 可达, 丢包率 0%, 平均延迟 34.7ms
```

### 核心能力

Agent 拥有 21 个工具，LLM 自主选择调用：

| 类别 | 工具 | 说明 |
|------|------|------|
| 服务器 | inspect_server, get_top_processes | 资源巡检、Top 进程 |
| 日志 | query_system_logs, read_log_file | journalctl 查询、文件读取 |
| 网络 | ping_host, check_port, dns_lookup | Ping、端口检测、DNS |
| K8s | k8s_cluster_inspect, k8s_pod_logs, scale, restart | 集群巡检、Pod 日志、扩缩容 |
| Docker | docker_list_containers, docker_container_logs | 容器列表、日志 |
| 安全 | scan_ports, check_ssl_cert | nmap 扫描、SSL 证书 |
| 运维 | manage_systemd_service, execute_shell_command | 服务管理、安全 Shell |
| Runbook | runbook_disk_cleanup, runbook_service_restart, runbook_log_rotate | 标准化运维流程 |
| 自由 | run_bash, read_file, write_file, list_directory, search_files | 通用操作 |

### 流式执行

Agent Loop 支持流式执行：工具调用和结果实时展示，不再阻塞等待全部完成。

### 错误恢复

工具失败时 Agent 自动重试或切换工具。同一工具连续 3 次调用会触发警告并要求尝试其他方案。

### 自服务引导

遇到缺失依赖或配置问题时，Agent 不会简单报错，而是主动引导：
- **nmap 未安装** → 提供跨平台安装命令，询问是否帮你执行
- **SSH 连接失败** → 引导提供密钥路径/用户名/密码
- **K8s 连接失败** → 引导配置 kubeconfig 或使用 kubectl CLI

---

## 使用示例

```bash
keeper    # 进入 Agent 交互模式

# 或者单命令模式
keeper run 检查本机
keeper run 测试 8.8.8.8 的延迟
keeper run 扫描漏洞 --host 192.168.1.100
```

### Agent 对话示例

```
keeper🤖> 分析一下为什么 CPU 高

[排查路线: 检查服务器整体资源状态 → 获取 CPU 占用最高的进程 → 查看异常进程对应的服务日志]

🔧 inspect_server(localhost)
  CPU: 92% ⚠️  内存: 45%  磁盘: 60%
  Top 进程: mysql (85% CPU)

🔧 get_top_processes(n=20)
  1. mysql (PID:1234) CPU:85% MEM:45%

🔧 query_system_logs(unit=mysql, priority=err, since=1h)
  [发现] 大量 slow query 日志

## 分析结论
根因：MySQL 慢查询导致 CPU 飙升至 92%
建议：
1. 查看慢查询日志定位具体 SQL
2. 考虑添加索引或优化查询
3. 临时方案：限制连接数
```

### Runbook 标准化运维

```bash
# Agent 自动识别并执行标准化流程
keeper🤖> 磁盘满了帮我清理

🔧 runbook_disk_cleanup(threshold=85)
[Runbook] 磁盘清理流程 (6 步)
  1/6 检查磁盘使用率     ✓
  2/6 查找大文件          ✓
  3/6 清理旧日志 (>30天)  ⚠️ 需确认
  4/6 清理缓存            ⚠️ 需确认
  5/6 验证清理结果        ✓

磁盘使用率: 62% → 45%  ✅
```

---

## 命令参考

### Agent 模式

| 命令 | 说明 |
|------|------|
| `keeper` | 启动 Agent 交互模式（默认） |
| `keeper agent` | 显式 Agent 模式 |
| `keeper --classic` | 经典路由器模式 |
| `keeper run <命令>` | 单命令执行（Agent 模式） |
| `keeper run --classic <命令>` | 单命令（经典模式） |

### 特殊命令（交互模式内）

| 命令 | 说明 |
|------|------|
| `/clear` | 清空对话历史 |
| `/history` | 查看上次执行详情 |
| `/tools` | 列出所有可用工具 |
| `/mode` | 查看当前运行模式 |
| `/memory` | 查看历史操作记忆 |

### 服务器巡检

| 命令 | 说明 |
|------|------|
| `keeper run 检查本机` | 单机巡检 |
| `keeper run 检查 192.168.1.100` | 远程巡检（SSH） |
| `keeper exec -- df -h /` | 执行 Shell 命令 |

### K8s 管理

| 命令 | 说明 |
|------|------|
| `keeper k8s inspect` | 集群巡检 |
| `keeper k8s inspect -n kube-system` | 指定命名空间 |
| `keeper k8s logs <pod>` | Pod 日志 |
| `keeper k8s events` | Warning 事件 |
| `keeper k8s exec <pod> -- <cmd>` | Pod 内执行 |
| `keeper k8s scale <deploy> -r 5` | 扩缩容 |
| `keeper k8s restart <deploy>` | 滚动重启 |

### 配置管理

| 命令 | 说明 |
|------|------|
| `keeper init` | 初始化配置 |
| `keeper config set --api-key xxx` | 配置 LLM |
| `keeper config set --threshold 80 --metric cpu` | 设置阈值 |
| `keeper config set --profile production` | 切换环境 |
| `keeper config show` | 当前配置 |
| `keeper config clear` | 清除配置 |
| `keeper status` | 系统状态 |

### Docker 管理

| 命令 | 说明 |
|------|------|
| `keeper docker ls` | 容器列表 |
| `keeper docker stats` | 资源统计 |
| `keeper docker images` | 镜像列表 |
| `keeper docker prune` | 清理无用镜像 |

### 网络诊断

| 命令 | 说明 |
|------|------|
| `keeper network ping <host>` | Ping 测试 |
| `keeper network port <host> <port>` | 端口检测 |
| `keeper network dns <domain>` | DNS 查询 |
| `keeper network http <url>` | HTTP 检查 |

### 安全 & 证书

| 命令 | 说明 |
|------|------|
| `keeper cert scan` | 扫描本地证书 |
| `keeper cert check-domain <domain>` | 域名证书检查 |
| `keeper run 扫描漏洞` | nmap 端口扫描 |

### 自动化

| 命令 | 说明 |
|------|------|
| `keeper schedule list` | 定时任务列表 |
| `keeper schedule add --cron "*/30 * * * *" --description "K8s检查"` | 添加任务 |
| `keeper fix suggest` | 修复建议 |
| `keeper fix verify` | 验证修复 |

### 通知 & 日志

| 命令 | 说明 |
|------|------|
| `keeper notify config --feishu-webhook <url>` | 飞书通知配置 |
| `keeper notify test` | 测试通知 |
| `keeper logs --hours 24` | 审计日志 |
| `keeper logs --host 192.168.1.100` | 按主机筛选 |

---

## 部署模式

### 模式 1：CLI 工具（默认）

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash
keeper
```

适用：个人运维、开发调试、服务器日常管理。

### 模式 2：Docker Compose

```bash
git clone https://github.com/seventhocean/Keeper.git
cd Keeper
docker compose up -d
```

服务：
- `keeper-api` — REST API（端口 8000）
- 支持 `docker compose run keeper-cli` 进入 CLI

### 模式 3：Kubernetes

```bash
kubectl apply -f deploy/
```

支持 Prometheus 指标采集集成。

### 模式 4：开发模式

```bash
git clone https://github.com/seventhocean/Keeper.git
cd Keeper
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
keeper
```

---

## 技术架构

```
keeper/
├── agent/          ← Agent Loop 引擎（HybridAgent + ReAct + 流式）
│   ├── loop.py              ← LangGraph / Manual 双模式
│   ├── hybrid.py            ← Fast Path + Agent Loop + 降级
│   ├── tools_registry.py    ← 21 个 @tool 注册
│   ├── planner.py           ← 6 个排查模板
│   ├── memory.py            ← 长期记忆（JSON 持久化）
│   ├── safety.py            ← 四级安全检查
│   └── free_tools.py        ← 5 个自由工具
├── api/            ← FastAPI REST 服务
├── cli.py          ← Click + Prompt Toolkit 入口
├── compliance/     ← CIS Benchmark 安全合规
├── core/           ← 经典路由器（降级兜底）+ 审计日志
├── integrations/   ← Prometheus 集成
├── knowledge/      ← 故障模式知识库（YAML）
├── nlu/            ← NLU 引擎（Fast Path + LangChain LLM）
├── notify/         ← 多通道通知（飞书/钉钉/企业微信）
├── runbook/        ← YAML 运维手册引擎（3 个内置模板）
├── storage/        ← SQLite 巡检历史
├── tools/          ← 底层工具（20+ 模块）
└── utils/          ← 日志/重试工具
```

### 技术栈

| 组件 | 技术 |
|------|------|
| CLI | Click + Prompt Toolkit |
| Agent | LangGraph + LangChain (OpenAI / Anthropic) |
| 流式 | LangGraph stream_mode="updates" |
| API | FastAPI + Uvicorn |
| 系统监控 | psutil |
| K8s | kubernetes SDK / kubectl CLI |
| Docker | Docker SDK / CLI |
| SSH | paramiko / OpenSSH |
| 安全扫描 | Nmap |
| 合规 | CIS Benchmark |
| 持久化 | SQLite + JSON |
| 通知 | 飞书 / 钉钉 / 企业微信 |
| 部署 | Docker / K8s / 一键安装脚本 |

---

## 开发

```bash
# 测试
pytest tests/ -v              # 374 tests
pytest tests/ --cov=keeper     # 覆盖率报告

# 代码检查
flake8 keeper/ --max-line-length=120
```

---

## 常见问题

**Q: 支持哪些 LLM？**
A: OpenAI 兼容 API（DeepSeek、豆包、通义千问等）和 Anthropic API。配置时指定 provider 即可。

**Q: 需要什么系统权限？**
A: 本地巡检无需特殊权限。远程 SSH / Docker / K8s 操作需要相应权限。Agent 会主动引导配置。

**Q: 配置文件在哪？**
A: `~/.keeper/config.yaml`。首次运行 `keeper` 会自动创建。

**Q: K8s 需要手动配置吗？**
A: 无需。自动检测 `/etc/rancher/k3s/k3s.yaml`、`~/.kube/config` 等常见路径。未找到时 Agent 会引导配置。

**Q: 离线环境能用吗？**
A: 本地巡检、Docker、K8s 等操作不依赖 LLM。智能分析功能需要 LLM API 连接。

---

## License

MIT
