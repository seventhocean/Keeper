"""CLI 入口 - Click + Prompt Toolkit"""
import os
import sys
import click
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from .config import AppConfig
from .core.agent import Agent
from .nlu.langchain_engine import LangChainEngine, LLMProvider


# ANSI 颜色样式
STYLE = Style.from_dict({
    'prompt': 'ansicyan bold',
    'info': 'ansigreen',
    'warning': 'ansiyellow',
    'error': 'ansired bold',
})

BANNER = """
┌─────────────────────────────────────────┐
│  Keeper v0.4.0-dev - 智能运维助手        │
└─────────────────────────────────────────┘
"""


def create_agent(config: AppConfig) -> Agent:
    """创建 Agent 实例"""
    # 根据配置选择 Provider
    provider_map = {
        "openai_compatible": LLMProvider.OPENAI_COMPATIBLE,
        "anthropic": LLMProvider.ANTHROPIC,
    }

    provider = provider_map.get(config.llm.provider, LLMProvider.OPENAI_COMPATIBLE)

    # 创建 LLM 引擎
    engine = LangChainEngine(
        provider=provider,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
    )
    engine.load()

    return Agent(nlu_engine=engine, config=config)


@click.group(invoke_without_command=True)
@click.version_option(version='0.4.0-dev')
@click.pass_context
def cli(ctx):
    """Keeper - 智能运维助手"""
    if ctx.invoked_subcommand is None:
        # 没有子命令时，启动交互模式
        start_chat()


def start_chat():
    """启动交互式对话模式"""
    # 加载配置
    config = AppConfig.from_env()
    config.load()

    # 检查 API Key（从配置文件加载）
    if not config.is_llm_configured():
        click.echo(click.style("[错误] 请配置 API Key:", fg='red'))
        click.echo("\n使用以下命令配置:")
        click.echo("  keeper config set --api-key YOUR_API_KEY")
        click.echo("\n或直接设置环境变量:")
        click.echo("  export KEEPER_API_KEY='your-api-key'")
        sys.exit(1)

    # 创建 Agent
    agent = create_agent(config)

    # 打印欢迎语
    click.echo(BANNER, color=True)
    click.echo(click.style("👋 你好！我是 Keeper，你的智能运维助手。", fg='green'))
    click.echo(f"   已连接：{config.llm.base_url} ({config.llm.model})")
    click.echo("   输入 '退出' 或 Ctrl+D 结束会话\n")

    # REPL 循环
    while True:
        try:
            user_input = prompt(
                [('class:prompt', 'keeper> ')],
                style=STYLE,
                history=FileHistory(os.path.expanduser('~/.keeper/history.txt')),
                auto_suggest=AutoSuggestFromHistory(),
            ).strip()

            if not user_input:
                continue

            if user_input in ("退出", "exit", "quit", "bye"):
                click.echo(click.style("👋 再见！", fg='green'))
                break

            # 处理输入
            response = agent.process(user_input)
            click.echo(f"\n{response}\n")

        except KeyboardInterrupt:
            continue
        except EOFError:
            click.echo(click.style("\n👋 再见！", fg='green'))
            break
        except Exception as e:
            click.echo(click.style(f"[错误] {e}\n", fg='red'))


@cli.command()
def chat():
    """启动交互式对话模式"""
    start_chat()


@cli.command(context_settings={'ignore_unknown_options': True})
@click.argument('command', nargs=-1)
@click.option('--host', '-h', help='目标主机 IP 或主机名')
@click.option('--profile', '-p', help='使用的环境配置')
@click.option('--full', is_flag=True, help='执行完整扫描')
def run(command, host, profile, full):
    """执行单条命令

    示例:
        keeper run 检查 192.168.1.100
        keeper run 扫描漏洞 --host 192.168.1.100
        keeper run 巡检 --profile production
    """
    # 加载配置
    config = AppConfig.from_env()
    config.load()

    # 检查 API Key
    if not config.is_llm_configured():
        click.echo(click.style("[错误] 请配置 API Key:", fg='red'))
        click.echo("  使用：keeper config set --api-key YOUR_API_KEY")
        sys.exit(1)

    # 创建 Agent
    agent = create_agent(config)

    # 构建用户输入
    user_input = ' '.join(command)

    # 添加命令行参数到上下文
    if host:
        user_input = f"{user_input} {host}"

    # 处理输入
    try:
        response = agent.process(user_input)
        click.echo(response)
    except Exception as e:
        click.echo(click.style(f"[错误] {e}", fg='red'))
        sys.exit(1)


