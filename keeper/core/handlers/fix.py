"""Fix Handler — 自动修复相关处理"""
from typing import Dict, Any

from ...tools.rca import RCAEngine
from ...tools.fixer import FixSuggester, FixPlan, generate_fix_prompt_from_data


def handle_auto_fix(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理自动修复意图"""
    fix_action = entities.get("fix_action", "suggest").lower()
    fix_index = entities.get("fix_index")

    # 执行具体修复
    if fix_action in ("execute", "执行") and fix_index is not None:
        return _execute_single_fix(int(fix_index), agent_ref=agent_ref)

    # 执行全部修复
    if fix_action in ("execute_all", "全部执行", "一键修复"):
        return _execute_all_fixes(agent_ref=agent_ref)

    # 验证修复效果
    if fix_action in ("verify", "验证"):
        if hasattr(agent_ref, "_fix_data_before"):
            data_after = RCAEngine.collect_server_data()
            result = FixSuggester.verify_fix(agent_ref._fix_data_before, data_after, "disk")
            return f"[自动修复] 验证结果：{result}"
        return "[自动修复] 没有修复前数据，无法验证"

    # 默认：生成修复建议
    data = RCAEngine.collect_server_data()
    rule_fixes = FixSuggester.generate_rule_based_fixes(data)

    if not rule_fixes:
        fix_prompt = generate_fix_prompt_from_data(data)
        return agent_ref._call_llm_diagnosis(fix_prompt)

    # 缓存数据
    agent_ref._fix_data_before = data
    agent_ref._pending_fix_suggestions = rule_fixes

    plan = FixPlan(
        summary="服务器问题修复",
        diagnosis=f"发现 {len(rule_fixes)} 个可修复问题",
        suggestions=rule_fixes,
        llm_advice="",
    )

    return FixSuggester.format_fix_plan(plan)


def _execute_single_fix(index: int, *, agent_ref) -> str:
    """执行单个修复建议"""
    if not hasattr(agent_ref, "_pending_fix_suggestions") or not agent_ref._pending_fix_suggestions:
        return "[自动修复] 没有待执行的修复建议，请先说'帮我修复'生成建议。"

    if index < 1 or index > len(agent_ref._pending_fix_suggestions):
        return f"[自动修复] 编号无效，请输入 1-{len(agent_ref._pending_fix_suggestions)}"

    fix = agent_ref._pending_fix_suggestions[index - 1]

    # 安全检查
    valid, msg = FixSuggester.validate_command(fix.command)
    if not valid:
        return f"[自动修复] 命令安全检查未通过：{msg}"

    # 破坏性命令需二次确认
    if FixSuggester.needs_confirmation(fix.command):
        from ..agent import PendingTask
        agent_ref.pending_task = PendingTask(
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
        return agent_ref.pending_task.message

    # 安全命令直接执行
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

    # 验证效果
    if hasattr(agent_ref, "_fix_data_before"):
        data_after = RCAEngine.collect_server_data()
        metric = "disk" if "磁盘" in fix.title or "clean" in fix.command.lower() else "memory"
        improved, verify_msg = FixSuggester.verify_fix(agent_ref._fix_data_before, data_after, metric)
        lines.append("")
        lines.append(f"  验证: {verify_msg}")
        if improved:
            agent_ref._fix_data_before = data_after

    # 移除已执行的建议
    agent_ref._pending_fix_suggestions.pop(index - 1)
    if agent_ref._pending_fix_suggestions:
        lines.append("")
        lines.append(f"  还有 {len(agent_ref._pending_fix_suggestions)} 个待修复建议。")

    return "\n".join(lines)


def _execute_all_fixes(*, agent_ref) -> str:
    """批量执行所有修复建议"""
    if not hasattr(agent_ref, "_pending_fix_suggestions") or not agent_ref._pending_fix_suggestions:
        return "[自动修复] 没有待执行的修复建议。"

    # 检查是否有破坏性命令
    has_destructive = any(
        FixSuggester.needs_confirmation(fix.command)
        for fix in agent_ref._pending_fix_suggestions
    )

    if has_destructive:
        from ..agent import PendingTask
        agent_ref.pending_task = PendingTask(
            task_type="fix_execute_all",
            message=(
                f"[自动修复] ⚠ 批量修复中包含文件清理操作，需要二次确认。\n"
                f"  共 {len(agent_ref._pending_fix_suggestions)} 个修复任务\n\n"
                f"输入 'yes' 或 '确认' 执行全部修复。"
            ),
        )
        return agent_ref.pending_task.message

    lines = ["[自动修复] 开始批量修复", "=" * 50]
    total = len(agent_ref._pending_fix_suggestions)
    success_count = 0
    fail_count = 0

    for i, fix in enumerate(list(agent_ref._pending_fix_suggestions), 1):
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
    if hasattr(agent_ref, "_fix_data_before"):
        data_after = RCAEngine.collect_server_data()
        for metric in ("disk", "memory", "load"):
            improved, verify_msg = FixSuggester.verify_fix(agent_ref._fix_data_before, data_after, metric)
            lines.append(f"  [{metric}] {verify_msg}")

    lines.append("")
    lines.append(f"修复完成: 成功 {success_count}/{total}, 失败 {fail_count}/{total}")
    agent_ref._pending_fix_suggestions = []
    return "\n".join(lines)
