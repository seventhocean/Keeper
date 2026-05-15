"""Schedule Handler — 定时任务相关处理"""
from typing import Dict, Any

from ...tools.scheduler import format_task_list


def handle_schedule(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理定时任务意图"""
    schedule_action = entities.get("schedule_action", "").lower()

    # 列出任务
    if schedule_action in ("list", "查看") or (
        not schedule_action and entities.get("query") in ("查看", "列表")
    ):
        tasks = agent_ref.scheduler.list_tasks()
        return format_task_list(tasks)

    # 删除任务
    if schedule_action in ("remove", "删除"):
        task_id = entities.get("task_id")
        if task_id:
            if agent_ref.scheduler.remove_task(task_id):
                return f"[定时任务] 任务 {task_id} 已删除"
            return f"[定时任务] 任务 {task_id} 不存在"
        tasks = agent_ref.scheduler.list_tasks()
        if tasks:
            last_task = tasks[-1]
            agent_ref.scheduler.remove_task(last_task.id)
            return f"[定时任务] 已删除最后一个任务: {last_task.description} ({last_task.id})"
        return "[定时任务] 没有可删除的任务"

    # 启用/禁用
    if schedule_action in ("enable", "启用", "disable", "禁用"):
        task_id = entities.get("task_id")
        tasks = agent_ref.scheduler.list_tasks()
        if not tasks:
            return "[定时任务] 没有任务"
        if task_id:
            task = agent_ref.scheduler.get_task(task_id)
        else:
            task = tasks[-1]
        if not task:
            return "[定时任务] 任务不存在"
        if schedule_action in ("enable", "启用"):
            agent_ref.scheduler.enable_task(task.id)
            return f"[定时任务] 已启用: {task.description}"
        else:
            agent_ref.scheduler.disable_task(task.id)
            return f"[定时任务] 已禁用: {task.description}"

    # 添加任务
    cron_expr = entities.get("cron_expr", "")
    description = entities.get("schedule_description", entities.get("query", ""))
    all_hosts = entities.get("all_hosts", False)

    if not cron_expr:
        from ..agent import PendingTask
        raw_input = entities.get("_raw_input", "")
        agent_ref.pending_task = PendingTask(
            task_type="schedule_confirm",
            message=(
                f"[定时任务] 请描述你的定时任务需求，例如：\n"
                f"  - '每 30 分钟检查一次 K8s 状态'\n"
                f"  - '每天早上 9 点巡检所有服务器'\n"
                f"  - '每小时检查 Pod 重启情况'\n\n"
                f"当前输入：{raw_input}"
            ),
        )
        return agent_ref.pending_task.message

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

    task = agent_ref.scheduler.add_task(
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