@cli.command(context_settings={'ignore_unknown_options': True})
@click.argument('shell_command', nargs=-1)
@click.option('--host', '-h', default='localhost', help='目标主机')
def exec(shell_command, host):
    """执行 Shell 命令

    示例:
        keeper exec ls -la /home
        keeper exec df -h
        keeper exec ps aux --sort=-%mem
    """
    import subprocess

    cmd = ' '.join(shell_command)
    if not cmd:
        click.echo(click.style("[错误] 请指定要执行的命令", fg='red'))
        sys.exit(1)

    try:
        if host == 'localhost':
            # 本地执行
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                click.echo(result.stdout)
            else:
                click.echo(click.style(f"[错误] {result.stderr}", fg='red'))
                sys.exit(result.returncode)
        else:
            # 远程执行
            from keeper.tools.ssh import SSHTools, SSHConfig
            ssh_config = SSHConfig(host=host)
            success, output = SSHTools.execute(ssh_config, cmd)
            if success:
                click.echo(output)
            else:
                click.echo(click.style(f"[错误] {output}", fg='red'))
                sys.exit(1)
    except subprocess.TimeoutExpired:
        click.echo(click.style("[错误] 命令执行超时", fg='red'))
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"[错误] {e}", fg='red'))
        sys.exit(1)


@cli.command()
def status():
    """显示当前状态"""
    config = AppConfig.from_env()
    config.load()

    click.echo("Keeper 状态")
    click.echo("━" * 40)
    click.echo(f"配置文件：{config.config_file}")
    click.echo(f"当前环境：{config.current_profile}")
    click.echo(f"LLM Provider: {config.llm.provider}")
    click.echo(f"Model: {config.llm.model}")
    click.echo(f"Base URL: {config.llm.base_url}")

    if config.is_llm_configured():
        key_preview = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else config.llm.api_key
        click.echo(f"API Key: {key_preview} ✓")
    else:
        click.echo(click.style("API Key: 未设置 ✗", fg='red'))


