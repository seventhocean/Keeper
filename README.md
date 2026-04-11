# Keeper

智能运维 Agent - 交互式 CLI 工具

**产品形态：** 类似 Claude Code 的对话式 CLI Agent

**项目定位：** 
- 轻量化的智能运维助手
- 通过自然语言对话完成服务器巡检、漏洞扫描、异常诊断
- 基于 LangChain + LLM 实现自然语言理解
- **版本：** v0.4.0-dev (2026-04-11)

---

## 快速开始

### 一键安装（推荐）

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Agent_Project/main/install.sh | bash
```

自动检测 Python → 创建隔离环境 → 安装依赖 → 注册命令。开箱即用！

### 手动安装（开发模式）

```bash
git clone https://github.com/Winter-wyh1314/Keeper.git
cd Keeper
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -e .
```

### 初始化配置

```bash
keeper init
```

### 初始化配置

```bash
keeper init
```

### 配置 API Key

```bash
# 使用 qnaigc (OpenAI 兼容)
keeper config set --api-key YOUR_API_KEY \
  --base-url https://api.qnaigc.com/v1 \
  --model doubao-seed-2.0-mini

# 或使用 Anthropic
keeper config set --provider anthropic \
  --api-key YOUR_API_KEY \
  --model claude-sonnet-4-6

# 查看配置
keeper config show
```

> **提示：** API Key 会保存在 `~/.keeper/api_key`（权限 600），不会提交到版本控制。

### 5. 启动 Agent

> 一键安装的用户可直接运行 `keeper`，无需手动激活虚拟环境。

```bash
keeper
```

进入交互式对话模式，支持自然语言交流：

```
┌─────────────────────────────────────────┐
│  Keeper v0.4.0-dev - 智能运维助手        │
└─────────────────────────────────────────┘

👋 你好！我是 Keeper，你的智能运维助手。
   已连接：https://api.qnaigc.com/v1 (deepseek/deepseek-v3.2-251201)

keeper> 帮我检查一下 spring 这台机器
keeper> K8s 集群状态怎么样？
keeper> 批量巡检所有服务器
keeper> 查看系统有没有什么问题
```

### 单命令模式（非交互）

```bash
# 快速执行
keeper run 检查 192.168.1.100

# 带参数
keeper run 巡检 --host 192.168.1.100

# 使用配置
keeper run 扫描 --profile production --full
```

---

## 核心功能 (MVP)

### 1. 智能对话

Keeper 基于 LLM 理解自然语言，支持两种交互模式：

**任务模式（运维操作）：**
```
keeper> 检查 192.168.1.100

[✓] 服务器健康检查 - localhost
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CPU:     5.0%  (阈值：90%)  ✓
  内存：   80.2%  (阈值：90%)  ✓
  磁盘：   64.8%  (阈值：95%)  ✓
  负载：   0.30  (阈值：8)    ✓

健康评分：100/100
```

**闲聊模式（知识问答/打招呼）：**
```
keeper> 你好

你好！我是 Keeper，有什么运维相关的需求都可以告诉我哦~

keeper> CPU 使用率高怎么办？

CPU 使用率较高时，你可以先通过 top、htop 等命令查看占用 CPU 资源较多
的进程，定位具体异常程序；也可以检查是否有恶意进程、服务配置不合理等
情况，还可以根据需要调整进程优先级或优化业务程序。
```

### 2. 多轮对话 & 记忆

Keeper 记住上下文，支持连续对话和指代消解：

```
keeper> 检查 192.168.1.100
[返回检查结果]

keeper> 那 192.168.1.101 呢？
[自动理解"呢"表示同样操作，检查另一台主机]

