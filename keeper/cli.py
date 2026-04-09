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
│  Keeper v0.1 - 智能运维助手              │
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
@click.version_option(version='0.1.0')
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
    config.save()

    click.echo(click.style("✓ 配置文件已创建:", fg='green'))
    click.echo(f"  {config.config_file}")
    click.echo("\n使用 'keeper config set' 命令配置 API Key。")


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
def set(threshold, metric, profile, api_key, base_url, model, provider):
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


def main():
    """主入口"""
    cli()


if __name__ == "__main__":
    main()
