"""自动修复建议生成与执行引擎"""
import subprocess
import json
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum


class SafetyLevel(Enum):
    """修复命令安全等级"""
    SAFE = "safe"           # 只读/低风险，如查看日志、检查状态
    CAUTION = "caution"     # 中等风险，如重启服务、清理文件
    DANGEROUS = "dangerous" # 高风险，如删除文件、修改配置


@dataclass
class FixSuggestion:
    """单个修复建议"""
    title: str              # 修复标题
    description: str        # 问题描述
    command: str            # 修复命令
    safety: SafetyLevel     # 安全等级
    expected_result: str    # 预期结果
    rollback: str           # 回滚方法


@dataclass
class FixPlan:
    """修复计划"""
    summary: str                        # 问题摘要
    diagnosis: str                      # 诊断结论
    suggestions: List[FixSuggestion]    # 修复建议列表
    llm_advice: str                     # LLM 建议文本


class FixSuggester:
    """修复建议生成器 — 基于规则 + LLM 生成安全的修复命令"""

    # 高危命令黑名单 — 不允许 LLM 生成
    DANGEROUS_PATTERNS = [
        r"\brm\s+-rf\s+/",            # rm -rf /
        r"\bdd\s+if=",                  # dd 写磁盘
        r"\bmkfs\b",                    # 格式化磁盘
        r">\s*/etc/",                   # 重写系统配置
        r">\s*/boot/",                  # 写 boot
        r"chmod\s+777\s+/",             # 全局 777
        r"kill\s+-9\s+1\b",             # kill init
        r":\(\)\{\s*:\|:\s*&\s*\};:",   # fork bomb
        r"\bupdate-grub\b",             # 更新引导
    ]

    # 安全命令白名单模式
    SAFE_COMMANDS = [
        r"^systemctl\s+(status|restart|stop|start|reload)\s+",
        r"^journalctl\s+",
        r"^docker\s+(restart|stop|start|logs|prune)",
        r"^kubectl\s+(get|describe|logs|rollout)",
        r"^find\s+\S+\s+-name\s+\S+\s+-mtime\s+\S+\s+-delete",
        r"^apt-get\s+(clean|autoremove)",
        r"^yum\s+clean\s+",
        r"^truncate\s+-s",
        r"^echo\s+\S+\s*>\s*/dev/null",
    ]

    @classmethod
    def classify_command_safety(cls, command: str) -> SafetyLevel:
        """分类命令安全等级"""
        cmd = command.strip().lower()

        # 黑名单检查
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, cmd):
                return SafetyLevel.DANGEROUS

        # 白名单检查
        for pattern in cls.SAFE_COMMANDS:
            if re.search(pattern, cmd):
                return SafetyLevel.CAUTION

        return SafetyLevel.CAUTION

    @classmethod
    def generate_rule_based_fixes(cls, data: Dict[str, Any]) -> List[FixSuggestion]:
        """基于规则生成修复建议（不依赖 LLM）"""
        fixes = []

        # 磁盘空间不足
        disk_pct = data.get("disk_percent", 0)
        if disk_pct > 85:
            fixes.append(FixSuggestion(
                title="清理系统磁盘空间",
                description=f"磁盘使用率 {disk_pct}%，超过 85% 阈值",
                command="journalctl --vacuum-size=100M",
                safety=SafetyLevel.CAUTION,
                expected_result="释放日志占用的磁盘空间",
                rollback="无需回滚",
            ))
            fixes.append(FixSuggestion(
                title="清理 Docker 无用数据",
                description="Docker 可能占用了大量磁盘空间",
                command="docker system prune -f",
                safety=SafetyLevel.CAUTION,
                expected_result="清理已停止容器、无用镜像和构建缓存",
                rollback="无需回滚",
            ))

        # 内存不足
        mem_pct = data.get("memory_percent", 0)
        swap_pct = data.get("swap_percent", 0)
        if mem_pct > 85:
            top_mem = data.get("top_memory_processes", [])
            top_name = top_mem[0]["name"] if top_mem else "未知"
            fixes.append(FixSuggestion(
                title="释放内存 - 重启高内存进程",
                description=f"内存使用率 {mem_pct}%，{top_name} 占用最高",
                command=f"systemctl restart {top_name}",
                safety=SafetyLevel.CAUTION,
                expected_result=f"重启 {top_name} 释放内存",
                rollback=f"如果重启失败: systemctl start {top_name}",
            ))

        if swap_pct > 50:
            fixes.append(FixSuggestion(
                title="Swap 使用过高",
                description=f"Swap 使用率 {swap_pct}%，可能影响性能",
                command="free -h && echo '---' && ps aux --sort=-%mem | head -10",
                safety=SafetyLevel.SAFE,
                expected_result="查看占用 Swap 的进程",
                rollback="无需回滚",
            ))

        # 系统负载过高
        load_avg = data.get("load_avg", {})
        load_per_cpu = data.get("load_per_cpu", 0)
        if load_per_cpu > 2.0:
            fixes.append(FixSuggestion(
                title="系统负载过高",
                description=f"每核心负载 {load_per_cpu}，远超正常值 1.0",
                command="ps aux --sort=-%cpu | head -10",
                safety=SafetyLevel.SAFE,
                expected_result="查看占用 CPU 的进程",
                rollback="无需回滚",
            ))

        # 网络错误
        net = data.get("network", {})
        if net.get("errin", 0) > 100 or net.get("errout", 0) > 100:
            fixes.append(FixSuggestion(
                title="网络错误过多",
                description=f"网络入错误 {net.get('errin', 0)}, 出错误 {net.get('errout', 0)}",
                command="ip link show && ethtool -S eth0 2>/dev/null || echo 'ethtool 未安装'",
                safety=SafetyLevel.SAFE,
                expected_result="检查网络接口状态和错误统计",
                rollback="无需回滚",
            ))

        # 错误日志
        if data.get("error_logs"):
            error_logs = data["error_logs"]
            # 检测服务失败
            if "Failed to start" in error_logs:
                fixes.append(FixSuggestion(
                    title="排查启动失败的服务",
                    description="系统日志中有服务启动失败记录",
                    command="systemctl list-units --state=failed",
                    safety=SafetyLevel.SAFE,
                    expected_result="列出启动失败的服务",
                    rollback="无需回滚",
                ))
            # 检测 OOM
            if "Out of memory" in error_logs or "oom" in error_logs.lower():
                fixes.append(FixSuggestion(
                    title="OOM 问题排查",
                    description="系统曾触发 OOM Killer",
                    command="dmesg -T | grep -i oom | tail -10",
                    safety=SafetyLevel.SAFE,
                    expected_result="查看被 OOM Killer 终止的进程",
                    rollback="无需回滚",
                ))
            # 检测 SSH 暴力破解
            if "Failed password" in error_logs:
                fixes.append(FixSuggestion(
                    title="SSH 暴力破解防护",
                    description="检测到 SSH 失败登录",
                    command="journalctl -u sshd | grep 'Failed password' | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn | head -10",
                    safety=SafetyLevel.SAFE,
                    expected_result="列出 SSH 暴力破解的源 IP",
                    rollback="无需回滚",
                ))

        return fixes

    @classmethod
    def validate_command(cls, command: str) -> Tuple[bool, str]:
        """验证修复命令的安全性"""
        # 黑名单检查
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return False, f"命令被拒绝：包含高危操作（安全规则）"

        # 长度限制
        if len(command) > 500:
            return False, "命令过长（超过 500 字符），请拆分为多个步骤"

        # 管道符限制（防止命令注入）
        if command.count("|") > 3:
            return False, "命令包含过多管道符，可能存在注入风险"

        # 分号限制（防止多命令串联）
        if command.count(";") > 2:
            return False, "命令包含过多分号，请拆分为多个独立步骤"

        return True, "命令安全检查通过"

    @classmethod
    def execute_command(cls, command: str, host: str = "localhost", timeout: int = 60) -> Tuple[bool, str]:
        """执行修复命令

        Args:
            command: 要执行的命令
            host: 目标主机（localhost 表示本地）
            timeout: 超时秒数

        Returns:
            (success, output)
        """
        if host == "localhost":
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = result.stdout or result.stderr
                return result.returncode == 0, output.strip()[:2000]
            except subprocess.TimeoutExpired:
                return False, f"命令执行超时（{timeout}s）"
            except Exception as e:
                return False, f"执行失败：{str(e)}"
        else:
            # 远程执行
            from .ssh import SSHTools, SSHConfig
            ssh_config = SSHConfig(host=host)
            return SSHTools.execute(ssh_config, command)

    @classmethod
    def verify_fix(cls, data_before: Dict[str, Any], data_after: Dict[str, Any], metric: str) -> Tuple[bool, str]:
        """验证修复效果

        Args:
            data_before: 修复前数据
            data_after: 修复后数据
            metric: 要验证的指标

        Returns:
            (improved, message)
        """
        metric_map = {
            "disk": ("disk_percent", "%"),
            "memory": ("memory_percent", "%"),
            "cpu": ("cpu_percent", "%"),
            "load": ("load_avg", ""),
        }

        if metric not in metric_map:
            return True, "修复完成"

        key, unit = metric_map[metric]
        before_val = data_before.get(key, 0)
        after_val = data_after.get(key, 0)

        if isinstance(before_val, dict):
            # load_avg 是字典
            before_val = before_val.get("1m", 0)
            after_val = after_val.get("1m", 0)

        if after_val < before_val:
            delta = before_val - after_val
            return True, f"改善 {delta:.1f}{unit} ({before_val:.1f} → {after_val:.1f}{unit})"
        elif after_val == before_val:
            return False, f"指标未变化 ({after_val:.1f}{unit})"
        else:
            delta = after_val - before_val
            return False, f"指标恶化 {delta:.1f}{unit} ({before_val:.1f} → {after_val:.1f}{unit})"

    @classmethod
    def format_fix_plan(cls, plan: FixPlan) -> str:
        """格式化修复计划"""
        lines = ["[自动修复]", "=" * 50]
        lines.append(f"  问题摘要：{plan.summary}")
        lines.append(f"  诊断结论：{plan.diagnosis}")
        lines.append("")
        lines.append("━" * 50)
        lines.append(f"  修复建议 ({len(plan.suggestions)} 个):")
        lines.append("━" * 50)

        for i, fix in enumerate(plan.suggestions, 1):
            safety_icon = {
                SafetyLevel.SAFE: "🟢",
                SafetyLevel.CAUTION: "🟡",
                SafetyLevel.DANGEROUS: "🔴",
            }[fix.safety]

            lines.append(f"\n  [{i}] {safety_icon} {fix.title}")
            lines.append(f"      问题：{fix.description}")
            lines.append(f"      命令：{fix.command}")
            lines.append(f"      预期：{fix.expected_result}")
            lines.append(f"      回滚：{fix.rollback}")

        lines.append("")
        lines.append("=" * 50)
        lines.append("请输入编号执行修复，或说'全部执行'批量修复。")
        return "\n".join(lines)


