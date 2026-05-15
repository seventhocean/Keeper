"""Agent 核心 - 意图处理和任务分发（经典路由器模式）

重构后仅保留：
- Agent 类定义和生命周期管理
- 意图分发路由
- 确认任务处理
- 辅助方法（LLM 调用、通知）

具体的意图处理逻辑已拆分到 keeper/core/handlers/ 目录。
"""
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from .context import ContextManager, MemoryManager, AgentState
from .audit import AuditLogger
from ..nlu.base import NLUEngine, ParsedIntent, IntentType
from ..nlu.langchain_engine import LangChainEngine
from ..config import AppConfig
from ..tools.server import ServerTools, format_status_report
from ..tools.scanner import NmapNotInstalledError
from ..tools.ssh import SSHTools, SSHConfig
from ..tools.docker_tools import DockerTools
from ..tools.network import NetworkTools, format_ping_result
from ..tools.rca import RCAEngine
from ..tools.fixer import FixSuggester
from ..tools.scheduler import TaskScheduler
from ..tools.notify import FeishuNotifier

# 导入所有 handler
from .handlers import (
    handle_inspect, handle_k8s_inspect, handle_k8s_logs,
    handle_k8s_export, handle_k8s_config, handle_k8s_ops,
    handle_docker, handle_network, handle_scan, handle_cert_check,
    handle_auto_fix, handle_logs, handle_send_notify, handle_schedule,
    handle_help, handle_chat, handle_unknown, handle_config,
    handle_export, handle_install, handle_confirm_no_task,
)


@dataclass
class PendingTask:
    """待确认任务"""
    task_type: str  # "install", "scan" 等
    package: Optional[str] = None
    host: Optional[str] = None
    message: Optional[str] = None


