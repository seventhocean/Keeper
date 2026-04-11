"""Agent 核心 - 意图处理和任务分发"""
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from .context import ContextManager, MemoryManager, AgentState
from .audit import AuditLogger
from ..nlu.base import NLUEngine, ParsedIntent, IntentType
from ..nlu.langchain_engine import LangChainEngine
from ..config import AppConfig
from ..tools.server import ServerTools, format_status_report, format_batch_report
from ..tools.scanner import ScannerTools, format_scan_result, NmapNotInstalledError
from ..tools.ssh import SSHTools, SSHConfig
from ..tools.docker_tools import DockerTools, format_docker_containers, format_docker_images
from ..tools.network import NetworkTools, format_ping_result, format_port_result, format_dns_result, format_http_result
from ..tools.rca import RCAEngine
from ..tools.fixer import FixSuggester, FixPlan, SafetyLevel, generate_fix_prompt_from_data
from ..tools.scheduler import TaskScheduler, format_task_list
from ..tools.cert_monitor import CertMonitor, format_cert_report


@dataclass
class PendingTask:
    """待确认任务"""
    task_type: str  # "install", "scan" 等
    package: Optional[str] = None
    host: Optional[str] = None
    message: Optional[str] = None


class Agent:
    """智能运维 Agent"""

    def __init__(self, nlu_engine: NLUEngine, config: Optional[AppConfig] = None):
        self.nlu = nlu_engine
        self.config = config or AppConfig.from_env()
        self.state = AgentState()
        self.state.is_running = True
        self.pending_task: Optional[PendingTask] = None
        self.audit = AuditLogger()  # 审计日志记录器
        self.scheduler = TaskScheduler(config_dir=self.config.config_dir)
        self.scheduler.set_callback(self._execute_scheduled_task)
        self.scheduler.start()

    def process(self, user_input: str) -> str:
        """处理用户输入

        Args:
            user_input: 用户输入文本

        Returns:
            str: Agent 回复
        """
        start_time = time.time()

        # 1. NLU 解析
        context_dict = {
            "last_host": self.state.context.current_host,
            "last_profile": self.state.context.current_profile,
            "last_intent": self.state.context.last_intent,
        }

        parsed = self.nlu.parse(user_input, context=context_dict)

        if parsed.error_message:
            # 记录审计日志
            response_time = int((time.time() - start_time) * 1000)
            self.audit.log_turn(
                intent="unknown",
                entities={},
                result="error",
                response_time_ms=response_time,
                error_message=parsed.error_message,
            )
            return f"[错误] NLU 解析失败：{parsed.error_message}"

        # 2. 如果不是任务，直接返回直接回复
        if not parsed.is_task:
            response = parsed.direct_response or "[系统] 抱歉，我没有理解您的意思。"
            # 非任务也记录到记忆，但不更新上下文
            self.state.memory.add_turn(
                user_input=user_input,
                agent_response=response,
                intent="chat",
                entities={},
            )
            # 记录审计日志
            response_time = int((time.time() - start_time) * 1000)
            self.audit.log_turn(
                intent="chat",
                entities={},
                result="success",
                response_time_ms=response_time,
            )
            return response

        # 3. 更新上下文（仅任务）
        self.state.context.update(parsed.intent.value, parsed.entities)

        # 4. 意图分发
        response = self._dispatch(parsed)

        # 5. 记录到记忆
        self.state.memory.add_turn(
            user_input=user_input,
            agent_response=response,
            intent=parsed.intent.value,
            entities=parsed.entities,
        )

        # 6. 记录审计日志
        response_time = int((time.time() - start_time) * 1000)
        is_error = response.startswith("[错误]") or response.startswith("[扫描] 扫描失败") or response.startswith("[巡检] 检查失败")
        self.audit.log_turn(
            intent=parsed.intent.value,
            entities=parsed.entities,
            result="error" if is_error else "success",
            response_time_ms=response_time,
            host=parsed.entities.get("host"),
            error_message=response if is_error else None,
        )

        return response

    def _dispatch(self, parsed: ParsedIntent) -> str:
        """意图分发"""
        # 优先处理确认任务
        if parsed.intent == IntentType.CONFIRM and self.pending_task:
            return self._handle_confirm(parsed.entities)

        handlers = {
            IntentType.INSPECT: self._handle_inspect,
            IntentType.SCAN: self._handle_scan,
            IntentType.CONFIG: self._handle_config,
            IntentType.LOGS: self._handle_logs,
            IntentType.HELP: self._handle_help,
            IntentType.INSTALL: self._handle_install,
            IntentType.CONFIRM: self._handle_confirm_no_task,
            IntentType.CHAT: self._handle_chat,
            IntentType.EXPORT: self._handle_export,
            IntentType.K8S_INSPECT: self._handle_k8s_inspect,
            IntentType.K8S_LOGS: self._handle_k8s_logs,
            IntentType.K8S_EXPORT: self._handle_k8s_export,
            IntentType.K8S_CONFIG: self._handle_k8s_config,
            IntentType.K8S_OPS: self._handle_k8s_ops,
            IntentType.DOCKER_INSPECT: self._handle_docker,
            IntentType.RCA_ANALYSIS: self._handle_rca,
            IntentType.NETWORK_DIAG: self._handle_network,
            IntentType.SCHEDULE_TASK: self._handle_schedule,
            IntentType.AUTO_FIX: self._handle_auto_fix,
            IntentType.CERT_CHECK: self._handle_cert_check,
            IntentType.UNKNOWN: self._handle_unknown,
        }

        handler = handlers.get(parsed.intent, self._handle_unknown)
        # 注入原始输入到 entities（用于问题排查意图检测）
        entities = dict(parsed.entities)
        entities["_raw_input"] = parsed.raw_input
        return handler(entities)

    def _handle_inspect(self, entities: Dict[str, Any]) -> str:
        """处理服务器巡检意图"""
        host = entities.get("host")
        all_hosts = entities.get("all_hosts", False)  # 是否巡检所有主机
        profile = entities.get("profile") or self.state.context.current_profile

        # 获取阈值配置
        thresholds = {
            "cpu": self.config.get_threshold("cpu", profile),
            "memory": self.config.get_threshold("memory", profile),
            "disk": self.config.get_threshold("disk", profile),
        }

        # 多主机批量巡检
        if all_hosts:
            from ..tools.ssh import SSHTools
            hosts = SSHTools.get_hosts_from_file("/etc/hosts")

            if not hosts:
                # /etc/hosts 没有配置，只巡检本机
                return "[巡检] /etc/hosts 中没有找到可巡检的主机\n\n请确保 /etc/hosts 中配置了待巡检主机的 IP 地址，或指定具体主机 IP 进行巡检。"

            # 批量巡检
            try:
                statuses = ServerTools.inspect_multiple_hosts(hosts)
                report = format_batch_report(statuses, thresholds)

                # 更新上下文
                self.state.context.current_host = "batch"
                return report
            except Exception as e:
                return f"[巡检] 批量巡检失败：{str(e)}"

        # 单主机巡检
        target_host = host or self.state.context.current_host or "localhost"

        try:
            status = ServerTools.inspect_server(target_host)
            report = format_status_report(status, thresholds)

            # 更新上下文
            self.state.context.current_host = target_host

            return report
        except NotImplementedError as e:
            return f"[巡检] {str(e)}"
        except Exception as e:
            return f"[巡检] 检查失败：{str(e)}"

    def _handle_scan(self, entities: Dict[str, Any]) -> str:
        """处理漏洞扫描意图"""
        host = entities.get("host") or self.state.context.current_host or "localhost"

        try:
            # 默认快速扫描
            scan_type = "quick" if not entities.get("full") else "full"

            if scan_type == "quick":
                result = ScannerTools.quick_scan(host)
            else:
                result = ScannerTools.full_scan(host)

            report = format_scan_result(result)

            # 更新上下文
            self.state.context.current_host = host

            return report
        except NmapNotInstalledError:
            # 设置待确认安装任务
            self.pending_task = PendingTask(
                task_type="install",
                package="nmap",
                host="localhost",
            )
            return NmapNotInstalledError.get_help_message()
        except RuntimeError as e:
            return f"[扫描] {str(e)}"
        except TimeoutError as e:
            return f"[扫描] 扫描超时：{str(e)}"
        except Exception as e:
            return f"[扫描] 扫描失败：{str(e)}"

    def _handle_install(self, entities: Dict[str, Any]) -> str:
        """处理安装软件意图"""
        package = entities.get("package") or "nmap"
        host = entities.get("host")

        if not host:
            # 本地安装 - 设置待确认任务
            cmd = NmapNotInstalledError.get_install_command()
            self.pending_task = PendingTask(
                task_type="install",
                package=package,
                host="localhost",
                message=f"请在本地执行以下命令安装 {package}:\n\n  {cmd}\n\n或者我可以帮你自动安装，输入 'yes' 或 '好的' 确认执行。"
            )
            return self.pending_task.message
        else:
            # 远程安装
            return self._remote_install(host, package)

    def _handle_confirm(self, entities: Dict[str, Any]) -> str:
        """处理确认执行任务"""
        if not self.pending_task:
            return "[系统] 当前没有待确认的任务。"

        task = self.pending_task
        self.pending_task = None  # 清除待办任务

        if task.task_type == "install":
            return self._execute_install(task.package, task.host)
        elif task.task_type == "scan":
            return self._execute_scan(task.host)
        elif task.task_type == "k8s_config":
            return self._execute_k8s_config(entities)
        elif task.task_type == "k8s_ops":
            return self._execute_k8s_ops(task)
        elif task.task_type == "schedule_confirm":
            return self._execute_schedule_confirm(task)
        elif task.task_type == "docker_prune":
            success, output = DockerTools.prune_images()
            icon = "✓" if success else "✗"
            return f"[Docker] {icon} 镜像清理: {output}"
        elif task.task_type == "fix_execute":
            index = int(task.package)
            return self._do_execute_fix(index)
        elif task.task_type == "fix_execute_all":
            return self._do_execute_all_fixes()

        return "[系统] 未知任务类型。"

    def _handle_confirm_no_task(self, entities: Dict[str, Any]) -> str:
        """处理确认但没有待办任务"""
        return "[系统] 当前没有待确认的任务。您可以尝试：\n  - '扫描漏洞'\n  - '检查 192.168.1.100'\n  - '帮助'"

    def _execute_install(self, package: str, host: str) -> str:
        """执行安装（本地）"""
        import subprocess

        lines = [f"[安装] 正在安装 {package}..."]
        lines.append("")

        # 获取安装命令
        install_cmd = NmapNotInstalledError.get_install_command()

        # 执行安装
        try:
            # 使用 subprocess 执行并显示输出
            result = subprocess.run(
                install_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                lines.append(f"[✓] {package} 已在 {host} 上成功安装")
                # 只显示最后几行
                output_lines = (result.stdout or "").strip().split("\n")
                lines.extend(output_lines[-10:])
                return "\n".join(lines)
            else:
                lines.append(f"[✗] {package} 安装失败")
                lines.append("")
                lines.append(result.stderr or result.stdout)
                return "\n".join(lines)

        except subprocess.TimeoutExpired:
            return f"[安装] ✗ 安装超时，请手动执行：{install_cmd}"
        except Exception as e:
            return f"[安装] ✗ 安装失败：{str(e)}"

    def _execute_scan(self, host: str) -> str:
        """执行扫描"""
        return self._handle_scan({"host": host})

    def _execute_k8s_config(self, entities: Dict[str, Any]) -> str:
        """执行 K8s 配置（用户选择后的确认）"""
        import os

        # 获取候选列表（从任务中保存的数据）
        candidates_str = ""
        if hasattr(self, '_pending_k8s_candidates'):
            candidates_str = self._pending_k8s_candidates
            self._pending_k8s_candidates = ""

        # 用户可能回复编号
        choice = entities.get("host") or entities.get("query") or "1"
        try:
            choice_num = int(choice)
        except (ValueError, TypeError):
            choice_num = 1

        candidates = []
        for item in (candidates_str or "").split(","):
            if ":" in item:
                t, p = item.split(":", 1)
                candidates.append((t, p))

        if not candidates or choice_num < 1 or choice_num > len(candidates):
            return f"[K8s] 无效选择，请重新输入编号（1-{len(candidates)}）。"

        cluster_type, kubeconfig = candidates[choice_num - 1]
        self.config.k8s["kubeconfig"] = kubeconfig
        self.config.k8s["cluster_type"] = cluster_type.lower() if cluster_type != "Kubeadm" else "k8s"
        self.config.save()

        # 测试连接
        from ..tools.k8s.client import K8sClient, K8sClusterConfig
        k8s_cfg = K8sClusterConfig(
            kubeconfig_path=kubeconfig,
            cluster_type=self.config.k8s["cluster_type"],
        )
        k8s_client = K8sClient(k8s_cfg)
        success, msg = k8s_client.connect()
        k8s_client.close()

        if success:
            return (
                f"[K8s] 已配置并连接成功\n\n"
                f"  集群类型：{self.config.k8s['cluster_type']}\n"
                f"  kubeconfig：{kubeconfig}\n"
                f"  集群信息：{msg}\n\n"
                f"现在可以说'检查 K8s 集群'了。"
            )
        else:
            return f"[K8s] kubeconfig 已配置但连接失败：{msg}"

    def _remote_install(self, host: str, package: str) -> str:
        """远程安装软件"""
        # 测试 SSH 连接
        if not SSHTools.test_connection(host):
            return f"""[连接] 无法连接到 {host}

请检查:
1. 主机是否在线
2. SSH 服务是否运行 (端口 22)
3. 防火墙设置
4. SSH 密钥/密码配置

示例命令:
  ssh root@{host}
"""

        # 执行安装
        success, output = SSHTools.execute(
            SSHConfig(host=host),
            f"sudo apt-get update && sudo apt-get install -y {package}"
        )

        if success:
            return f"""[安装] ✓ {package} 已在 {host} 上成功安装

{output[:500]}
"""
        else:
            return f"""[安装] ✗ {package} 安装失败

{output}

可能原因:
1. 权限不足 (需要 sudo)
2. 包管理器不可用
3. 网络连接问题
"""

    def _handle_config(self, entities: Dict[str, Any]) -> str:
        """处理配置管理意图"""
        action = entities.get("action")
        profile = entities.get("profile")
        metric = entities.get("metric")
        threshold = entities.get("threshold")

        # 切换环境
        if profile and not action:
            self.state.context.current_profile = profile
            self.config.current_profile = profile
            return f"[配置] 已切换到环境：{profile}"

        # 修改阈值
        if action in ("set", "update") and threshold is not None:
            current_profile = self.config.current_profile
            profile_config = self.config.get_profile(current_profile)

            # 更新阈值
            if "thresholds" not in profile_config:
                profile_config["thresholds"] = {}

            # 支持单个或全部阈值修改
            if metric:
                profile_config["thresholds"][metric] = int(threshold)
                self.config.set_profile(current_profile, profile_config)
                metric_name = {"cpu": "CPU", "memory": "内存", "disk": "磁盘"}.get(metric, metric)
                return f"[配置] 已将 {metric_name} 阈值设置为 {threshold}%"
            else:
                # 全部阈值
                profile_config["thresholds"]["cpu"] = int(threshold)
                profile_config["thresholds"]["memory"] = int(threshold)
                profile_config["thresholds"]["disk"] = int(threshold)
                self.config.set_profile(current_profile, profile_config)
                return f"[配置] 已将所有阈值设置为 {threshold}%"

        # 显示配置
        current_profile = self.config.get_profile()
        lines = [f"[配置] 当前环境：{self.config.current_profile}"]

        if current_profile:
            lines.append("\n配置详情:")
            hosts = current_profile.get("hosts", [])
            thresholds = current_profile.get("thresholds", {})

            if hosts:
                lines.append(f"  主机列表：{', '.join(hosts)}")
            if thresholds:
                lines.append(f"  阈值配置：CPU={thresholds.get('cpu', 80)}%, "
                           f"内存={thresholds.get('memory', 85)}%, "
                           f"磁盘={thresholds.get('disk', 90)}%")

        return "\n".join(lines)

    def _handle_logs(self, entities: Dict[str, Any]) -> str:
        """处理日志查询意图"""
        # 支持三种日志：
        # 1. 审计日志（Keeper 操作记录）
        # 2. 系统日志（journalctl, /var/log）
        # 3. Docker 容器日志

        log_source = entities.get("log_source")  # "audit", "system", "docker", "file"
        query = entities.get("query")  # 搜索关键词

        # 判断是否是"问题排查"意图（用户询问有没有问题/异常）
        raw_input = entities.get("_raw_input", "")
        is_troubleshoot = any(w in raw_input for w in ["问题", "异常", "错误", "故障", "告警", "报警", "有没有什么", "健康"])

        # 系统日志查询
        if log_source in ("system", "journal"):
            from ..tools.logs import LogTools

            unit = entities.get("unit")
            lines = int(entities.get("lines", 50))
            since = entities.get("since")

            # 问题排查模式：查询错误级别日志 + 常见问题模式匹配
            if is_troubleshoot and not unit:
                return self._system_troubleshoot(since)

            # 有关键词过滤
            keyword = query
            if keyword and all(ord(c) < 128 for c in keyword):
                # 纯英文关键词，直接搜索
                success, output = LogTools.query_journal(
                    lines=lines, unit=unit, since=since, keyword=keyword
                )
                if not success:
                    return f"[系统日志] {output}"
                if not output.strip():
                    return "[系统日志] 未找到匹配的日志"
            else:
                # 中文关键词或不带关键词，查询原始日志
                success, output = LogTools.query_journal(
                    lines=lines, unit=unit, since=since
                )
                if not success:
                    return f"[系统日志] {output}"
                if not output.strip():
                    return "[系统日志] 未找到匹配的日志"

            # 截断过长输出
            max_lines = 200
            output_lines = output.split("\n")
            if len(output_lines) > max_lines:
                output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"

            return f"[系统日志] (journalctl -n {lines}):\n\n{output}"

        # Docker 日志查询
        if log_source in ("docker", "container"):
            from ..tools.logs import LogTools

            container = entities.get("container") or entities.get("host")
            lines = int(entities.get("lines", 50))
            keyword = entities.get("query")

            if not container:
                return "[日志] 请指定容器名称，例如：查看 nginx 容器日志"

            success, output = LogTools.query_docker_logs(
                container_name=container, lines=lines, keyword=keyword
            )

            if not success:
                return f"[Docker 日志] {output}"
            if not output.strip():
                return f"[Docker 日志] 容器 {container} 无日志输出"

            return f"[Docker 日志] ({container}):\n\n{output}"

        # 文件日志查询
        if log_source in ("file",):
            from ..tools.logs import LogTools

            path = entities.get("path")
            lines = int(entities.get("lines", 50))
            keyword = entities.get("query")

            if not path:
                return "[日志] 请指定日志文件路径，例如：查看 /var/log/nginx/access.log"

            success, output = LogTools.query_file(path=path, lines=lines, keyword=keyword)

            if not success:
                return f"[文件日志] {output}"
            if not output.strip():
                return f"[文件日志] 文件 {path} 无匹配内容"

            return f"[文件日志] ({path}):\n\n{output}"

        # 查询审计日志（Keeper 操作记录）
        query = entities.get("query")
        host = entities.get("host")
        hours = entities.get("hours")
        intent_filter = entities.get("intent_type")

        # 如果有具体查询条件，查询审计日志
        if query or host or hours or intent_filter:
            hours_int = int(hours) if hours else 24
            records = self.audit.get_history(
                hours=hours_int,
                limit=20,
                host=host,
                intent=intent_filter,
            )

            if not records:
                return f"[日志] 过去 {hours_int} 小时内没有找到 Keeper 操作记录"

            lines = [f"[日志] 过去 {hours_int} 小时的 Keeper 操作记录:"]
            for i, record in enumerate(records, 1):
                time_str = record.timestamp[11:19]  # 提取 HH:MM:SS
                result_icon = "✓" if record.result == "success" else "✗"
                host_str = f" ({record.host})" if record.host else ""
                lines.append(f"  {i}. [{time_str}] {result_icon} {record.intent}{host_str}")

            return "\n".join(lines)

        # 默认显示最近的对话记忆
        recent_turns = self.state.memory.get_recent_turns(5)

        if not recent_turns:
            return "[日志] 暂无历史记录"

        lines = ["[日志] 最近操作记录:"]
        for i, turn in enumerate(recent_turns, 1):
            lines.append(f"  {i}. {turn.user_input} → {turn.intent}")

        return "\n".join(lines)

    def _system_troubleshoot(self, since: Optional[str] = None) -> str:
        """系统问题排查 - 自动查询错误级别日志和常见问题模式"""
        import subprocess

        lines = []

        # 1. 查询错误级别日志 (err 及以上)
        try:
            cmd = ["journalctl", "--no-pager", "-n", "100", "-p", "err"]
            if since:
                cmd.extend(["--since", since])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            err_output = result.stdout.strip() if result.returncode == 0 else ""

            # 过滤掉常见的无害错误
            harmless_patterns = ["Failed to parse bus name", "Cannot find device"]
            err_lines = [
                l for l in err_output.split("\n")
                if not any(p in l for p in harmless_patterns)
            ]
            err_output = "\n".join(err_lines)

            if err_output.strip():
                max_lines = 50
                err_out = err_output.split("\n")
                if len(err_out) > max_lines:
                    err_output = "\n".join(err_out[:max_lines]) + f"\n\n... (截断，共 {len(err_out)} 行)"
                lines.append("━━━ 错误级别日志 (最近 100 条) ━━━")
                lines.append(err_output)
                lines.append("")

                # 提取关键问题
                issues_found = self._analyze_error_logs(err_output)
                if issues_found:
                    lines.append("━━━ 发现的问题 ━━━")
                    for issue in issues_found:
                        lines.append(f"  ⚠ {issue}")
                    lines.append("")
            else:
                lines.append("✓ 未发现错误级别日志")
                lines.append("")
        except Exception as e:
            lines.append(f"[错误日志] 查询失败：{e}")
            lines.append("")

        # 2. 常见问题模式检测
        issues = []

        # SSH 暴力破解检测
        try:
            cmd = ["journalctl", "--no-pager", "-n", "20", "--since", since or "24 hours ago",
                   "-t", "sshd"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            sshd_output = result.stdout.strip() if result.returncode == 0 else ""
            failed_count = sshd_output.lower().count("failed password")
            if failed_count > 10:
                # 提取攻击 IP
                import re
                ips = re.findall(r"Failed password for .*? from (\d+\.\d+\.\d+\.\d+)", sshd_output)
                ip_list = ", ".join(list(set(ips))[:10])
                issues.append(f"SSH 暴力破解检测：过去 24 小时内有 {failed_count} 次失败登录尝试，来源 IP: {ip_list}")
            elif failed_count > 0:
                import re
                ips = re.findall(r"Failed password for .*? from (\d+\.\d+\.\d+\.\d+)", sshd_output)
                ip_list = ", ".join(list(set(ips))[:10])
                issues.append(f"SSH 失败登录：{failed_count} 次，来源 IP: {ip_list}")
        except Exception:
            pass

        # OOM Killer 检测
        try:
            cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "7 days ago",
                   "-k", "--grep", "Out of memory"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.stdout.strip():
                issues.append("OOM Killer 被触发，存在内存溢出问题")
        except Exception:
            pass

        # 磁盘错误检测
        try:
            cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "24 hours ago",
                   "--grep", "I/O error"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.stdout.strip():
                issues.append("检测到磁盘 I/O 错误")
        except Exception:
            pass

        # 系统服务失败
        try:
            cmd = ["journalctl", "--no-pager", "-n", "10", "--since", since or "24 hours ago",
                   "--grep", "Failed to start"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.stdout.strip():
                issues.append(f"有服务启动失败:\n{result.stdout.strip()[:300]}")
        except Exception:
            pass

        if issues:
            lines.append("━━━ 自动检测到的问题 ━━━")
            for i, issue in enumerate(issues, 1):
                lines.append(f"  {i}. {issue}")
        else:
            lines.append("✓ 未检测到常见问题模式")

        return "\n".join(lines)

    def _analyze_error_logs(self, output: str) -> List[str]:
        """分析错误日志，提取关键问题"""
        issues = []
        import re

        # 提取认证失败
        auth_fails = len(re.findall(r"authentication failure", output))
        if auth_fails > 0:
            issues.append(f"认证失败 {auth_fails} 次")

        # 提取连接拒绝
        conn_refused = len(re.findall(r"Connection refused", output))
        if conn_refused > 0:
            issues.append(f"连接拒绝 {conn_refused} 次")

        # 提取服务超时
        timeouts = len(re.findall(r"[Tt]imeout", output))
        if timeouts > 0:
            issues.append(f"超时错误 {timeouts} 次")

        # 提取磁盘满
        if "No space left on device" in output:
            issues.append("磁盘空间不足")

        # 提取权限拒绝
        perm_denied = len(re.findall(r"[Pp]ermission denied", output))
        if perm_denied > 0:
            issues.append(f"权限拒绝 {perm_denied} 次")

        return issues

    def _handle_help(self, entities: Dict[str, Any]) -> str:
        """处理帮助请求"""
        return """📖 Keeper 支持的命令：

**服务器巡检**
  - "检查 192.168.1.100"
  - "看看这台机器健康吗"
  - "服务器状态"

**K8s 集群管理**
  - "检查 K8s 集群状态"
  - "K8s 巡检"
  - "查看 Pod 的情况"
  - "查看 my-app Pod 的日志"

**漏洞扫描**
  - "扫描漏洞"
  - "检查有没有安全问题"
  - "全面扫描"

**配置管理**
  - "保存配置"
  - "切换到 production 环境"
  - "显示当前配置"

**日志查询**
  - "查看最近操作"
  - "显示昨天的告警"

**其他**
  - "退出" - 结束会话
"""

    def _handle_export(self, entities: Dict[str, Any]) -> str:
        """处理报告导出意图"""
        from ..tools.reporter import ReportExporter
        from ..tools.ssh import SSHTools

        fmt = (entities.get("format") or "html").lower()

        # 获取上次巡检的主机
        host = entities.get("host") or self.state.context.current_host
        if not host:
            # 尝试从记忆中获取最近的主机
            mentioned_hosts = self.state.memory.get_hosts_mentioned()
            if mentioned_hosts:
                host = mentioned_hosts[-1]

        # 获取阈值
        profile = entities.get("profile") or self.state.context.current_profile
        thresholds = {
            "cpu": self.config.get_threshold("cpu", profile),
            "memory": self.config.get_threshold("memory", profile),
            "disk": self.config.get_threshold("disk", profile),
        }

        # 确定导出格式
        if fmt in ("json",):
            export_fmt = "json"
        elif fmt in ("md", "markdown"):
            export_fmt = "markdown"
        else:
            export_fmt = "html"

        # 生成文件名
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 确定主机列表
        all_hosts = entities.get("all_hosts", False)
        if all_hosts:
            hosts = SSHTools.get_hosts_from_file("/etc/hosts")
            if not hosts:
                return "[报告] /etc/hosts 中没有找到可巡检的主机"
        elif host:
            hosts = [host]
        else:
            hosts = ["localhost"]

        # 采集数据
        try:
            statuses = ServerTools.inspect_multiple_hosts(hosts, max_workers=5)
        except Exception as e:
            return f"[报告] 采集数据失败：{str(e)}"

        # 导出
        ext = {"json": "json", "html": "html", "markdown": "md"}[export_fmt]
        output_path = f"./keeper_report_{timestamp}.{ext}"

        if export_fmt == "json":
            return ReportExporter.export_json(statuses, thresholds, output_path)
        elif export_fmt == "html":
            return ReportExporter.export_html(statuses, thresholds, output_path)
        else:
            return ReportExporter.export_markdown(statuses, thresholds, output_path)

    def _handle_chat(self, entities: Dict[str, Any]) -> str:
        """处理闲聊意图（备用，正常情况下不会走到这里）"""
        return """👋 你好！我是 Keeper，你的智能运维助手。我可以帮你：
  - 服务器资源巡检
  - 漏洞扫描
  - 配置管理
试试说"检查 192.168.1.100"？"""

    def _handle_unknown(self, entities: Dict[str, Any]) -> str:
        """处理未知意图"""
        return """抱歉，我没有理解您的意思。您可以尝试：
  - "检查 192.168.1.100"
  - "扫描漏洞"
  - "帮助" - 查看更多命令
"""

    def get_context(self) -> ContextManager:
        """获取上下文管理器"""
        return self.state.context

    def get_memory(self) -> MemoryManager:
        """获取记忆管理器"""
        return self.state.memory

    def stop(self) -> None:
        """停止 Agent"""
        self.state.is_running = False

    def _get_k8s_client(self, auto_detect: bool = True):
        """获取已连接的 K8s 客户端

        Args:
            auto_detect: 连接失败时是否自动检测 kubeconfig 并询问用户

        Returns:
            (k8s_client, formatter, error_msg)
            如果需要用户确认，error_msg 包含询问信息
        """
        from ..tools.k8s.client import K8sClient, K8sClusterConfig
        from ..tools.k8s.formatter import format_cluster_report

        k8s_cfg_data = self.config.get_k8s_config()
        kubeconfig = k8s_cfg_data.get("kubeconfig", "")
        context = k8s_cfg_data.get("context", "")
        cluster_type = k8s_cfg_data.get("cluster_type", "k8s")

        k8s_cfg = K8sClusterConfig(
            kubeconfig_path=kubeconfig,
            context=context,
            cluster_type=cluster_type,
        )

        k8s_client = K8sClient(k8s_cfg)
        success, msg = k8s_client.connect()

        if success:
            return k8s_client, format_cluster_report, None

        # 连接失败，尝试自动检测
        if not auto_detect:
            return None, None, f"[K8s] 连接集群失败：{msg}"

        # 检测 K3s
        import os
        k3s_path = "/etc/rancher/k3s/k3s.yaml"
        if os.path.exists(k3s_path):
            # K3s 环境，直接自动配置
            k8s_cfg_data["kubeconfig"] = k3s_path
            k8s_cfg_data["cluster_type"] = "k3s"
            self.config.k8s = k8s_cfg_data
            self.config.save()

            k8s_cfg = K8sClusterConfig(
                kubeconfig_path=k3s_path,
                context=context,
                cluster_type="k3s",
            )
            k8s_client = K8sClient(k8s_cfg)
            success, msg = k8s_client.connect()
            if success:
                return k8s_client, format_cluster_report, None
            return None, None, f"[K8s] 连接 K3s 失败：{msg}"

        # 检测标准 K8s
        std_path = str(Path.home() / ".kube/config")
        if os.path.exists(std_path):
            k8s_cfg_data["kubeconfig"] = std_path
            k8s_cfg_data["cluster_type"] = "k8s"
            self.config.k8s = k8s_cfg_data
            self.config.save()

            k8s_cfg = K8sClusterConfig(
                kubeconfig_path=std_path,
                context=context,
                cluster_type="k8s",
            )
            k8s_client = K8sClient(k8s_cfg)
            success, msg = k8s_client.connect()
            if success:
                return k8s_client, format_cluster_report, None
            return None, None, f"[K8s] 连接集群失败：{msg}"

        # 没有找到 kubeconfig，询问用户
        return None, None, (
            "[K8s] 未找到 Kubeconfig 配置文件\n\n"
            "我检测到以下可能的位置：\n"
            "  - K3s: /etc/rancher/k3s/k3s.yaml\n"
            "  - K8s: ~/.kube/config\n\n"
            "请告诉我你的 kubeconfig 路径，或者说'帮我配置'我来自动检测。"
        )

    def _handle_k8s_inspect(self, entities: Dict[str, Any]) -> str:
        """处理 K8s 集群巡检意图"""
        k8s_client, fmt, err = self._get_k8s_client(auto_detect=True)
        if err:
            return err

        try:
            from ..tools.k8s.inspector import K8sInspector
            from ..tools.k8s.formatter import format_cluster_report

            namespace = entities.get("namespace")

            success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
            if not success:
                return f"[K8s] 巡检失败：{report.issues[0] if report.issues else '未知错误'}"

            self.state.context.current_host = "k8s-cluster"
            return format_cluster_report(report, namespace)
        except Exception as e:
            return f"[K8s] 巡检失败：{str(e)}"
        finally:
            k8s_client.close()

    def _handle_k8s_logs(self, entities: Dict[str, Any]) -> str:
        """处理 K8s Pod 日志查询意图"""
        k8s_client, _, err = self._get_k8s_client(auto_detect=True)
        if err:
            return err

        try:
            from ..tools.k8s.logs import K8sLogTools

            pod_name = entities.get("pod_name")
            namespace = entities.get("namespace") or "default"
            lines = int(entities.get("lines", 100))
            keyword = entities.get("query")
            container = entities.get("container")

            if not pod_name:
                return "[K8s] 请指定 Pod 名称，例如：查看 my-app Pod 的日志"

            success, output = K8sLogTools.get_pod_logs(
                k8s_client,
                pod_name=pod_name,
                namespace=namespace,
                lines=lines,
                keyword=keyword,
                container=container,
            )

            if not success:
                return f"[K8s 日志] {output}"

            # 截断过长输出
            max_lines = 200
            output_lines = output.split("\n")
            if len(output_lines) > max_lines:
                output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"

            ns_prefix = f"{namespace}/" if namespace != "default" else ""
            return f"[K8s 日志] ({ns_prefix}{pod_name}):\n\n{output}"
        except Exception as e:
            return f"[K8s 日志] 查询失败：{str(e)}"
        finally:
            k8s_client.close()

    def _handle_k8s_export(self, entities: Dict[str, Any]) -> str:
        """处理 K8s 报告导出意图"""
        k8s_client, _, err = self._get_k8s_client(auto_detect=True)
        if err:
            return err

        try:
            from ..tools.k8s.inspector import K8sInspector
            from ..tools.k8s.formatter import format_cluster_report
            from datetime import datetime

            namespace = entities.get("namespace")
            fmt = (entities.get("format") or "html").lower()

            success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
            if not success:
                return f"[K8s] 导出数据获取失败"

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if fmt == "json":
                import json
                output_path = f"./k8s_report_{timestamp}.json"
                data = {
                    "timestamp": report.timestamp,
                    "cluster_type": report.cluster_type,
                    "k8s_version": report.k8s_version,
                    "score": report.score,
                    "node_count": report.node_count,
                    "pods_total": report.pods_total,
                    "abnormal_pods": [
                        {"name": p.name, "namespace": p.namespace, "phase": p.phase, "issues": p.issues}
                        for p in report.abnormal_pods
                    ],
                    "issues": report.issues,
                }
                with open(output_path, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return f"[K8s] 报告已导出：{output_path}"
            else:
                # HTML 或 MD 默认使用文本格式
                output_path = f"./k8s_report_{timestamp}.md"
                text_report = format_cluster_report(report, namespace)
                with open(output_path, "w") as f:
                    f.write(text_report)
                return f"[K8s] 报告已导出：{output_path}"
        except Exception as e:
            return f"[K8s] 导出失败：{str(e)}"
        finally:
            k8s_client.close()

    def _handle_k8s_config(self, entities: Dict[str, Any]) -> str:
        """处理 K8s 配置意图 - 检测并配置 K8s 连接"""
        import os

        # 检测常见的 kubeconfig 路径
        candidates = []
        k3s_path = "/etc/rancher/k3s/k3s.yaml"
        std_path = str(Path.home() / ".kube/config")
        kubeadm_path = "/etc/kubernetes/admin.conf"

        if os.path.exists(k3s_path):
            candidates.append(("K3s", k3s_path))
        if os.path.exists(std_path):
            candidates.append(("K8s", std_path))
        if os.path.exists(kubeadm_path):
            candidates.append(("Kubeadm", kubeadm_path))

        if not candidates:
            return (
                "[K8s] 未检测到 Kubeconfig 文件\n\n"
                "请手动指定 kubeconfig 路径，例如：\n"
                "  keeper config set --k8s-kubeconfig /path/to/kubeconfig"
            )

        # 只找到一个，直接配置
        if len(candidates) == 1:
            cluster_type, kubeconfig = candidates[0]
            self.config.k8s["kubeconfig"] = kubeconfig
            self.config.k8s["cluster_type"] = cluster_type.lower() if cluster_type != "Kubeadm" else "k8s"
            self.config.save()

            # 测试连接
            from ..tools.k8s.client import K8sClient, K8sClusterConfig
            k8s_cfg = K8sClusterConfig(
                kubeconfig_path=kubeconfig,
                cluster_type=self.config.k8s["cluster_type"],
            )
            k8s_client = K8sClient(k8s_cfg)
            success, msg = k8s_client.connect()
            k8s_client.close()

            if success:
                return (
                    f"[K8s] 已自动配置并连接成功\n\n"
                    f"  集群类型：{self.config.k8s['cluster_type']}\n"
                    f"  kubeconfig：{kubeconfig}\n"
                    f"  集群信息：{msg}\n\n"
                    f"现在可以说'检查 K8s 集群'了。"
                )
            else:
                return f"[K8s] kubeconfig 已配置但连接失败：{msg}"

        # 找到多个，询问用户
        options = "\n".join(f"  {i+1}. {t}: {p}" for i, (t, p) in enumerate(candidates))
        self._pending_k8s_candidates = ",".join(f"{t}:{p}" for t, p in candidates)
        self.pending_task = PendingTask(
            task_type="k8s_config",
            message=(
                f"[K8s] 检测到多个 Kubeconfig 文件：\n{options}\n\n"
                f"请问使用哪一个？请回复编号。"
            ),
            package="k8s_config_options",
            host=",".join(f"{t}:{p}" for t, p in candidates),
        )
        return self.pending_task.message

    def _handle_k8s_ops(self, entities: Dict[str, Any]) -> str:
        """处理 K8s 深度操作意图"""
        k8s_client, _, err = self._get_k8s_client(auto_detect=True)
        if err:
            return err

        try:
            action = entities.get("action", "").lower()
            namespace = entities.get("namespace") or "default"

            # exec 直接执行
            if action == "exec":
                from ..tools.k8s.ops import K8sOps
                pod_name = entities.get("pod_name")
                command = entities.get("pod_command") or "ls /"
                if not pod_name:
                    return "[K8s] 请指定 Pod 名称"
                success, output = K8sOps.exec_in_pod(
                    k8s_client, pod_name=pod_name, namespace=namespace, command=command,
                )
                if not success:
                    return f"[K8s] {output}"
                return f"[K8s Exec] ({namespace}/{pod_name}) $ {command}\n{output}"

            # restart/scale/rollback 需要二次确认
            if action in ("restart", "scale", "rollback"):
                deployment = entities.get("deployment")
                if not deployment:
                    return "[K8s] 请指定 Deployment 名称"

                action_desc = {"restart": "重启", "scale": "扩缩容", "rollback": "回滚"}[action]
                replicas = entities.get("replicas")

                detail = ""
                if action == "scale" and replicas:
                    detail = f" (目标副本数: {replicas})"

                self.pending_task = PendingTask(
                    task_type="k8s_ops",
                    package=action,
                    host=deployment,
                    message=(
                        f"[K8s] 确认{action_desc}: {namespace}/{deployment}{detail}\n\n"
                        f"此操作会影响线上服务，输入 'yes' 或 '确认' 执行。"
                    ),
                )
                if replicas:
                    self._pending_k8s_replicas = replicas
                return self.pending_task.message

            # 默认列出工作负载状态
            from ..tools.k8s.client import K8sClient
            from ..tools.k8s.inspector import K8sInspector

            workloads = K8sInspector._check_workloads(k8s_client, namespace)
            if not workloads:
                return f"[K8s] 命名空间 '{namespace}' 中未找到工作负载"

            lines = [f"[K8s] 工作负载列表 ({namespace}):"]
            lines.append("━" * 70)
            for w in workloads:
                icon = "✓" if not w.issues else "✗"
                lines.append(f"  {icon} {w.kind}/{w.name} - {w.ready}/{w.desired} ready")
                if w.issues:
                    lines.append(f"    问题: {'; '.join(w.issues)}")
            return "\n".join(lines)

        except Exception as e:
            return f"[K8s] 操作失败：{str(e)}"
        finally:
            k8s_client.close()

    def _execute_k8s_ops(self, task: PendingTask) -> str:
        """执行 K8s 确认操作"""
        k8s_client, _, err = self._get_k8s_client(auto_detect=False)
        if err:
            return err

        try:
            from ..tools.k8s.ops import K8sOps
            action = task.package
            deployment = task.host
            namespace = "default"

            if action == "restart":
                return K8sOps.restart_deployment(k8s_client, deployment, namespace)[1]
            elif action == "scale":
                replicas = getattr(self, '_pending_k8s_replicas', 1)
                self._pending_k8s_replicas = None
                return K8sOps.scale_deployment(k8s_client, deployment, namespace, int(replicas))[1]
            elif action == "rollback":
                return K8sOps.rollback_deployment(k8s_client, deployment, namespace)[1]
            return "[K8s] 未知操作"
        except Exception as e:
            return f"[K8s] 执行失败：{str(e)}"
        finally:
            k8s_client.close()

    def _handle_docker(self, entities: Dict[str, Any]) -> str:
        """处理 Docker 容器管理意图"""
        if not DockerTools.is_docker_available():
            return "[Docker] Docker 未安装或未运行\n\n请确保已安装 Docker 并启动服务。"

        action = entities.get("docker_action", "").lower()
        container_name = entities.get("host") or entities.get("container") or entities.get("query")

        # 列出容器
        if action in ("list", "stats", ""):
            containers = DockerTools.list_containers()
            if action in ("stats", ""):
                stats = DockerTools.get_container_stats()
            else:
                stats = []
            return format_docker_containers(containers, stats)

        # 镜像列表
        if action == "images":
            images = DockerTools.list_images()
            return format_docker_images(images)

        # 清理镜像
        if action == "prune":
            self.pending_task = PendingTask(
                task_type="docker_prune",
                message="[Docker] 确认清理无用的 Docker 镜像？此操作不可逆，输入 'yes' 确认。",
            )
            return self.pending_task.message

        # 容器日志
        if action == "logs" and container_name:
            success, output = DockerTools.get_container_logs(container_name, lines=100)
            if not success:
                return f"[Docker] {output}"
            max_lines = 200
            output_lines = output.split("\n")
            if len(output_lines) > max_lines:
                output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"
            return f"[Docker 日志] ({container_name}):\n{output}"

        # 容器详情
        if action == "inspect" and container_name:
            success, info = DockerTools.inspect_container(container_name)
            if not success:
                return f"[Docker] {info.get('error', '获取失败')}"
            lines = [f"[Docker] 容器详情: {info['name']}"]
            lines.append("━" * 50)
            lines.append(f"  状态: {info['state']}")
            lines.append(f"  镜像: {info['image']}")
            lines.append(f"  创建: {info['created']}")
            lines.append(f"  重启策略: {info['restart_policy']}")
            if info.get("memory_limit"):
                lines.append(f"  内存限制: {info['memory_limit'] / (1024**3):.1f} GB")
            if info.get("networks"):
                lines.append(f"  网络: {', '.join(info['networks'])}")
            if info.get("mounts"):
                lines.append(f"  挂载: {len(info['mounts'])} 个")
            return "\n".join(lines)

        # 容器操作 (restart/stop/start)
        if action in ("restart", "stop", "start") and container_name:
            if action == "restart":
                success, output = DockerTools.restart_container(container_name)
            elif action == "stop":
                success, output = DockerTools.stop_container(container_name)
            else:
                success, output = DockerTools.start_container(container_name)
            return f"[Docker] {output}" if success else f"[Docker] {output}"

        # 默认：列出容器
        containers = DockerTools.list_containers()
        stats = DockerTools.get_container_stats()
        return format_docker_containers(containers, stats)

    def _handle_rca(self, entities: Dict[str, Any]) -> str:
        """处理根因分析意图"""
        symptom = entities.get("symptom", "")
        comparison_host = entities.get("comparison_host")

        # 双机对比
        if comparison_host:
            try:
                data_a = RCAEngine.collect_server_data()
                data_b = RCAEngine.collect_server_data(comparison_host)
                compare_text = RCAEngine.compare_hosts(
                    data_a, data_b, "localhost", comparison_host
                )
                prompt = RCAEngine.generate_compare_prompt(compare_text)
                return self._call_llm_diagnosis(prompt)
            except Exception as e:
                return f"[RCA] 对比分析失败：{str(e)}"

        # 单主机分析
        try:
            data = RCAEngine.collect_server_data()
            data_text = RCAEngine.analyze_server(data)
            prompt = RCAEngine.generate_diagnosis_prompt(data_text, symptom)
            return self._call_llm_diagnosis(prompt)
        except Exception as e:
            return f"[RCA] 分析失败：{str(e)}"

    def _handle_network(self, entities: Dict[str, Any]) -> str:
        """处理网络诊断意图"""
        action = entities.get("network_action", "").lower()
        host = entities.get("host")
        port = entities.get("port")
        domain = entities.get("domain")
        url = entities.get("url")

        lines = []

        # 无明确 action — 做一组基础检测
        if not action:
            # 默认 ping 8.8.8.8 + DNS 解析 baidu.com
            ping_result = NetworkTools.ping("8.8.8.8", count=4)
            lines.append(format_ping_result(ping_result))
            lines.append("")
            dns_result = NetworkTools.dns_lookup("baidu.com")
            lines.append(format_dns_result(dns_result))
            return "\n".join(lines)

        # Ping
        if action == "ping":
            target = host or "8.8.8.8"
            count = int(entities.get("lines", 4))
            result = NetworkTools.ping(target, count=count)
            return format_ping_result(result)

        # 端口检测
        if action == "port":
            if not host or not port:
                return "[网络诊断] 请指定主机和端口，例如：检查 192.168.1.100 的 3306 端口"
            result = NetworkTools.check_port(host, int(port))
            return format_port_result(result)

        # DNS
        if action == "dns":
            target = domain or "baidu.com"
            result = NetworkTools.dns_lookup(target)
            return format_dns_result(result)

        # HTTP
        if action == "http":
            target = url or "http://localhost"
            result = NetworkTools.http_check(target)
            return format_http_result(result)

        # Traceroute
        if action == "traceroute":
            target = host or "8.8.8.8"
            success, output = NetworkTools.traceroute(target)
            if not success:
                return f"[网络诊断] {output}"
            return f"[网络诊断] 路由追踪到 {target}:\n{output}"

        return "[网络诊断] 未识别的检测类型，请说清楚一些，如 'ping 8.8.8.8' 或 '检查 3306 端口'"

    def _handle_schedule(self, entities: Dict[str, Any]) -> str:
        """处理定时任务意图"""
        schedule_action = entities.get("schedule_action", "").lower()

        # 列出任务
        if schedule_action in ("list", "查看") or (not schedule_action and entities.get("query") in ("查看", "列表")):
            tasks = self.scheduler.list_tasks()
            return format_task_list(tasks)

        # 删除任务
        if schedule_action in ("remove", "删除"):
            task_id = entities.get("task_id")
            if task_id:
                if self.scheduler.remove_task(task_id):
                    return f"[定时任务] 任务 {task_id} 已删除"
                return f"[定时任务] 任务 {task_id} 不存在"
            # 尝试从记忆中获取最后提到的任务 ID
            tasks = self.scheduler.list_tasks()
            if tasks:
                last_task = tasks[-1]
                self.scheduler.remove_task(last_task.id)
                return f"[定时任务] 已删除最后一个任务: {last_task.description} ({last_task.id})"
            return "[定时任务] 没有可删除的任务"

        # 启用/禁用
        if schedule_action in ("enable", "启用", "disable", "禁用"):
            task_id = entities.get("task_id")
            tasks = self.scheduler.list_tasks()
            if not tasks:
                return "[定时任务] 没有任务"
            if task_id:
                task = self.scheduler.get_task(task_id)
            else:
                task = tasks[-1]
            if not task:
                return f"[定时任务] 任务不存在"
            if schedule_action in ("enable", "启用"):
                self.scheduler.enable_task(task.id)
                return f"[定时任务] 已启用: {task.description}"
            else:
                self.scheduler.disable_task(task.id)
                return f"[定时任务] 已禁用: {task.description}"

        # 添加任务
        cron_expr = entities.get("cron_expr", "")
        description = entities.get("schedule_description", entities.get("query", ""))
        all_hosts = entities.get("all_hosts", False)

        # 如果没有 cron 表达式，让用户描述需求
        if not cron_expr:
            raw_input = entities.get("_raw_input", "")
            self.pending_task = PendingTask(
                task_type="schedule_confirm",
                message=(
                    f"[定时任务] 请描述你的定时任务需求，例如：\n"
                    f"  - '每 30 分钟检查一次 K8s 状态'\n"
                    f"  - '每天早上 9 点巡检所有服务器'\n"
                    f"  - '每小时检查 Pod 重启情况'\n\n"
                    f"当前输入：{raw_input}"
                ),
            )
            return self.pending_task.message

        # 确定任务类型
        task_type = "inspect"
        params = {}
        if "k8s" in description.lower() or "k8s" in entities.get("_raw_input", "").lower():
            task_type = "k8s_inspect"
            params["namespace"] = entities.get("namespace", "")
        elif all_hosts:
            task_type = "batch_inspect"

        if not description:
            description = entities.get("_raw_input", "定时任务")

        task = self.scheduler.add_task(
            cron_expr=cron_expr,
            description=description,
            task_type=task_type,
            params=params,
        )
        return (
            f"[定时任务] 已添加任务\n\n"
            f"  ID: {task.id}\n"
            f"  描述: {task.description}\n"
            f"  Cron: {task.cron_expr}\n"
            f"  类型: {task.task_type}\n\n"
            f"任务将在到达时间自动执行。使用 '查看定时任务' 管理任务。"
        )

    def _execute_schedule_confirm(self, task: PendingTask) -> str:
        """确认并添加定时任务 — 需要 LLM 重新解析 cron"""
        raw_input = task.message.split("当前输入：")[-1] if "当前输入：" in task.message else ""
        # 使用 LLM 重新解析输入来获取 cron 表达式
        from ..nlu.base import ParsedIntent
        context_dict = {
            "last_host": self.state.context.current_host,
            "last_intent": self.state.context.last_intent,
        }
        parsed = self.nlu.parse(raw_input, context=context_dict)
        cron_expr = parsed.entities.get("cron_expr", "")

        if not cron_expr:
            return "[定时任务] 抱歉，我没有理解你的定时任务需求。请用更明确的描述，如 '每 30 分钟检查一次' 或 '每天早上 9 点巡检'。"

        description = parsed.entities.get("schedule_description", raw_input)
        task_type = "inspect"
        if "k8s" in raw_input.lower():
            task_type = "k8s_inspect"
        elif parsed.entities.get("all_hosts"):
            task_type = "batch_inspect"

        task_obj = self.scheduler.add_task(
            cron_expr=cron_expr,
            description=description,
            task_type=task_type,
            params=parsed.entities,
        )
        return (
            f"[定时任务] 已添加任务\n\n"
            f"  ID: {task_obj.id}\n"
            f"  描述: {task_obj.description}\n"
            f"  Cron: {task_obj.cron_expr}\n"
            f"  类型: {task_obj.task_type}\n\n"
            f"任务将在到达时间自动执行。"
        )

    def _execute_scheduled_task(self, task) -> str:
        """执行定时任务回调"""
        task_type = task.task_type
        params = task.params

        if task_type == "inspect":
            from ..tools.server import ServerTools, format_status_report
            thresholds = {
                "cpu": self.config.get_threshold("cpu"),
                "memory": self.config.get_threshold("memory"),
                "disk": self.config.get_threshold("disk"),
            }
            status = ServerTools.inspect_server("localhost")
            return format_status_report(status, thresholds)

        elif task_type == "batch_inspect":
            from ..tools.server import ServerTools, format_batch_report
            hosts = SSHTools.get_hosts_from_file("/etc/hosts")
            if not hosts:
                return "[定时任务] 批量巡检：/etc/hosts 中无主机"
            thresholds = {
                "cpu": self.config.get_threshold("cpu"),
                "memory": self.config.get_threshold("memory"),
                "disk": self.config.get_threshold("disk"),
            }
            statuses = ServerTools.inspect_multiple_hosts(hosts)
            return format_batch_report(statuses, thresholds)

        elif task_type == "k8s_inspect":
            k8s_client, fmt, err = self._get_k8s_client(auto_detect=True)
            if err:
                return f"[定时任务] K8s 巡检：{err}"
            try:
                from ..tools.k8s.inspector import K8sInspector
                namespace = params.get("namespace") or None
                success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
                if not success:
                    return f"[定时任务] K8s 巡检失败"
                result = fmt(report, namespace)
                return result
            finally:
                k8s_client.close()

        elif task_type == "network_diag":
            result = NetworkTools.ping("8.8.8.8", count=4)
            return format_ping_result(result)

        return f"[定时任务] 已触发: {task.description}"

    def _call_llm_diagnosis(self, prompt: str) -> str:
        """调用 LLM 进行诊断"""
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            chain = ChatPromptTemplate.from_messages([
                ("system", "你是一个资深运维工程师，擅长问题诊断和根因分析。请用简洁专业的中文回答。"),
                ("human", prompt),
            ]) | self.nlu._llm | StrOutputParser()

            response = chain.invoke({})
            return f"[智能分析]\n\n{response.strip()}"
        except Exception as e:
            return f"[智能分析] LLM 诊断失败：{str(e)}"

    def _handle_auto_fix(self, entities: Dict[str, Any]) -> str:
        """处理自动修复意图"""
        fix_action = entities.get("fix_action", "suggest").lower()
        fix_index = entities.get("fix_index")

        # 执行具体修复
        if fix_action in ("execute", "执行") and fix_index is not None:
            return self._execute_single_fix(int(fix_index))

        # 执行全部修复
        if fix_action in ("execute_all", "全部执行", "一键修复"):
            return self._execute_all_fixes()

        # 验证修复效果
        if fix_action in ("verify", "验证"):
            if hasattr(self, "_fix_data_before"):
                data_after = RCAEngine.collect_server_data()
                result = FixSuggester.verify_fix(self._fix_data_before, data_after, "disk")
                return f"[自动修复] 验证结果：{result}"
            return "[自动修复] 没有修复前数据，无法验证"

        # 默认：生成修复建议
        data = RCAEngine.collect_server_data()
        rule_fixes = FixSuggester.generate_rule_based_fixes(data)

        if not rule_fixes:
            # 规则未发现问题，调用 LLM
            fix_prompt = generate_fix_prompt_from_data(data)
            return self._call_llm_diagnosis(fix_prompt)

        # 缓存数据供后续使用
        self._fix_data_before = data
        self._pending_fix_suggestions = rule_fixes

        plan = FixPlan(
            summary="服务器问题修复",
            diagnosis=f"发现 {len(rule_fixes)} 个可修复问题",
            suggestions=rule_fixes,
            llm_advice="",
        )

        return FixSuggester.format_fix_plan(plan)

    def _do_execute_fix(self, index: int) -> str:
        """确认后的实际执行（已通过安全检查）"""
        if not hasattr(self, "_pending_fix_suggestions") or not self._pending_fix_suggestions:
            return "[自动修复] 修复建议已过期，请重新生成。"

        if index < 1 or index > len(self._pending_fix_suggestions):
            return f"[自动修复] 编号无效"

        fix = self._pending_fix_suggestions[index - 1]
        safety = fix.safety

        lines = [f"[自动修复] 正在执行: {fix.title}"]
        lines.append(f"  命令: {fix.command}")
        lines.append(f"  安全等级: {safety.value}")
        lines.append("")

        success, output = FixSuggester.execute_command(fix.command)
        if success:
            lines.append(f"  ✓ 执行成功")
            if output:
                lines.append(f"  输出: {output[:300]}")
        else:
            lines.append(f"  ✗ 执行失败: {output}")

        if hasattr(self, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            metric = "disk" if "磁盘" in fix.title or "clean" in fix.command.lower() else "memory"
            improved, verify_msg = FixSuggester.verify_fix(self._fix_data_before, data_after, metric)
            lines.append(f"")
            lines.append(f"  验证: {verify_msg}")
            if improved:
                self._fix_data_before = data_after

        self._pending_fix_suggestions.pop(index - 1)
        if self._pending_fix_suggestions:
            lines.append("")
            lines.append(f"  还有 {len(self._pending_fix_suggestions)} 个待修复建议。")

        return "\n".join(lines)

    def _do_execute_all_fixes(self) -> str:
        """确认后批量执行"""
        if not hasattr(self, "_pending_fix_suggestions") or not self._pending_fix_suggestions:
            return "[自动修复] 修复建议已过期，请重新生成。"

        lines = ["[自动修复] 开始批量修复", "=" * 50]
        total = len(self._pending_fix_suggestions)
        success_count = 0
        fail_count = 0

        for i, fix in enumerate(list(self._pending_fix_suggestions), 1):
            valid, msg = FixSuggester.validate_command(fix.command)
            if not valid:
                lines.append(f"  [{i}] 跳过: {fix.title} (安全检查未通过: {msg})")
                fail_count += 1
                continue

            success, output = FixSuggester.execute_command(fix.command)
            if success:
                lines.append(f"  [{i}] ✓ {fix.title}")
                success_count += 1
            else:
                lines.append(f"  [{i}] ✗ {fix.title}: {output}")
                fail_count += 1

        if hasattr(self, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            for metric in ("disk", "memory", "load"):
                improved, verify_msg = FixSuggester.verify_fix(self._fix_data_before, data_after, metric)
                lines.append(f"  [{metric}] {verify_msg}")

        lines.append("")
        lines.append(f"修复完成: 成功 {success_count}/{total}, 失败 {fail_count}/{total}")
        self._pending_fix_suggestions = []
        return "\n".join(lines)

    def _execute_single_fix(self, index: int) -> str:
        """执行单个修复建议"""
        if not hasattr(self, "_pending_fix_suggestions") or not self._pending_fix_suggestions:
            return "[自动修复] 没有待执行的修复建议，请先说'帮我修复'生成建议。"

        if index < 1 or index > len(self._pending_fix_suggestions):
            return f"[自动修复] 编号无效，请输入 1-{len(self._pending_fix_suggestions)}"

        fix = self._pending_fix_suggestions[index - 1]
        safety = fix.safety

        # 安全检查 — 黑名单直接拒绝
        valid, msg = FixSuggester.validate_command(fix.command)
        if not valid:
            return f"[自动修复] 命令安全检查未通过：{msg}"

        # 破坏性命令 — 必须二次确认
        if FixSuggester.needs_confirmation(fix.command):
            self.pending_task = PendingTask(
                task_type="fix_execute",
                package=str(index),
                message=(
                    f"[自动修复] ⚠ 此操作涉及文件清理/数据删除：\n"
                    f"  标题: {fix.title}\n"
                    f"  命令: {fix.command}\n"
                    f"  预期: {fix.expected_result}\n\n"
                    f"此操作不可逆，输入 'yes' 或 '确认' 执行。"
                ),
            )
            return self.pending_task.message

        # 安全命令 — 直接执行
        lines = [f"[自动修复] 正在执行: {fix.title}"]
        lines.append(f"  命令: {fix.command}")
        lines.append(f"  安全等级: {safety.value}")
        lines.append("")

        success, output = FixSuggester.execute_command(fix.command)
        if success:
            lines.append(f"  ✓ 执行成功")
            if output:
                output_preview = output[:300]
                lines.append(f"  输出: {output_preview}")
        else:
            lines.append(f"  ✗ 执行失败: {output}")

        # 验证效果
        if hasattr(self, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            metric = "disk" if "磁盘" in fix.title or "clean" in fix.command.lower() else "memory"
            improved, verify_msg = FixSuggester.verify_fix(self._fix_data_before, data_after, metric)
            lines.append(f"")
            lines.append(f"  验证: {verify_msg}")
            if improved:
                self._fix_data_before = data_after

        # 移除已执行的建议
        self._pending_fix_suggestions.pop(index - 1)
        if self._pending_fix_suggestions:
            lines.append("")
            lines.append(f"  还有 {len(self._pending_fix_suggestions)} 个待修复建议。")

        return "\n".join(lines)

    def _execute_all_fixes(self) -> str:
        """批量执行所有修复建议"""
        if not hasattr(self, "_pending_fix_suggestions") or not self._pending_fix_suggestions:
            return "[自动修复] 没有待执行的修复建议。"

        # 检查是否有破坏性命令
        has_destructive = any(
            FixSuggester.needs_confirmation(fix.command)
            for fix in self._pending_fix_suggestions
        )

        if has_destructive:
            self.pending_task = PendingTask(
                task_type="fix_execute_all",
                message=(
                    f"[自动修复] ⚠ 批量修复中包含文件清理操作，需要二次确认。\n"
                    f"  共 {len(self._pending_fix_suggestions)} 个修复任务\n\n"
                    f"输入 'yes' 或 '确认' 执行全部修复。"
                ),
            )
            return self.pending_task.message

        lines = ["[自动修复] 开始批量修复", "=" * 50]
        total = len(self._pending_fix_suggestions)
        success_count = 0
        fail_count = 0

        for i, fix in enumerate(list(self._pending_fix_suggestions), 1):
            valid, msg = FixSuggester.validate_command(fix.command)
            if not valid:
                lines.append(f"  [{i}] 跳过: {fix.title} (安全检查未通过: {msg})")
                fail_count += 1
                continue

            success, output = FixSuggester.execute_command(fix.command)
            if success:
                lines.append(f"  [{i}] ✓ {fix.title}")
                success_count += 1
            else:
                lines.append(f"  [{i}] ✗ {fix.title}: {output}")
                fail_count += 1

        # 验证总体效果
        if hasattr(self, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            for metric in ("disk", "memory", "load"):
                improved, verify_msg = FixSuggester.verify_fix(self._fix_data_before, data_after, metric)
                lines.append(f"  [{metric}] {verify_msg}")

        lines.append("")
        lines.append(f"修复完成: 成功 {success_count}/{total}, 失败 {fail_count}/{total}")
        self._pending_fix_suggestions = []
        return "\n".join(lines)

    def _handle_cert_check(self, entities: Dict[str, Any]) -> str:
        """处理证书监控意图"""
        domain = entities.get("domain")

        # 检查指定域名
        if domain:
            cert = CertMonitor.check_domain_cert(domain)
            if cert:
                status_icon = {"valid": "🟢", "expiring_soon": "🟡", "expired": "🔴"}[cert.status]
                days = f"剩余 {cert.days_left} 天" if cert.status == "valid" else (f"已过 {abs(cert.days_left)} 天" if cert.status == "expired" else f"剩余 {cert.days_left} 天")
                lines = [f"[SSL/TLS] {domain}:"]
                lines.append(f"  状态: {status_icon} {days}")
                lines.append(f"  主体: {cert.subject}")
                lines.append(f"  过期: {cert.not_after}")
                if cert.domains:
                    lines.append(f"  域名: {', '.join(cert.domains[:5])}")
                return "\n".join(lines)
            return f"[SSL/TLS] 无法获取 {domain} 的证书信息"

        # 全面扫描
        lines = []

        # 本地证书
        local_certs = CertMonitor.scan_local_certs()
        lines.append(f"[SSL/TLS] 本地证书扫描: 发现 {len(local_certs)} 个证书")
        for c in local_certs:
            if c.status != "valid":
                icon = "🔴" if c.status == "expired" else "🟡"
                lines.append(f"  {icon} {c.path} - 剩余 {c.days_left} 天 ({c.not_after})")

        # K8s 证书
        k8s_client, _, err = self._get_k8s_client(auto_detect=True)
        k8s_certs = []
        if not err and k8s_client:
            try:
                k8s_certs = CertMonitor.check_k8s_certs(k8s_client)
                lines.append(f"\n[SSL/TLS] K8s 证书扫描: 发现 {len(k8s_certs)} 个证书")
                for c in k8s_certs:
                    if c.status != "valid":
                        icon = "🔴" if c.status == "expired" else "🟡"
                        lines.append(f"  {icon} {c.path} - 剩余 {c.days_left} 天 ({c.not_after})")
            finally:
                k8s_client.close()

        # 域名证书
        domains = CertMonitor.detect_domains_from_config()
        domain_certs = []
        if domains:
            lines.append(f"\n[SSL/TLS] 检测到 {len(domains)} 个潜在域名，检查前 5 个:")
            for d in domains[:5]:
                cert = CertMonitor.check_domain_cert(d)
                if cert:
                    domain_certs.append(cert)
                    icon = "🔴" if cert.status == "expired" else ("🟡" if cert.status == "expiring_soon" else "🟢")
                    lines.append(f"  {icon} {d} - 剩余 {cert.days_left} 天 ({cert.not_after})")
                else:
                    lines.append(f"  ✗ {d} - 无法获取证书")

        if not lines:
            return "[SSL/TLS] 未发现任何证书"

        # 汇总报告
        all_certs = local_certs + k8s_certs + domain_certs
        expired = [c for c in all_certs if c.status == "expired"]
        expiring = [c for c in all_certs if c.status == "expiring_soon"]
        if expired or expiring:
            lines.append("")
            lines.append(f"⚠ 发现 {len(expired)} 个已过期、{len(expiring)} 个即将过期的证书")

        return "\n".join(lines)