keeper> 把它的阈值调到 75%
[自动识别"它"指代上一台主机]
```

### 3. 服务器资源巡检

| 指标 | 说明 | 默认阈值 |
|------|------|----------|
| CPU 使用率 | 当前 CPU 占用百分比 | 90% |
| 内存使用率 | RAM 占用百分比 | 90% |
| 磁盘使用率 | 根分区占用百分比 | 95% |
| 系统负载 | 1 分钟平均负载 | CPU 核心数 * 2 |
| 异常进程 | CPU/内存占用 Top5 进程 | - |

### 4. 漏洞扫描

需要安装 `nmap` 后使用：

```
keeper> 扫描 192.168.1.100 的安全漏洞

[端口扫描] 发现 12 个开放端口
[服务识别] SSH(22), HTTP(80), MySQL(3306)...
[风险检测] ⚠️ 发现 2 个中风险项

1. SSH 使用密码登录 (建议改用密钥)
2. MySQL 绑定 0.0.0.0 (建议限制 IP)
```

### 5. 报告导出

巡检完成后可导出为多种格式：

```
keeper> 导出为 JSON
[报告] JSON 报告已保存至: ./keeper_report_20260409_103000.json

keeper> 生成 HTML 报告
[报告] HTML 报告已保存至: ./keeper_report_20260409_103000.html

keeper> 保存为 Markdown
[报告] Markdown 报告已保存至: ./keeper_report_20260409_103000.md
```

### 6. 系统日志查询

支持查询系统日志、容器日志等：

```
keeper> 查看系统日志
keeper> 查看 Nginx 的访问日志
keeper> 查看 nginx 容器日志
keeper> 查看 /var/log/syslog 最后 100 行
```

### 7. 审计日志

所有操作自动记录，支持查询历史：

```
keeper> 查看最近的操作记录
keeper> 过去 24 小时做了什么？
keeper> 查看对 192.168.1.100 的操作
```

---

## 命令参考

### 交互模式

```bash
keeper          # 直接启动交互式对话
keeper chat     # 也可使用此命令（向后兼容）
```

### 单命令模式

```bash
keeper run 检查 192.168.1.100             # 自然语言命令
keeper run 巡检 --host 192.168.1.100      # 带参数
keeper run 扫描 --profile production      # 使用配置
keeper run 扫描 --full                    # 完整扫描
```

### 配置命令

```bash
keeper init                               # 初始化配置文件
keeper config set --api-key xxx           # 设置 API Key
keeper config set --threshold 90 --metric cpu  # 设置阈值
keeper config set --k8s-kubeconfig /path/to/kubeconfig  # K8s 配置
keeper config set --k8s-context k3s-default  # K8s 上下文
keeper config show                        # 查看配置
keeper config clear                       # 清除配置
keeper status                             # 显示当前状态
keeper logs --hours 24                    # 查看操作记录
keeper logs --host 192.168.1.100          # 按主机过滤
keeper logs --json                        # JSON 格式输出
```

### K8s 命令

```bash
keeper k8s inspect                        # K8s 集群巡检
keeper k8s inspect -n kube-system         # 指定 namespace
keeper k8s logs <pod> [--lines 50]        # Pod 日志查询
keeper k8s logs <pod> -n kube-system      # 指定 namespace
keeper k8s events                         # 查看 Warning 事件
keeper k8s inspect --kubeconfig /etc/rancher/k3s/k3s.yaml  # 指定 kubeconfig
```

### 支持的意图

| 意图 | 说明 | 示例 |
|------|------|------|
| inspect | 服务器巡检 | "检查 192.168.1.100", "看看这台机器健康吗" |
| batch_inspect | 批量巡检 | "批量检查所有服务器", "巡检所有主机" |
| scan | 漏洞扫描 | "扫描漏洞", "检查有没有安全问题" |
| config | 配置管理 | "保存配置", "切换到 production" |
| logs | 日志查询 | "查看最近操作", "查看系统日志" |
| export | 报告导出 | "导出为 JSON", "生成 HTML 报告" |
| k8s_inspect | K8s 巡检 | "检查 K8s 集群", "K8s 巡检" |
| k8s_logs | K8s 日志 | "查看 coredns 的 Pod 日志" |
| k8s_export | K8s 报告 | "导出 K8s 巡检报告" |
| help | 帮助 | "你能做什么？", "帮助" |
| chat | 闲聊/知识问答 | "你好", "CPU 使用率高怎么办" |

---

## 技术架构

### 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| CLI 框架 | Click + Prompt Toolkit | 命令行解析 + 交互式输入 |
| NLU 引擎 | LangChain + LLM | 自然语言理解 |
| LLM 提供商 | OpenAI 兼容 / Anthropic | 支持多种 API |
| 系统监控 | psutil | 资源采集 |
| 漏洞扫描 | Nmap | 端口/服务扫描 |
| 配置管理 | PyYAML | YAML 解析 |
| 日志 | logging | 结构化日志 |

### 目录结构

```
├── keeper/
│   ├── __init__.py
│   ├── cli.py            # Click 入口 + 交互模式
│   ├── config.py         # 配置管理
│   ├── nlu/
│   │   ├── base.py       # NLU 抽象基类
│   │   └── langchain_engine.py  # LangChain 引擎实现
│   ├── core/
│   │   ├── agent.py      # Agent 核心（意图分发、K8s 自动检测）
│   │   ├── context.py    # 上下文管理 + 记忆系统
│   │   └── audit.py      # 审计日志持久化
│   └── tools/
│       ├── server.py     # 服务器工具 (psutil)
│       ├── scanner.py    # 扫描工具 (Nmap)
│       ├── ssh.py        # SSH 远程采集
│       ├── reporter.py   # 报告导出 (JSON/HTML/MD)
│       ├── logs.py       # 系统日志查询
│       ├── docker_tools.py  # Docker 容器管理
│       ├── network.py    # 网络诊断 (ping/port/dns/http)
│       ├── rca.py        # 根因分析引擎
│       ├── fixer.py      # 自动修复建议
│       ├── scheduler.py  # 定时任务管理
│       ├── cert_monitor.py # SSL 证书监控
│       ├── notify.py     # 飞书通知推送
│       ├── alert.py      # 告警规则引擎
│       └── k8s/
│           ├── client.py       # K8s 客户端封装
│           ├── inspector.py    # K8s 集群巡检
│           ├── formatter.py    # 巡检报告格式化
│           ├── logs.py         # Pod 日志查询 & exec
│           └── ops.py          # K8s 深度操作（扩缩容/重启/回滚）
├── tests/
│   ├── test_keeper.py    # 核心测试
│   ├── test_audit.py     # 审计日志测试
│   ├── test_reporter.py  # 报告导出测试
│   └── test_logs.py      # 日志查询测试
├── keeper_entry.py       # 入口脚本
├── pyproject.toml        # 项目配置
└── README.md
```

### NLU 解析流程

```
用户输入 → LLM 判断 → is_task?
              ├─ yes → 意图识别 → 工具调用 → 返回报告
              └─ no  → 直接回复 → 显示响应
