"""Docker Handler — Docker 容器管理相关处理"""
from typing import Dict, Any

from ...tools.docker_tools import (
    DockerTools, format_docker_containers, format_docker_images, format_docker_inspect,
)


def handle_docker(entities: Dict[str, Any], *, config, state, agent_ref) -> str:
    """处理 Docker 容器管理意图"""
    if not DockerTools.is_docker_available():
        return "[Docker] Docker 未安装或未运行\n\n请确保已安装 Docker 并启动服务。"

    action = entities.get("docker_action", "").lower()
    container_name = entities.get("host") or entities.get("container") or entities.get("query")
    raw_input = entities.get("_raw_input", "").lower()

    # 巡检
    if action in ("inspect", "check") or any(
        k in raw_input for k in ("巡检", "检查", "健康", "状态", "有什么问题")
    ):
        data = DockerTools.docker_inspect()
        return format_docker_inspect(data)

    # 列出容器
    if action in ("list", "stats", ""):
        containers = DockerTools.list_containers()
        stats = DockerTools.get_container_stats() if action in ("stats", "") else []
        return format_docker_containers(containers, stats)

    # 镜像列表
    if action == "images":
        images = DockerTools.list_images()
        return format_docker_images(images)

    # 清理镜像
    if action == "prune":
        from ..agent import PendingTask
        agent_ref.pending_task = PendingTask(
            task_type="docker_prune",
            message="[Docker] 确认清理无用的 Docker 镜像？此操作不可逆，输入 'yes' 确认。",
        )
        return agent_ref.pending_task.message

    # 容器日志
    if action == "logs" and container_name:
        success, output = DockerTools.get_container_logs(container_name, lines=100)
        if not success:
            return f"[Docker] {output}"
        max_lines = 200
        output_lines = output.split("\n")
        if len(output_lines) > max_lines:
            output = "\n".join(output_lines[:max_lines]) + f"\n\n... (截断，共 {len(output_lines)} 行)"
        return f"[Docker 日志] ({container_name}):\n{output}"

    # 容器详情
    if action == "inspect" and container_name:
        success, info = DockerTools.inspect_container(container_name)
        if not success:
            return f"[Docker] {info.get('error', '获取失败')}"
        lines = [f"[Docker] 容器详情: {info['name']}"]
        lines.append("━" * 50)
        lines.append(f"  状态: {info['state']}")
        lines.append(f"  镜像: {info['image']}")
        lines.append(f"  创建: {info['created']}")
        lines.append(f"  重启策略: {info['restart_policy']}")
        if info.get("memory_limit"):
            lines.append(f"  内存限制: {info['memory_limit'] / (1024**3):.1f} GB")
        if info.get("networks"):
            lines.append(f"  网络: {', '.join(info['networks'])}")
        if info.get("mounts"):
            lines.append(f"  挂载: {len(info['mounts'])} 个")
        return "\n".join(lines)

    # 容器操作 (restart/stop/start)
    if action in ("restart", "stop", "start") and container_name:
        if action == "restart":
            success, output = DockerTools.restart_container(container_name)
        elif action == "stop":
            success, output = DockerTools.stop_container(container_name)
        else:
            success, output = DockerTools.start_container(container_name)
        return f"[Docker] {output}"

    # 默认：列出容器
    containers = DockerTools.list_containers()
    stats = DockerTools.get_container_stats()
    return format_docker_containers(containers, stats)
