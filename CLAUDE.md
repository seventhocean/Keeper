# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**Keeper** - 智能运维 Agent，类似 Claude Code 的对话式 CLI 工具

**版本：** v0.4.0-dev (2026-04-11)

## 开发进度

| 阶段 | 版本 | 状态 | 内容 |
|------|------|------|------|
| Phase 1 - MVP | v0.1.0 | ✅ 完成 | CLI 框架、NLU 引擎、服务器巡检、配置管理、对话记忆 |
| Phase 2 - 增强 | v0.2.0 | ✅ 完成 | 报告导出、审计日志、系统日志查询、多主机巡检、SSH 采集 |
| Phase 3 - K8s | v0.3.0 | ✅ 完成 | K8s 集群管理、资源巡检、异常检测、ConfigMap/Secret/Ingress/LimitRange |
| Phase 4 - 智能分析 | v0.4.0 | 🚧 开发中 | Docker 管理、根因分析、网络诊断、K8s 深度操作、定时任务、自动修复、证书监控 |
| Phase 5 - 安全集成 | v0.5.0 | 🔲 规划中 | 安全基线、审计报表、Prometheus 集成、IM 通知 |

## 快速命令

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行测试
pytest tests/ -v

# 启动交互模式（直接进入对话）
keeper

# 单命令执行
keeper run 检查 192.168.1.100

# 执行 Shell 命令
keeper exec -- df -h /
keeper exec -- ps aux --sort=-%mem

# 配置管理
keeper config set --threshold 80 --metric cpu
keeper config show

# 审计日志
keeper logs --hours 24
keeper logs --host 192.168.1.100
```

## 技术架构

### 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| NLU 引擎 | `keeper/nlu/` | LangChain + LLM 意图识别 |
| Agent 核心 | `keeper/core/` | 意图分发、上下文管理、审计日志 |
| 工具 | `keeper/tools/` | 服务器采集、扫描、报告导出、日志查询、K8s 管理 |
| CLI | `keeper/cli.py` | Click + Prompt Toolkit 交互 |
| 配置 | `keeper/config.py` | 环境变量 + YAML 配置 |

### 意图路由 (`keeper/core/agent.py`)

| 意图 | 处理器 | 功能 |
|------|--------|------|
| `inspect` | `_handle_inspect` | 服务器资源巡检 |
| `scan` | `_handle_scan` | 漏洞扫描 |
| `config` | `_handle_config` | 配置管理 |
| `logs` | `_handle_logs` | 日志查询（审计/系统/Docker） |
| `export` | `_handle_export` | 报告导出（JSON/HTML/MD） |
| `install` | `_handle_install` | 软件安装 |
| `confirm` | `_handle_confirm` | 确认执行 |

## 配置

### 配置文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 配置文件 | `~/.keeper/config.yaml` | 所有配置（LLM、环境、阈值、主机列表） |

### 配置结构

```yaml
# ~/.keeper/config.yaml
current_profile: dev
profiles:
  dev:
    hosts: [localhost]
    thresholds: {cpu: 90, memory: 90, disk: 95}
llm:
  provider: openai_compatible
  api_key: sk-xxx
  base_url: https://api.qnaigc.com/v1
  model: doubao-seed-2.0-mini
