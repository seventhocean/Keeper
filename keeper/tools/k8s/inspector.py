"""K8s 集群巡检工具"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from kubernetes.client.rest import ApiException

from .client import K8sClient


@dataclass
class K8sNodeStatus:
    """K8s 节点状态"""
    name: str
    status: str  # Ready/NotReady
    roles: List[str]
    k8s_version: str
    cpu_capacity: str
    memory_capacity: str
    pods_count: int
    conditions: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class K8sPodStatus:
    """K8s Pod 状态"""
    name: str
    namespace: str
    status: str
    phase: str
    restarts: int
    node: str
    ip: str
    age: str
    issues: List[str] = field(default_factory=list)


@dataclass
class K8sWorkloadStatus:
    """K8s 工作负载状态 (Deployment/StatefulSet/DaemonSet)"""
    kind: str
    name: str
    namespace: str
    desired: int
    current: int
    ready: int
    available: int
    updated: int = 0
    issues: List[str] = field(default_factory=list)


@dataclass
class K8sStorageStatus:
    """K8s 存储状态"""
    kind: str  # PVC/PV
    name: str
    namespace: str
    storage_class: str
    capacity: str
    status: str  # Bound/Pending/Lost
    issues: List[str] = field(default_factory=list)


@dataclass
class K8sServiceStatus:
    """K8s Service 状态"""
    name: str
    namespace: str
    type: str
    cluster_ip: str
    external_ip: str
    ports: List[str]
    endpoints_count: int


@dataclass
class K8sEventSummary:
    """K8s 事件摘要"""
    namespace: str
    count: int
    reason: str
    message: str
    involved_object: str
    first_seen: str
    last_seen: str
    severity: str  # Warning/Normal


@dataclass
class K8sClusterReport:
    """K8s 集群巡检报告"""
    timestamp: str
    cluster_type: str
    k8s_version: str
    node_count: int
    nodes: List[K8sNodeStatus]
    pods_total: int
    abnormal_pods: List[K8sPodStatus]
    workloads: List[K8sWorkloadStatus]
    services: List[K8sServiceStatus]
    storage: List[K8sStorageStatus]
    events_warnings: List[K8sEventSummary]
    namespaces: List[str]
    resource_quotas: List[Dict[str, Any]]
    score: int = 100
    issues: List[str] = field(default_factory=list)


class K8sInspector:
    """K8s 集群巡检工具"""

    @staticmethod
    def inspect_cluster(k8s_client: K8sClient, namespace: Optional[str] = None) -> Tuple[bool, K8sClusterReport]:
        """一键巡检 K8s 集群

        Args:
            k8s_client: 已连接的 K8s 客户端
            namespace: 限定 namespace，None 表示全部

        Returns:
            (success, report)
        """
        try:
            report = K8sClusterReport(
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cluster_type=k8s_client.cluster_info.get("cluster_type", "unknown"),
                k8s_version=k8s_client.cluster_info.get("git_version", "unknown"),
                node_count=int(k8s_client.cluster_info.get("node_count", 0)),
                nodes=[],
                pods_total=0,
                abnormal_pods=[],
                workloads=[],
                services=[],
                storage=[],
                events_warnings=[],
                namespaces=[],
                resource_quotas=[],
            )

            # 1. 节点检查
            report.nodes = K8sInspector._check_nodes(k8s_client)
            for node in report.nodes:
                if node.status != "Ready":
                    report.issues.append(f"节点 {node.name} 状态异常: {node.status}")

            # 2. Pod 检查
            all_pods = K8sInspector._check_pods(k8s_client, namespace)
            report.pods_total = len(all_pods)
            report.abnormal_pods = [p for p in all_pods if p.issues]

            # 3. 工作负载检查
            report.workloads = K8sInspector._check_workloads(k8s_client, namespace)
            for w in report.workloads:
                if w.issues:
                    report.issues.extend([f"[{w.kind}/{w.name}] {issue}" for issue in w.issues])

            # 4. Service 检查
            report.services = K8sInspector._check_services(k8s_client, namespace)

            # 5. 存储检查
            report.storage = K8sInspector._check_storage(k8s_client, namespace)

            # 6. 事件警告
            report.events_warnings = K8sInspector._check_events(k8s_client, namespace)

            # 7. Namespace 列表
            report.namespaces = K8sInspector._list_namespaces(k8s_client)

            # 8. ResourceQuota 检查
            report.resource_quotas = K8sInspector._check_resource_quotas(k8s_client, namespace)

            # 9. 计算健康评分
            report.score = K8sInspector._calculate_score(report)

            return True, report

        except ApiException as e:
            return False, K8sClusterReport(
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cluster_type="unknown",
                k8s_version="unknown",
                node_count=0,
                nodes=[],
                pods_total=0,
                abnormal_pods=[],
                workloads=[],
                services=[],
                storage=[],
                events_warnings=[],
                namespaces=[],
                resource_quotas=[],
                issues=[f"API 错误：{e.reason}"],
            )
        except Exception as e:
            return False, K8sClusterReport(
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cluster_type="unknown",
                k8s_version="unknown",
                node_count=0,
                nodes=[],
                pods_total=0,
                abnormal_pods=[],
                workloads=[],
                services=[],
                storage=[],
                events_warnings=[],
                namespaces=[],
                resource_quotas=[],
                issues=[f"巡检失败：{str(e)}"],
            )

    @staticmethod
    def _check_nodes(k8s_client: K8sClient) -> List[K8sNodeStatus]:
        """检查 Node 状态"""
        nodes = k8s_client.core_v1.list_node()
        results = []

        for node in nodes.items:
            # 状态条件
            conditions = []
            status_str = "NotReady"
            for cond in node.status.conditions:
                conditions.append({"type": cond.type, "status": cond.status, "reason": cond.reason or ""})
                if cond.type == "Ready" and cond.status == "True":
                    status_str = "Ready"

            # 角色标签
            roles = []
            if node.metadata.labels:
                for label in node.metadata.labels:
                    if label.startswith("node-role.kubernetes.io/"):
                        role = label.split("/")[-1]
                        roles.append(role)
            if not roles:
                roles = ["<none>"]

            # 容量
            cpu = node.status.capacity.get("cpu", "unknown")
            memory = node.status.capacity.get("memory", "unknown")

            # Pod 计数
            pods_count = 0
            try:
                all_pods = k8s_client.core_v1.list_pod_for_all_namespaces(
                    field_selector=f"spec.nodeName={node.metadata.name}"
                )
                pods_count = len(all_pods.items)
            except Exception:
                pass

            results.append(K8sNodeStatus(
                name=node.metadata.name,
                status=status_str,
                roles=roles,
                k8s_version=node.status.node_info.kubelet_version or "unknown",
                cpu_capacity=cpu,
                memory_capacity=memory,
                pods_count=pods_count,
                conditions=conditions,
            ))

        return results

    @staticmethod
    def _check_pods(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[K8sPodStatus]:
        """检查 Pod 状态并检测异常"""
        if namespace:
            pods = k8s_client.core_v1.list_namespaced_pod(namespace)
        else:
            pods = k8s_client.core_v1.list_pod_for_all_namespaces()

        results = []
        for pod in pods.items:
            phase = pod.status.phase or "Unknown"
            restarts = sum(
                cs.restart_count
                for cs in (pod.status.container_statuses or [])
            )

            # 计算运行时间
            age = "unknown"
            if pod.metadata.creation_timestamp:
                from datetime import timezone
                created = pod.metadata.creation_timestamp
                now = datetime.now(timezone.utc)
                delta = now - created
                if delta.days > 0:
                    age = f"{delta.days}d"
                else:
                    hours = delta.seconds // 3600
                    mins = (delta.seconds % 3600) // 60
                    age = f"{hours}h{mins}m" if hours > 0 else f"{mins}m"

            # 异常检测
            issues = []
            if phase == "Pending":
                issues.append("Pod 处于 Pending 状态")
            elif phase == "Failed":
                issues.append("Pod 执行失败")
            elif phase == "Unknown":
                issues.append("Pod 状态未知")

            if restarts > 0:
                issues.append(f"容器重启 {restarts} 次")

            # 检查容器状态
            for cs in (pod.status.container_statuses or []):
                if cs.state.waiting:
                    reason = cs.state.waiting.reason
                    if reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"):
                        issues.append(f"容器 {cs.name}: {reason}")
                if cs.state.terminated:
                    if cs.state.terminated.reason != "Completed":
                        issues.append(f"容器 {cs.name}: 已终止 ({cs.state.terminated.reason})")

            # 检查 OOMKilled
            for cs in (pod.status.container_statuses or []):
                if cs.last_state and cs.last_state.terminated:
                    if cs.last_state.terminated.reason == "OOMKilled":
                        issues.append(f"容器 {cs.name}: 曾发生 OOMKilled")

            results.append(K8sPodStatus(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace or "default",
                status=phase,
                phase=phase,
                restarts=restarts,
                node=pod.spec.node_name or "unscheduled",
                ip=pod.status.pod_ip or "",
                age=age,
                issues=issues,
            ))

        return results

    @staticmethod
    def _check_workloads(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[K8sWorkloadStatus]:
        """检查 Deployment/StatefulSet/DaemonSet 状态"""
        results = []

        # Deployments
        try:
            if namespace:
                deploys = k8s_client.apps_v1.list_namespaced_deployment(namespace)
            else:
                deploys = k8s_client.apps_v1.list_deployment_for_all_namespaces()

            for d in deploys.items:
                issues = []
                spec_replicas = d.spec.replicas or 0
                ready_replicas = d.status.ready_replicas or 0
                available_replicas = d.status.available_replicas or 0
                updated_replicas = d.status.updated_replicas or 0

                if ready_replicas < spec_replicas:
                    issues.append(f"副本不就绪: {ready_replicas}/{spec_replicas}")
                if updated_replicas < spec_replicas:
                    issues.append(f"更新未完成: {updated_replicas}/{spec_replicas}")

                # 检查条件
                if d.status.conditions:
                    for cond in d.status.conditions:
                        if cond.type == "Available" and cond.status == "False":
                            issues.append(f"不可用: {cond.message or cond.reason}")
                        if cond.type == "Progressing" and cond.status == "False":
                            issues.append(f"进度停滞: {cond.message or cond.reason}")

                results.append(K8sWorkloadStatus(
                    kind="Deployment",
                    name=d.metadata.name,
                    namespace=d.metadata.namespace or "default",
                    desired=spec_replicas,
                    current=d.status.replicas or 0,
                    ready=ready_replicas,
                    available=available_replicas,
                    updated=updated_replicas,
                    issues=issues,
                ))
        except Exception:
            pass

        # StatefulSets
        try:
            if namespace:
                ss = k8s_client.apps_v1.list_namespaced_stateful_set(namespace)
            else:
                ss = k8s_client.apps_v1.list_stateful_set_for_all_namespaces()

            for s in ss.items:
                issues = []
                spec_replicas = s.spec.replicas or 0
                ready_replicas = s.status.ready_replicas or 0

                if ready_replicas < spec_replicas:
                    issues.append(f"副本不就绪: {ready_replicas}/{spec_replicas}")

                results.append(K8sWorkloadStatus(
                    kind="StatefulSet",
                    name=s.metadata.name,
                    namespace=s.metadata.namespace or "default",
                    desired=spec_replicas,
                    current=s.status.replicas or 0,
                    ready=ready_replicas,
                    available=ready_replicas,
                    issues=issues,
                ))
        except Exception:
            pass

        # DaemonSets
        try:
            if namespace:
                ds = k8s_client.apps_v1.list_namespaced_daemon_set(namespace)
            else:
                ds = k8s_client.apps_v1.list_daemon_set_for_all_namespaces()

            for d in ds.items:
                issues = []
                desired = d.status.desired_number_scheduled
                current = d.status.current_number_scheduled

                if current < desired:
                    issues.append(f"调度不完整: {current}/{desired}")

                results.append(K8sWorkloadStatus(
                    kind="DaemonSet",
                    name=d.metadata.name,
                    namespace=d.metadata.namespace or "default",
                    desired=desired,
                    current=current,
                    ready=d.status.number_ready,
                    available=d.status.number_ready,
                    issues=issues,
                ))
        except Exception:
            pass

        return results

    @staticmethod
    def _check_services(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[K8sServiceStatus]:
        """检查 Service 状态"""
        results = []

        try:
            if namespace:
                svcs = k8s_client.core_v1.list_namespaced_service(namespace)
            else:
                svcs = k8s_client.core_v1.list_service_for_all_namespaces()

            for svc in svcs.items:
                svc_type = svc.spec.type or "ClusterIP"
                cluster_ip = svc.spec.cluster_ip or "None"

                # External IP
                external_ip = ""
                if svc.status.load_balancer and svc.status.load_balancer.ingress:
                    ingresses = [
                        i.ip or i.hostname
                        for i in svc.status.load_balancer.ingress
                    ]
                    external_ip = ",".join(ingresses)
                elif svc.spec.external_ips:
                    external_ip = ",".join(svc.spec.external_ips)

                # Ports
                ports = []
                for p in (svc.spec.ports or []):
                    port_str = str(p.port)
                    if p.target_port:
                        port_str += f"->{p.target_port}"
                    if p.protocol:
                        port_str += f"/{p.protocol}"
                    ports.append(port_str)

                # Endpoints 计数
                endpoints_count = 0
                try:
                    eps = k8s_client.core_v1.read_namespaced_endpoints(
                        svc.metadata.name, svc.metadata.namespace or "default"
                    )
                    if eps.subsets:
                        endpoints_count = sum(
                            len(s.addresses) for s in eps.subsets
                        )
                except Exception:
                    pass

                results.append(K8sServiceStatus(
                    name=svc.metadata.name,
                    namespace=svc.metadata.namespace or "default",
                    type=svc_type,
                    cluster_ip=cluster_ip,
                    external_ip=external_ip or "None",
                    ports=ports,
                    endpoints_count=endpoints_count,
                ))
        except Exception:
            pass

        return results

    @staticmethod
    def _check_storage(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[K8sStorageStatus]:
        """检查 PVC/PV 存储状态"""
        results = []

        # PVC
        try:
            if namespace:
                pvcs = k8s_client.core_v1.list_namespaced_persistent_volume_claim(namespace)
            else:
                pvcs = k8s_client.core_v1.list_persistent_volume_claim_for_all_namespaces()

            for pvc in pvcs.items:
                issues = []
                if pvc.status.phase == "Pending":
                    issues.append("PVC 待绑定")
                elif pvc.status.phase == "Lost":
                    issues.append("PV 绑定丢失")

                capacity = ""
                if pvc.spec.resources and "storage" in pvc.spec.resources.requests:
                    capacity = pvc.spec.resources.requests["storage"]

                results.append(K8sStorageStatus(
                    kind="PVC",
                    name=pvc.metadata.name,
                    namespace=pvc.metadata.namespace or "default",
                    storage_class=pvc.spec.storage_class_name or "default",
                    capacity=capacity,
                    status=pvc.status.phase or "Unknown",
                    issues=issues,
                ))
        except Exception:
            pass

        return results

    @staticmethod
    def _check_events(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[K8sEventSummary]:
        """检查集群 Warning 事件"""
        results = []

        try:
            if namespace:
                events = k8s_client.core_v1.list_namespaced_event(
                    namespace,
                    field_selector="reason!=Scheduled,type!=Normal",
                )
            else:
                events = k8s_client.core_v1.list_event_for_all_namespaces(
                    field_selector="reason!=Scheduled,type!=Normal",
                )

            # 按 reason 聚合去重
            seen = set()
            for event in sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or datetime.min.replace(tzinfo=None), reverse=True):
                key = f"{event.involved_object.kind}/{event.involved_object.name}:{event.reason}"
                if key in seen:
                    continue
                seen.add(key)

                # 时间
                ts = event.last_timestamp or event.event_time
                first_ts = event.first_timestamp or event.event_time
                fmt = "%Y-%m-%d %H:%M"
                last_seen = ts.strftime(fmt) if ts else "unknown"
                first_seen = first_ts.strftime(fmt) if first_ts else "unknown"

                results.append(K8sEventSummary(
                    namespace=event.metadata.namespace or "default",
                    count=event.count or 1,
                    reason=event.reason or "Unknown",
                    message=event.message or "",
                    involved_object=f"{event.involved_object.kind}/{event.involved_object.name}",
                    first_seen=first_seen,
                    last_seen=last_seen,
                    severity=event.type or "Warning",
                ))

                if len(results) >= 30:
                    break
        except Exception:
            pass

        return results

    @staticmethod
    def _list_namespaces(k8s_client: K8sClient) -> List[str]:
        """列出所有 Namespace"""
        try:
            namespaces = k8s_client.core_v1.list_namespace()
            return [ns.metadata.name for ns in namespaces.items]
        except Exception:
            return []

    @staticmethod
    def _check_resource_quotas(k8s_client: K8sClient, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """检查 ResourceQuota"""
        results = []

        try:
            if namespace:
                quotas = k8s_client.core_v1.list_namespaced_resource_quota(namespace)
            else:
                quotas = k8s_client.core_v1.list_resource_quota_for_all_namespaces()

            for q in quotas.items:
                if q.status:
                    results.append({
                        "namespace": q.metadata.namespace or "default",
                        "name": q.metadata.name,
                        "hard": dict(q.spec.hard or {}),
                        "used": dict(q.status.used or {}),
                    })
        except Exception:
            pass

        return results

    @staticmethod
    def _calculate_score(report: K8sClusterReport) -> int:
        """计算集群健康评分 (0-100)"""
        score = 100

        # 节点异常 (-15 each)
        for node in report.nodes:
            if node.status != "Ready":
                score -= 15

        # 异常 Pod (-1 each, max -20)
        pod_penalty = min(len(report.abnormal_pods), 20)
        score -= pod_penalty

        # 工作负载异常 (-5 each)
        for w in report.workloads:
            if w.issues:
                score -= 5 * len(w.issues)

        # 存储异常 (-5 each)
        for s in report.storage:
            if s.issues:
                score -= 5

        # Warning 事件 (-1 each, max -10)
        event_penalty = min(len(report.events_warnings), 10)
        score -= event_penalty

        return max(0, score)
