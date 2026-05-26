"""工具模块测试 — Docker, Network, Scanner, SSH, RCA, Notify, Alert

覆盖之前零测试的核心工具模块。所有测试基于实际 API 签名。
"""
import sys
sys.path.insert(0, ".")

import tempfile
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Network Tools
# ═══════════════════════════════════════════════════════════════

class TestNetworkTools:
    def test_ping_localhost(self):
        import pytest
        from keeper.tools.network import NetworkTools
        result = NetworkTools.ping("127.0.0.1", count=1)
        if not result["success"]:
            pytest.skip("ping not available in this environment")
        assert result["reachable"] is True
        assert result["host"] == "127.0.0.1"

    def test_ping_unreachable(self):
        from keeper.tools.network import NetworkTools
        # TEST-NET address — should be unreachable
        result = NetworkTools.ping("192.0.2.1", count=1, timeout=2)
        assert not result["reachable"] or result["packet_loss"] > 0

    def test_check_port(self):
        from keeper.tools.network import NetworkTools
        result = NetworkTools.check_port("127.0.0.1", 22)
        assert result["port"] == 22
        assert "open" in result  # key is "open" (bool)

    def test_dns_lookup_localhost(self):
        from keeper.tools.network import NetworkTools
        result = NetworkTools.dns_lookup("localhost")
        assert result["resolved"] is True
        assert len(result["a_records"]) > 0

    def test_ping_format(self):
        from keeper.tools.network import NetworkTools, format_ping_result
        result = NetworkTools.ping("127.0.0.1", count=1)
        formatted = format_ping_result(result)
        assert "127.0.0.1" in formatted

    def test_port_format(self):
        from keeper.tools.network import format_port_result
        result = {"host": "127.0.0.1", "port": 22, "open": True, "response_time_ms": 1}
        formatted = format_port_result(result)
        assert "22" in formatted

    def test_dns_format(self):
        from keeper.tools.network import format_dns_result
        result = {"domain": "localhost", "a_records": ["127.0.0.1"], "resolved": True,
                  "dns_server": "127.0.0.1", "query_time_ms": 2}
        formatted = format_dns_result(result)
        assert "localhost" in formatted


# ═══════════════════════════════════════════════════════════════
# Scanner Tools
# ═══════════════════════════════════════════════════════════════

class TestScannerTools:
    def test_port_info_dataclass(self):
        from keeper.tools.scanner import PortInfo
        port = PortInfo(port=80, protocol="tcp", state="open", service="http", version="nginx 1.24.0")
        assert port.port == 80
        assert port.protocol == "tcp"
        assert port.state == "open"
        assert port.service == "http"
        assert "nginx" in port.version

    def test_scan_result_dataclass(self):
        from keeper.tools.scanner import ScanResult, PortInfo
        port = PortInfo(port=443, protocol="tcp", state="open", service="https")
        result = ScanResult(host="test", timestamp="2026-05-15",
                           open_ports=[port], closed_ports=99)
        assert result.host == "test"
        assert len(result.open_ports) == 1
        assert result.open_ports[0].port == 443

    def test_risk_analysis(self):
        from keeper.tools.scanner import ScannerTools, PortInfo
        port = PortInfo(port=23, protocol="tcp", state="open", service="telnet")
        risks = ScannerTools._analyze_risks([port])
        assert isinstance(risks, list)

    def test_format_scan_result(self):
        from keeper.tools.scanner import ScanResult, PortInfo, format_scan_result
        ports = [PortInfo(port=22, protocol="tcp", state="open", service="ssh", version="OpenSSH")]
        result = ScanResult(host="localhost", timestamp="2026-05-15",
                           open_ports=ports,
                           risks=[{"level": "medium", "port": "22", "service": "ssh", "description": "SSH 开放"}])
        formatted = format_scan_result(result)
        assert "localhost" in formatted
        assert "22" in formatted

    def test_nmap_error(self):
        from keeper.tools.scanner import NmapNotInstalledError
        e = NmapNotInstalledError()
        assert isinstance(e, Exception)
        # 默认消息可能为空，但应有 get_install_command 可用
        cmd = NmapNotInstalledError.get_install_command()
        assert "nmap" in cmd.lower()


# ═══════════════════════════════════════════════════════════════
# Docker Tools
# ═══════════════════════════════════════════════════════════════

class TestDockerTools:
    def test_is_docker_available(self):
        from keeper.tools.docker_tools import DockerTools
        assert isinstance(DockerTools.is_docker_available(), bool)

    def test_list_containers(self):
        from keeper.tools.docker_tools import DockerTools
        containers = DockerTools.list_containers()
        assert isinstance(containers, list)
        if containers:
            assert "name" in containers[0]

    def test_get_stats(self):
        from keeper.tools.docker_tools import DockerTools
        stats = DockerTools.get_container_stats()
        assert isinstance(stats, list)

    def test_list_images(self):
        from keeper.tools.docker_tools import DockerTools
        images = DockerTools.list_images()
        assert isinstance(images, list)

    def test_docker_inspect(self):
        from keeper.tools.docker_tools import DockerTools
        result = DockerTools.docker_inspect()
        assert isinstance(result, dict)
        assert "service_ok" in result or "version" in result
        assert "health_score" in result


# ═══════════════════════════════════════════════════════════════
# SSH Tools
# ═══════════════════════════════════════════════════════════════

