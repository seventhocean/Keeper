# Keeper 统一运维记忆 — 规划文档

> 创建: 2026-05-16 | 版本: v1.0.0

---

## 目标

让 Keeper 成为「有记忆的运维管家」——不只执行任务，还记住系统状态变迁和过去的排查过程，支持溯源和线索追踪。

## 差异化定位（vs Claude Code）

| | Claude Code | Keeper（目标） |
|------|-------------|---------|
| 记忆内容 | 对话文本 | **系统状态变迁** |
| 时间维度 | 单次会话 | **跨天/周/月的趋势** |
| 溯源能力 | "上次讨论了什么" | "上周二 CPU 开始异常，跟周三的部署有关" |

## 现有组件

| 组件 | 记录什么 | 状态 |
|------|---------|------|
| `InspectionHistory` (SQLite) | CPU/内存/磁盘指标 | ✅ 已实现，未自动采集 |
| `AgentMemory` (JSON) | 用户问什么 + 工具用了什么 + 结论 | ✅ 已接入 Agent Loop |
| `AuditLogger` | 操作审计日志 | ✅ 每次 Agent 执行都记录 |
| `Timeline` (timeline.py) | 运维事件时间线 | ✅ 已写，未使用 |
| `Snapshot` (snapshot.py) | 系统状态快照 | ✅ 已写，未使用 |
| `Comparator` (comparator.py) | 巡检历史对比 | ✅ 已实现，未自动触发 |
| `CapacityPredictor` (capacity.py) | 容量预测 | ✅ 已实现，未自动触发 |

## 当前状态

- ✅ Agent 执行完自动保存记忆到磁盘
- ✅ 新会话加载历史记忆
- ❌ 新会话不向 LLM 注入「上次做了什么」
- 🟡 关键词匹配后才注入上下文（被动），不主动告知
- ❌ InspectionHistory 从不自动采集巡检数据

## 待实现

### P0: 会话启动时注入记忆摘要

- [ ] 在 `start_agent_chat` 或 `HybridAgent.process` 首次调用时，从 `AgentMemory` 读取最近 5 条记忆格式化为摘要文本
- [ ] 摘要作为第一条系统/上下文消息发送给 LLM
- [ ] 效果：用户打开 Keeper 就能看到「上次你在排查 xxx，结论是 yyy」

### P1: 巡检数据自动采集

- [ ] `inspect_server` 执行后自动写入 `InspectionHistory`（SQLite）
- [ ] 配合 `Comparator` 实现「和三天前对比，CPU 涨了 20%」
- [ ] 配合 `CapacityPredictor` 实现「按趋势，磁盘将在 7 天后满」

### P2: 统一记忆查询

- [ ] 新增 `Timeline` 查询能力，按时间线查看所有事件
- [ ] `/memory` 命令支持更多筛选维度（按日期/主机/类别）
- [ ] Agent 对话中支持「上周三发生了什么」

### P3: 主动告警

- [ ] 每次巡检后对比历史数据
- [ ] 自动检测异常趋势（如 CPU 连续 3 天上升）
- [ ] 主动通知用户而不是等着被问

## 目标体验

```
keeper🤖> 你好，Keeper v1.0.0

  📋 上次工作回顾 (最近3次):
    • 5/16 排查 CPU 异常 → nginx worker_connections 不足，已修复
    • 5/15 检查服务器 → 健康 100 分
    • 5/14 检查网络 → 正常

  📊 本周趋势: CPU ↑15%  内存 →  磁盘 ↓5%
  💡 一切正常，需要我做什么？

keeper🤖> 最近有异常吗？

  过去 7 天发现 1 次异常：
  📅 5/16 09:12  CPU 飙升至 68%（阈值 70%）
    根因: nginx worker_connections 不足
    处理: 调整配置后恢复 → 当前 CPU 35%
```
