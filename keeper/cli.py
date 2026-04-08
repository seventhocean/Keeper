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


@click.group()
@click.version_option(version='0.1.0')
def cli():
    """Keeper - 智能运维助手"""
    pass


@cli.command()
def chat():
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
    click.echo(f"  {config.llm_config_file}")
    click.echo("\n使用 'keeper config set' 命令配置 API Key。")


@cli.group()
def config():
    """配置管理命令"""
    pass


@config.command()
@click.option('--api-key', help='API Key')
@click.option('--base-url', help='API Base URL')
@click.option('--model', help='模型名称')
@click.option('--provider', type=click.Choice(['openai_compatible', 'anthropic']), help='LLM 提供商')
def set(api_key, base_url, model, provider):
    """设置 LLM 配置

    示例:
        keeper config set --api-key sk-xxx
        keeper config set --api-key sk-xxx --base-url https://api.qnaigc.com/v1
        keeper config set --provider anthropic --model claude-sonnet-4-6
    """
    config = AppConfig.from_env()
    config.load()

    updated = False

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

    if updated:
        config.save_llm_config()
        click.echo(click.style("✓ 配置已保存:", fg='green'))
        click.echo(f"  Provider: {config.llm.provider}")
        click.echo(f"  Model: {config.llm.model}")
        click.echo(f"  Base URL: {config.llm.base_url}")
        if api_key:
            key_preview = api_key[:8] + "..." if len(api_key) > 8 else "***"
            click.echo(f"  API Key: {key_preview} ✓")
    else:
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
