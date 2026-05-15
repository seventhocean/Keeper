"""K8s Handler — Kubernetes 集群管理相关处理"""
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from ...config import AppConfig


def _get_k8s_client(config: AppConfig, auto_detect: bool = True):
    """获取已连接的 K8s 客户端

    Returns:
        (k8s_client, format_cluster_report, error_msg)
    """
    from ...tools.k8s.client import K8sClient, K8sClusterConfig
    from ...tools.k8s.formatter import format_cluster_report

    k8s_cfg_data = config.get_k8s_config()
    kubeconfig = k8s_cfg_data.get("kubeconfig", "")
    context = k8s_cfg_data.get("context", "")
    cluster_type = k8s_cfg_data.get("cluster_type", "k8s")

    k8s_cfg = K8sClusterConfig(
        kubeconfig_path=kubeconfig,
        context=context,
        cluster_type=cluster_type,
    )

    k8s_client = K8sClient(k8s_cfg)
    success, msg = k8s_client.connect()

    if success:
        return k8s_client, format_cluster_report, None

    if not auto_detect:
        return None, None, f"[K8s] 连接集群失败：{msg}"

    # 检测 K3s
    k3s_path = "/etc/rancher/k3s/k3s.yaml"
    if os.path.exists(k3s_path):
        k8s_cfg_data["kubeconfig"] = k3s_path
        k8s_cfg_data["cluster_type"] = "k3s"
        config.k8s = k8s_cfg_data
        config.save()

        k8s_cfg = K8sClusterConfig(kubeconfig_path=k3s_path, context=context, cluster_type="k3s")
        k8s_client = K8sClient(k8s_cfg)
        success, msg = k8s_client.connect()
        if success:
            return k8s_client, format_cluster_report, None
        return None, None, f"[K8s] 连接 K3s 失败：{msg}"

    # 检测标准 K8s
    std_path = str(Path.home() / ".kube/config")
    if os.path.exists(std_path):
        k8s_cfg_data["kubeconfig"] = std_path
        k8s_cfg_data["cluster_type"] = "k8s"
        config.k8s = k8s_cfg_data
        config.save()

        k8s_cfg = K8sClusterConfig(kubeconfig_path=std_path, context=context, cluster_type="k8s")
        k8s_client = K8sClient(k8s_cfg)
        success, msg = k8s_client.connect()
        if success:
            return k8s_client, format_cluster_report, None
        return None, None, f"[K8s] 连接集群失败：{msg}"

    return None, None, (
        "[K8s] 未找到 Kubeconfig 配置文件\n\n"
        "我检测到以下可能的位置：\n"
        "  - K3s: /etc/rancher/k3s/k3s.yaml\n"
        "  - K8s: ~/.kube/config\n\n"
        "请告诉我你的 kubeconfig 路径，或者说'帮我配置'我来自动检测。"
    )