```

### 支持的 LLM 提供商

| 提供商 | Base URL | 推荐模型 |
|--------|----------|----------|
| OpenAI 兼容 | https://api.qnaigc.com/v1 | doubao-seed-2.0-mini |
| Anthropic | https://api.qnaigc.com | claude-sonnet-4-6 |

---

## 记忆系统

### 短期记忆（会话内）
- 保留最近 10 轮对话
- 记住上下文中的实体（主机、环境、阈值等）
- 支持指代消解（"它"、"这台"、"那台"）
- 会话结束即清除

### 长期记忆（持久化）
- 用户配置偏好
- 常用主机列表
- 历史巡检记录
- YAML 文件存储于 `~/.keeper/`

### 上下文示例

```
用户："检查 192.168.1.100"           → 记住当前主机
 Keeper："CPU 45%，内存 62%..."
用户："那 192.168.1.101 呢？"        → 理解"呢"表示同样操作
 Keeper："正在检查 192.168.1.101..."
用户："把它的阈值调到 75%"           → "它"指代上一台主机
 Keeper："已更新 192.168.1.101 的阈值为 75%"
```

---

## 配置

### 配置文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 主配置 | `~/.keeper/config.yaml` | 环境配置、阈值、主机列表 |
| LLM 配置 | `~/.keeper/llm_config.yaml` | LLM 设置（provider, model, base_url） |
| API Key | `~/.keeper/api_key` | 敏感信息，权限 600 |

### 使用 config 命令

```bash
# 设置 API Key
keeper config set --api-key YOUR_API_KEY

