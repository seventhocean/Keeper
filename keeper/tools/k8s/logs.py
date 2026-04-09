"""K8s Pod 日志查询工具"""
from typing import Optional, List, Tuple

from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

from .client import K8sClient


class K8sLogTools:
    """K8s 日志查询工具"""

    @staticmethod
    def get_pod_logs(
        k8s_client: K8sClient,
        pod_name: str,
        namespace: str = "default",
        lines: int = 100,
        keyword: Optional[str] = None,
        container: Optional[str] = None,
        previous: bool = False,
    ) -> Tuple[bool, str]:
        """获取 Pod 日志

        Args:
            k8s_client: 已连接的 K8s 客户端
            pod_name: Pod 名称 (支持模糊匹配)
            namespace: Namespace
            lines: 日志行数
            keyword: 关键词过滤
            container: 容器名称 (多容器 Pod 需要指定)
            previous: 获取上一个实例的日志 (容器重启后)

        Returns:
            (success, output)
        """
        try:
            # 模糊匹配 Pod
            pods = k8s_client.core_v1.list_namespaced_pod(
                namespace,
                field_selector=f"metadata.name={pod_name}",
            )

            if not pods.items:
                # 尝试前缀匹配
                pods = k8s_client.core_v1.list_namespaced_pod(namespace)
                matched = [p for p in pods.items if p.metadata.name.startswith(pod_name)]
                if len(matched) == 1:
                    pods.items = matched
                elif len(matched) > 1:
                    names = [p.metadata.name for p in matched[:10]]
                    return False, f"匹配到多个 Pod:\n  " + "\n  ".join(names) + "\n\n请指定更精确的 Pod 名称"
                else:
                    return False, f"在 namespace '{namespace}' 中未找到 Pod: {pod_name}"

            pod = pods.items[0]

            # 获取日志
            kwargs = {
                "tail_lines": lines,
                "previous": previous,
            }
            if container:
                kwargs["container"] = container

            logs = k8s_client.core_v1.read_namespaced_pod_log(
                pod.metadata.name,
                pod.metadata.namespace or namespace,
                **kwargs,
            )

            if not logs:
                return False, f"Pod {pod.metadata.name} 无日志输出"

            output = logs

            # 关键词过滤
            if keyword:
                filtered = [
                    line for line in output.split("\n")
                    if keyword.lower() in line.lower()
                ]
                output = "\n".join(filtered)

            if not output.strip():
                return False, f"Pod {pod.metadata.name} 中未找到匹配关键词 '{keyword}' 的日志"

            return True, output

        except ApiException as e:
            return False, f"获取日志失败：{e.reason}"
        except Exception as e:
            return False, f"获取日志失败：{str(e)}"

    @staticmethod
    def exec_in_pod(
        k8s_client: K8sClient,
        pod_name: str,
        namespace: str = "default",
        command: str = "ls /",
        container: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """在 Pod 中执行命令

        Args:
            k8s_client: 已连接的 K8s 客户端
            pod_name: Pod 名称
            namespace: Namespace
            command: 要执行的命令
            container: 容器名称

        Returns:
            (success, output)
        """
        try:
            pods = k8s_client.core_v1.list_namespaced_pod(
                namespace,
                field_selector=f"metadata.name={pod_name}",
            )

            if not pods.items:
                return False, f"未找到 Pod: {pod_name}"

            pod = pods.items[0]

            exec_command = ["/bin/sh", "-c", command]

            resp = stream(
                k8s_client.core_v1.connect_get_namespaced_pod_exec,
                pod.metadata.name,
                pod.metadata.namespace or namespace,
                command=exec_command,
                container=container,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            return True, resp

        except ApiException as e:
            return False, f"执行命令失败：{e.reason}"
        except Exception as e:
            return False, f"执行命令失败：{str(e)}"
