"""Agent 核心 - 意图处理和任务分发"""
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from .context import ContextManager, MemoryManager, AgentState
from ..nlu.base import NLUEngine, ParsedIntent, IntentType
from ..nlu.langchain_engine import LangChainEngine
from ..config import AppConfig
from ..tools.server import ServerTools, format_status_report
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

    def process(self, user_input: str) -> str:
        """处理用户输入

        Args:
            user_input: 用户输入文本

        Returns:
            str: Agent 回复
        """
        # 1. NLU 解析
        context_dict = {
            "last_host": self.state.context.current_host,
            "last_profile": self.state.context.current_profile,
            "last_intent": self.state.context.last_intent,
        }

        parsed = self.nlu.parse(user_input, context=context_dict)

        if parsed.error_message:
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
            IntentType.UNKNOWN: self._handle_unknown,
        }

        handler = handlers.get(parsed.intent, self._handle_unknown)
        return handler(parsed.entities)

    def _handle_inspect(self, entities: Dict[str, Any]) -> str:
        """处理服务器巡检意图"""
        host = entities.get("host") or self.state.context.current_host or "localhost"

        # 获取阈值配置
        profile = entities.get("profile") or self.state.context.current_profile
        thresholds = {
            "cpu": self.config.get_threshold("cpu", profile),
            "memory": self.config.get_threshold("memory", profile),
            "disk": self.config.get_threshold("disk", profile),
        }

        try:
            status = ServerTools.inspect_server(host)
            report = format_status_report(status, thresholds)

            # 更新上下文
            self.state.context.current_host = host

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

        # 切换环境
        if profile:
            self.state.context.current_profile = profile
            self.config.current_profile = profile
            return f"[配置] 已切换到环境：{profile}"

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
        # 获取最近的对话记忆
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