class TestSSHTools:
    def test_ssh_config_defaults(self):
        from keeper.tools.ssh import SSHConfig
        c = SSHConfig(host="192.168.1.1")
        assert c.host == "192.168.1.1"
        assert c.port == 22
        assert c.username == "root"

    def test_ssh_config_custom(self):
        from keeper.tools.ssh import SSHConfig
        c = SSHConfig(host="10.0.0.1", port=2222, username="admin", key_file="/k")
        assert c.port == 2222
        assert c.username == "admin"

    def test_get_hosts_from_file(self):
        from keeper.tools.ssh import SSHTools
        with tempfile.TemporaryDirectory() as td:
            hosts_file = Path(td) / "hosts"
            hosts_file.write_text("127.0.0.1 localhost\n192.168.1.100 server-a\n")
            hosts = SSHTools.get_hosts_from_file(str(hosts_file))
            # get_hosts_from_file 返回 IP 列表（过滤 127.0.0.1）
            assert "192.168.1.100" in hosts


# ═══════════════════════════════════════════════════════════════
# RCA Tools
# ═══════════════════════════════════════════════════════════════

class TestRCATools:
    def test_collect_server_data(self):
        from keeper.tools.rca import RCAEngine
        data = RCAEngine.collect_server_data()
        assert "cpu_percent" in data
        assert "memory_percent" in data
        assert "disk_percent" in data
        assert "top_cpu_processes" in data

    def test_analyze_server(self):
        from keeper.tools.rca import RCAEngine
        data = RCAEngine.collect_server_data()
        text = RCAEngine.analyze_server(data)
        assert len(text) > 50
        assert "CPU" in text or "cpu" in text.lower()

    def test_generate_diagnosis_prompt(self):
        from keeper.tools.rca import RCAEngine
        prompt = RCAEngine.generate_diagnosis_prompt("CPU 使用率 95%")
        assert "CPU" in prompt
        assert len(prompt) > 100

    def test_compare_hosts(self):
        from keeper.tools.rca import RCAEngine
        data = RCAEngine.collect_server_data()
        text = RCAEngine.compare_hosts(data, data, "a", "b")
        assert "a" in text and "b" in text


# ═══════════════════════════════════════════════════════════════
# Alert Engine
# ═══════════════════════════════════════════════════════════════

class TestAlertEngine:
    def test_no_alerts_healthy(self):
        from keeper.tools.alert import AlertEngine
        data = {"cpu_percent": 10.0, "memory_percent": 30.0, "disk_percent": 20.0,
                "load_avg": {"1m": 0.5}, "failed_services": [], "swap_percent": 0.0}
        alerts = AlertEngine.check_server(data, {"cpu": 90, "memory": 90, "disk": 95})
        assert isinstance(alerts, list)

    def test_cpu_triggered(self):
        from keeper.tools.alert import AlertEngine
        data = {"cpu_percent": 95.0, "memory_percent": 30.0, "disk_percent": 20.0,
                "load_avg": {"1m": 0.5}, "failed_services": [], "swap_percent": 0.0}
        alerts = AlertEngine.check_server(data, {"cpu": 90, "memory": 90, "disk": 95})
        cpu_alerts = [a for a in alerts if "CPU" in a.name.upper()]
        assert len(cpu_alerts) > 0

    def test_alert_dataclass(self):
        from keeper.tools.alert import Alert
        alert = Alert(name="CPU告警", severity="critical", message="CPU 98%")
        assert alert.severity == "critical"


# ═══════════════════════════════════════════════════════════════
# Notify Tools
# ═══════════════════════════════════════════════════════════════

class TestNotifyTools:
    def test_init_no_secret(self):
        from keeper.tools.notify import FeishuNotifier
        n = FeishuNotifier("https://hooks.example.com/test")
        assert n.webhook_url == "https://hooks.example.com/test"
        assert n.secret is None

    def test_init_with_secret(self):
        from keeper.tools.notify import FeishuNotifier
        n = FeishuNotifier("https://hooks.example.com/test", "s3cr3t")
        assert n.secret == "s3cr3t"

    def test_gen_sign(self):
        from keeper.tools.notify import FeishuNotifier
        import time
        n = FeishuNotifier("https://hooks.example.com/test", "secret")
        sign = n._gen_sign(int(time.time()))
        assert isinstance(sign, str) and len(sign) > 0


# ═══════════════════════════════════════════════════════════════
# Server Tools
# ═══════════════════════════════════════════════════════════════

class TestServerToolsExtended:
    def test_get_cpu(self):
        from keeper.tools.server import ServerTools
        cpu = ServerTools.get_cpu_percent()
        assert isinstance(cpu, (int, float))

    def test_get_memory(self):
        from keeper.tools.server import ServerTools
        mem = ServerTools.get_memory_info()
        assert "percent" in mem
        assert mem["used_gb"] > 0

    def test_get_disk(self):
        from keeper.tools.server import ServerTools
        disk = ServerTools.get_disk_info()
        assert "percent" in disk

    def test_get_load(self):
        from keeper.tools.server import ServerTools
        load = ServerTools.get_load_avg()
        assert "1m" in load
        assert isinstance(load["1m"], (int, float))

    def test_get_top_processes(self):
        from keeper.tools.server import ServerTools
        procs = ServerTools.get_top_processes(3)
        assert len(procs) <= 3
        for p in procs:
            assert "pid" in p and "name" in p

    def test_inspect_local(self):
        from keeper.tools.server import ServerTools, format_status_report
        status = ServerTools.inspect_server("localhost")
        thresholds = {"cpu": 90, "memory": 90, "disk": 95}
        report = format_status_report(status, thresholds)
        assert "CPU" in report
        assert "localhost" in report


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