def handle_k8s_inspect(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 K8s 集群巡检意图"""
    k8s_client, fmt, err = _get_k8s_client(config, auto_detect=True)
    if err:
        return err

    try:
        from ...tools.k8s.inspector import K8sInspector
        from ...tools.k8s.formatter import format_cluster_report

        namespace = entities.get("namespace")
        success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
        if not success:
            return f"[K8s] 巡检失败：{report.issues[0] if report.issues else '未知错误'}"

        state.context.current_host = "k8s-cluster"
        return format_cluster_report(report, namespace)
    except Exception as e:
        return f"[K8s] 巡检失败：{str(e)}"
    finally:
        k8s_client.close()


def handle_k8s_logs(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 K8s Pod 日志查询意图"""
    k8s_client, _, err = _get_k8s_client(config, auto_detect=True)
    if err:
        return err

    try:
        from ...tools.k8s.logs import K8sLogTools

        pod_name = entities.get("pod_name")
        namespace = entities.get("namespace") or "default"
        lines = int(entities.get("lines", 100))
        keyword = entities.get("query")
        container = entities.get("container")

        if not pod_name:
            return "[K8s] 请指定 Pod 名称，例如：查看 my-app Pod 的日志"

        success, output = K8sLogTools.get_pod_logs(
            k8s_client,
            pod_name=pod_name,
            namespace=namespace,
            lines=lines,
            keyword=keyword,
            container=container,
        )

        if not success:
            return f"[K8s 日志] {output}"

        max_lines = 200
        output_lines = output.split("\n")
        if len(output_lines) > max_lines:
            output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"

        ns_prefix = f"{namespace}/" if namespace != "default" else ""
        return f"[K8s 日志] ({ns_prefix}{pod_name}):\n\n{output}"
    except Exception as e:
        return f"[K8s 日志] 查询失败：{str(e)}"
    finally:
        k8s_client.close()


def handle_k8s_export(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 K8s 报告导出意图"""
    k8s_client, _, err = _get_k8s_client(config, auto_detect=True)
    if err:
        return err

    try:
        from ...tools.k8s.inspector import K8sInspector
        from ...tools.k8s.formatter import format_cluster_report
        from datetime import datetime

        namespace = entities.get("namespace")
        fmt = (entities.get("format") or "html").lower()

        success, report = K8sInspector.inspect_cluster(k8s_client, namespace)
        if not success:
            return "[K8s] 导出数据获取失败"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if fmt == "json":
            import json
            output_path = f"./k8s_report_{timestamp}.json"
            data = {
                "timestamp": report.timestamp,
                "cluster_type": report.cluster_type,
                "k8s_version": report.k8s_version,
                "score": report.score,
                "node_count": report.node_count,
                "pods_total": report.pods_total,
                "abnormal_pods": [
                    {"name": p.name, "namespace": p.namespace, "phase": p.phase, "issues": p.issues}
                    for p in report.abnormal_pods
                ],
                "issues": report.issues,
            }
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return f"[K8s] 报告已导出：{output_path}"
        else:
            output_path = f"./k8s_report_{timestamp}.md"
            text_report = format_cluster_report(report, namespace)
            with open(output_path, "w") as f:
                f.write(text_report)
            return f"[K8s] 报告已导出：{output_path}"
    except Exception as e:
        return f"[K8s] 导出失败：{str(e)}"
    finally:
        k8s_client.close()


def handle_k8s_config(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 K8s 配置意图"""
    candidates = []
    k3s_path = "/etc/rancher/k3s/k3s.yaml"
    std_path = str(Path.home() / ".kube/config")
    kubeadm_path = "/etc/kubernetes/admin.conf"

    if os.path.exists(k3s_path):
        candidates.append(("K3s", k3s_path))
    if os.path.exists(std_path):
        candidates.append(("K8s", std_path))
    if os.path.exists(kubeadm_path):
        candidates.append(("Kubeadm", kubeadm_path))

    if not candidates:
        return (
            "[K8s] 未检测到 Kubeconfig 文件\n\n"
            "请手动指定 kubeconfig 路径，例如：\n"
            "  keeper config set --k8s-kubeconfig /path/to/kubeconfig"
        )

    if len(candidates) == 1:
        cluster_type, kubeconfig = candidates[0]
        config.k8s["kubeconfig"] = kubeconfig
        config.k8s["cluster_type"] = cluster_type.lower() if cluster_type != "Kubeadm" else "k8s"
        config.save()

        from ...tools.k8s.client import K8sClient, K8sClusterConfig
        k8s_cfg = K8sClusterConfig(
            kubeconfig_path=kubeconfig,
            cluster_type=config.k8s["cluster_type"],
        )
        k8s_client = K8sClient(k8s_cfg)
        success, msg = k8s_client.connect()
        k8s_client.close()

        if success:
            return (
                f"[K8s] 已自动配置并连接成功\n\n"
                f"  集群类型：{config.k8s['cluster_type']}\n"
                f"  kubeconfig：{kubeconfig}\n"
                f"  集群信息：{msg}\n\n"
                f"现在可以说'检查 K8s 集群'了。"
            )
        else:
            return f"[K8s] kubeconfig 已配置但连接失败：{msg}"

    # 多个候选，需要用户选择
    from ..agent import PendingTask
    options = "\n".join(f"  {i+1}. {t}: {p}" for i, (t, p) in enumerate(candidates))
    agent_ref._pending_k8s_candidates = ",".join(f"{t}:{p}" for t, p in candidates)
    agent_ref.pending_task = PendingTask(
        task_type="k8s_config",
        message=(
            f"[K8s] 检测到多个 Kubeconfig 文件：\n{options}\n\n"
            f"请问使用哪一个？请回复编号。"
        ),
        package="k8s_config_options",
        host=",".join(f"{t}:{p}" for t, p in candidates),
    )
    return agent_ref.pending_task.message


def handle_k8s_ops(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 K8s 深度操作意图"""
    k8s_client, _, err = _get_k8s_client(config, auto_detect=True)
    if err:
        return err

    try:
        action = entities.get("action", "").lower()
        namespace = entities.get("namespace") or "default"

        # exec 直接执行
        if action == "exec":
            from ...tools.k8s.ops import K8sOps
            pod_name = entities.get("pod_name")
            command = entities.get("pod_command") or "ls /"
            if not pod_name:
                return "[K8s] 请指定 Pod 名称"
            success, output = K8sOps.exec_in_pod(
                k8s_client, pod_name=pod_name, namespace=namespace, command=command,
            )
            if not success:
                return f"[K8s] {output}"
            return f"[K8s Exec] ({namespace}/{pod_name}) $ {command}\n{output}"

        # restart/scale/rollback 需要二次确认
        if action in ("restart", "scale", "rollback"):
            from ..agent import PendingTask
            deployment = entities.get("deployment")
            if not deployment:
                return "[K8s] 请指定 Deployment 名称"

            action_desc = {"restart": "重启", "scale": "扩缩容", "rollback": "回滚"}[action]
            replicas = entities.get("replicas")

            detail = ""
            if action == "scale" and replicas:
                detail = f" (目标副本数: {replicas})"

            agent_ref.pending_task = PendingTask(
                task_type="k8s_ops",
                package=action,
                host=deployment,
                message=(
                    f"[K8s] 确认{action_desc}: {namespace}/{deployment}{detail}\n\n"
                    f"此操作会影响线上服务，输入 'yes' 或 '确认' 执行。"
                ),
            )
            if replicas:
                agent_ref._pending_k8s_replicas = replicas
            return agent_ref.pending_task.message

        # 默认列出工作负载状态
        from ...tools.k8s.inspector import K8sInspector

        workloads = K8sInspector._check_workloads(k8s_client, namespace)
        if not workloads:
            return f"[K8s] 命名空间 '{namespace}' 中未找到工作负载"

        lines = [f"[K8s] 工作负载列表 ({namespace}):"]
        lines.append("━" * 70)
        for w in workloads:
            icon = "✓" if not w.issues else "✗"
            lines.append(f"  {icon} {w.kind}/{w.name} - {w.ready}/{w.desired} ready")
            if w.issues:
                lines.append(f"    问题: {'; '.join(w.issues)}")
        return "\n".join(lines)

    except Exception as e:
        return f"[K8s] 操作失败：{str(e)}"
    finally:
        k8s_client.close()
