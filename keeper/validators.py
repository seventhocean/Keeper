"""输入参数校验模块 — 防止命令注入和非法输入

校验规则：
1. IP 地址：必须是合法的 IPv4/IPv6 格式
2. Hostname：只允许字母、数字、点、横杠
3. 命令参数：黑名单字符拦截（; | & $() `` 等）
4. 端口号：1-65535 范围
5. 文件路径：禁止路径穿越
"""
import re
from typing import Tuple

from .exceptions import ValidationError


# ─── IP 地址校验 ─────────────────────────────────────────────────

_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)

_IPV6_PATTERN = re.compile(
    r"^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|"
    r"^::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}$|"
    r"^(?:[0-9a-fA-F]{1,4}:){1,6}:$|"
    r"^(?:[0-9a-fA-F]{1,4}:){1,7}:$|"
    r"^::$"
)


def validate_ip(ip: str) -> str:
    """校验 IP 地址格式

    Args:
        ip: 待校验的 IP 地址字符串

    Returns:
        校验通过的 IP 地址（去除首尾空白）

    Raises:
        ValidationError: IP 格式不合法
    """
    ip = ip.strip()
    if not ip:
        raise ValidationError("IP 地址不能为空", field="ip", value=ip)

    if _IPV4_PATTERN.match(ip) or _IPV6_PATTERN.match(ip):
        return ip

    raise ValidationError(
        f"IP 地址格式不合法: {ip}",
        field="ip",
        value=ip,
        details="支持 IPv4 (如 192.168.1.1) 和 IPv6 格式",
    )


# ─── Hostname 校验 ───────────────────────────────────────────────

_HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$")

# 特殊允许的 hostname
_ALLOWED_HOSTNAMES = {"localhost"}


def validate_hostname(hostname: str) -> str:
    """校验 hostname 格式

    Args:
        hostname: 待校验的主机名

    Returns:
        校验通过的 hostname

    Raises:
        ValidationError: hostname 格式不合法或包含危险字符
    """
    hostname = hostname.strip()
    if not hostname:
        raise ValidationError("主机名不能为空", field="hostname", value=hostname)

    if hostname in _ALLOWED_HOSTNAMES:
        return hostname

    if _HOSTNAME_PATTERN.match(hostname):
        return hostname

    raise ValidationError(
        f"主机名格式不合法: {hostname}",
        field="hostname",
        value=hostname,
        details="只允许字母、数字、点(.)和横杠(-)",
    )


# ─── Host 校验（IP 或 Hostname）───────────────────────────────────

def validate_host(host: str) -> str:
    """校验主机地址（IP 或 hostname）

    Args:
        host: IP 地址或主机名

    Returns:
        校验通过的地址

    Raises:
        ValidationError: 格式不合法
    """
    host = host.strip()
    if not host:
        raise ValidationError("主机地址不能为空", field="host", value=host)

    # 先尝试 IP
    if re.match(r"^\d", host) or ":" in host:
        return validate_ip(host)

    # 否则按 hostname
    return validate_hostname(host)


# ─── 端口校验 ─────────────────────────────────────────────────────

def validate_port(port) -> int:
    """校验端口号

    Args:
        port: 端口号（int 或 str）

    Returns:
        校验通过的端口号（int）

    Raises:
        ValidationError: 端口不在有效范围
    """
    try:
        port_int = int(port)
    except (ValueError, TypeError):
        raise ValidationError(
            f"端口号必须是数字: {port}",
            field="port",
            value=str(port),
        )

    if 1 <= port_int <= 65535:
        return port_int

    raise ValidationError(
        f"端口号超出范围: {port_int}",
        field="port",
        value=str(port_int),
        details="有效范围: 1-65535",
    )


# ─── 命令注入检测 ─────────────────────────────────────────────────

# 危险字符/模式 — 可能导致命令注入
_INJECTION_PATTERNS = [
    (r"[;&|]", "包含命令分隔符 (; & |)"),
    (r"\$\(", "包含命令替换 $()"),
    (r"`", "包含反引号命令替换"),
    (r"\$\{", "包含变量展开 ${}"),
    (r">\s*/", "包含重定向到系统路径"),
    (r"\.\./", "包含路径穿越 ../"),
    (r"\\n|\\r", "包含换行符注入"),
]


def validate_command_input(value: str, field_name: str = "input") -> str:
    """校验用户输入是否包含命令注入 payload

    Args:
        value: 用户输入值
        field_name: 字段名称（用于错误消息）

    Returns:
        校验通过的输入

    Raises:
        ValidationError: 检测到注入 payload
    """
    if not value:
        return value

    for pattern, description in _INJECTION_PATTERNS:
        if re.search(pattern, value):
            raise ValidationError(
                f"输入包含不安全字符: {description}",
                field=field_name,
                value=value[:50],
                details="禁止在输入中使用 shell 特殊字符",
            )

    return value


# ─── 文件路径校验 ─────────────────────────────────────────────────

def validate_file_path(path: str) -> str:
    """校验文件路径（防止路径穿越）

    Args:
        path: 文件路径

    Returns:
        校验通过的路径

    Raises:
        ValidationError: 路径不安全
    """
    path = path.strip()
    if not path:
        raise ValidationError("文件路径不能为空", field="path", value=path)

    # 检测路径穿越
    if ".." in path:
        raise ValidationError(
            "文件路径包含路径穿越",
            field="path",
            value=path,
            details="禁止使用 .. 进行路径穿越",
        )

    # 检测命令注入
    if any(c in path for c in [";", "|", "&", "`", "$"]):
        raise ValidationError(
            "文件路径包含非法字符",
            field="path",
            value=path,
        )

    return path


# ─── 便捷函数：安全校验 host 参数 ─────────────────────────────────

def safe_validate_host(host: str) -> Tuple[bool, str]:
    """安全校验 host（不抛异常版本）

    Returns:
        (is_valid, host_or_error_message)
    """
    try:
        validated = validate_host(host)
        return True, validated
    except ValidationError as e:
        return False, str(e)