# 设置 Base URL 和模型
keeper config set --base-url https://api.qnaigc.com/v1 \
  --model doubao-seed-2.0-mini

# 切换 Provider
keeper config set --provider anthropic

# 设置 K8s 配置（自动检测环境时可省略）
keeper config set --k8s-kubeconfig /etc/rancher/k3s/k3s.yaml
keeper config set --k8s-context k3s-default
keeper config set --k8s-type k3s

# 查看配置
keeper config show

# 清除配置
keeper config clear
```

### 配置文件结构

```yaml
# ~/.keeper/config.yaml
current_profile: dev

profiles:
  dev:
    hosts:
      - 192.168.1.100
      - 192.168.1.101
    thresholds:
      cpu: 80
      memory: 85
      disk: 90

  production:
    hosts:
      - 10.0.0.1
      - 10.0.0.2
    thresholds:
      cpu: 70
      memory: 80
      disk: 85
```

---

## 安全设计

### 操作审计

所有操作记录到 `~/.keeper/audit.log`:

```json
{"timestamp": "2026-04-08T10:00:00Z", "user": "gaoyuan", "intent": "server_inspect", "host": "192.168.1.100", "result": "success"}
```

### 高危操作确认

以下操作需要二次确认：
- 删除配置文件
- 批量操作 (>5 台主机)
- 执行系统修改命令

### 敏感信息保护
- API Key 保存在独立文件（`~/.keeper/api_key`）
- 文件权限 600（仅所有者可读写）
- 配置文件不存储明文密码
- 审计日志脱敏处理

---

## 开发计划

### Phase 1 - MVP (已完成 ✅)
- [x] CLI 框架搭建 (Click + Prompt Toolkit)
- [x] 交互模式入口 (`keeper` 命令，无子命令直接进入对话)
- [x] LangChain NLU 引擎（支持任务/闲聊判断）
- [x] 服务器资源巡检 (psutil)
- [x] 对话记忆系统
- [x] 配置管理（分离敏感信息）
- [x] 单元测试
- [x] 漏洞扫描集成 (Nmap)
- [x] CLI 入口优化（`keeper` 直接进入交互模式）

### Phase 2 - 增强功能 (已完成 ✅)
- [x] 报告生成 (JSON/HTML/Markdown)
- [x] 多主机批量巡检（SSH + 线程池并行）
- [x] SSH 远程采集（base64 编码执行 Python 脚本，避免转义问题）
- [x] 审计日志持久化 (audit.log)
- [x] 系统日志查询 (journalctl, /var/log, Docker)
- [x] 系统异常自动检测（SSH 暴力登录/OOM/磁盘 I/O/服务失败）
- [x] 31 个测试用例全部通过

### Phase 3 - K8s 集群管理 (已完成 ✅)

#### K8s 集群巡检
```
keeper> 检查 K8s 集群状态

