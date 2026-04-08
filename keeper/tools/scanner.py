"""扫描工具 - Nmap 集成"""
import subprocess
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class PortInfo:
    """端口信息"""
    port: int
    protocol: str
    state: str
    service: str
    version: str = ""


@dataclass
class ScanResult:
    """扫描结果"""
    host: str
    timestamp: str
    open_ports: List[PortInfo] = field(default_factory=list)
    filtered_ports: List[PortInfo] = field(default_factory=list)
    closed_ports: int = 0
    os_guess: str = ""
    risks: List[Dict[str, str]] = field(default_factory=list)


class NmapNotInstalledError(Exception):
    """Nmap 未安装异常"""

    INSTALL_COMMANDS = {
        "ubuntu": "sudo apt-get install -y nmap",
        "debian": "sudo apt-get install -y nmap",
        "centos": "sudo yum install -y nmap",
        "rhel": "sudo yum install -y nmap",
        "fedora": "sudo dnf install -y nmap",
        "arch": "sudo pacman -S --noconfirm nmap",
        "macos": "brew install nmap",
    }

    @staticmethod
    def detect_os() -> str:
        """检测操作系统"""
        import platform
        system = platform.system().lower()

        if system == "linux":
            # 检测发行版
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                    if "ubuntu" in content:
                        return "ubuntu"
                    elif "debian" in content:
                        return "debian"
                    elif "centos" in content:
                        return "centos"
                    elif "fedora" in content:
                        return "fedora"
                    elif "arch" in content:
                        return "arch"
            except:
                pass
            return "linux"
        elif system == "darwin":
            return "macos"
        return "unknown"

    @classmethod
    def get_install_command(cls) -> str:
        """获取安装命令"""
        os_type = cls.detect_os()
        return cls.INSTALL_COMMANDS.get(os_type, "请使用包管理器安装 nmap")

    @classmethod
    def get_help_message(cls) -> str:
        """获取帮助信息"""
        os_type = cls.detect_os()
        cmd = cls.get_install_command()

        return f"""[扫描] 未找到 nmap 命令

安装建议:
  {cmd}

输入 "yes" 或 "y" 自动安装"""


class ScannerTools:
    """扫描工具类"""

    # 高危端口列表
    HIGH_RISK_PORTS = {
        21: "FTP - 明文传输，建议改用 SFTP",
        23: "Telnet - 明文传输，建议改用 SSH",
        25: "SMTP - 邮件服务，注意开放中继风险",
        3306: "MySQL - 数据库不应暴露给公网",
        6379: "Redis - 未授权访问风险",
        11211: "Memcached - 未授权访问风险",
        27017: "MongoDB - 未授权访问风险",
    }

    # 敏感端口
    SENSITIVE_PORTS = {
        22: "SSH - 确保使用密钥登录并禁用密码登录",
        3389: "RDP - 远程桌面，易受暴力破解",
        5432: "PostgreSQL - 数据库访问控制",
        1433: "MSSQL - 数据库访问控制",
    }

    @classmethod
    def scan_ports(
        cls,
        host: str,
        ports: Optional[str] = None,
        scan_type: str = "-sS",
        version_detect: bool = True,
    ) -> ScanResult:
        """扫描端口

        Args:
            host: 目标主机
            ports: 端口范围，如 "1-1000" 或 "22,80,443"
            scan_type: Nmap 扫描类型
            version_detect: 是否检测服务版本

        Returns:
            ScanResult: 扫描结果
        """
        # 构建 Nmap 命令
        cmd = ["nmap", scan_type]

        if ports:
            cmd.extend(["-p", ports])
        else:
            cmd.extend(["-p", "1-1000"])  # 默认扫描 1-1000

        if version_detect:
            cmd.append("-sV")

        cmd.append(host)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout + result.stderr
            return cls._parse_nmap_output(output, host)

        except subprocess.TimeoutExpired:
            raise TimeoutError(f"扫描 {host} 超时")
        except FileNotFoundError:
            raise NmapNotInstalledError()

    @classmethod
    def _parse_nmap_output(cls, output: str, host: str) -> ScanResult:
        """解析 Nmap 输出"""
        result = ScanResult(
            host=host,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 解析端口信息
        port_pattern = r"(\d+)/(\w+)\s+(\w+)\s+(\S+)(?:\s+(.*))?"
        for match in re.finditer(port_pattern, output):
            port = int(match.group(1))
            protocol = match.group(2)
            state = match.group(3)
            service = match.group(4)
            version = match.group(5) or ""

            port_info = PortInfo(
                port=port,
                protocol=protocol,
                state=state,
                service=service,
                version=version.strip() if version else "",
            )

            if state == "open":
                result.open_ports.append(port_info)
            elif state == "filtered":
                result.filtered_ports.append(port_info)
            elif state == "closed":
                result.closed_ports += 1

        # 分析风险
        result.risks = cls._analyze_risks(result.open_ports)

        return result

    @classmethod
    def _analyze_risks(cls, open_ports: List[PortInfo]) -> List[Dict[str, str]]:
        """分析开放端口的风险"""
        risks = []

        for port_info in open_ports:
            port = port_info.port

            # 高危端口
            if port in cls.HIGH_RISK_PORTS:
                risks.append({
                    "level": "high",
                    "port": port,
                    "service": port_info.service,
                    "description": cls.HIGH_RISK_PORTS[port],
                })

            # 敏感端口
            elif port in cls.SENSITIVE_PORTS:
                risks.append({
                    "level": "medium",
                    "port": port,
                    "service": port_info.service,
                    "description": cls.SENSITIVE_PORTS[port],
                })

        return risks

    @classmethod
    def quick_scan(cls, host: str) -> ScanResult:
        """快速扫描常用端口"""
        return cls.scan_ports(host, ports="22,80,443,3306,6379,8080")

    @classmethod
    def full_scan(cls, host: str) -> ScanResult:
        """全面扫描所有端口"""
        return cls.scan_ports(host, ports="1-65535", version_detect=True)


def format_scan_result(result: ScanResult) -> str:
    """格式化扫描结果"""
    lines = []
    lines.append(f"[扫描] {result.host} - {result.timestamp}")
    lines.append("━" * 50)

    # 开放端口
    lines.append(f"\n开放端口：{len(result.open_ports)} 个")
    if result.open_ports:
        for port in result.open_ports:
            version_info = f" ({port.version})" if port.version else ""
            lines.append(f"  {port.port}/{port.protocol}  {port.service}{version_info}")
    else:
        lines.append("  无")

    # 过滤端口
    if result.filtered_ports:
        lines.append(f"\n过滤端口：{len(result.filtered_ports)} 个")
        for port in result.filtered_ports[:5]:  # 只显示前 5 个
            lines.append(f"  {port.port}/{port.protocol}  {port.service}")

    # 风险项
    lines.append(f"\n风险检测：{len(result.risks)} 项")
    if result.risks:
        for risk in result.risks:
            level_icon = "🔴" if risk["level"] == "high" else "🟡"
            lines.append(f"  {level_icon} 端口 {risk['port']} ({risk['service']}): {risk['description']}")
    else:
        lines.append("  ✅ 未发现明显风险")

    return "\n".join(lines)
