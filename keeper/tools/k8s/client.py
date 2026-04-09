"""K8s 客户端封装 - 基于 kubernetes Python SDK"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException


@dataclass
class K8sClusterConfig:
    """K8s 集群配置"""
    kubeconfig_path: str = ""
    context: str = ""
    cluster_type: str = "k8s"  # "k8s" 或 "k3s"
    timeout: int = 30


class K8sClient:
    """K8s API 客户端封装"""

    def __init__(self, cluster_config: Optional[K8sClusterConfig] = None):
        self.cluster_config = cluster_config or K8sClusterConfig()
        self.core_v1: client.CoreV1Api = None
        self.apps_v1: client.AppsV1Api = None
        self.storage_v1: client.StorageV1Api = None
        self.networking_v1: client.NetworkingV1Api = None
        self._api_client: client.ApiClient = None
        self.connected = False
        self.cluster_info: Dict[str, str] = {}

    # 常见 Kubeconfig 路径（含 K3s）
    KUBECONFIG_PATHS = [
        "/etc/rancher/k3s/k3s.yaml",          # K3s 默认
        str(Path.home() / ".kube/config"),     # 标准 K8s 默认
        "/etc/kubernetes/admin.conf",          # kubeadm
        "/root/.kube/config",
    ]

    def _find_kubeconfig(self) -> Optional[str]:
        """自动查找 kubeconfig 文件"""
        for path in self.KUBECONFIG_PATHS:
            if Path(path).exists():
                return path
        return None

    def connect(self) -> Tuple[bool, str]:
        """连接 K8s 集群

        Returns:
            (success, message)
        """
        try:
            kubeconfig = self.cluster_config.kubeconfig_path
            context = self.cluster_config.context or None

            if kubeconfig and Path(kubeconfig).exists():
                config.load_kube_config(
                    config_file=kubeconfig,
                    context=context,
                )
            else:
                # 自动查找 kubeconfig
                found = self._find_kubeconfig()
                if found:
                    config.load_kube_config(
                        config_file=found,
                        context=context,
                    )
                    # 保存自动发现的路径
                    self.cluster_config.kubeconfig_path = found
                else:
                    # 尝试 in-cluster config (Pod 内运行)
                    config.load_incluster_config()

            self._api_client = client.ApiClient()
            self._api_client.configuration.timeout = self.cluster_config.timeout

            # 初始化 API 客户端
            self.core_v1 = client.CoreV1Api(self._api_client)
            self.apps_v1 = client.AppsV1Api(self._api_client)
            self.storage_v1 = client.StorageV1Api(self._api_client)
            self.networking_v1 = client.NetworkingV1Api(self._api_client)

            # 健康检查
            success, msg = self.health_check()
            if success:
                self.connected = True
                return True, f"已连接到集群: {self.cluster_info.get('server', 'unknown')}"
            return False, msg

        except ConfigException as e:
            return False, f"kubeconfig 加载失败：{str(e)}"
        except Exception as e:
            return False, f"连接集群失败：{str(e)}"

    def health_check(self) -> Tuple[bool, str]:
        """集群连接健康检查

        Returns:
            (success, message)
        """
        try:
            version_api = client.VersionApi(self._api_client)
            version = version_api.get_code()

            nodes = self.core_v1.list_node()
            node_count = len(nodes.items)

            self.cluster_info = {
                "git_version": version.git_version,
                "platform": version.platform,
                "server": self._api_client.configuration.host,
                "node_count": str(node_count),
                "cluster_type": self._detect_cluster_type(),
            }

            return True, f"集群健康 - {version.git_version}, {node_count} 个节点"
        except ApiException as e:
            return False, f"API 调用失败：{e.reason}"
        except Exception as e:
            return False, f"健康检查失败：{str(e)}"

    def switch_context(self, context_name: str) -> Tuple[bool, str]:
        """切换 K8s 上下文

        Args:
            context_name: 上下文名称

        Returns:
            (success, message)
        """
        try:
            kubeconfig = self.cluster_config.kubeconfig_path or str(Path.home() / ".kube" / "config")
            config.load_kube_config(config_file=kubeconfig, context=context_name)

            self.cluster_config.context = context_name

            # 重新初始化 API 客户端
            self._api_client = client.ApiClient()
            self.core_v1 = client.CoreV1Api(self._api_client)
            self.apps_v1 = client.AppsV1Api(self._api_client)
            self.storage_v1 = client.StorageV1Api(self._api_client)
            self.networking_v1 = client.NetworkingV1Api(self._api_client)

            success, msg = self.health_check()
            if success:
                self.connected = True
                return True, f"已切换到上下文: {context_name}"
            return False, msg
        except ConfigException as e:
            return False, f"上下文不存在：{context_name}"
        except Exception as e:
            return False, f"切换上下文失败：{str(e)}"

    def list_contexts(self) -> Tuple[bool, List[Dict[str, str]]]:
        """列出所有可用的上下文

        Returns:
            (success, contexts)
        """
        try:
            contexts, active_context = config.list_kube_config_contexts(
                config_file=self.cluster_config.kubeconfig_path or None
            )
            result = []
            for ctx in contexts:
                result.append({
                    "name": ctx["name"],
                    "cluster": ctx["context"]["cluster"],
                    "user": ctx["context"]["user"],
                    "namespace": ctx["context"].get("namespace", "default"),
                    "is_active": ctx["name"] == active_context["name"],
                })
            return True, result
        except Exception as e:
            return False, [{"error": str(e)}]

    def _detect_cluster_type(self) -> str:
        """自动检测集群类型 (k8s/k3s)

        通过检查 kube-system namespace 中的组件来判断
        """
        try:
            # K3s 有 k3s 相关的 Deployment/ConfigMap
            deployments = self.apps_v1.list_namespaced_deployment("kube-system")
            for deploy in deployments.items:
                name = deploy.metadata.name
                if "k3s" in name.lower() or "local-path" in name.lower():
                    self.cluster_config.cluster_type = "k3s"
                    return "k3s"

            # K3s 的 apiserver 以 Deployment 运行
            ds_list = self.apps_v1.list_namespaced_daemon_set("kube-system")
            for ds in ds_list.items:
                if "k3s" in ds.metadata.name.lower():
                    self.cluster_config.cluster_type = "k3s"
                    return "k3s"

        except Exception:
            pass

        return "k8s"

    def close(self):
        """关闭连接"""
        if self._api_client:
            self._api_client.close()
            self._api_client = None
            self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