[K8s 巡检] 集群巡检报告
集群类型：  k3s
K8s 版本：  v1.34.6+k3s1
节点数量：  1
健康评分：100/100 - 健康
```

自动检测 K3s / 标准 K8s 环境，一键巡检：
- **Node 检查** — Ready 状态、角色、版本、可调度状态、Taints
- **Pod 检查** — 异常检测（Pending/Failed/CrashLoopBackOff/OOMKilled/ImagePullBackOff）
- **工作负载** — Deployment/StatefulSet/DaemonSet 副本数与滚动更新状态
- **Service 检查** — 类型、端口映射、Endpoints 健康
- **存储巡检** — PVC/PV 绑定状态、StorageClass、容量
- **ConfigMap/Secret** — 过大 ConfigMap、TLS 证书过期检测、空资源清理提示
- **Ingress** — 路由规则、TLS 配置、后端服务验证
- **LimitRange** — Namespace 资源限制检查
- **ResourceQuota** — 资源配额使用率对比
- **Warning 事件** — 聚合去重，Top 20 展示
- **健康评分** — 0-100 分，综合节点/Pod/工作负载/事件计算

#### K8s 日志查询
```
keeper> 查看 coredns 的日志
keeper> 查看 kube-system 下 coredns 最近 50 行日志
```
支持 Pod 模糊匹配、namespace 指定、行数限制、容器指定。

#### K8s 命令
```bash
keeper k8s inspect                        # K8s 集群巡检
keeper k8s inspect -n kube-system         # 指定 namespace
keeper k8s logs <pod-name>                # 查看 Pod 日志
keeper k8s logs <pod> --namespace kube-system  # 指定 namespace
keeper k8s events                         # 查看 Warning 事件
keeper k8s inspect --kubeconfig /path/to/config  # 指定 kubeconfig
```

#### K3s 自动检测
自动搜索 kubeconfig 路径（`/etc/rancher/k3s/k3s.yaml` → `~/.kube/config`），
自动识别集群类型（k3s / 标准 K8s），无需手动配置。

### Phase 4 - 智能分析与变更 (v0.4.0-dev)
- [x] Docker 容器管理（列表/统计/镜像/清理/操作）
- [x] 根因分析 (RCA) — 进程级/依赖链分析 + 双机对比
- [x] 网络诊断（Ping/端口/DNS/HTTP/Traceroute）
- [x] K8s 深度操作（扩缩容/重启/回滚/Exec）
- [x] 定时任务管理（Cron 表达式）
- [x] 自动修复建议（规则引擎 + LLM 生成 + 安全拦截）
- [x] SSL/TLS 证书监控（本地文件/K8s Secret/域名）
- [x] 飞书通知推送（Webhook + 签名校验）
- [x] 告警规则引擎（阈值/异常/自动告警）

### Phase 5 - 安全与集成
- [ ] 安全基线检查 (CIS Benchmark/弱密码/端口暴露)
- [ ] 操作审计报表（定期生成）
- [ ] Prometheus 告警集成
- [ ] IM 通知扩展（钉钉/企业微信/Slack）

---

## 开发环境

### 一键安装（用户）

```bash
curl -sSL https://raw.githubusercontent.com/seventhocean/Agent_Project/main/install.sh | bash
```

### 开发者模式

```bash
# 克隆源码
git clone https://github.com/Winter-wyh1314/Keeper.git
cd Keeper

# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/

# 代码检查
flake8 keeper/
black --check keeper/
```

### 升级

---

## 常见问题

**Q: 如何快速安装？**
A: 一条命令：`curl -sSL https://raw.githubusercontent.com/seventhocean/Agent_Project/main/install.sh | bash`

**Q: 如何在本地测试？**
A: 使用 `keeper` 进入交互模式，或运行 `keeper run 检查 localhost`

**Q: 配置文件在哪里？**
A: `~/.keeper/config.yaml`，首次运行 `keeper init` 自动创建

**Q: 如何查看操作记录？**
A: `keeper logs --hours 24` 或对话中输入 "查看最近的操作记录"

**Q: 如何导出巡检报告？**
A: 对话中说 "导出为 JSON" 或 "生成 HTML 报告"，也可命令行 `keeper run 巡检 --export json`

**Q: 支持哪些 LLM？**
A: 支持 OpenAI 兼容 API 和 Anthropic API，推荐使用 `doubao-seed-2.0-mini`

**Q: 没有 API Key 能用吗？**
A: 需要配置 LLM API Key 才能使用自然语言理解功能

**Q: 如何查看系统日志？**
A: 对话中说 "查看系统日志" 或 "查看 Nginx 的访问日志"，也可命令行 `keeper logs system --lines 50`

---

## License

MIT