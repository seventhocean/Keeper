"""SSL/TLS 证书监控工具"""
import os
import ssl
import socket
import subprocess
import tempfile
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class CertInfo:
    """证书信息"""
    path: str               # 证书路径（文件）或域名（远程）
    source: str             # 来源: file, domain, k8s
    subject: str            # 证书主体
    issuer: str             # 颁发者
    not_before: str         # 生效时间
    not_after: str          # 过期时间
    days_left: int          # 剩余天数
    status: str             # valid, expiring_soon, expired
    domains: List[str]      # SAN 域名列表


# 常见证书路径
CERT_PATHS = [
    "/etc/letsencrypt/live",
    "/etc/letsencrypt/archive",
    "/etc/ssl/certs",
    "/etc/nginx/ssl",
    "/etc/nginx/certs",
    "/etc/apache2/ssl",
    "/etc/apache2/certs",
    "/etc/pki/tls/certs",
    "/etc/haproxy/certs",
    "/etc/traefik/certs",
    "/opt/certs",
    "/root/.acme.sh",
    "/var/lib/rancher/k3s/server/tls",
    "/var/lib/rancher/k3s/agent/client-ca.crt",
]


class CertMonitor:
    """SSL/TLS 证书监控"""

    EXPIRING_SOON_DAYS = 30
    EXPIRING_WARNING_DAYS = 60

    @classmethod
    def scan_local_certs(cls, extra_paths: Optional[List[str]] = None) -> List[CertInfo]:
        """扫描本地文件系统中的证书

        Args:
            extra_paths: 额外扫描路径

        Returns:
            证书信息列表
        """
        all_paths = CERT_PATHS + (extra_paths or [])
        certs = []

        for base_path in all_paths:
            if not Path(base_path).exists():
                continue

            # 查找 .pem, .crt, .cer 文件
            for ext in ("*.pem", "*.crt", "*.cer"):
                for cert_file in Path(base_path).rglob(ext):
                    if not cert_file.is_file():
                        continue

                    # 跳过 CA 证书和系统证书
                    if "/usr/share/ca-certificates" in str(cert_file):
                        continue

                    info = cls._read_cert_file(str(cert_file))
                    if info:
                        certs.append(info)

        return certs

    @classmethod
    def _read_cert_file(cls, path: str) -> Optional[CertInfo]:
        """读取单个证书文件"""
        try:
            with open(path, "r") as f:
                content = f.read()

            # 检查是否是 PEM 格式
            if "-----BEGIN CERTIFICATE-----" not in content:
                return None

            # 提取证书（可能多个）
            cert_blocks = re.findall(
                r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                content, re.DOTALL,
            )

            certs_info = []
            now = datetime.now(timezone.utc)

            for cert_pem in cert_blocks:
                # 使用 openssl 解析
                with tempfile.NamedTemporaryFile(suffix=".pem", mode="w", delete=False) as f:
                    f.write(cert_pem)
                    tmp_path = f.name

                try:
                    # 获取主题
                    subj_result = subprocess.run(
                        ["openssl", "x509", "-in", tmp_path, "-noout", "-subject"],
                        capture_output=True, text=True, timeout=5,
                    )
                    subject = subj_result.stdout.strip().replace("subject=", "").strip()

                    # 获取颁发者
                    issuer_result = subprocess.run(
                        ["openssl", "x509", "-in", tmp_path, "-noout", "-issuer"],
                        capture_output=True, text=True, timeout=5,
                    )
                    issuer = issuer_result.stdout.strip().replace("issuer=", "").strip()

                    # 获取过期时间
                    end_result = subprocess.run(
                        ["openssl", "x509", "-in", tmp_path, "-noout", "-enddate"],
                        capture_output=True, text=True, timeout=5,
                    )
                    end_date_str = end_result.stdout.strip().replace("notAfter=", "").strip()

                    # 获取生效时间
                    start_result = subprocess.run(
                        ["openssl", "x509", "-in", tmp_path, "-noout", "-startdate"],
                        capture_output=True, text=True, timeout=5,
                    )
                    start_date_str = start_result.stdout.strip().replace("notBefore=", "").strip()

                    # 获取 SAN 域名
                    san_result = subprocess.run(
                        ["openssl", "x509", "-in", tmp_path, "-noout", "-text"],
                        capture_output=True, text=True, timeout=5,
                    )
                    domains = []
                    san_match = re.search(r"DNS:([^\n]+)", san_result.stdout)
                    if san_match:
                        domains = [d.strip() for d in san_match.group(1).split(",")]

                    # 解析日期
                    for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                        try:
                            end_date = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        continue

                    for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                        try:
                            start_date = datetime.strptime(start_date_str, fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        continue

                    days_left = (end_date - now).days

                    if days_left < 0:
                        status = "expired"
                    elif days_left < cls.EXPIRING_SOON_DAYS:
                        status = "expiring_soon"
                    else:
                        status = "valid"

                    certs_info.append(CertInfo(
                        path=path,
                        source="file",
                        subject=subject,
                        issuer=issuer,
                        not_before=start_date.strftime("%Y-%m-%d"),
                        not_after=end_date.strftime("%Y-%m-%d"),
                        days_left=days_left,
                        status=status,
                        domains=domains,
                    ))

                finally:
                    os.unlink(tmp_path)

            # 如果有多个证书，返回最后一个（通常是 leaf cert）
            if certs_info:
                # 优先返回剩余天数最短的
                certs_info.sort(key=lambda c: c.days_left)
                return certs_info[0]

        except Exception:
            pass

        return None

    @classmethod
    def check_domain_cert(cls, domain: str, port: int = 443) -> Optional[CertInfo]:
        """检查域名证书

        Args:
            domain: 域名
            port: 端口

        Returns:
            证书信息
        """
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with ctx.wrap_socket(socket.socket(socket.AF_INET), server_hostname=domain) as s:
                s.settimeout(10)
                s.connect((domain, port))
                cert = s.getpeercert(binary_form=True)

            if not cert:
                return None

            # 解析证书
            der_to_pem = ssl.DER_cert_to_PEM_cert(cert)
            with tempfile.NamedTemporaryFile(suffix=".pem", mode="w", delete=False) as f:
                f.write(der_to_pem)
                tmp_path = f.name

            try:
                subj_result = subprocess.run(
                    ["openssl", "x509", "-in", tmp_path, "-noout", "-subject"],
                    capture_output=True, text=True, timeout=5,
                )
                subject = subj_result.stdout.strip().replace("subject=", "").strip()

                issuer_result = subprocess.run(
                    ["openssl", "x509", "-in", tmp_path, "-noout", "-issuer"],
                    capture_output=True, text=True, timeout=5,
                )
                issuer = issuer_result.stdout.strip().replace("issuer=", "").strip()

                end_result = subprocess.run(
                    ["openssl", "x509", "-in", tmp_path, "-noout", "-enddate"],
                    capture_output=True, text=True, timeout=5,
                )
                end_date_str = end_result.stdout.strip().replace("notAfter=", "").strip()

                start_result = subprocess.run(
                    ["openssl", "x509", "-in", tmp_path, "-noout", "-startdate"],
                    capture_output=True, text=True, timeout=5,
                )
                start_date_str = start_result.stdout.strip().replace("notBefore=", "").strip()

                san_result = subprocess.run(
                    ["openssl", "x509", "-in", tmp_path, "-noout", "-text"],
                    capture_output=True, text=True, timeout=5,
                )
                domains = []
                san_match = re.search(r"DNS:([^\n]+)", san_result.stdout)
                if san_match:
                    domains = [d.strip() for d in san_match.group(1).split(",")]

                for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                    try:
                        end_date = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    return None

                for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                    try:
                        start_date = datetime.strptime(start_date_str, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    return None

                now = datetime.now(timezone.utc)
                days_left = (end_date - now).days
                status = "expired" if days_left < 0 else ("expiring_soon" if days_left < cls.EXPIRING_SOON_DAYS else "valid")

                return CertInfo(
                    path=domain,
                    source="domain",
                    subject=subject,
                    issuer=issuer,
                    not_before=start_date.strftime("%Y-%m-%d"),
                    not_after=end_date.strftime("%Y-%m-%d"),
                    days_left=days_left,
                    status=status,
                    domains=domains,
                )

            finally:
                os.unlink(tmp_path)

        except Exception:
            return None

    @classmethod
    def check_k8s_certs(cls, k8s_client) -> List[CertInfo]:
        """检查 K8s 集群中的 TLS 证书

        检查：
        1. Ingress TLS
        2. Secret 中的 TLS 证书
        3. K3s 系统组件证书
        """
        certs = []

        try:
            # 1. 检查 Secret 中的 TLS 证书
            from kubernetes.client.rest import ApiException

            secrets = k8s_client.core_v1.list_secret_for_all_namespaces()
            now = datetime.now(timezone.utc)

            for sec in secrets.items:
                if sec.type != "kubernetes.io/tls":
                    continue

                cert_data = sec.data.get("tls.crt", "")
                if not cert_data:
                    continue

                try:
                    import base64
                    cert_pem = base64.b64decode(cert_data)
                    pem_str = cert_pem.decode("utf-8")

                    with tempfile.NamedTemporaryFile(suffix=".pem", mode="w", delete=False) as f:
                        f.write(pem_str)
                        tmp_path = f.name

                    try:
                        end_result = subprocess.run(
                            ["openssl", "x509", "-in", tmp_path, "-noout", "-enddate"],
                            capture_output=True, text=True, timeout=5,
                        )
                        end_date_str = end_result.stdout.strip().replace("notAfter=", "").strip()

                        subj_result = subprocess.run(
                            ["openssl", "x509", "-in", tmp_path, "-noout", "-subject"],
                            capture_output=True, text=True, timeout=5,
                        )
                        subject = subj_result.stdout.strip().replace("subject=", "").strip()

                        issuer_result = subprocess.run(
                            ["openssl", "x509", "-in", tmp_path, "-noout", "-issuer"],
                            capture_output=True, text=True, timeout=5,
                        )
                        issuer = issuer_result.stdout.strip().replace("issuer=", "").strip()

                        san_result = subprocess.run(
                            ["openssl", "x509", "-in", tmp_path, "-noout", "-text"],
                            capture_output=True, text=True, timeout=5,
                        )
                        domains = []
                        san_match = re.search(r"DNS:([^\n]+)", san_result.stdout)
                        if san_match:
                            domains = [d.strip() for d in san_match.group(1).split(",")]

                        for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                            try:
                                end_date = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                                break
                            except ValueError:
                                continue
                        else:
                            continue

                        days_left = (end_date - now).days
                        status = "expired" if days_left < 0 else ("expiring_soon" if days_left < cls.EXPIRING_SOON_DAYS else "valid")

                        certs.append(CertInfo(
                            path=f"{sec.metadata.namespace}/{sec.metadata.name}",
                            source="k8s",
                            subject=subject,
                            issuer=issuer,
                            not_before="",
                            not_after=end_date.strftime("%Y-%m-%d"),
                            days_left=days_left,
                            status=status,
                            domains=domains,
                        ))

                    finally:
                        os.unlink(tmp_path)

                except Exception:
                    continue

            # 2. 检查 Ingress TLS
            try:
                ingresses = k8s_client.networking_v1.list_ingress_for_all_namespaces()
                for ing in ingresses.items:
                    if ing.spec and ing.spec.tls:
                        for tls_entry in ing.spec.tls:
                            if tls_entry.secret_name:
                                # 这个 Secret 已在上面对 Secret 的扫描中检查过了
                                # 只需标记一下关联的 Ingress
                                for cert in certs:
                                    if cert.path.endswith(f"/{tls_entry.secret_name}"):
                                        cert.path = f"Ingress/{ing.metadata.namespace}/{ing.metadata.name} -> {tls_entry.secret_name}"
            except Exception:
                pass

        except Exception:
            pass

        return certs

    @classmethod
    def detect_domains_from_config(cls) -> List[str]:
        """从系统配置中检测可能的域名"""
        domains = set()

        # 从 Nginx 配置中提取
        nginx_paths = ["/etc/nginx/conf.d", "/etc/nginx/sites-enabled", "/etc/nginx/sites-available"]
        for conf_dir in nginx_paths:
            if Path(conf_dir).exists():
                for conf_file in Path(conf_dir).rglob("*.conf"):
                    try:
                        with open(conf_file) as f:
                            content = f.read()
                        # 提取 server_name
                        for match in re.finditer(r"server_name\s+([^;]+);", content):
                            for d in match.group(1).split():
                                if d != "_" and "." in d:
                                    domains.add(d)
                    except Exception:
                        pass

        # 从 hosts 文件提取（跳过 IP 和本地域名）
        try:
            with open("/etc/hosts") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    for part in parts[1:]:
                        if part.startswith("spring") or part.startswith("autumn") or part.startswith("summer") or part.startswith("winter"):
                            continue
                        if "." in part and not part.startswith("127."):
                            domains.add(part)
        except Exception:
            pass

        return list(domains)


def format_cert_report(
    local_certs: List[CertInfo],
    k8s_certs: List[CertInfo],
    domain_certs: Optional[List[CertInfo]] = None,
) -> str:
    """格式化证书报告"""
    all_certs = local_certs + k8s_certs + (domain_certs or [])

    if not all_certs:
        return "[SSL/TLS] 未发现证书"

    # 按状态排序：expired > expiring_soon > valid
    status_order = {"expired": 0, "expiring_soon": 1, "valid": 2}
    all_certs.sort(key=lambda c: (status_order.get(c.status, 3), c.days_left))

    lines = ["[SSL/TLS 证书监控]", "=" * 80]

    # 统计
    expired = [c for c in all_certs if c.status == "expired"]
    expiring = [c for c in all_certs if c.status == "expiring_soon"]
    valid = [c for c in all_certs if c.status == "valid"]

    lines.append(f"  总计: {len(all_certs)} 个证书")
    if expired:
        lines.append(f"  🔴 已过期: {len(expired)} 个")
    if expiring:
        lines.append(f"  🟡 即将过期（{CertMonitor.EXPIRING_SOON_DAYS}天内）: {len(expiring)} 个")
    lines.append(f"  🟢 正常: {len(valid)} 个")

    # 问题证书详情
    problem_certs = expired + expiring
    if problem_certs:
        lines.append("")
        lines.append("━" * 80)
        lines.append("问题证书:")
        lines.append("━" * 80)

        for c in problem_certs:
            icon = "🔴" if c.status == "expired" else "🟡"
            days = f"已过 {abs(c.days_left)} 天" if c.status == "expired" else f"剩余 {c.days_left} 天"
            lines.append(f"\n  {icon} [{c.source}] {c.path}")
            lines.append(f"      状态: {days}")
            lines.append(f"      主体: {c.subject}")
            lines.append(f"      颁发者: {c.issuer}")
            lines.append(f"      过期时间: {c.not_after}")
            if c.domains:
                lines.append(f"      域名: {', '.join(c.domains[:5])}")

    # 正常证书摘要
    if valid:
        lines.append("")
        lines.append("━" * 80)
        lines.append("正常证书（前 10 个）:")
        lines.append("━" * 80)
        for c in valid[:10]:
            lines.append(f"  🟢 [{c.source}] {c.path} - 剩余 {c.days_left} 天 ({c.not_after})")
        if len(valid) > 10:
            lines.append(f"  ... 还有 {len(valid) - 10} 个正常证书")

    lines.append("=" * 80)
    return "\n".join(lines)
