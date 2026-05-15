"""Runbook 执行引擎

功能：
- YAML 文件加载与校验
- 变量模板渲染 ({{variable}})
- 顺序执行各步骤
- 确认步骤暂停等待
- 预期检查（expect 表达式）
- 失败时按 on_fail 策略处理
- 执行结果记录
"""
import re
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Callable, Tuple

from .models import Runbook, RunbookStep, StepSafety, StepStatus, OnFailAction


class RunbookExecutor:
    """Runbook 执行引擎"""

    # 高危命令黑名单（与 safety.py 一致）
    DANGEROUS_PATTERNS = [
        r"\brm\s+-[rRf]", r"\bdd\s+", r"\bmkfs\b",
        r">\s*/etc/", r"\bchmod\s+777\s+/",
    ]

    def __init__(self, confirm_callback: Optional[Callable] = None,
                 output_callback: Optional[Callable] = None):
        """
        Args:
            confirm_callback: 确认回调 (prompt) -> bool，返回用户是否确认
            output_callback: 输出回调 (text) -> None，显示执行过程
        """
        self.confirm_callback = confirm_callback or (lambda _: True)
        self.output_callback = output_callback or (lambda _: None)

    def load_from_yaml(self, yaml_path: str) -> Runbook:
        """从 YAML 文件加载 Runbook"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Runbook 文件不存在: {yaml_path}")

        with open(path, "r", encoding="utf-8") as f:
            try:
                import yaml
                data = yaml.safe_load(f)
            except ImportError:
                from ruamel.yaml import YAML
                f.seek(0)
                ry = YAML()
                data = ry.load(f)

        if not data:
            raise ValueError(f"Runbook 文件为空: {yaml_path}")

        return Runbook.from_dict(data)

    def execute(self, runbook: Runbook, variables: Optional[Dict] = None) -> Tuple[bool, str]:
        """执行 Runbook

        Args:
            runbook: Runbook 实例
            variables: 运行时变量（覆盖 Runbook 默认变量）

        Returns:
            (all_success, summary_text)
        """
        # 合并变量
        vars_merged = dict(runbook.variables)
        if variables:
            vars_merged.update(variables)

        self.output_callback(f"[Runbook] 开始执行: {runbook.name}")
        self.output_callback(f"  描述: {runbook.description}")
        self.output_callback(f"  步骤数: {len(runbook.steps)}")
        self.output_callback("")

        all_success = True

        for i, step in enumerate(runbook.steps):
            step_num = i + 1
            self.output_callback(f"  [{step_num}/{len(runbook.steps)}] {step.name}")

            # 安全检查
            if not self._safety_check(step):
                step.status = StepStatus.SKIPPED
                step.output = "安全检查拒绝"
                self.output_callback(f"    🔴 拒绝: 命令被安全策略拦截")
                all_success = False
                break

            # 确认步骤
            if step.confirm or step.safety in (StepSafety.CAUTION, StepSafety.DESTRUCTIVE):
                prompt = f"    ⚠️ [{step.safety.value}] 确认执行: {step.command[:80]}？"
                step.status = StepStatus.CONFIRM_WAIT
                if not self.confirm_callback(prompt):
                    step.status = StepStatus.SKIPPED
                    step.output = "用户取消"
                    self.output_callback(f"    ⊘ 用户取消")
                    continue

            # 渲染变量
            command = self._render_variables(step.command, vars_merged)

            # 执行
            step.status = StepStatus.RUNNING
            t_start = time.time()

            try:
                success, output = self._execute_command(command, step.timeout)
                step.duration_ms = int((time.time() - t_start) * 1000)
                step.output = output[:2000]

                if success:
                    # 检查预期
                    if step.expect and not self._check_expect(output, step.expect):
                        step.status = StepStatus.FAILED
                        step.output += f"\n[预期检查失败] expect: {step.expect}"
                        success = False
                    else:
                        step.status = StepStatus.DONE
                else:
                    step.status = StepStatus.FAILED

            except subprocess.TimeoutExpired:
                step.status = StepStatus.FAILED
                step.output = f"超时 ({step.timeout}s)"
                step.duration_ms = step.timeout * 1000
                success = False
            except Exception as e:
                step.status = StepStatus.FAILED
                step.output = str(e)
                step.duration_ms = int((time.time() - t_start) * 1000)
                success = False

            # 显示结果
            icon = "✓" if step.status == StepStatus.DONE else "✗"
            self.output_callback(f"    {icon} ({step.duration_ms}ms)")

            # 失败处理
            if not success:
                all_success = False
                if step.on_fail == OnFailAction.ABORT:
                    self.output_callback(f"    中止: {step.on_fail.value}")
                    break
                elif step.on_fail == OnFailAction.ROLLBACK and step.rollback:
                    self.output_callback(f"    回滚: {step.rollback[:60]}")
                    self._execute_command(step.rollback, 30)

        # 生成摘要
        summary = self._generate_summary(runbook)
        self.output_callback(f"\n{summary}")

        return all_success, summary

    def _safety_check(self, step: RunbookStep) -> bool:
        """安全检查 — 黑名单命令直接拒绝"""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, step.command, re.IGNORECASE):
                return False
        return True

    def _render_variables(self, template: str, variables: Dict) -> str:
        """渲染变量模板 {{var}}"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def _execute_command(self, command: str, timeout: int = 30) -> Tuple[bool, str]:
        """执行 shell 命令"""
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode == 0, output.strip()

    def _check_expect(self, output: str, expect: str) -> bool:
        """检查输出是否符合预期

        支持简单表达式：
        - "< 85%" — 数字小于 85
        - "> 0" — 数字大于 0
        - "contains xxx" — 包含文本
        - "not_contains xxx" — 不包含文本
        """
        expect = expect.strip()

        # contains 检查
        if expect.startswith("contains "):
            keyword = expect[9:].strip()
            return keyword in output

        if expect.startswith("not_contains "):
            keyword = expect[13:].strip()
            return keyword not in output

        # 数字比较
        numbers = re.findall(r"[\d.]+", output)
        if not numbers:
            return False

        try:
            actual = float(numbers[-1])  # 取最后一个数字
        except ValueError:
            return False

        if expect.startswith("< "):
            threshold = float(re.findall(r"[\d.]+", expect)[0])
            return actual < threshold
        elif expect.startswith("> "):
            threshold = float(re.findall(r"[\d.]+", expect)[0])
            return actual > threshold
        elif expect.startswith("<= "):
            threshold = float(re.findall(r"[\d.]+", expect)[0])
            return actual <= threshold
        elif expect.startswith(">= "):
            threshold = float(re.findall(r"[\d.]+", expect)[0])
            return actual >= threshold

        return True  # 无法解析的 expect 默认通过

    def _generate_summary(self, runbook: Runbook) -> str:
        """生成执行摘要"""
        total = len(runbook.steps)
        done = sum(1 for s in runbook.steps if s.status == StepStatus.DONE)
        failed = sum(1 for s in runbook.steps if s.status == StepStatus.FAILED)
        skipped = sum(1 for s in runbook.steps if s.status == StepStatus.SKIPPED)
        total_time = sum(s.duration_ms for s in runbook.steps)

        lines = [
            f"[Runbook 执行报告] {runbook.name}",
            "━" * 40,
        ]
        for i, s in enumerate(runbook.steps, 1):
            icon = {"done": "✓", "failed": "✗", "skipped": "⊘", "pending": "○"}.get(s.status.value, "?")
            lines.append(f"  {icon} Step {i}: {s.name} ({s.duration_ms}ms)")
        lines.append("━" * 40)
        lines.append(f"  完成: {done}/{total} | 失败: {failed} | 跳过: {skipped} | 耗时: {total_time}ms")

        return "\n".join(lines)


def list_builtin_runbooks() -> List[str]:
    """列出内置 Runbook 模板"""
    template_dir = Path(__file__).parent / "templates"
    if not template_dir.exists():
        return []
    return [f.stem for f in template_dir.glob("*.yaml")]