def generate_fix_prompt_from_data(data: Dict[str, Any]) -> str:
    """生成 LLM 修复建议 prompt"""
    # 获取当前问题
    issues = []
    if data.get("disk_percent", 0) > 85:
        issues.append(f"磁盘使用率 {data['disk_percent']}%")
    if data.get("memory_percent", 0) > 85:
        issues.append(f"内存使用率 {data['memory_percent']}%")
    if data.get("load_per_cpu", 0) > 2.0:
        issues.append(f"每核心负载 {data['load_per_cpu']}")
    if data.get("network", {}).get("errin", 0) > 100:
        issues.append(f"网络入错误 {data['network']['errin']}")
    if data.get("error_logs"):
        issues.append("系统日志中存在错误信息")

    return f"""你是一个资深运维工程师，以下服务器存在以下问题：

## 当前问题
{chr(10).join(f'- {i}' for i in issues)}

## 监控数据
CPU: {data.get('cpu_percent', 0)}% ({data.get('cpu_count', 0)} 核心)
内存: {data.get('memory_percent', 0)}% ({data.get('memory_used_gb', 0)}GB / {data.get('memory_total_gb', 0)}GB)
磁盘: {data.get('disk_percent', 0)}% ({data.get('disk_used_gb', 0)}GB / {data.get('disk_total_gb', 0)}GB)
负载: {data.get('load_avg', {})}

## Top CPU 进程
{chr(10).join(f'- {p["name"]} CPU:{p["cpu_percent"]}%' for p in data.get('top_cpu_processes', [])[:5])}

## Top 内存进程
{chr(10).join(f'- {p["name"]} MEM:{p["memory_percent"]}%' for p in data.get('top_memory_processes', [])[:5])}

## 错误日志摘要
{data.get('error_logs', '无')[:500]}

请提供具体的修复命令。每条命令必须：
1. 是安全的（不删除系统关键文件，不破坏服务）
2. 有明确的预期效果
3. 最好有回滚方案
4. 只输出可直接执行的命令，不要输出说明文字"""
