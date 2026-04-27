# Keeper

智能运维 Agent — 交互式 CLI 工具

**产品形态：** 类似 Claude Code 的对话式 CLI Agent

用自然语言说"检查 192.168.1.100"或"K8s 集群状态怎么样"，Keeper 通过 LLM 理解意图后自动执行对应运维操作。

**版本：** v0.5.0-dev

---

## 快速开始

### 一键安装（推荐）

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash
```

自动检测 Python → 创建隔离环境 → 安装依赖 → 注册命令。开箱即用！

### 手动安装（开发模式）

```bash
git clone git@github.com:seventhocean/Keeper.git
cd Keeper
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -e .
```

### 初始化 & 配置

```bash
keeper init

# 配置 LLM API Key（二选一）
keeper config set --api-key YOUR_API_KEY \
  --base-url https://api.qnaigc.com/v1 \
  --model doubao-seed-2.0-mini

keeper config set --provider anthropic \
  --api-key YOUR_API_KEY \
  --model claude-sonnet-4-6
```

### 启动

```bash
keeper
```

进入交互式对话模式：

```
keeper> 帮我检查这台机器
keeper> K8s 集群状态怎么样？
keeper> 批量巡检所有服务器
keeper> 查看系统有没有什么异常
```

### 单命令模式（脚本集成）

```bash
keeper run 检查 192.168.1.100
keeper run 扫描 --host 192.168.1.100 --full
```

---

## 核心功能

### 服务器巡检

```
keeper> 检查 192.168.1.100

[✓] 服务器健康检查 - 192.168.1.100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CPU:     5.0%  (阈值：90%)  ✓
  内存：   80.2%  (阈值：90%)  ✓
  磁盘：   64.8%  (阈值：95%)  ✓
  负载：   0.30  (阈值：8)    ✓

健康评分：100/100
```

支持单主机巡检、批量巡检、SSH 远程采集。

### K8s 集群管理

```
keeper> 检查 K8s 集群状态

[K8s 巡检] 集群巡检报告
集群类型：  k3s
K8s 版本：  v1.34.6+k3s1
节点数量：  1
健康评分：100/100 - 健康
```

- 自动检测 K3s / 标准 K8s 环境，无需手动配置 kubeconfig
- 节点 / Pod / 工作负载 / Service / 存储 / 资源配额巡检
- Pod 日志查询、扩缩容、滚动重启、回滚

### Docker 容器管理

```
keeper> 查看 Docker 容器状态
keeper> 清理无用镜像
keeper> 重启 nginx 容器
```

### 漏洞扫描

需要系统安装 `nmap`：

```
keeper> 扫描 192.168.1.100 的安全漏洞

[端口扫描] 发现 12 个开放端口
[风险检测] ⚠️ 发现 2 个中风险项
```

### 根因分析 & 自动修复

```
keeper> 分析一下为什么 CPU 高
keeper> 帮我修复服务器问题
```

### 网络诊断

```
keeper> 测试 8.8.8.8 的延迟
keeper> 检查 192.168.1.100 的 3306 端口通不通
```

### 定时任务

```
keeper> 每 30 分钟检查一次 K8s 状态
keeper> 每天早上 9 点巡检所有服务器
```

### 报告导出 & 飞书通知

支持 JSON / HTML / Markdown 格式导出，巡检结果可自动推送到飞书群机器人。

---

## 命令参考

### 交互 & 单命令

| 命令 | 说明 |
|------|------|
| `keeper` | 启动交互模式 |
| `keeper run <command>` | 单命令执行 |
| `keeper exec -- <cmd>` | 执行 Shell 命令 |

### 配置

| 命令 | 说明 |
|------|------|
| `keeper init` | 初始化配置 |
| `keeper config set --api-key xxx` | 配置 LLM |
| `keeper config set --threshold 80 --metric cpu` | 设置阈值 |
| `keeper config set --profile production` | 切换环境 |
| `keeper config show` | 查看当前配置 |
| `keeper status` | 显示状态 |

### K8s

| 命令 | 说明 |
|------|------|
| `keeper k8s inspect` | 集群巡检 |
| `keeper k8s logs <pod>` | Pod 日志 |
| `keeper k8s events` | Warning 事件 |
| `keeper k8s exec <pod> -- <cmd>` | Pod 内执行命令 |
| `keeper k8s scale <deploy> -r 5` | 扩缩容 |
| `keeper k8s restart <deploy>` | 滚动重启 |

### Docker

| 命令 | 说明 |
|------|------|
| `keeper docker ls` | 列出容器 |
| `keeper docker stats` | 资源统计 |
| `keeper docker images` | 列出镜像 |
| `keeper docker prune` | 清理镜像 |

### 网络 & 其他

| 命令 | 说明 |
|------|------|
| `keeper network ping <host>` | Ping 测试 |
| `keeper network port <host> <port>` | 端口检测 |
| `keeper network dns <domain>` | DNS 查询 |
| `keeper network http <url>` | HTTP 检查 |
| `keeper schedule list/add/remove` | 定时任务 |
| `keeper fix suggest/verify` | 自动修复 |
| `keeper cert scan/check-domain` | 证书监控 |
| `keeper notify config/test/status` | 飞书通知 |
| `keeper logs --hours 24` | 操作记录 |

---

## 技术栈

| 组件 | 技术 |
|------|------|
| CLI | Click + Prompt Toolkit |
| NLU | LangChain + LLM (OpenAI 兼容 / Anthropic) |
| 系统监控 | psutil |
| K8s | kubernetes SDK |
| Docker | subprocess 调用 Docker CLI |
| 远程执行 | paramiko (SSH) |
| 漏洞扫描 | Nmap |
| 定时任务 | schedule 库 |

---

## 开发环境

```bash
git clone git@github.com:seventhocean/Keeper.git
cd Keeper
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pytest tests/
```

---

## 常见问题

**Q: 如何快速安装？**
A: `curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash`

**Q: 配置文件在哪里？**
A: `~/.keeper/config.yaml`，首次运行 `keeper init` 自动创建。

**Q: 支持哪些 LLM？**
A: 支持 OpenAI 兼容 API 和 Anthropic API。

**Q: 没有 API Key 能用吗？**
A: 需要配置 LLM API Key 才能使用自然语言理解功能。

**Q: 漏洞扫描需要额外安装什么？**
A: 需要系统安装 `nmap`（`sudo apt install nmap`）。

---

## License

MIT
