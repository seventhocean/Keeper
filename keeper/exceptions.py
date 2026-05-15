"""Keeper 统一异常体系

所有 Keeper 自定义异常的基类和子类定义。
使用统一异常可以：
1. 在 Agent 层统一 catch 并给出友好提示
2. 区分可恢复/不可恢复异常
3. 在审计日志中记录准确的错误类型
"""


class KeeperError(Exception):
    """Keeper 所有异常的基类"""

    def __init__(self, message: str = "", details: str = ""):
        self.message = message
        self.details = details
        super().__init__(message)

    def __str__(self):
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class ConfigError(KeeperError):
    """配置错误 — 配置文件缺失、格式错误、必填项为空"""
    pass


class ConnectionError(KeeperError):
    """连接失败 — SSH/K8s/LLM API 连接不上"""

    def __init__(self, message: str = "", target: str = "", details: str = ""):
        self.target = target
        super().__init__(message, details)


class TimeoutError(KeeperError):
    """操作超时 — 命令执行、API 调用、网络请求超时"""

    def __init__(self, message: str = "", timeout_seconds: int = 0, details: str = ""):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, details)


class PermissionError(KeeperError):
    """权限不足 — SSH 无权限、K8s RBAC 拒绝、文件不可读"""
    pass


class ValidationError(KeeperError):
    """输入校验失败 — IP 格式错误、命令注入检测、参数越界"""

    def __init__(self, message: str = "", field: str = "", value: str = "", details: str = ""):
        self.field = field
        self.value = value
        super().__init__(message, details)


class ToolExecutionError(KeeperError):
    """工具执行失败 — 扫描失败、巡检异常、报告生成错误"""

    def __init__(self, message: str = "", tool_name: str = "", details: str = ""):
        self.tool_name = tool_name
        super().__init__(message, details)


class NLUError(KeeperError):
    """NLU 解析异常 — LLM 返回格式错误、解析超时"""
    pass


class SafetyError(KeeperError):
    """安全拦截 — 危险命令被拒绝执行"""

    def __init__(self, message: str = "", command: str = "", level: str = "", details: str = ""):
        self.command = command
        self.level = level
        super().__init__(message, details)