@cli.command()
@click.option('--hours', '-h', default=24, type=int, help='查询最近 N 小时的记录')
@click.option('--host', type=str, help='按主机过滤')
@click.option('--intent', type=str, help='按意图类型过滤 (inspect, scan, config 等)')
@click.option('--json', 'as_json', is_flag=True, help='以 JSON 格式输出')
def logs(hours, host, intent, as_json):
    """查看审计日志

    示例:
        keeper logs --hours 24
        keeper logs --host 192.168.1.100
        keeper logs --intent inspect
        keeper logs --json
    """
    from keeper.core.agent import Agent
    from keeper.nlu.langchain_engine import LangChainEngine, LLMProvider

    # 加载配置
    config = AppConfig.from_env()
    config.load()

    # 检查 API Key
    if not config.is_llm_configured():
        click.echo(click.style("[错误] 请配置 API Key:", fg='red'))
        click.echo("  使用：keeper config set --api-key YOUR_API_KEY")
        sys.exit(1)

    # 创建 Agent（用于获取审计日志）
    provider_map = {
        "openai_compatible": LLMProvider.OPENAI_COMPATIBLE,
        "anthropic": LLMProvider.ANTHROPIC,
    }
    provider = provider_map.get(config.llm.provider, LLMProvider.OPENAI_COMPATIBLE)
    engine = LangChainEngine(
        provider=provider,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
    )
    engine.load()
    agent = Agent(nlu_engine=engine, config=config)

    # 查询审计日志
    records = agent.audit.get_history(hours=hours, limit=100, host=host, intent=intent)

    if not records:
        click.echo(f"[日志] 过去 {hours} 小时内没有找到操作记录")
        return

    if as_json:
        import json
        output = []
        for record in records:
            output.append({
                "timestamp": record.timestamp,
                "intent": record.intent,
                "host": record.host,
                "result": record.result,
                "response_time_ms": record.response_time_ms,
            })
        click.echo(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # 格式化输出
        lines = [f"[日志] 过去 {hours} 小时的操作记录:"]
        lines.append("━" * 60)
        for i, record in enumerate(records, 1):
            time_str = record.timestamp[11:19]  # 提取 HH:MM:SS
            result_icon = "✓" if record.result == "success" else "✗"
            host_str = f" ({record.host})" if record.host else ""
            lines.append(f"  {i}. [{time_str}] {result_icon} {record.intent}{host_str} ({record.response_time_ms}ms)")

        lines.append("━" * 60)
        lines.append(f"共 {len(records)} 条记录")

        click.echo("\n".join(lines))


@cli.command()
def init():
    """初始化配置文件"""
    config = AppConfig.from_env()

    # 创建默认配置
    config.profiles = {
        "dev": {
            "hosts": ["localhost"],
            "thresholds": {
                "cpu": 90,
                "memory": 90,
                "disk": 95,
            }
        },
        "production": {
            "hosts": [],
            "thresholds": {
                "cpu": 70,
                "memory": 80,
                "disk": 85,
            }
        }
    }
    config.current_profile = "dev"

    # 通知配置占位
    config.notifications = {
        "feishu_webhook": "",
        "feishu_secret": "",
    }

    config.save()

    click.echo(click.style("✓ 配置文件已创建:", fg='green'))
    click.echo(f"  {config.config_file}")
    click.echo("\n请配置以下信息:")
    click.echo("  keeper config set --api-key YOUR_API_KEY")
    click.echo("  keeper config set --feishu-webhook 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx'")


@cli.group()
def config():
    """配置管理命令"""
    pass


@config.command()
@click.option('--threshold', '-t', type=int, help='阈值百分比')
@click.option('--metric', '-m', type=click.Choice(['cpu', 'memory', 'disk']), help='指标名称')
@click.option('--profile', '-p', help='环境名称')
@click.option('--api-key', help='API Key')
@click.option('--base-url', help='API Base URL')
@click.option('--model', help='模型名称')
@click.option('--provider', type=click.Choice(['openai_compatible', 'anthropic']), help='LLM 提供商')
@click.option('--k8s-kubeconfig', type=str, help='K8s kubeconfig 文件路径')
@click.option('--k8s-context', type=str, help='K8s 集群上下文名称')
@click.option('--k8s-type', type=click.Choice(['k8s', 'k3s']), help='K8s 集群类型')
@click.option('--feishu-webhook', type=str, help='飞书 Webhook URL')
@click.option('--feishu-secret', type=str, help='飞书 Webhook 签名密钥')
def set(threshold, metric, profile, api_key, base_url, model, provider, k8s_kubeconfig, k8s_context, k8s_type, feishu_webhook, feishu_secret):
    """设置配置

    示例:
        keeper config set --threshold 80 --metric cpu  # 设置 CPU 阈值为 80%
        keeper config set --threshold 80  # 设置所有阈值为 80%
        keeper config set --profile production  # 切换环境
        keeper config set --api-key sk-xxx
        keeper config set --model claude-sonnet-4-6
    """
    config = AppConfig.from_env()
    config.load()

    updated = False

    # 修改阈值
    if threshold is not None:
        profile_name = profile or config.current_profile
        profile_config = config.get_profile(profile_name)
        if "thresholds" not in profile_config:
            profile_config["thresholds"] = {}

        if metric:
            profile_config["thresholds"][metric] = threshold
            click.echo(click.style(f"✓ 已将 {metric.upper()} 阈值设置为 {threshold}%", fg='green'))
        else:
            profile_config["thresholds"]["cpu"] = threshold
            profile_config["thresholds"]["memory"] = threshold
            profile_config["thresholds"]["disk"] = threshold
            click.echo(click.style(f"✓ 已将所有阈值设置为 {threshold}%", fg='green'))

        config.set_profile(profile_name, profile_config)
        updated = True

    # 切换环境
    if profile and threshold is None:
        config.current_profile = profile
        config.save()
        click.echo(click.style(f"✓ 已切换到环境：{profile}", fg='green'))
        updated = True

    # LLM 配置
    if api_key:
        config.llm.api_key = api_key
        updated = True

    if base_url:
        config.llm.base_url = base_url
        updated = True

    if model:
        config.llm.model = model
        updated = True

    if provider:
        config.llm.provider = provider
        updated = True

    if updated and (api_key or base_url or model or provider):
        config.save_llm_config()
        click.echo(click.style("✓ LLM 配置已保存:", fg='green'))
        click.echo(f"  Provider: {config.llm.provider}")
        click.echo(f"  Model: {config.llm.model}")
        click.echo(f"  Base URL: {config.llm.base_url}")
        if api_key:
            key_preview = api_key[:8] + "..." if len(api_key) > 8 else "***"
            click.echo(f"  API Key: {key_preview} ✓")
    elif not updated:
        # 显示当前配置
        click.echo("当前 LLM 配置:")
        click.echo(f"  Provider: {config.llm.provider}")
        click.echo(f"  Model: {config.llm.model}")
        click.echo(f"  Base URL: {config.llm.base_url}")
        if config.llm.api_key:
            key_preview = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else "***"
            click.echo(f"  API Key: {key_preview} ✓")
        else:
            click.echo("  API Key: 未设置")

    # K8s 配置
    k8s_updated = False
    if k8s_kubeconfig is not None:
        config.k8s["kubeconfig"] = k8s_kubeconfig
        k8s_updated = True
    if k8s_context is not None:
        config.k8s["context"] = k8s_context
        k8s_updated = True
    if k8s_type is not None:
        config.k8s["cluster_type"] = k8s_type
        k8s_updated = True

    if k8s_updated:
        config.save()
        click.echo(click.style("✓ K8s 配置已保存:", fg='green'))
        click.echo(f"  kubeconfig: {config.k8s.get('kubeconfig', 'auto')}")
        click.echo(f"  context: {config.k8s.get('context', 'default')}")
        click.echo(f"  cluster_type: {config.k8s.get('cluster_type', 'k8s')}")

    # 通知配置
    if feishu_webhook is not None:
        nc = {
            "feishu_webhook": feishu_webhook,
        }
        if feishu_secret:
            nc["feishu_secret"] = feishu_secret
        config.set_notification_config(nc)
        click.echo(click.style("✓ 飞书 Webhook 已配置", fg='green'))


@config.command()
def show():
    """显示当前配置"""
    config = AppConfig.from_env()
    config.load()

    click.echo("Keeper 配置")
    click.echo("━" * 40)

    # LLM 配置
    click.echo("\nLLM 配置:")
    click.echo(f"  Provider: {config.llm.provider}")
    click.echo(f"  Model: {config.llm.model}")
    click.echo(f"  Base URL: {config.llm.base_url}")

    if config.is_llm_configured():
        key_preview = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else "***"
        click.echo(f"  API Key: {key_preview} ✓")
    else:
        click.echo(click.style("  API Key: 未设置 ✗", fg='red'))

    # 环境配置
    click.echo(f"\n当前环境：{config.current_profile}")
    profile = config.get_profile()
    if profile:
        hosts = profile.get("hosts", [])
        thresholds = profile.get("thresholds", {})

        if hosts:
            click.echo(f"  主机列表：{', '.join(hosts)}")
        if thresholds:
            click.echo(f"  阈值：CPU={thresholds.get('cpu')}%, "
                      f"内存={thresholds.get('memory')}%, "
                      f"磁盘={thresholds.get('disk')}%")


@config.command()
@click.confirmation_option(prompt='确定要删除所有配置吗？')
def clear():
    """清除所有配置"""
    import shutil

    config = AppConfig.from_env()

    if config.config_dir.exists():
        shutil.rmtree(config.config_dir)
        click.echo(click.style("✓ 配置已清除", fg='green'))
        click.echo("  使用 'keeper init' 重新初始化。")
    else:
        click.echo("没有需要清除的配置。")


@cli.group()
def k8s():
    """K8s 集群管理命令"""
    pass


@k8s.command("inspect")
@click.option('--namespace', '-n', type=str, help='限定命名空间')
@click.option('--kubeconfig', '-k', type=str, help='kubeconfig 文件路径')
@click.option('--context', '-c', type=str, help='集群上下文名称')
def k8s_inspect(namespace, kubeconfig, context):
    """K8s 集群巡检

    示例:
        keeper k8s inspect
        keeper k8s inspect -n kube-system
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.inspector import K8sInspector
    from .tools.k8s.formatter import format_cluster_report

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=kubeconfig or k8s_cfg_data.get("kubeconfig", ""),
        context=context or k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        ok, report = K8sInspector.inspect_cluster(k8s_client, namespace)
        if not ok:
            click.echo(click.style(f"[K8s] 巡检失败", fg='red'))
            sys.exit(1)
        click.echo(format_cluster_report(report, namespace))
    except Exception as e:
        click.echo(click.style(f"[K8s] 巡检失败：{str(e)}", fg='red'))
        sys.exit(1)
    finally:
        k8s_client.close()


@k8s.command("logs")
@click.argument('pod_name')
@click.option('--namespace', '-n', default='default', help='命名空间')
@click.option('--lines', '-l', default=100, type=int, help='日志行数')
@click.option('--keyword', '-k', type=str, help='关键词过滤')
@click.option('--container', '-c', type=str, help='容器名称')
@click.option('--kubeconfig', type=str, help='kubeconfig 文件路径')
def k8s_logs(pod_name, namespace, lines, keyword, container, kubeconfig):
    """查看 Pod 日志

    示例:
        keeper k8s logs my-app
        keeper k8s logs nginx -n kube-system -l 200
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.logs import K8sLogTools

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=kubeconfig or k8s_cfg_data.get("kubeconfig", ""),
        context=k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        ok, output = K8sLogTools.get_pod_logs(
            k8s_client, pod_name=pod_name, namespace=namespace,
            lines=lines, keyword=keyword, container=container,
        )
        if not ok:
            click.echo(click.style(f"[K8s] {output}", fg='yellow'))
            return
        click.echo(f"[K8s 日志] ({namespace}/{pod_name}):\n{output}")
    except Exception as e:
        click.echo(click.style(f"[K8s] 日志查询失败：{str(e)}", fg='red'))
        sys.exit(1)
    finally:
        k8s_client.close()


@k8s.command("events")
@click.option('--namespace', '-n', type=str, help='限定命名空间')
@click.option('--kubeconfig', type=str, help='kubeconfig 文件路径')
def k8s_events(namespace, kubeconfig):
    """查看集群 Warning 事件

    示例:
        keeper k8s events
        keeper k8s events -n kube-system
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.inspector import K8sInspector

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=kubeconfig or k8s_cfg_data.get("kubeconfig", ""),
        context=k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        events = K8sInspector._check_events(k8s_client, namespace)
        if not events:
            click.echo("[K8s] 无 Warning 事件")
            return

        lines = [f"[K8s] Warning 事件:"]
        lines.append("━" * 60)
        for ev in events[:30]:
            lines.append(f"  [{ev.severity}] {ev.involved_object} - {ev.reason} (x{ev.count})")
            if ev.message:
                msg = ev.message[:120] + "..." if len(ev.message) > 120 else ev.message
                lines.append(f"    {msg}")
            lines.append(f"    最近: {ev.last_seen}")
        lines.append("━" * 60)
        lines.append(f"共 {len(events)} 条事件")
        click.echo("\n".join(lines))
    except Exception as e:
        click.echo(click.style(f"[K8s] 事件查询失败：{str(e)}", fg='red'))
        sys.exit(1)
    finally:
        k8s_client.close()


@k8s.command("exec")
@click.argument('pod_name')
@click.argument('command', nargs=-1)
@click.option('--namespace', '-n', default='default', help='命名空间')
@click.option('--container', '-c', type=str, help='容器名称')
@click.option('--kubeconfig', type=str, help='kubeconfig 文件路径')
def k8s_exec(pod_name, command, namespace, container, kubeconfig):
    """在 Pod 中执行命令

    示例:
        keeper k8s exec my-pod -- ls /
        keeper k8s exec nginx -n kube-system -- cat /etc/resolv.conf
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.ops import K8sOps

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=kubeconfig or k8s_cfg_data.get("kubeconfig", ""),
        context=k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        cmd_str = ' '.join(command) or "ls /"
        success, output = K8sOps.exec_in_pod(
            k8s_client, pod_name=pod_name, namespace=namespace,
            command=cmd_str, container=container,
        )
        if not success:
            click.echo(click.style(f"[K8s] {output}", fg='yellow'))
        else:
            click.echo(f"[K8s Exec] ({namespace}/{pod_name}) $ {cmd_str}\n{output}")
    except Exception as e:
        click.echo(click.style(f"[K8s] 执行失败：{str(e)}", fg='red'))
    finally:
        k8s_client.close()


@k8s.command("scale")
@click.argument('deployment')
@click.option('--replicas', '-r', required=True, type=int, help='目标副本数')
@click.option('--namespace', '-n', default='default', help='命名空间')
def k8s_scale(deployment, replicas, namespace):
    """扩缩容 Deployment

    示例:
        keeper k8s scale frontend --replicas 5
        keeper k8s scale api -n production -r 3
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.ops import K8sOps

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=k8s_cfg_data.get("kubeconfig", ""),
        context=k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        ok, output = K8sOps.scale_deployment(k8s_client, deployment, namespace, replicas)
        if ok:
            click.echo(f"[K8s] {output}")
        else:
            click.echo(click.style(f"[K8s] {output}", fg='red'))
    except Exception as e:
        click.echo(click.style(f"[K8s] 扩缩容失败：{str(e)}", fg='red'))
    finally:
        k8s_client.close()


@k8s.command("restart")
@click.argument('deployment')
@click.option('--namespace', '-n', default='default', help='命名空间')
def k8s_restart(deployment, namespace):
    """滚动重启 Deployment

    示例:
        keeper k8s restart frontend
        keeper k8s restart api -n production
    """
    config = AppConfig.from_env()
    config.load()

    from .tools.k8s.client import K8sClient, K8sClusterConfig
    from .tools.k8s.ops import K8sOps

    k8s_cfg_data = config.get_k8s_config()
    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=k8s_cfg_data.get("kubeconfig", ""),
        context=k8s_cfg_data.get("context", ""),
        cluster_type=k8s_cfg_data.get("cluster_type", "k8s"),
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()
    if not success:
        click.echo(click.style(f"[K8s] 连接失败：{msg}", fg='red'))
        sys.exit(1)

    try:
        ok, output = K8sOps.restart_deployment(k8s_client, deployment, namespace)
        if ok:
            click.echo(f"[K8s] {output}")
        else:
            click.echo(click.style(f"[K8s] {output}", fg='red'))
    except Exception as e:
        click.echo(click.style(f"[K8s] 重启失败：{str(e)}", fg='red'))
    finally:
        k8s_client.close()


@cli.group()
def docker():
    """Docker 容器管理命令"""
    pass


@docker.command("ls")
def docker_ls():
    """列出 Docker 容器"""
    from .tools.docker_tools import DockerTools, format_docker_containers

    if not DockerTools.is_docker_available():
        click.echo(click.style("[Docker] Docker 未安装或未运行", fg='red'))
        sys.exit(1)

    containers = DockerTools.list_containers()
    stats = DockerTools.get_container_stats()
    click.echo(format_docker_containers(containers, stats))


@docker.command("stats")
def docker_stats():
    """Docker 容器资源统计"""
    from .tools.docker_tools import DockerTools, format_docker_containers

    if not DockerTools.is_docker_available():
        click.echo(click.style("[Docker] Docker 未安装或未运行", fg='red'))
        sys.exit(1)

    containers = DockerTools.list_containers()
    stats = DockerTools.get_container_stats()
    click.echo(format_docker_containers(containers, stats))


@docker.command("images")
def docker_images():
    """列出 Docker 镜像"""
    from .tools.docker_tools import DockerTools, format_docker_images

    if not DockerTools.is_docker_available():
        click.echo(click.style("[Docker] Docker 未安装或未运行", fg='red'))
        sys.exit(1)

    images = DockerTools.list_images()
    click.echo(format_docker_images(images))


@docker.command("prune")
def docker_prune():
    """清理无用的 Docker 镜像"""
    from .tools.docker_tools import DockerTools

    if not DockerTools.is_docker_available():
        click.echo(click.style("[Docker] Docker 未安装或未运行", fg='red'))
        sys.exit(1)

    success, output = DockerTools.prune_images()
    if success:
        click.echo(click.style(f"[Docker] ✓ 镜像清理: {output}", fg='green'))
    else:
        click.echo(click.style(f"[Docker] ✗ {output}", fg='red'))


@cli.group()
def network():
    """网络诊断命令"""
    pass


@network.command()
@click.argument('host', default='8.8.8.8')
@click.option('--count', '-c', default=4, type=int, help='Ping 次数')
def ping(host, count):
    """Ping 测试"""
    from .tools.network import NetworkTools, format_ping_result
    result = NetworkTools.ping(host, count=count)
    click.echo(format_ping_result(result))


@network.command()
@click.argument('host')
@click.argument('port', type=int)
def port(host, port):
    """端口连通性检测"""
    from .tools.network import NetworkTools, format_port_result
    result = NetworkTools.check_port(host, port)
    click.echo(format_port_result(result))


@network.command()
@click.argument('domain', default='baidu.com')
@click.option('--server', '-s', type=str, help='指定 DNS 服务器')
def dns(domain, server):
    """DNS 解析检测"""
    from .tools.network import NetworkTools, format_dns_result
    result = NetworkTools.dns_lookup(domain, server=server)
    click.echo(format_dns_result(result))


@network.command()
@click.argument('url')
def http(url):
    """HTTP 健康检查"""
    from .tools.network import NetworkTools, format_http_result
    result = NetworkTools.http_check(url)
    click.echo(format_http_result(result))


@cli.group()
def schedule():
    """定时任务管理命令"""
    pass


@schedule.command("list")
def schedule_list():
    """列出所有定时任务"""
    from .tools.scheduler import TaskScheduler, format_task_list
    scheduler = TaskScheduler()
    click.echo(format_task_list(scheduler.list_tasks()))


@schedule.command("add")
@click.option('--cron', '-c', required=True, type=str, help='Cron 表达式')
@click.option('--description', '-d', required=True, type=str, help='任务描述')
@click.option('--type', 'task_type', default='inspect', type=str, help='任务类型')
def schedule_add(cron, description, task_type):
    """添加定时任务

    示例:
        keeper schedule add --cron "*/30 * * * *" --description "每30分钟检查K8s" --type k8s_inspect
        keeper schedule add --cron "0 9 * * *" --description "每天9点巡检" --type batch_inspect
    """
    from .tools.scheduler import TaskScheduler
    scheduler = TaskScheduler()
    task = scheduler.add_task(cron_expr=cron, description=description, task_type=task_type)
    click.echo(click.style(f"[定时任务] 已添加任务: {task.description}", fg='green'))
    click.echo(f"  ID: {task.id}")
    click.echo(f"  Cron: {task.cron_expr}")
    click.echo(f"  类型: {task.task_type}")


@schedule.command("remove")
@click.argument('task_id')
def schedule_remove(task_id):
    """删除定时任务"""
    from .tools.scheduler import TaskScheduler
    scheduler = TaskScheduler()
    if scheduler.remove_task(task_id):
        click.echo(click.style(f"[定时任务] 任务 {task_id} 已删除", fg='green'))
    else:
        click.echo(click.style(f"[定时任务] 任务 {task_id} 不存在", fg='red'))


@cli.group()
def fix():
    """自动修复建议与执行"""
    pass


@fix.command("suggest")
@click.option('--host', '-h', default='localhost', help='目标主机')
def fix_suggest(host):
    """生成修复建议"""
    from .tools.rca import RCAEngine
    from .tools.fixer import FixSuggester, SafetyLevel

    data = RCAEngine.collect_server_data()
    fixes = FixSuggester.generate_rule_based_fixes(data)

    if not fixes:
        click.echo(click.style("[自动修复] 当前未发现需要修复的问题", fg='green'))
        return

    lines = ["[自动修复] 修复建议:", "=" * 50]
    for i, fix in enumerate(fixes, 1):
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
    lines.append("在对话中说 '执行第N个' 或 '全部执行' 来应用修复。")
    click.echo("\n".join(lines))


@fix.command("verify")
@click.option('--host', '-h', default='localhost', help='目标主机')
def fix_verify(host):
    """验证修复效果 — 显示当前服务器状态摘要"""
    from .tools.rca import RCAEngine

    data = RCAEngine.collect_server_data()
    lines = ["[自动修复] 当前服务器状态:"]
    lines.append(f"  CPU: {data.get('cpu_percent', 0)}%")
    lines.append(f"  内存: {data.get('memory_percent', 0)}%")
    lines.append(f"  磁盘: {data.get('disk_percent', 0)}%")
    lines.append(f"  负载: {data.get('load_avg', {}).get('1m', 0)}")
    click.echo("\n".join(lines))


@cli.group()
def cert():
    """SSL/TLS 证书监控"""
    pass


@cert.command("scan")
@click.option('--extra-paths', '-p', multiple=True, help='额外扫描路径')
def cert_scan(extra_paths):
    """扫描本地证书"""
    from .tools.cert_monitor import CertMonitor, format_cert_report

    local_certs = CertMonitor.scan_local_certs(extra_paths=list(extra_paths) if extra_paths else None)
    domain_certs = []

    # 自动检测域名
    domains = CertMonitor.detect_domains_from_config()
    if domains:
        click.echo(f"[证书] 检测到 {len(domains)} 个潜在域名，检查前 5 个...")
        for d in domains[:5]:
            cert = CertMonitor.check_domain_cert(d)
            if cert:
                domain_certs.append(cert)

    click.echo(format_cert_report(local_certs, [], domain_certs))


@cert.command("check-domain")
@click.argument('domain')
@click.option('--port', '-p', default=443, type=int, help='端口号')
def cert_check_domain(domain, port):
    """检查指定域名的 SSL 证书"""
    from .tools.cert_monitor import CertMonitor

    cert = CertMonitor.check_domain_cert(domain, port)
    if cert:
        status_icon = {"valid": "🟢", "expiring_soon": "🟡", "expired": "🔴"}[cert.status]
        days = f"剩余 {cert.days_left} 天" if cert.status == "valid" else (f"已过 {abs(cert.days_left)} 天" if cert.status == "expired" else f"剩余 {cert.days_left} 天")
        lines = [f"[SSL/TLS] {domain}:"]
        lines.append(f"  状态: {status_icon} {days}")
        lines.append(f"  主体: {cert.subject}")
        lines.append(f"  颁发者: {cert.issuer}")
        lines.append(f"  过期: {cert.not_after}")
        if cert.domains:
            lines.append(f"  域名: {', '.join(cert.domains[:5])}")
        click.echo("\n".join(lines))
    else:
        click.echo(click.style(f"[SSL/TLS] 无法获取 {domain} 的证书信息", fg='red'))


@cli.group()
def notify():
    """IM 通知推送管理"""
    pass


@notify.command("config")
@click.option('--feishu-webhook', type=str, help='飞书群机器人 Webhook URL')
@click.option('--feishu-secret', type=str, help='飞书 Webhook 签名密钥（可选）')
def notify_config(feishu_webhook, feishu_secret):
    """配置通知推送"""
    config = AppConfig.from_env()
    config.load()

    nc = {}
    if feishu_webhook:
        nc["feishu_webhook"] = feishu_webhook
    elif config.notifications.get("feishu_webhook"):
        nc["feishu_webhook"] = config.notifications["feishu_webhook"]

    if feishu_secret:
        nc["feishu_secret"] = feishu_secret
    elif config.notifications.get("feishu_secret"):
        nc["feishu_secret"] = config.notifications["feishu_secret"]

    if nc:
        config.set_notification_config(nc)
        click.echo(click.style("✓ 飞书 Webhook 已配置", fg='green'))
    else:
        # 显示当前配置
        nc = config.get_notification_config()
        if nc.get("feishu_webhook"):
            click.echo("当前通知配置:")
            click.echo(f"  飞书 Webhook: {nc['feishu_webhook'][:30]}...")
            click.echo(f"  签名校验: {'已配置' if nc.get('feishu_secret') else '未配置'}")
        else:
            click.echo("未配置通知推送。使用 --feishu-webhook 配置。")


@notify.command("test")
def notify_test():
    """发送测试消息到飞书"""
    config = AppConfig.from_env()
    config.load()

    from .tools.notify import FeishuNotifier

    nc = config.get_notification_config()
    webhook = nc.get("feishu_webhook")
    secret = nc.get("feishu_secret")

    if not webhook:
        click.echo(click.style("[通知] 未配置飞书 Webhook", fg='red'))
        click.echo("  使用: keeper notify config --feishu-webhook <url>")
        sys.exit(1)

    notifier = FeishuNotifier(webhook, secret)

    # 发送测试文本
    ok = notifier.send_text("🔔 Keeper 测试消息 — 通知推送功能正常")
    if ok:
        click.echo(click.style("✓ 测试消息已发送到飞书", fg='green'))
    else:
        click.echo(click.style("✗ 发送失败，请检查 Webhook URL 和网络连接", fg='red'))
        sys.exit(1)


@notify.command("status")
def notify_status():
    """显示当前通知配置"""
    config = AppConfig.from_env()
    config.load()

    nc = config.get_notification_config()

    click.echo("通知推送状态")
    click.echo("━" * 40)

    if nc.get("feishu_webhook"):
        url = nc["feishu_webhook"]
        click.echo(f"  飞书 Webhook: {url[:40]}... ✓")
        click.echo(f"  签名校验: {'已配置 ✓' if nc.get('feishu_secret') else '未配置'}")
        click.echo(click.style("  状态: 已启用", fg='green'))
    else:
        click.echo(click.style("  飞书 Webhook: 未配置 ✗", fg='red'))
        click.echo("  使用 'keeper notify config --feishu-webhook <url>' 配置")


def main():
    """主入口"""
    cli()


if __name__ == "__main__":
    main()
