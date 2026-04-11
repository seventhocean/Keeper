# Keeper 使用文档

> **智能运维 Agent** — 通过自然语言对话管理服务器、K8s 集群、Docker 容器，自动巡检、诊断、告警与修复。
>
> **版本：** v0.4.0-dev (2026-04-11)

---

## 目录

- [快速开始](#快速开始)
- [交互模式](#交互模式)
- [功能一览](#功能一览)
  - [服务器巡检](#服务器巡检)
  - [批量巡检](#批量巡检)
  - [漏洞扫描](#漏洞扫描)
  - [配置管理](#配置管理)
  - [日志查询](#日志查询)
  - [报告导出](#报告导出)
  - [K8s 集群管理](#k8s-集群管理)
  - [Docker 容器管理](#docker-容器管理)
  - [根因分析 (RCA)](#根因分析-rca)
  - [网络诊断](#网络诊断)
  - [定时任务](#定时任务)
  - [自动修复](#自动修复)
  - [证书监控](#证书监控)
  - [飞书通知推送](#飞书通知推送)
  - [软件安装](#软件安装)
  - [问题排查](#问题排查)
- [CLI 命令参考](#cli-命令参考)
- [配置文件](#配置文件)
- [开发进度](#开发进度)

---

## 快速开始

### 一键安装（推荐）

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Agent_Project/main/install.sh | bash
```

自动完成：检测 Python → 创建隔离环境 → 安装依赖 → 注册命令。

### 手动安装

```bash
git clone https://github.com/Winter-wyh1314/Keeper.git
cd Keeper
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 初始化

```bash
# 初始化配置（首次使用）
keeper init

# 配置 LLM API
keeper config set --api-key YOUR_API_KEY --base-url https://api.qnaigc.com/v1 --model doubao-seed-2.0-mini

# 配置飞书通知（可选）
keeper notify config --feishu-webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx

# 开始对话
keeper
```

---

## 交互模式

运行 `keeper` 进入对话界面，输入自然语言即可：

```
> 你好
> 检查本机
> 扫描漏洞
> 检查 K8s 集群状态
> 查看所有 Docker 容器
> 导出报告
> 帮助
```

---

## 功能一览

### 服务器巡检

采集 CPU、内存、磁盘、负载、进程、开机时间等指标，与阈值对比输出健康评分。

| 你可以说 | 说明 |
|----------|------|
| `检查本机` / `看看这台机器` | 巡检本机 |
| `检查 192.168.1.100` | 巡检指定主机（通过 SSH） |
| `服务器状态` | 查看最近巡检结果 |

### 批量巡检

并行采集多台主机，生成汇总表格和详细报告。从 `/etc/hosts` 读取主机列表。

| 你可以说 | 说明 |
|----------|------|
| `批量巡检所有主机` | 巡检 /etc/hosts 中所有主机 |
| `检查所有机器` | 同上 |

### 漏洞扫描

使用 `nmap` 扫描开放端口和已知 CVE 漏洞。

| 你可以说 | 说明 |
|----------|------|
| `扫描漏洞` | 快速扫描本机 |
| `扫描 192.168.1.100` | 扫描指定主机 |
| `全面扫描` | 完整深度扫描 |

### 配置管理

管理阈值、环境切换、LLM 配置等。

| 你可以说 | 说明 |
|----------|------|
| `把 CPU 阈值设为 80%` | 修改阈值 |
| `切换到 production 环境` | 切换环境 |
| `显示配置` | 查看当前配置 |
| `保存配置` | 保存配置到文件 |

CLI 方式：
```bash
keeper config set --threshold 80 --metric cpu
keeper config set --api-key xxx --model claude-sonnet-4-6
keeper config show
keeper config clear
```

### 日志查询

支持三种日志源：审计日志（Keeper 操作记录）、系统日志（journalctl）、Docker 容器日志。

| 你可以说 | 说明 |
|----------|------|
| `查看最近的操作记录` | Keeper 审计日志 |
| `过去 24 小时做了什么？` | 带时间范围的审计日志 |
| `查看系统日志` | journalctl 查询 |
| `查看 nginx 容器日志` | Docker 容器日志 |
| `查看 /var/log/syslog 最后 100 行` | 文件日志 |

CLI：`keeper logs --hours 24 --host 192.168.1.100`

### 报告导出

将巡检结果导出为 JSON、HTML 或 Markdown 格式。

| 你可以说 | 说明 |
|----------|------|
| `导出为 JSON` | JSON 格式报告 |
| `生成 HTML 报告` | HTML 可视化报告 |
| `保存为 Markdown` | Markdown 格式 |

报告会自动推送到飞书群（如果配置了 Webhook）。

CLI：`keeper run 导出报告`

### K8s 集群管理

支持标准 K8s 和 K3s 环境，自动检测 kubeconfig 路径。

#### 集群巡检

| 你可以说 | 说明 |
|----------|------|
| `检查 K8s 集群状态` | 一键巡检集群 |
| `K8s 巡检` | 同上 |
| `查看 Pod 的情况` | 查看 Pod 状态 |
| `查看 kube-system 的 Pod` | 指定命名空间 |

巡检内容包括：Node 状态、Pod 异常检测（Pending/Failed/CrashLoopBackOff/OOMKilled/ImagePullBackOff）、Deployment/StatefulSet/DaemonSet 状态、Service 端口映射、PVC 绑定、Namespace 资源配额、Warning 事件聚合、健康评分。

#### Pod 日志

| 你可以说 | 说明 |
|----------|------|
| `查看 my-app Pod 的日志` | 查看指定 Pod 日志 |
| `查看 default namespace 下 nginx Pod 日志` | 指定命名空间 |

#### K8s 深度操作

| 你可以说 | 说明 |
|----------|------|
| `重启 my-app 这个 deployment` | 重启 Deployment（需二次确认） |
| `把 frontend 扩到 5 个副本` | 扩缩容（需二次确认） |
| `回滚 api-gateway` | 回滚 Deployment（需二次确认） |
| `进入 my-pod 执行 ls /` | Pod 内执行命令 |

#### K8s 报告导出

| 你可以说 | 说明 |
|----------|------|
| `导出 K8s 巡检报告` | 导出 K8s 报告为文件 |

CLI：
```bash
keeper k8s inspect
keeper k8s logs <pod-name>
keeper k8s events
```

### Docker 容器管理

| 你可以说 | 说明 |
|----------|------|
| `查看 Docker 容器状态` | 列出运行中的容器 |
| `看看有哪些容器在运行` | 同上 |
| `Docker 镜像占用多大` | 查看镜像列表和大小 |
| `清理无用的 Docker 镜像` | 清理悬空镜像 |
| `查看 xxx 容器日志` | 容器日志 |
| `查看 xxx 容器详情` | 容器详细信息 |
| `重启/停止/启动 xxx 容器` | 容器操作 |

CLI：
```bash
keeper docker ls
keeper docker stats
keeper docker images
keeper docker prune
```

### 根因分析 (RCA)

基于巡检数据自动生成问题诊断，支持单机分析和双机对比。

| 你可以说 | 说明 |
|----------|------|
| `分析一下为什么 CPU 高` | 单机根因分析 |
| `帮我排查生产环境问题` | 通用问题排查 |
| `对比 spring 和 autumn 的差异` | 双主机对比分析 |

### 网络诊断

支持 Ping、端口检测、DNS 解析、HTTP 检查和路由追踪。

| 你可以说 | 说明 |
|----------|------|
| `测试 8.8.8.8 的延迟` | Ping 测试 |
| `检查 192.168.1.100 的 3306 端口通不通` | 端口检测 |
| `DNS 解析正常吗` | DNS 解析（默认 baidu.com） |
| `看看 baidu.com 能不能访问` | HTTP 检查 |
| `追踪到 8.8.8.8 的路由` | Traceroute |

CLI：
```bash
keeper network ping 8.8.8.8
keeper network port 192.168.1.100 3306
keeper network dns baidu.com
keeper network http https://baidu.com
```

### 定时任务

支持 Cron 表达式，可定时执行巡检、K8s 巡检、网络诊断等任务。

| 你可以说 | 说明 |
|----------|------|
| `每 30 分钟检查一次` | 添加定时任务 |
| `每天早上 9 点巡检所有服务器` | 每日定时巡检 |
| `每小时检查 K8s 状态` | 定时 K8s 巡检 |
| `查看定时任务` | 列出所有任务 |
| `删除第 2 个定时任务` | 删除任务 |
| `禁用/启用定时任务` | 启用/禁用任务 |

CLI：
```bash
keeper schedule add
keeper schedule list
keeper schedule remove
```

### 自动修复

自动检测服务器问题（磁盘空间、内存、SSH 暴力破解、OOM 等）并生成修复建议，支持单步执行和批量执行。

| 你可以说 | 说明 |
|----------|------|
| `帮我修复服务器问题` | 生成修复建议列表 |
| `自动修复` | 同上 |
| `帮我清理一下磁盘` | 针对性修复建议 |
| `执行第 1 个修复` | 执行指定编号的修复 |
| `一键修复` | 批量执行所有修复 |
| `验证修复效果` | 验证修复后的效果 |

**安全机制：**
- **安全命令**：直接执行
- **破坏性命令**（涉及文件删除/清理）：需要二次确认
- **危险命令**（如 `rm` 系列）：直接拒绝，绝不生成

### 证书监控

监控本地文件证书、K8s 证书和域名证书的状态。

| 你可以说 | 说明 |
|----------|------|
| `检查 SSL 证书` | 全面扫描所有证书 |
| `看看证书有没有过期` | 同上 |
| `检查 baidu.com 的证书` | 检查指定域名 |
| `TLS 证书状态` | 同上 |

支持本地 PEM 证书、K8s Secret 证书、远程 HTTPS 域名证书，自动识别过期/即将过期状态。

CLI：
```bash
keeper cert scan
keeper cert check-domain baidu.com
```

### 飞书通知推送

配置飞书群机器人 Webhook 后，所有任务执行结果自动推送到飞书群，包含：
- **巡检报告**：Markdown 格式，含汇总表格、主机详情、异常提醒
- **任务通知**：每次任务执行后推送摘要卡片
- **告警推送**：触发告警时自动推送严重告警

| 你可以说 | 说明 |
|----------|------|
| `发送到飞书` | 推送最近操作结果 |
| `推送巡检结果` | 推送巡检结果到飞书 |
| `发到飞书群` | 同上 |

CLI：
```bash
keeper notify config --feishu-webhook <url> [--secret <sign>]
keeper notify test
keeper notify status
```

### 软件安装

| 你可以说 | 说明 |
|----------|------|
| `安装 nmap` | 本地安装软件 |
| `在 192.168.1.100 上安装 nmap` | 远程安装软件 |

### 问题排查

自动查询错误级别日志、检测 SSH 暴力破解、OOM Killer、磁盘 I/O 错误、服务启动失败等问题模式。

| 你可以说 | 说明 |
|----------|------|
| `有没有什么问题/异常` | 自动检测系统问题 |
| `系统健康吗` | 同上 |
| `有什么故障吗` | 同上 |

---

## CLI 命令参考

```bash
# 交互模式
keeper                    # 进入对话

# 执行命令
keeper run <自然语言>     # 单次执行

# 子命令
keeper status             # 系统状态
keeper init               # 初始化配置
keeper exec -- <命令>     # 执行 Shell 命令
keeper chat               # 快速聊天模式

# 配置
keeper config set [--api-key xxx] [--model xxx] [--threshold 80] [--metric cpu] [--feishu-webhook url]
keeper config show
keeper config clear

# 通知
keeper notify config --feishu-webhook <url>
keeper notify test
keeper notify status

# 日志
keeper logs [--hours 24] [--host xxx]

# K8s
keeper k8s inspect
keeper k8s logs <pod>
keeper k8s events

# Docker
keeper docker ls
keeper docker stats
keeper docker images
keeper docker prune

# 定时任务
keeper schedule list
keeper schedule add
keeper schedule remove

# 证书
keeper cert scan
keeper cert check-domain <domain>

# 网络
keeper network ping <host>
keeper network port <host> <port>
keeper network dns <domain>
keeper network http <url>

# 修复
keeper fix suggest
keeper fix verify
```

---

## 配置文件

配置文件位于 `~/.keeper/config.yaml`：

```yaml
current_profile: dev

llm:
  provider: openai_compatible
  api_key: sk-xxx
  base_url: https://api.qnaigc.com/v1
  model: doubao-seed-2.0-mini

profiles:
  dev:
    hosts: [localhost]
    thresholds: {cpu: 90, memory: 90, disk: 95}
  production:
    hosts: [10.0.0.1, 10.0.0.2]
    thresholds: {cpu: 70, memory: 80, disk: 85}

k8s:
  kubeconfig: /etc/rancher/k3s/k3s.yaml
  cluster_type: k3s

notifications:
  feishu_webhook: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  feishu_secret: ""
```

---

## 开发进度

| 阶段 | 版本 | 状态 | 内容 |
|------|------|------|------|
| Phase 1 - MVP | v0.1.0 | ✅ 完成 | CLI 框架、NLU 引擎、服务器巡检、配置管理、对话记忆 |
| Phase 2 - 增强 | v0.2.0 | ✅ 完成 | 报告导出、审计日志、系统日志查询、多主机巡检、SSH 采集 |
| Phase 3 - K8s | v0.3.0 | ✅ 完成 | K8s 集群管理、资源巡检、异常检测、Pod 日志、ConfigMap/Secret/Ingress |
| Phase 4 - 智能分析 | v0.4.0 | 🚧 开发中 | Docker/RCA/网络诊断/K8s 操作/定时任务/自动修复/证书监控/飞书通知/告警引擎 |
| Phase 5 - 安全集成 | v0.5.0 | 🔲 规划中 | 安全基线、审计报表、Prometheus 集成、IM 通知扩展 |

### 分发方式

| 方式 | 说明 |
|------|------|
| 一键安装脚本 | `curl -sSL ... | bash` — 自动检测 Python、创建 venv、安装依赖、注册命令 |
| 手动安装 | `git clone` + `pip install -e .` — 适合开发者 |
| PyPI（规划） | `pip install keeper` — 发布到 PyPI |

### 架构概览

```
keeper/
├── cli.py              # CLI 入口（Click + Prompt Toolkit）
├── config.py           # 配置管理（YAML + 环境变量）
├── nlu/
│   ├── base.py         # NLU 抽象基类 + IntentType 枚举
│   └── langchain_engine.py  # LangChain + LLM 意图识别
├── core/
│   ├── agent.py        # Agent 核心（意图分发 + 通知）
│   ├── context.py      # 上下文管理 + 对话记忆
│   └── audit.py        # 审计日志
├── tools/
│   ├── server.py       # 服务器采集（psutil）+ SSH 远程
│   ├── scanner.py      # 漏洞扫描（nmap）
│   ├── reporter.py     # 报告导出（JSON/HTML/MD）
│   ├── docker_tools.py # Docker 容器管理
│   ├── network.py      # 网络诊断（ping/port/dns/http/traceroute）
│   ├── rca.py          # 根因分析引擎
│   ├── fixer.py        # 自动修复（规则 + LLM + 安全拦截）
│   ├── scheduler.py    # 定时任务（Cron）
│   ├── cert_monitor.py # SSL/TLS 证书监控
│   ├── notify.py       # 飞书通知推送（Webhook + 签名）
│   ├── alert.py        # 告警规则引擎
│   ├── k8s/            # K8s 模块
│   │   ├── client.py   # K8s 客户端封装
│   │   ├── inspector.py# 集群巡检
│   │   ├── logs.py     # Pod 日志
│   │   ├── ops.py      # 深度操作（扩缩容/重启/回滚/Exec）
│   │   └── formatter.py# 报告格式化
│   └── logs.py         # 日志查询工具
├── install.sh          # 一键安装脚本
├── pyproject.toml      # 项目配置
└── ...
```
