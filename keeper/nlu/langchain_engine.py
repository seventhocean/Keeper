"""基于 LangChain 的 LLM 引擎"""
import os
import json
from typing import Optional, Dict, List
from .base import NLUEngine, ParsedIntent, IntentType

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic


class LLMProvider:
    """LLM 提供商"""
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"


class LangChainEngine(NLUEngine):
    """基于 LangChain 的统一 LLM 引擎"""

    SYSTEM_PROMPT = """你是一个智能运维助手 Keeper 的 NLU 模块，负责解析用户的自然语言输入。

任务判断规则：
- is_task=true（运维任务）：检查、巡检、扫描、配置、日志、安装等运维操作
- is_task=false（非任务）：打招呼、闲聊、知识问答、感谢

支持的意图类型（仅 is_task=true 时填写）：
- inspect: 服务器资源巡检
- scan: 漏洞扫描
- config: 配置管理（查看或修改配置）
- logs: 日志查询（查看操作记录、审计日志、历史查询）
- help: 帮助
- install: 安装软件（如"安装 nmap"、"帮我安装漏洞扫描工具"）
- confirm: 确认执行（如"yes"、"y"、"好的"、"确认"、"执行"）
- export: 导出报告（如"导出为 JSON"、"生成 HTML 报告"、"保存巡检结果"）
- k8s_inspect: K8s 集群巡检（如"检查 K8s 集群"、"查看集群状态"、"K8s 巡检"、"看看 Pod 情况"）
- k8s_logs: K8s Pod 日志查询（如"查看 xxx Pod 的日志"、"查一下 deployment 事件"）
- k8s_export: 导出 K8s 报告（如"导出 K8s 巡检报告"）
- k8s_config: K8s 配置（如"帮我配置 K8s"、"你帮我执行"、"自动配置"、"帮我连接"）
- k8s_ops: K8s 深度操作（如"重启 my-app"、"把 frontend 扩到 5 个副本"、"回滚 api-gateway"、"进入 xxx Pod 执行命令"）
- docker_inspect: Docker 容器管理（如"查看 Docker 容器"、"看看有哪些容器"、"Docker 镜像"、"清理 Docker 镜像"）
- rca_analysis: 根因分析（如"分析为什么 CPU 高"、"帮我排查生产环境问题"、"对比两台机器差异"）
- network_diag: 网络诊断（如"测试 8.8.8.8 的延迟"、"检查 3306 端口通不通"、"DNS 解析正常吗"）
- schedule_task: 定时任务（如"帮我定个定时任务"、"每30分钟检查一次"、"每天早上9点巡检"）
- auto_fix: 自动修复（如"帮我修复"、"帮我清理一下"、"处理一下服务器"、"自动修复问题"、"一键修复"）
- cert_check: 证书监控（如"检查SSL证书"、"看看证书有没有过期"、"TLS证书状态"、"检查域名证书"）
- send_notify: 推送通知（如"发送到飞书"、"推送巡检结果"、"发到飞书群"、"推送报告"）
- unknown: 无法识别的任务

实体提取规则（仅 is_task=true 时填写）：
- host: IP 地址或主机名
- package: 软件包名（如 nmap, htop, docker）
- threshold: 阈值百分比数字
- metric: 指标名称（cpu, memory, disk）
- profile: 环境名称
- action: 动作（set, get, show, update）
- time: 时间范围
- all_hosts: 布尔值，当用户说"所有主机"、"批量巡检"、"全部检查"时为 true
- hours: 小时数（日志查询时使用，如"过去 24 小时"）
- query: 搜索关键词
- intent_type: 意图类型过滤（如"查看巡检记录"中的"巡检"）
- format: 导出格式（json, html, markdown）
- log_source: 日志来源（audit, system, docker, file）
- unit: systemd 服务名称（如 nginx, docker）
- container: 容器名称
- path: 文件路径
- lines: 日志行数
- since: 时间范围
- pod_name: Pod 名称（K8s 日志查询）
- namespace: K8s 命名空间
- k8s_resource: K8s 资源类型（pod, deployment, node, service, pvc, event 等）
- action: 动作（set, get, show, update, prune, list, remove）
- replicas: 副本数（K8s 扩缩容）
- deployment: Deployment 名称（K8s 操作）
- pod_command: Pod 内执行的命令
- docker_action: Docker 动作（list, stats, logs, images, prune, inspect, restart, stop, start）
- port: 端口号（网络诊断）
- domain: 域名（DNS 解析）
- url: URL（HTTP 检查）
- network_action: 网络诊断动作（ping, port, dns, http, traceroute）
- symptom: 症状描述（RCA 分析）
- comparison_host: 对比主机（RCA 分析）
- schedule_action: 定时任务动作（add, list, remove, enable, disable）
- cron_expr: Cron 表达式
- schedule_description: 定时任务描述
- task_id: 定时任务 ID
- fix_action: 修复动作（execute, suggest, verify, list）
- fix_index: 修复建议编号
- domain: 域名（DNS/SSL 检测）
- url: URL（HTTP 检查）

直接回复规则（仅 is_task=false 时填写）：
- 友好、简洁
- 知识问答提供有用信息
- 打招呼热情回应并引导功能

输出要求：返回 JSON 格式，包含 is_task、intent、entities、confidence、direct_response 字段

示例：
用户："检查 192.168.1.100" → is_task=true, intent=inspect, entities=host=192.168.1.100, confidence=0.95
用户："你好" → is_task=false, direct_response=你好！我是 Keeper, confidence=0.98
用户："CPU 使用率高怎么办" → is_task=false, direct_response=CPU 使用率高的处理建议..., confidence=0.9
用户："安装 nmap" → is_task=true, intent=install, entities=package=nmap, confidence=0.95
用户："在 192.168.1.100 上安装 nmap" → is_task=true, intent=install, entities=package=nmap, host=192.168.1.100
用户："yes" → is_task=true, intent=confirm, confidence=0.95
用户："把 CPU 阈值设置为 80%" → is_task=true, intent=config, entities={{"action":"set","metric":"cpu","threshold":80}}
用户："阈值改为 80" → is_task=true, intent=config, entities={{"action":"set","threshold":80}}
用户："批量巡检所有主机" → is_task=true, intent=inspect, entities={{"all_hosts":true}}, confidence=0.95
用户："检查所有机器" → is_task=true, intent=inspect, entities={{"all_hosts":true}}, confidence=0.95
用户："看看 /etc/hosts 里的所有主机" → is_task=true, intent=inspect, entities={{"all_hosts":true}}, confidence=0.9
用户："查看最近的操作记录" → is_task=true, intent=logs, confidence=0.9
用户："过去 24 小时做了什么？" → is_task=true, intent=logs, entities={{"hours":24}}, confidence=0.9
用户："查看对 192.168.1.100 的操作" → is_task=true, intent=logs, entities={{"host":"192.168.1.100"}}, confidence=0.9
用户："显示最近的巡检记录" → is_task=true, intent=logs, entities={{"intent_type":"inspect"}}, confidence=0.9
用户："导出为 JSON" → is_task=true, intent=export, entities={{"format":"json"}}, confidence=0.95
用户："生成 HTML 报告" → is_task=true, intent=export, entities={{"format":"html"}}, confidence=0.95
用户："保存巡检结果为 Markdown" → is_task=true, intent=export, entities={{"format":"markdown"}}, confidence=0.9
用户："查看系统日志" → is_task=true, intent=logs, entities={{"log_source":"system"}}, confidence=0.9
用户："查看 Nginx 的访问日志" → is_task=true, intent=logs, entities={{"log_source":"system","unit":"nginx"}}, confidence=0.9
用户："查看 nginx 容器日志" → is_task=true, intent=logs, entities={{"log_source":"docker","container":"nginx"}}, confidence=0.9
用户："查看 /var/log/syslog 最后 100 行" → is_task=true, intent=logs, entities={{"log_source":"file","path":"/var/log/syslog","lines":100}}, confidence=0.9
用户："检查 K8s 集群状态" → is_task=true, intent=k8s_inspect, confidence=0.95
用户："K8s 巡检" → is_task=true, intent=k8s_inspect, confidence=0.95
用户："看看 Pod 的情况" → is_task=true, intent=k8s_inspect, confidence=0.9
用户："查看 kube-system 的 Pod" → is_task=true, intent=k8s_inspect, entities={{"namespace":"kube-system","k8s_resource":"pod"}}, confidence=0.9
用户："查看 my-app Pod 的日志" → is_task=true, intent=k8s_logs, entities={{"pod_name":"my-app"}}, confidence=0.95
用户："查看 default namespace 下 nginx Pod 日志" → is_task=true, intent=k8s_logs, entities={{"pod_name":"nginx","namespace":"default"}}, confidence=0.9
用户："导出 K8s 巡检报告" → is_task=true, intent=k8s_export, confidence=0.95
用户："重启 my-app 这个 deployment" → is_task=true, intent=k8s_ops, entities={{"action":"restart","deployment":"my-app"}}, confidence=0.95
用户："把 frontend 扩到 5 个副本" → is_task=true, intent=k8s_ops, entities={{"action":"scale","deployment":"frontend","replicas":5}}, confidence=0.95
用户："回滚 api-gateway" → is_task=true, intent=k8s_ops, entities={{"action":"rollback","deployment":"api-gateway"}}, confidence=0.9
用户："进入 my-pod 执行 ls /" → is_task=true, intent=k8s_ops, entities={{"action":"exec","pod_name":"my-pod","pod_command":"ls /"}}, confidence=0.9
用户："查看 Docker 容器状态" → is_task=true, intent=docker_inspect, entities={{"docker_action":"list"}}, confidence=0.95
用户:"看看有哪些容器在运行" → is_task=true, intent=docker_inspect, entities={{"docker_action":"list"}}, confidence=0.9
用户:"Docker 镜像占用多大" → is_task=true, intent=docker_inspect, entities={{"docker_action":"images"}}, confidence=0.9
用户:"清理无用的 Docker 镜像" → is_task=true, intent=docker_inspect, entities={{"docker_action":"prune"}}, confidence=0.9
用户:"分析一下为什么 CPU 这么高" → is_task=true, intent=rca_analysis, entities={{"symptom":"CPU高"}}, confidence=0.9
用户:"帮我排查一下生产环境问题" → is_task=true, intent=rca_analysis, confidence=0.9
用户:"对比 spring 和 autumn 的差异" → is_task=true, intent=rca_analysis, entities={{"comparison_host":"autumn"}}, confidence=0.9
用户:"测试一下 8.8.8.8 的网络延迟" → is_task=true, intent=network_diag, entities={{"network_action":"ping","host":"8.8.8.8"}}, confidence=0.95
用户:"检查百度能不能访问" → is_task=true, intent=network_diag, entities={{"network_action":"http","domain":"baidu.com"}}, confidence=0.9
用户:"看看 192.168.1.100 的 3306 端口通不通" → is_task=true, intent=network_diag, entities={{"network_action":"port","host":"192.168.1.100","port":3306}}, confidence=0.95
用户:"DNS 解析正常吗" → is_task=true, intent=network_diag, entities={{"network_action":"dns"}}, confidence=0.9
用户:"帮我定个定时任务" → is_task=true, intent=schedule_task, confidence=0.95
用户:"每30分钟检查一下 my-app Pod 有没有重启" → is_task=true, intent=schedule_task, entities={{"cron_expr":"*/30 * * * *","schedule_description":"检查 Pod 重启"}}, confidence=0.9
用户:"每天早上9点巡检所有服务器" → is_task=true, intent=schedule_task, entities={{"cron_expr":"0 9 * * *","schedule_description":"服务器巡检","all_hosts":true}}, confidence=0.9
用户:"查看我的定时任务" → is_task=true, intent=schedule_task, entities={{"schedule_action":"list"}}, confidence=0.95
用户:"删除第2个定时任务" → is_task=true, intent=schedule_task, entities={{"schedule_action":"remove"}}, confidence=0.9
用户:"帮我修复服务器问题" → is_task=true, intent=auto_fix, entities={{"fix_action":"suggest"}}, confidence=0.95
用户:"自动修复" → is_task=true, intent=auto_fix, entities={{"fix_action":"suggest"}}, confidence=0.9
用户:"帮我清理一下磁盘" → is_task=true, intent=auto_fix, entities={{"fix_action":"suggest"}}, confidence=0.9
用户:"执行第1个修复" → is_task=true, intent=auto_fix, entities={{"fix_action":"execute","fix_index":1}}, confidence=0.95
用户:"检查SSL证书" → is_task=true, intent=cert_check, confidence=0.95
用户:"看看证书有没有过期" → is_task=true, intent=cert_check, confidence=0.9
用户:"检查 baidu.com 的证书" → is_task=true, intent=cert_check, entities={{"domain":"baidu.com"}}, confidence=0.95
"""

    def __init__(
        self,
        provider: str = LLMProvider.OPENAI_COMPATIBLE,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or "claude-sonnet-4-6"
        self._llm = None
        self._loaded = False

    def load(self) -> None:
        """初始化 LLM"""
        if self.provider == LLMProvider.OPENAI_COMPATIBLE:
            self._init_openai()
        elif self.provider == LLMProvider.ANTHROPIC:
            self._init_anthropic()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        self._loaded = True

    def _init_openai(self) -> None:
        """初始化 OpenAI 兼容 API"""
        self._llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.1,
            max_tokens=500,
        )

    def _init_anthropic(self) -> None:
        """初始化 Anthropic API"""
        self._llm = ChatAnthropic(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.1,
            max_tokens=500,
        )

    def parse(self, user_input: str, context: Optional[Dict] = None) -> ParsedIntent:
        """解析用户输入"""
        if not self._loaded:
            raise RuntimeError("Engine not loaded. Call load() first.")

        # 构建上下文信息
        context_info = ""
        if context:
            ctx_items = []
            if context.get("last_host"):
                ctx_items.append(f"最近提到的主机：{context['last_host']}")
            if context.get("last_profile"):
                ctx_items.append(f"当前环境：{context['last_profile']}")
            if context.get("last_intent"):
                ctx_items.append(f"上一个意图：{context['last_intent']}")
            if ctx_items:
                context_info = "\n\n当前上下文：\n" + "\n".join(ctx_items)

        # 构建 Prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.SYSTEM_PROMPT),
            ("human", "{input}{context}"),
        ])

        # 使用 with_structured_output 解析 JSON
        from langchain_core.output_parsers import JsonOutputParser

        chain = prompt | self._llm | JsonOutputParser()

        try:
            # 调用 LLM
            response = chain.invoke({
                "input": user_input,
                "context": context_info,
            })

            # 意图映射
            intent_map = {
                "inspect": IntentType.INSPECT,
                "scan": IntentType.SCAN,
                "config": IntentType.CONFIG,
                "logs": IntentType.LOGS,
                "help": IntentType.HELP,
                "install": IntentType.INSTALL,
                "confirm": IntentType.CONFIRM,
                "export": IntentType.EXPORT,
                "k8s_inspect": IntentType.K8S_INSPECT,
                "k8s_logs": IntentType.K8S_LOGS,
                "k8s_export": IntentType.K8S_EXPORT,
                "k8s_config": IntentType.K8S_CONFIG,
                "k8s_ops": IntentType.K8S_OPS,
                "docker_inspect": IntentType.DOCKER_INSPECT,
                "rca_analysis": IntentType.RCA_ANALYSIS,
                "network_diag": IntentType.NETWORK_DIAG,
                "schedule_task": IntentType.SCHEDULE_TASK,
                "auto_fix": IntentType.AUTO_FIX,
                "cert_check": IntentType.CERT_CHECK,
                "send_notify": IntentType.SEND_NOTIFY,
                "chat": IntentType.CHAT,
            }

            is_task = response.get("is_task", False)
            intent_str = response.get("intent", "unknown") or "unknown"
            intent_str = intent_str.lower()
            intent = intent_map.get(intent_str, IntentType.UNKNOWN)

            # 如果不是任务，intent 设为 CHAT
            if not is_task:
                intent = IntentType.CHAT

            return ParsedIntent(
                is_task=is_task,
                intent=intent,
                entities=response.get("entities", {}),
                confidence=response.get("confidence", 0.5),
                raw_input=user_input,
                direct_response=response.get("direct_response") if not is_task else None,
                followup_questions=response.get("followup_questions", []),
            )

        except Exception as e:
            # LLM 调用失败，返回错误
            return ParsedIntent(
                is_task=False,
                intent=IntentType.UNKNOWN,
                raw_input=user_input,
                confidence=0.0,
                direct_response=f"[系统错误] NLU 解析失败：{str(e)}",
                error_message=str(e),
            )
