"""Agent 工具注册层测试

测试内容：
1. 所有工具能正确注册
2. 工具描述格式正确
3. 安全命令检查正确拦截
4. fallback 模式下工具可调用
"""
import sys
sys.path.insert(0, ".")

from keeper.agent.tools_registry import (
    ALL_TOOLS,
    get_tools_description,
    LANGCHAIN_AVAILABLE,
    inspect_server,
    get_top_processes,
    execute_shell_command,
    manage_systemd_service,
    ping_host,
    check_port,
    dns_lookup,
)


class TestToolsRegistry:
    """工具注册表测试"""

    def test_all_tools_count(self):
        """应注册 18 个工具"""
        assert len(ALL_TOOLS) == 18

    def test_all_tools_have_name(self):
        """每个工具都应有 name 属性"""
        for tool in ALL_TOOLS:
            name = tool.name if hasattr(tool, "name") else tool.__name__
            assert name, f"Tool missing name: {tool}"
            assert isinstance(name, str)

    def test_all_tools_have_description(self):
        """每个工具都应有 description/docstring"""
        for tool in ALL_TOOLS:
            desc = ""
            if hasattr(tool, "description"):
                desc = tool.description
            elif hasattr(tool, "__doc__") and tool.__doc__:
                desc = tool.__doc__
            assert desc, f"Tool {getattr(tool, 'name', '?')} missing description"

    def test_get_tools_description_format(self):
        """get_tools_description 应返回格式化字符串"""
        desc = get_tools_description()
        assert "可用工具列表" in desc
        assert "inspect_server" in desc
        assert "execute_shell_command" in desc
        assert "共 18 个工具可用" in desc

    def test_tool_names_unique(self):
        """工具名称不应重复"""
        names = []
        for tool in ALL_TOOLS:
            name = tool.name if hasattr(tool, "name") else tool.__name__
            names.append(name)
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_langchain_fallback_mode(self):
        """无 langchain 时应使用 fallback 装饰器"""
        # 在当前环境中 langchain 不可用，验证 fallback 正常工作
        if not LANGCHAIN_AVAILABLE:
            # 验证工具有 invoke 方法（fallback 提供）
            assert hasattr(inspect_server, "invoke")
            assert hasattr(execute_shell_command, "invoke")
            assert callable(inspect_server.invoke)


class TestToolSafety:
    """工具安全性测试"""

    def test_dangerous_command_blocked(self):
        """危险命令应被拦截"""
        result = execute_shell_command.invoke({"command": "rm -rf /"})
        assert "安全拦截" in result or "高危" in result

    def test_dangerous_dd_blocked(self):
        """dd 命令应被拦截"""
        result = execute_shell_command.invoke({"command": "dd if=/dev/zero of=/dev/sda"})
        assert "安全拦截" in result or "高危" in result

    def test_dangerous_mkfs_blocked(self):
        """mkfs 命令应被拦截"""
        result = execute_shell_command.invoke({"command": "mkfs.ext4 /dev/sda1"})
        assert "安全拦截" in result or "高危" in result

    def test_safe_command_allowed(self):
        """安全命令应能执行"""
        result = execute_shell_command.invoke({"command": "echo hello"})
        # 应该不包含安全拦截
        assert "安全拦截" not in result

    def test_safe_df_command(self):
        """df 命令应能执行"""
        result = execute_shell_command.invoke({"command": "df -h /"})
        assert "安全拦截" not in result
        # df 应该有输出（Filesystem 或 文件系统）
        assert len(result) > 10

    def test_systemd_service_invalid_action(self):
        """无效的 service action 应报错"""
        result = manage_systemd_service.invoke({"service": "nginx", "action": "destroy"})
        assert "不支持的操作" in result


class TestToolExecution:
    """工具执行测试（在可用环境下）"""

    def test_execute_shell_echo(self):
        """execute_shell_command 应能执行 echo"""
        result = execute_shell_command.invoke({"command": "echo test_output_12345"})
        assert "test_output_12345" in result

    def test_execute_shell_timeout_info(self):
        """超长命令应被截断提示"""
        # 生成一个会产生大量输出的命令
        result = execute_shell_command.invoke({"command": "seq 1 10000"})
        # 结果应该被截断或正常返回
        assert len(result) <= 3200  # MAX 3000 + 一些截断提示

    def test_execute_empty_command(self):
        """空输出命令应有提示"""
        result = execute_shell_command.invoke({"command": "true"})
        assert "无输出" in result or result.strip() == ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
