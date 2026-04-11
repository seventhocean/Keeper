"""K8s 巡检报告格式化工具"""
from typing import Optional

from .inspector import K8sClusterReport


def format_cluster_report(report: K8sClusterReport, namespace: Optional[str] = None) -> str:
    """格式化 K8s 集群巡检报告

    Args:
        report: 集群巡检报告
        namespace: 过滤的 namespace

    Returns:
        str: 格式化的报告文本
    """
    lines = []
    ns_filter = f" (namespace: {namespace})" if namespace else ""

    # 头部
    lines.append(f"[K8s 巡检] 集群巡检报告{ns_filter}")
    lines.append("=" * 50)
    lines.append(f"  集群类型：  {report.cluster_type}")
    lines.append(f"  K8s 版本：  {report.k8s_version}")
    lines.append(f"  节点数量：  {report.node_count}")
    lines.append(f"  Pod 总数：  {report.pods_total}")
    lines.append(f"  巡检时间：  {report.timestamp}")

    # 节点状态
    lines.append("")
    lines.append("━" * 50)
    lines.append("节点状态:")
    lines.append("━" * 50)

    if report.nodes:
        lines.append(f"  {'节点':<25} {'状态':<10} {'角色':<15} {'Pod数':<8} {'可调度':<8} {'版本'}")
        lines.append("  " + "-" * 50)
        for node in report.nodes:
            sched_icon = "✓" if node.schedulable else "✗"
            roles = ",".join(node.roles[:2])
            lines.append(f"  {node.name:<25} {node.status:<10} {roles:<15} {node.pods_count:<8} {sched_icon:<8} {node.k8s_version}")
            if not node.schedulable:
                lines.append(f"    ⚠ 节点被标记为不可调度")
            if node.taints:
                for t in node.taints:
                    lines.append(f"    Taint: {t['key']}={t['effect']}")
    else:
        lines.append("  未找到节点")

    # 异常 Pod
    lines.append("")
    lines.append("━" * 50)
    lines.append("异常 Pod 检测:")
    lines.append("━" * 50)

    if report.abnormal_pods:
        for pod in report.abnormal_pods:
            issue_str = "; ".join(pod.issues)
            lines.append(f"  ✗ {pod.namespace}/{pod.name} - {pod.phase}")
            lines.append(f"    节点: {pod.node} | 重启: {pod.restarts} | 运行: {pod.age}")
            lines.append(f"    问题: {issue_str}")
    else:
        lines.append("  ✓ 未发现异常 Pod")

    # 工作负载
    lines.append("")
    lines.append("━" * 50)
    lines.append("工作负载 (Deployment/StatefulSet/DaemonSet):")
    lines.append("━" * 50)

    if report.workloads:
        # 按 namespace 分组
        ns_workloads = {}
        for w in report.workloads:
            if w.namespace not in ns_workloads:
                ns_workloads[w.namespace] = []
            ns_workloads[w.namespace].append(w)

        for ns, workloads in ns_workloads.items():
            lines.append(f"  [{ns}]")
            for w in workloads:
                if w.issues:
                    icon = "✗"
                    issues_note = f" ({'; '.join(w.issues)})"
                else:
                    icon = "✓"
                    issues_note = ""
                lines.append(f"    {icon} {w.kind}/{w.name} - {w.ready}/{w.desired} ready")
                if issues_note:
                    lines.append(f"      {issues_note}")
    else:
        lines.append("  未找到工作负载")

    # 存储
    if report.storage:
        lines.append("")
        lines.append("━" * 50)
        lines.append("存储 (PVC/PV):")
        lines.append("━" * 50)
        for s in report.storage:
            icon = "✓" if not s.issues else "✗"
            lines.append(f"  {icon} {s.kind}/{s.name} - {s.status} ({s.capacity}, SC: {s.storage_class})")
            for issue in s.issues:
                lines.append(f"    问题: {issue}")

    # Ingress
    if report.ingresses:
        lines.append("")
        lines.append("━" * 50)
        lines.append("Ingress 路由:")
        lines.append("━" * 50)
        for ing in report.ingresses:
            icon = "✓" if not ing.issues else "✗"
            lines.append(f"  {icon} {ing.namespace}/{ing.name}")
            for rule in ing.rules:
                lines.append(f"    规则: {rule}")
            if ing.tls_hosts:
                lines.append(f"    TLS: {', '.join(ing.tls_hosts)}")
            if ing.backend_services:
                lines.append(f"    后端: {', '.join(ing.backend_services)}")
            for issue in ing.issues:
                lines.append(f"    问题: {issue}")
    else:
        lines.append("")
        lines.append("  (未配置 Ingress)")

    # ConfigMap/Secret 摘要
    if report.config_secrets:
        lines.append("")
        lines.append("━" * 50)
        lines.append("ConfigMap/Secret 巡检:")
        lines.append("━" * 50)
        cms = [c for c in report.config_secrets if c.kind == "ConfigMap"]
        secrets = [c for c in report.config_secrets if c.kind == "Secret"]

        # ConfigMap 摘要
        large_cms = [c for c in cms if c.size_bytes > 500 * 1024]
        empty_cms = [c for c in cms if not c.data_keys]
        if large_cms or empty_cms:
            for cm in large_cms:
                lines.append(f"  ✗ ConfigMap/{cm.namespace}/{cm.name} - 体积过大 ({cm.size_bytes / 1024:.0f}KB)")
            for cm in empty_cms:
                lines.append(f"  ⚠ ConfigMap/{cm.namespace}/{cm.name} - 空 ConfigMap")
        else:
            lines.append(f"  ✓ ConfigMap: {len(cms)} 个，无异常")

        # Secret 摘要
        tls_secrets = [s for s in secrets if s.secret_type == "kubernetes.io/tls"]
        cert_issues = [s for s in secrets if any("TLS" in i or "证书" in i for i in s.issues)]
        large_secrets = [s for s in secrets if any("异常大" in i for i in s.issues)]

        if cert_issues:
            for s in cert_issues:
                for issue in s.issues:
                    if "TLS" in issue or "证书" in issue:
                        lines.append(f"  ✗ Secret/{s.namespace}/{s.name} - {issue}")
        else:
            lines.append(f"  ✓ TLS 证书: {len(tls_secrets)} 个，无过期")

        if large_secrets:
            for s in large_secrets:
                for issue in s.issues:
                    if "异常大" in issue:
                        lines.append(f"  ⚠ Secret/{s.namespace}/{s.name} - {issue}")

        # 敏感信息提示
        total_secrets = len(secrets)
        lines.append(f"  总计: Secret {total_secrets} 个, ConfigMap {len(cms)} 个")

    # LimitRange
    if report.limit_ranges:
        lines.append("")
        lines.append("━" * 50)
        lines.append("LimitRange (资源限制):")
        lines.append("━" * 50)
        for lr in report.limit_ranges:
            icon = "✓" if not lr.issues else "✗"
            lines.append(f"  {icon} {lr.namespace}/{lr.name}")
            for limit in lr.limits:
                if limit["default"]:
                    lines.append(f"    默认限制: {limit['default']}")
                if limit["default_request"]:
                    lines.append(f"    默认请求: {limit['default_request']}")

    # Warning 事件
    if report.events_warnings:
        lines.append("")
        lines.append("━" * 50)
        lines.append(f"Warning 事件 (Top {min(len(report.events_warnings), 20)}):")
        lines.append("━" * 50)
        for ev in report.events_warnings[:20]:
            lines.append(f"  [{ev.severity}] {ev.involved_object} - {ev.reason} (x{ev.count})")
            if ev.message:
                msg = ev.message[:120] + "..." if len(ev.message) > 120 else ev.message
                lines.append(f"    {msg}")
            lines.append(f"    最近: {ev.last_seen}")
    else:
        lines.append("")
        lines.append("  ✓ 无 Warning 事件")

    # Namespace 列表
    if report.namespaces:
        lines.append("")
        lines.append("━" * 50)
        lines.append("Namespaces:")
        lines.append("━" * 50)
        lines.append(f"  {', '.join(report.namespaces)}")

    # ResourceQuota
    if report.resource_quotas:
        lines.append("")
        lines.append("━" * 50)
        lines.append("ResourceQuota:")
        lines.append("━" * 50)
        for q in report.resource_quotas:
            lines.append(f"  [{q['namespace']}] {q['name']}")
            # 对比 used vs hard
            for key in q["hard"]:
                hard = q["hard"][key]
                used = q["used"].get(key, "0")
                lines.append(f"    {key}: {used}/{hard}")

    # 健康评分
    lines.append("")
    lines.append("=" * 50)
    if report.score >= 90:
        status_text = "健康"
    elif report.score >= 70:
        status_text = "基本健康，有少量警告"
    elif report.score >= 50:
        status_text = "需要注意，存在异常"
    else:
        status_text = "异常较多，建议立即排查"
    lines.append(f"  健康评分：{report.score}/100 - {status_text}")

    if report.issues:
        lines.append(f"  问题数：{len(report.issues)}")
        for issue in report.issues[:5]:
            lines.append(f"    - {issue}")
        if len(report.issues) > 5:
            lines.append(f"    ... 还有 {len(report.issues) - 5} 个问题")

    lines.append("=" * 50)
    return "\n".join(lines)
