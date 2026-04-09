"""Agent 核心 - 意图处理和任务分发"""
import time
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from .context import ContextManager, MemoryManager, AgentState
from .audit import AuditLogger
from ..nlu.base import NLUEngine, ParsedIntent, IntentType
from ..nlu.langchain_engine import LangChainEngine
from ..config import AppConfig
from ..tools.server import ServerTools, format_status_report, format_batch_report
from ..tools.scanner import ScannerTools, format_scan_result, NmapNotInstalledError
from ..tools.ssh import SSHTools, SSHConfig


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
            IntentType.UNKNOWN: self._handle_unknown,
        }

        handler = handlers.get(parsed.intent, self._handle_unknown)
        return handler(parsed.entities)

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

        # 系统日志查询
        if log_source in ("system", "journal"):
            from ..tools.logs import LogTools

            unit = entities.get("unit")
            lines = int(entities.get("lines", 50))
            since = entities.get("since")
            keyword = entities.get("query")

            success, output = LogTools.query_journal(
                lines=lines, unit=unit, since=since, keyword=keyword
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
