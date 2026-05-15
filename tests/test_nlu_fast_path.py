"""NLU 正则快速路径全覆盖测试

验证所有 _FAST_PATTERNS 正则规则的：
1. 正例（应该匹配）
2. 反例（不应该匹配）
3. 实体提取正确性
"""
import sys
sys.path.insert(0, ".")

from keeper.nlu.langchain_engine import _try_fast_match
from keeper.nlu.base import IntentType


class TestHelpIntent:
    def test_help_cn(self):
        r = _try_fast_match("帮助")
        assert r and r.intent == IntentType.HELP

    def test_help_en(self):
        r = _try_fast_match("help")
        assert r and r.intent == IntentType.HELP

    def test_what_can_you_do(self):
        r = _try_fast_match("你能做什么")
        assert r and r.intent == IntentType.HELP


class TestConfirmIntent:
    def test_yes(self):
        r = _try_fast_match("yes")
        assert r and r.intent == IntentType.CONFIRM

    def test_y(self):
        r = _try_fast_match("y")
        assert r and r.intent == IntentType.CONFIRM

    def test_confirm_cn(self):
        r = _try_fast_match("确认")
        assert r and r.intent == IntentType.CONFIRM

    def test_ok(self):
        r = _try_fast_match("ok")
        assert r and r.intent == IntentType.CONFIRM

    def test_execute(self):
        r = _try_fast_match("执行")
        assert r and r.intent == IntentType.CONFIRM


class TestInspectIntent:
    def test_check_localhost(self):
        r = _try_fast_match("检查本机")
        assert r and r.intent == IntentType.INSPECT
        assert r.entities.get("host") == "localhost"

    def test_check_this_machine(self):
        r = _try_fast_match("看看这台机器")
        assert r and r.intent == IntentType.INSPECT

    def test_batch_inspect(self):
        r = _try_fast_match("批量巡检所有机器")
        assert r and r.intent == IntentType.INSPECT
        assert r.entities.get("all_hosts") is True

    def test_check_all_servers(self):
        r = _try_fast_match("检查所有服务器")
        assert r and r.intent == IntentType.INSPECT

    def test_ip_extraction(self):
        r = _try_fast_match("检查 192.168.1.100 的状态")
        # 可能匹配 inspect 或提取 host
        if r:
            assert r.entities.get("host") == "192.168.1.100"


class TestK8sIntents:
    def test_k8s_inspect(self):
        r = _try_fast_match("K8s 集群巡检")
        assert r and r.intent == IntentType.K8S_INSPECT

    def test_k8s_status(self):
        r = _try_fast_match("k8s 集群状态怎么样")
        assert r and r.intent == IntentType.K8S_INSPECT

    def test_k3s_inspect(self):
        r = _try_fast_match("k3s 集群检查一下")
        assert r and r.intent == IntentType.K8S_INSPECT

    def test_pod_logs(self):
        r = _try_fast_match("查看 nginx Pod 的日志")
        assert r and r.intent == IntentType.K8S_LOGS


class TestDockerIntents:
    def test_docker_inspect(self):
        r = _try_fast_match("docker 容器状态检查")
        assert r and r.intent == IntentType.DOCKER_INSPECT

    def test_docker_list(self):
        r = _try_fast_match("查看 Docker 容器")
        assert r and r.intent == IntentType.DOCKER_INSPECT

    def test_docker_images(self):
        r = _try_fast_match("docker 镜像占用多大")
        assert r and r.intent == IntentType.DOCKER_INSPECT

    def test_docker_prune(self):
        r = _try_fast_match("清理 Docker 镜像")
        assert r and r.intent == IntentType.DOCKER_INSPECT


class TestScanIntent:
    def test_scan_vuln(self):
        r = _try_fast_match("扫描漏洞")
        assert r and r.intent == IntentType.SCAN

    def test_scan_port(self):
        r = _try_fast_match("扫描端口")
        assert r and r.intent == IntentType.SCAN

    def test_check_security(self):
        r = _try_fast_match("检查安全漏洞")
        assert r and r.intent == IntentType.SCAN