class Agent:
    """智能运维 Agent（经典路由器模式）"""

    def __init__(self, nlu_engine: NLUEngine, config: Optional[AppConfig] = None):
        self.nlu = nlu_engine
        self.config = config or AppConfig.from_env()
        self.state = AgentState()
        self.state.is_running = True
        self.pending_task: Optional[PendingTask] = None
        self.audit = AuditLogger()
        self.scheduler = TaskScheduler(config_dir=self.config.config_dir)
        self.scheduler.set_callback(self._execute_scheduled_task)
        self.scheduler.start()
        self._last_inspect_statuses: Optional[List] = None

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
            response_time = int((time.time() - start_time) * 1000)
            self.audit.log_turn(
                intent="unknown", entities={}, result="error",
                response_time_ms=response_time, error_message=parsed.error_message,
            )
            return f"[错误] NLU 解析失败：{parsed.error_message}"

        # 2. 非任务直接返回
        if not parsed.is_task:
            response = parsed.direct_response or "[系统] 抱歉，我没有理解您的意思。"
            self.state.memory.add_turn(
                user_input=user_input, agent_response=response, intent="chat", entities={},
            )
            response_time = int((time.time() - start_time) * 1000)
            self.audit.log_turn(
                intent="chat", entities={}, result="success",
                response_time_ms=response_time, response=response,
            )
            return response

        # 3. 更新上下文
        self.state.context.update(parsed.intent.value, parsed.entities)

        # 4. 意图分发
        response = self._dispatch(parsed)

        # 5. 记录到记忆
        self.state.memory.add_turn(
            user_input=user_input, agent_response=response,
            intent=parsed.intent.value, entities=parsed.entities,
        )

        # 6. 记录审计日志
        response_time = int((time.time() - start_time) * 1000)
        is_error = response.startswith("[错误]") or response.startswith("[扫描] 扫描失败") or response.startswith("[巡检] 检查失败")
        self.audit.log_turn(
            intent=parsed.intent.value, entities=parsed.entities,
            result="error" if is_error else "success",
            response_time_ms=response_time,
            host=parsed.entities.get("host"),
            error_message=response if is_error else None,
            response=response if not is_error else None,
        )

        # 7. 自动通知
        self._maybe_notify(parsed.intent, parsed.entities, response, is_error)

        return response

    def _dispatch(self, parsed: ParsedIntent) -> str:
        """意图分发"""
        # 优先处理确认任务
        if parsed.intent == IntentType.CONFIRM and self.pending_task:
            return self._handle_confirm(parsed.entities)

        # Handler 映射表 — 委托给 handlers 模块
        handlers = {
            IntentType.INSPECT: handle_inspect,
            IntentType.SCAN: handle_scan,
            IntentType.CONFIG: handle_config,
            IntentType.LOGS: handle_logs,
            IntentType.HELP: handle_help,
            IntentType.INSTALL: handle_install,
            IntentType.CONFIRM: handle_confirm_no_task,
            IntentType.CHAT: handle_chat,
            IntentType.EXPORT: handle_export,
            IntentType.K8S_INSPECT: handle_k8s_inspect,
            IntentType.K8S_LOGS: handle_k8s_logs,
            IntentType.K8S_EXPORT: handle_k8s_export,
            IntentType.K8S_CONFIG: handle_k8s_config,
            IntentType.K8S_OPS: handle_k8s_ops,
            IntentType.DOCKER_INSPECT: handle_docker,
            IntentType.RCA_ANALYSIS: self._handle_rca,
            IntentType.NETWORK_DIAG: handle_network,
            IntentType.SCHEDULE_TASK: handle_schedule,
            IntentType.AUTO_FIX: handle_auto_fix,
            IntentType.CERT_CHECK: handle_cert_check,
            IntentType.SEND_NOTIFY: handle_send_notify,
            IntentType.UNKNOWN: handle_unknown,
        }

        handler = handlers.get(parsed.intent, handle_unknown)

        # 注入原始输入到 entities
        entities = dict(parsed.entities)
        entities["_raw_input"] = parsed.raw_input

        # 区分内部方法和外部 handler
        if callable(handler) and hasattr(handler, '__self__'):
            # 绑定方法 (self._handle_xxx)
            return handler(entities)
        else:
            # 外部 handler 函数 — 传入上下文
            return handler(
                entities,
                config=self.config,
                state=self.state,
                agent_ref=self,
            )

    # ─── 确认任务处理 ───────────────────────────────────────────

    def _handle_confirm(self, entities: Dict[str, Any]) -> str:
        """处理确认执行任务"""
        if not self.pending_task:
            return "[系统] 当前没有待确认的任务。"

        task = self.pending_task
        self.pending_task = None

        if task.task_type == "install":
            return self._execute_install(task.package, task.host)
        elif task.task_type == "scan":
            from .handlers.security import handle_scan
            return handle_scan(
                {"host": task.host}, config=self.config, state=self.state, agent_ref=self
            )
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

    def _execute_install(self, package: str, host: str) -> str:
        """执行安装（本地）"""
        import subprocess

        lines = [f"[安装] 正在安装 {package}..."]
        lines.append("")

        install_cmd = NmapNotInstalledError.get_install_command()

        try:
            result = subprocess.run(
                install_cmd, shell=True, capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                lines.append(f"[✓] {package} 已在 {host} 上成功安装")
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

    def _execute_k8s_config(self, entities: Dict[str, Any]) -> str:
        """执行 K8s 配置（用户选择后的确认）"""
        candidates_str = getattr(self, '_pending_k8s_candidates', "")
        self._pending_k8s_candidates = ""

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

        from ..tools.k8s.client import K8sClient, K8sClusterConfig
        k8s_cfg = K8sClusterConfig(
            kubeconfig_path=kubeconfig, cluster_type=self.config.k8s["cluster_type"],
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

    def _execute_k8s_ops(self, task: PendingTask) -> str:
        """执行 K8s 确认操作"""
        from .handlers.k8s import _get_k8s_client
        k8s_client, _, err = _get_k8s_client(self.config, auto_detect=False)
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

    def _execute_schedule_confirm(self, task: PendingTask) -> str:
        """确认并添加定时任务"""
        raw_input = task.message.split("当前输入：")[-1] if "当前输入：" in task.message else ""
        context_dict = {
            "last_host": self.state.context.current_host,
            "last_intent": self.state.context.last_intent,
        }
        parsed = self.nlu.parse(raw_input, context=context_dict)
        cron_expr = parsed.entities.get("cron_expr", "")

        if not cron_expr:
            return "[定时任务] 抱歉，我没有理解你的定时任务需求。请用更明确的描述。"

        description = parsed.entities.get("schedule_description", raw_input)
        task_type = "inspect"
        if "k8s" in raw_input.lower():
            task_type = "k8s_inspect"
        elif parsed.entities.get("all_hosts"):
            task_type = "batch_inspect"

        task_obj = self.scheduler.add_task(
            cron_expr=cron_expr, description=description,
            task_type=task_type, params=parsed.entities,
        )
        return (
            f"[定时任务] 已添加任务\n\n"
            f"  ID: {task_obj.id}\n"
            f"  描述: {task_obj.description}\n"
            f"  Cron: {task_obj.cron_expr}\n"
            f"  类型: {task_obj.task_type}\n\n"
            f"任务将在到达时间自动执行。"
        )

    def _do_execute_fix(self, index: int) -> str:
        """确认后执行单个修复"""
        if not hasattr(self, "_pending_fix_suggestions") or not self._pending_fix_suggestions:
            return "[自动修复] 修复建议已过期，请重新生成。"

        if index < 1 or index > len(self._pending_fix_suggestions):
            return "[自动修复] 编号无效"

        fix = self._pending_fix_suggestions[index - 1]

        lines = [f"[自动修复] 正在执行: {fix.title}"]
        lines.append(f"  命令: {fix.command}")
        lines.append(f"  安全等级: {fix.safety.value}")
        lines.append("")

        success, output = FixSuggester.execute_command(fix.command)
        if success:
            lines.append("  ✓ 执行成功")
            if output:
                lines.append(f"  输出: {output[:300]}")
        else:
            lines.append(f"  ✗ 执行失败: {output}")

        if hasattr(self, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            metric = "disk" if "磁盘" in fix.title or "clean" in fix.command.lower() else "memory"
            improved, verify_msg = FixSuggester.verify_fix(self._fix_data_before, data_after, metric)
            lines.append("")
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
            return "[自动修复] 修复建议已过期。"

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

    # ─── RCA（根因分析 — 保留在此，因为需要调用 _call_llm_diagnosis）───

    def _handle_rca(self, entities: Dict[str, Any]) -> str:
        """处理根因分析意图"""
        symptom = entities.get("symptom", "")
        comparison_host = entities.get("comparison_host")

        if comparison_host:
            try:
                data_a = RCAEngine.collect_server_data()
                data_b = RCAEngine.collect_server_data(comparison_host)
                compare_text = RCAEngine.compare_hosts(data_a, data_b, "localhost", comparison_host)
                prompt = RCAEngine.generate_compare_prompt(compare_text)
                return self._call_llm_diagnosis(prompt)
            except Exception as e:
                return f"[RCA] 对比分析失败：{str(e)}"

        try:
            data = RCAEngine.collect_server_data()
            data_text = RCAEngine.analyze_server(data)
            prompt = RCAEngine.generate_diagnosis_prompt(data_text, symptom)
            return self._call_llm_diagnosis(prompt)
        except Exception as e:
            return f"[RCA] 分析失败：{str(e)}"

    # ─── 辅助方法 ─────────────────────────────────────────────────

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

    def _maybe_notify(self, intent: IntentType, entities: Dict[str, Any], response: str, is_error: bool) -> None:
        """任务执行后自动推送到飞书"""
        nc = self.config.get_notification_config()
        webhook = nc.get("feishu_webhook")
        if not webhook:
            return

        inspect_intents = {IntentType.INSPECT, IntentType.K8S_INSPECT, IntentType.DOCKER_INSPECT}
        if intent not in inspect_intents:
            return

        notifier = FeishuNotifier(webhook, nc.get("feishu_secret"))

        if self._last_inspect_statuses:
            thresholds = {
                "cpu": self.config.get_threshold("cpu"),
                "memory": self.config.get_threshold("memory"),
                "disk": self.config.get_threshold("disk"),
            }
            notifier.send_report(
                statuses=self._last_inspect_statuses,
                thresholds=thresholds,
                title="Keeper 服务器巡检报告",
            )

    def _execute_scheduled_task(self, task) -> str:
        """执行定时任务回调"""
        task_type = task.task_type
        params = task.params

        thresholds = {
            "cpu": self.config.get_threshold("cpu"),
            "memory": self.config.get_threshold("memory"),
            "disk": self.config.get_threshold("disk"),
        }

        if task_type == "inspect":
            status = ServerTools.inspect_server("localhost")
            return format_status_report(status, thresholds)
        elif task_type == "batch_inspect":
            from ..tools.server import format_batch_report
            hosts = SSHTools.get_hosts_from_file("/etc/hosts")
            if not hosts:
                return "[定时任务] 批量巡检：/etc/hosts 中无主机"
            statuses = ServerTools.inspect_multiple_hosts(hosts)
            return format_batch_report(statuses, thresholds)
        elif task_type == "k8s_inspect":
            from .handlers.k8s import _get_k8s_client
            k8s_client, fmt, err = _get_k8s_client(self.config, auto_detect=True)
            if err:
                return f"[定时任务] K8s 巡检：{err}"
            try:
                from ..tools.k8s.inspector import K8sInspector
                namespace = params.get("namespace") or None
                success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
                if not success:
                    return "[定时任务] K8s 巡检失败"
                return fmt(report, namespace)
            finally:
                k8s_client.close()
        elif task_type == "network_diag":
            result = NetworkTools.ping("8.8.8.8", count=4)
            return format_ping_result(result)

        return f"[定时任务] 已触发: {task.description}"

    # ─── 公共接口 ────────────────────────────────────────────────

    def get_context(self) -> ContextManager:
        """获取上下文管理器"""
        return self.state.context

    def get_memory(self) -> MemoryManager:
        """获取记忆管理器"""
        return self.state.memory

    def stop(self) -> None:
        """停止 Agent"""
        self.state.is_running = False
