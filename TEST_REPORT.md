# Keeper v0.5.0-dev E2E 测试报告

> 测试日期: 2026-05-15 ~ 2026-05-16 | 环境: Linux 6.8.0 | Python 3.12.3

---

## 总体结果

| 指标 | 数值 |
|------|------|
| 单元测试 | **374/374 passed** |
| 集成测试（新增） | 70 |
| E2E 功能验证 | 57 通过 / 8 跳过 / 0 失败 |

---

## 测试结果明细

### Agent 模式

| 测试项 | 状态 | 备注 |
|--------|------|------|
| Fast Path 中英文帮助 | ✅ | <1ms |
| 退出检测（exit/quit/退出） | ✅ | 设 is_running=False |
| 空输入处理 | ✅ | 返回空字符串 |
| /clear /history /tools /mode /memory | ✅ | 全部正常 |
| 未知斜杠命令 | ✅ | 显示可用命令 |
| Agent Loop 服务器巡检 | ✅ | LLM 调用结构化工具 + run_bash 混合 |
| Agent Loop 网络诊断 | ✅ | ping_host + dns_lookup |
| Agent Loop 流式执行 | ✅ | 实时展示 tool_call/tool_result |
| Agent Loop 错误恢复 | ✅ | 多工具调用，同工具 3 次警告 |
| Planner 模板匹配 | ✅ | CPU 高→cpu_high / 网络不通→network_issue |
| Memory 持久化 | ✅ | 操作后自动保存到 agent_memory.json |
| 任务分类（_classify_input） | ✅ | 检查→inspect / K8s→k8s |
| LLM 未配置降级 | ✅ | 友好提示 |
| 自服务引导（K8s SSH nmap） | ✅ | 可操作引导信息 |
| 首次启动交互式 API 配置 | ✅ | 不退出，引导输入 |

### CLI 命令

| 测试项 | 状态 | 备注 |
|--------|------|------|
| keeper status | ✅ | 显示完整配置 |
| keeper logs --hours 1 | ✅ | 审计记录查询 |
| keeper docker ls/stats/images | ✅ | 容器/镜像状态 |
| keeper network ping 8.8.8.8 | ✅ | 丢包 0%, 延迟 34.7ms |
| keeper network dns baidu.com | ✅ | 解析正常 |
| keeper cert check-domain baidu.com | ✅ | 剩余 86 天 |
| keeper run 检查本机 | ✅ | 健康评分 100/100 |
| keeper inspect_server | ✅ | 含 AlertEngine 自动告警 |
| keeper k8s inspect | ✅ | 友好提示 SDK 未安装 |
| keeper fix suggest | ✅ | 健康系统无修复建议 |
| keeper schedule list | ✅ | 暂无任务 |
| keeper run 扫描漏洞 | ✅ | 发现 2 端口 + SSH 风险 |

### 工具层

| 测试项 | 状态 | 备注 |
|--------|------|------|
| inspect_server | ✅ | + AlertEngine 自动触发 |
| get_top_processes | ✅ | 表格输出 |
| ping_host / check_port / dns_lookup | ✅ | 格式正确 |
| scan_ports (nmap) | ✅ | 已修复方法名 |
| check_ssl_cert | ✅ | 已修复方法名 |
| docker_list_containers | ✅ | 已修复 stats 参数 |
| manage_systemd_service | ✅ | 无效 action 报错 |
| execute_shell_command | ✅ | 危险命令拦截 |
| read_log_file | ✅ | 已修复方法名 |
| k8s_cluster_inspect | ✅ | 已修复为静态调用 |
| runbook_disk_cleanup | ✅ | 新增，6 步流程 |
| runbook_service_restart | ✅ | 新增，含回滚 |
| runbook_log_rotate | ✅ | 新增 |
| inspect_remote_server (SSH) | ✅ | 失败时有凭据引导 |

### 安全模块