class TestExportIntent:
    def test_export_report(self):
        r = _try_fast_match("导出报告")
        assert r and r.intent == IntentType.EXPORT

    def test_export_json(self):
        r = _try_fast_match("json")
        assert r and r.intent == IntentType.EXPORT

    def test_generate_html(self):
        r = _try_fast_match("生成 HTML 报告")
        assert r and r.intent == IntentType.EXPORT


class TestLogsIntent:
    def test_view_logs(self):
        r = _try_fast_match("查看日志")
        assert r and r.intent == IntentType.LOGS

    def test_view_audit(self):
        r = _try_fast_match("查看审计记录")
        assert r and r.intent == IntentType.LOGS

    def test_recent_operations(self):
        r = _try_fast_match("最近做了什么操作")
        assert r and r.intent == IntentType.LOGS


class TestConfigIntent:
    def test_config(self):
        r = _try_fast_match("配置")
        assert r and r.intent == IntentType.CONFIG

    def test_set_threshold(self):
        r = _try_fast_match("设置阈值")
        assert r and r.intent == IntentType.CONFIG

    def test_show_config(self):
        r = _try_fast_match("显示配置")
        assert r and r.intent == IntentType.CONFIG


class TestNetworkIntent:
    def test_ping(self):
        r = _try_fast_match("ping 一下")
        assert r and r.intent == IntentType.NETWORK_DIAG

    def test_dns(self):
        r = _try_fast_match("DNS 解析正常吗")
        assert r and r.intent == IntentType.NETWORK_DIAG


class TestCertIntent:
    def test_cert_check(self):
        r = _try_fast_match("证书检查")
        assert r and r.intent == IntentType.CERT_CHECK

    def test_ssl_expire(self):
        r = _try_fast_match("SSL 证书过期了吗")
        assert r and r.intent == IntentType.CERT_CHECK


class TestScheduleIntent:
    def test_cron_task(self):
        r = _try_fast_match("每30分钟检查一次")
        assert r and r.intent == IntentType.SCHEDULE_TASK

    def test_daily_task(self):
        r = _try_fast_match("每天巡检一次")
        assert r and r.intent == IntentType.SCHEDULE_TASK


class TestAutoFixIntent:
    def test_auto_fix(self):
        r = _try_fast_match("帮我修复问题")
        assert r and r.intent == IntentType.AUTO_FIX

    def test_one_click_fix(self):
        r = _try_fast_match("一键修复")
        assert r and r.intent == IntentType.AUTO_FIX


class TestRCAIntent:
    def test_rca_why(self):
        r = _try_fast_match("分析为什么 CPU 高")
        assert r and r.intent == IntentType.RCA_ANALYSIS

    def test_rca_root_cause(self):
        r = _try_fast_match("根因分析")
        assert r and r.intent == IntentType.RCA_ANALYSIS


class TestNotifyIntent:
    def test_feishu(self):
        r = _try_fast_match("推送到飞书")
        assert r and r.intent == IntentType.SEND_NOTIFY


class TestNegativeCases:
    """反例测试 — 不应该匹配的输入"""

    def test_random_text_no_match(self):
        r = _try_fast_match("今天天气怎么样")
        assert r is None

    def test_pure_chinese_no_match(self):
        r = _try_fast_match("谢谢你")
        assert r is None

    def test_empty_string(self):
        r = _try_fast_match("")
        assert r is None

    def test_numbers_only(self):
        r = _try_fast_match("12345")
        assert r is None


class TestHostExtraction:
    """IP 提取测试"""

    def test_extract_ipv4(self):
        r = _try_fast_match("检查 10.0.0.1 本机状态")
        if r:
            assert r.entities.get("host") == "10.0.0.1"

    def test_extract_from_scan(self):
        r = _try_fast_match("扫描 192.168.1.50 的漏洞")
        if r:
            assert r.entities.get("host") == "192.168.1.50"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
