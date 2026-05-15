# Keeper — 智能运维 Agent
# 多阶段构建，最小化镜像体积

# ─── Builder 阶段 ────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime 阶段 ────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="seventhocean"
LABEL description="Keeper - 智能运维 Agent"
LABEL version="0.5.0-dev"

WORKDIR /app

# 安装运行时系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    openssh-client \
    iputils-ping \
    dnsutils \
    curl \
    net-tools \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 安装 kubectl（可选）
RUN curl -fsSL https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl \
    -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl || true

# 从 builder 复制 Python 包
COPY --from=builder /install /usr/local

# 复制应用代码
COPY . /app

# 安装 keeper
RUN pip install --no-cache-dir -e .

# 创建非 root 用户
RUN useradd -m -s /bin/bash keeper && \
    mkdir -p /home/keeper/.keeper && \
    chown -R keeper:keeper /home/keeper/.keeper

# 配置持久化目录
VOLUME ["/home/keeper/.keeper"]

# 默认使用 keeper 用户运行
USER keeper
ENV HOME=/home/keeper

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD keeper status || exit 1

# 默认命令：交互模式
ENTRYPOINT ["keeper"]
CMD ["--classic"]