| 测试项 | 状态 | 备注 |
|--------|------|------|
| rm -rf / 拦截 | ✅ | DANGEROUS 级拒绝 |
| dd / mkfs 拦截 | ✅ | DANGEROUS 级拒绝 |
| ps / df / grep 放行 | ✅ | READ_ONLY 直接执行 |
| systemctl restart 需确认 | ✅ | WRITE 级标记 |
| docker prune 需确认 | ✅ | DESTRUCTIVE 级 |
| TOOL_PERMISSIONS 表 | ✅ | 18 个工具全部有权限定义 |
| Agent Loop 内权限检查 | ✅ | WRITE 级工具显示 ⚠️ |

### 基础设施

| 测试项 | 状态 | 备注 |
|--------|------|------|
| Runbook 模板加载 | ✅ | 3 个模板，变量渲染 |
| Storage SQLite | ✅ | 已修复 string→Path |
| Snapshot 快照 | ✅ | 已修复 string→Path |
| Validators | ✅ | IP/主机/端口/注入 |
| Exceptions | ✅ | 8 个异常类 |
| Logger + Retry | ✅ | 结构化日志 + 指数退避 |
| Capacity / Comparator | ✅ | 无历史数据正确降级 |
| Compliance 导入 | ✅ | CIS Linux Basic |
| Prometheus 导入 | ✅ | 需要服务端 |
| API Server 导入 | ✅ | 需要 uvicorn |
| 钉钉/企微通知 导入 | ✅ | 需要 webhook |

---

## 跳过的测试项（均需外部依赖）

| 测试项 | 原因 |
|--------|------|
| K8s 集群巡检 | kubernetes SDK 未安装（可选依赖） |
| Prometheus 监控 | 需要 Prometheus 服务端 |
| API Server 运行 | 需要启动 uvicorn |
| 钉钉/企微 webhook | 需要真实 webhook URL |
| Compliance 全量检查 | 需要实际目标系统 |
| SSH 远程巡检 | 需要远程主机 |
| Timeline 时间线 | 需要历史数据 |
| 飞书通知发送 | 需要 webhook URL |

---

## 已修复的 Bug

| # | 文件 | 问题 | 严重度 |
|---|------|------|--------|
| 1 | tools_registry.py | ScannerTools.scan 方法不存在 | 🔴 |
| 2 | tools_registry.py | CertMonitor.check_domain 方法不存在 | 🔴 |
| 3 | tools_registry.py | LogTools.read_file 方法不存在 | 🔴 |
| 4 | tools_registry.py | K8sInspector 用实例调用静态方法 | 🔴 |
| 5 | tools_registry.py | format_docker_containers 缺参数 | 🔴 |
| 6 | tools_registry.py | docker_container_logs 绕过 DockerTools | 🟡 |
| 7 | planner.py | head-10 缺空格 | 🟡 |
| 8 | loop.py | state_modifier → prompt（langgraph 1.1.6） | 🔴 |
| 9 | loop.py | _run_langgraph 最后消息 content=None | 🟡 |
| 10 | loop.py | t_duration 作用域反模式 | 🟡 |
| 11 | storage/history.py | db_path 字符串未转 Path | 🟡 |
| 12 | tools/snapshot.py | snapshot_dir 字符串未转 Path | 🟡 |
| 13 | hybrid.py | _classify_input 顺序不当 | 🟡 |
| 14 | cli.py | K8s 命令缺少友好错误 | 🟡 |

---

## 新增功能

| 功能 | 描述 |
|------|------|
| 流式 Agent Loop | LangGraph stream_mode="updates"，实时展示 |
| 错误恢复 | 同工具 3 次警告 + 自动降级 |
| 自服务引导 | SSH/K8s/nmap 等失败时引导用户配置 |
| 交互式 API 配置 | 首次启动不退出，当场输入 API Key |
| Runbook 注册 | 3 个 @tool，LLM 可自主调度 |
| AlertEngine 自动触发 | inspect_server 后自动检查告警 |
| 审计 host 参数 | 从工具调用参数提取主机 |
| keeper run 统一 Agent | 默认走 HybridAgent + 流式回调 |
| 70 个新集成测试 | test_integration.py + test_tools_extended.py |
