# Runbook 引擎 — YAML 定义的标准化运维流程

from pathlib import Path

# 用户自定义 Runbook 目录
USER_RUNBOOKS_DIR = Path.home() / ".keeper" / "runbooks"


def get_user_runbooks_dir() -> Path:
    """获取用户 Runbook 目录，不存在时自动创建"""
    USER_RUNBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_RUNBOOKS_DIR