```

### 配置命令

```bash
keeper config set --api-key YOUR_API_KEY --model claude-sonnet-4-6
keeper config set --threshold 80 --metric cpu
keeper config show
keeper config clear
```

## 开发注意事项

1. **虚拟环境：** 所有命令需先激活 `venv/bin/activate`
2. **测试：** 修改代码后运行 `pytest tests/ -v`
3. **LLM 依赖：** 需要有效的 API Key 才能测试 NLU 功能
4. **本地采集：** `ServerTools.inspect_server("localhost")` 无需远程连接
5. **Nmap 依赖：** 漏洞扫描需要系统安装 `nmap` 包
6. **CLI 入口：** `keeper` 直接进入交互模式（`invoke_without_command=True`）

## 已实现功能

### Phase 1 - MVP ✅
- CLI 框架、NLU 引擎、服务器巡检、配置管理、对话记忆

### Phase 2 - 增强功能 ✅
- 报告导出 (JSON/HTML/Markdown)、审计日志持久化、系统日志查询 (journalctl/文件/Docker)、多主机批量巡检、SSH 远程采集

## Phase 3 - K8s 集群管理 (v0.3.0) ✅ 已完成

### K8s 客户端封装 ✅
- [x] `keeper/tools/k8s/client.py` — 基于 `kubernetes` Python SDK 封装
- [x] kubeconfig 加载与多集群上下文切换
- [x] 连接健康检查与超时重试
- [x] 自动检测 kubeconfig 路径（K3s/标准 K8s/in-cluster）
- [x] 自动识别集群类型（k8s/k3s）

### 资源状态检查 ✅
- [x] Node 状态检查 (Ready/角色/版本/资源容量)
- [x] Pod 状态检查与异常检测 (Pending/Failed/CrashLoopBackOff/OOMKilled/ImagePullBackOff)
- [x] Deployment/StatefulSet/DaemonSet 状态检查 (副本数/滚动更新/进度)
- [x] Service 配置检查 (类型/端口映射/Endpoints 健康)
- [x] PVC/PV 存储状态检查 (容量/绑定状态/StorageClass)

### K8s 巡检工具 ✅
- [x] `keeper/tools/k8s/inspector.py` — K8s 集群一键巡检
- [x] Namespace 资源配额监控 (ResourceQuota)
- [x] 集群事件聚合分析 (Warning 事件归类/去重)
- [x] 巡检结果与现有 ServerTools 输出格式统一
- [x] 健康评分计算 (0-100)
- [x] `keeper/tools/k8s/formatter.py` — 报告格式化输出

### Pod 日志查询 ✅
- [x] `keeper/tools/k8s/logs.py` — Pod 日志查询
- [x] Pod 模糊匹配/前缀匹配
- [x] 关键词过滤/行数限制/容器指定
- [x] Pod 内命令执行 (exec)

### NLU 意图扩展 ✅
- [x] `k8s_inspect` — "检查 K8s 集群状态" / "查看 Pod 情况" / "K8s 巡检"
- [x] `k8s_logs` — "查看 xxx Pod 的日志"
- [x] `k8s_export` — "导出 K8s 巡检报告"
- [x] `k8s_config` — "帮我配置 K8s"

### CLI 扩展 ✅
- [x] `keeper k8s inspect` — K8s 集群巡检
- [x] `keeper k8s logs <pod>` — 查看 Pod 日志
- [x] `keeper k8s events` — 查看集群事件
- [x] 配置文件 K8s 配置 (`config set --k8s-kubeconfig/--k8s-context/--k8s-type`)

### 交互设计 ✅
- [x] 自动检测 K3s/标准 K8s 环境并自动配置
- [x] 多个 kubeconfig 时询问用户选择
- [x] 问题排查模式（系统日志查询自动检测异常）

## Phase 4 - 智能分析与变更 (v0.4.0) 规划中
- [ ] 根因分析 (RCA) — 基于巡检结果的异常归因
- [ ] 告警分析 — 接入 Prometheus Alertmanager 告警历史
- [ ] 自动修复建议 — LLM 生成修复命令 + 人工确认执行
- [ ] 变更管理 — 扩缩容/重启/回滚的对话式操作

## Phase 5 - 安全与集成 (v0.5.0) 规划中
- [ ] 安全基线检查 — CIS Benchmark 自动化扫描
- [ ] 操作审计报表 — 定期生成运维操作审计报告
- [ ] 告警集成 — Prometheus/Webhook 告警接入
- [ ] IM 通知集成 — 钉钉/企业微信/Slack 消息推送
