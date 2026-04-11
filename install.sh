#!/usr/bin/env bash
# ============================================================================
# Keeper - 智能运维 Agent 一键安装脚本
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash
#
# Or download and run:
#   chmod +x install.sh && ./install.sh
#
# Options:
#   --upgrade    Upgrade existing installation
#   --uninstall  Remove Keeper completely
#   --help       Show this help message
# ============================================================================
set -euo pipefail

# ─── Colors & Formatting ─────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────
log_info()  { echo -e "${BLUE}[Keeper]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[Keeper]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[Keeper]${NC} $*"; }
log_error() { echo -e "${RED}[Keeper]${NC} $*"; }
log_step()  { echo -e "\n${BOLD}${CYAN}>>> $*${NC}"; }
die()       { log_error "$*"; exit 1; }

# Install paths: app lives in ~/.keeper/app/ (or /opt/keeper/ if root)
if [ "$(id -u)" -eq 0 ]; then
    log_warn "正在以 root 用户运行，安装路径默认使用 /opt/keeper"
    KEEPER_BASE="${KEEPER_INSTALL_DIR:-/opt/keeper}"
    KEEPER_BIN_DIR="${KEEPER_BIN_INSTALL_DIR:-/usr/local/bin}"
else
    KEEPER_BASE="${KEEPER_INSTALL_DIR:-$HOME/.keeper}"
    KEEPER_BIN_DIR="${KEEPER_BIN_INSTALL_DIR:-$HOME/.local/bin}"
fi
KEEPER_DIR="$KEEPER_BASE/app"
REPO_URL="git@github.com:seventhocean/Keeper.git"
KEEPER_BRANCH="main"

# ─── Ensure PATH ─────────────────────────────────────────────────────────────
export PATH="$KEEPER_BIN_DIR:$PATH"

# ─── Arguments ───────────────────────────────────────────────────────────────
MODE="install"
for arg in "$@"; do
    case "$arg" in
        --upgrade)    MODE="upgrade" ;;
        --uninstall)  MODE="uninstall" ;;
        --help|-h)
            cat <<'HELP'
Keeper - 智能运维 Agent 一键安装脚本

Usage:
  curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash

Or download and run:
  chmod +x install.sh && ./install.sh

Options:
  --upgrade    Upgrade existing installation
  --uninstall  Remove Keeper completely
  --help       Show this help message
HELP
            exit 0
            ;;
        *) die "Unknown option: $arg" ;;
    esac
done

# ─── Uninstall ───────────────────────────────────────────────────────────────
if [ "$MODE" = "uninstall" ]; then
    log_step "卸载 Keeper"
    if [ -d "$KEEPER_DIR" ]; then
        rm -rf "$KEEPER_DIR"
        log_ok "已删除 $KEEPER_DIR"
    fi
    if [ -f "$KEEPER_BIN_DIR/keeper" ]; then
        rm -f "$KEEPER_BIN_DIR/keeper"
        log_ok "已删除 $KEEPER_BIN_DIR/keeper"
    fi
    log_ok "Keeper 已卸载。配置文件 $KEEPER_BASE/config.yaml 已保留。"
    exit 0
fi

# ─── Python Check ────────────────────────────────────────────────────────────
log_step "检查 Python 环境"

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=${ver%%.*}
        minor=${ver##*.}
        if [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            PYTHON_VER="$ver"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    log_error "需要 Python 3.9+，但未找到。"
    echo ""
    echo -e "${BOLD}请先安装 Python 3.9+：${NC}"
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv"
    echo "  CentOS/RHEL:    sudo yum install python3 python3-venv"
    echo "  macOS:          brew install python3"
    echo ""
    exit 1
fi

log_ok "找到 $PYTHON_CMD (Python $PYTHON_VER)"

# ─── Clone/Download ──────────────────────────────────────────────────────────
if [ -d "$KEEPER_DIR/.git" ] && [ "$MODE" = "upgrade" ]; then
    log_step "升级 Keeper"
    cd "$KEEPER_DIR"
    git stash --include-untracked &>/dev/null || true
    if git pull origin "$KEEPER_BRANCH"; then
        log_ok "代码已更新"
    else
        log_warn "pull 失败，尝试重新克隆..."
        cd /
        rm -rf "$KEEPER_DIR"
        git clone --depth 1 -b "$KEEPER_BRANCH" "$REPO_URL" "$KEEPER_DIR"
        log_ok "代码已重新克隆"
    fi
    cd - >/dev/null
elif [ -d "$KEEPER_DIR/.git" ]; then
    log_info "已存在 Keeper 安装（使用 --upgrade 更新）"
else
    log_step "下载 Keeper 源码"
    mkdir -p "$(dirname "$KEEPER_DIR")"
    git clone --depth 1 -b "$KEEPER_BRANCH" "$REPO_URL" "$KEEPER_DIR"
    log_ok "源码已下载"
fi

# ─── Virtual Environment ─────────────────────────────────────────────────────
log_step "创建虚拟环境"

if [ -d "$KEEPER_DIR/venv" ]; then
    log_info "已存在虚拟环境，将重建..."
    rm -rf "$KEEPER_DIR/venv"
fi

"$PYTHON_CMD" -m venv "$KEEPER_DIR/venv"
# shellcheck disable=SC1091
source "$KEEPER_DIR/venv/bin/activate"

# Upgrade pip and install
pip install --upgrade pip -q 2>/dev/null
pip install -e "$KEEPER_DIR" -q 2>/dev/null

log_ok "依赖安装完成"

# ─── Register CLI Shim ───────────────────────────────────────────────────────
log_step "注册 keeper 命令"

mkdir -p "$KEEPER_BIN_DIR"

cat > "$KEEPER_BIN_DIR/keeper" << SHIM
#!/usr/bin/env bash
# Keeper CLI shim — auto-generated by install.sh
KEEPER_BASE="\${KEEPER_INSTALL_DIR:-$KEEPER_BASE}"
KEEPER_VENV="\$KEEPER_BASE/app/venv"
if [ ! -f "\$KEEPER_VENV/bin/keeper" ]; then
    echo "[Keeper] 虚拟环境不存在，请运行安装脚本重新安装。" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "\$KEEPER_VENV/bin/activate"
exec "\$KEEPER_VENV/bin/keeper" "\$@"
SHIM

chmod +x "$KEEPER_BIN_DIR/keeper"

log_ok "keeper → $KEEPER_BIN_DIR/keeper"

# ─── PATH Warning ────────────────────────────────────────────────────────────
if ! echo "$PATH" | tr ':' '\n' | grep -qxF "$KEEPER_BIN_DIR"; then
    log_warn "$KEEPER_BIN_DIR 不在 PATH 中"
    echo ""
    echo "  添加到 ~/.bashrc 或 ~/.zshrc："
    echo -e "  ${CYAN}export PATH=\"$KEEPER_BIN_DIR:\$PATH\"${NC}"
    echo ""
fi

# ─── Version Check ───────────────────────────────────────────────────────────
VERSION=""
if [ -f "$KEEPER_DIR/pyproject.toml" ]; then
    VERSION=$(grep '^version = ' "$KEEPER_DIR/pyproject.toml" | head -1 | sed 's/version = "\(.*\)"/\1/')
fi

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}========================================${NC}"
echo -e "${BOLD}${GREEN}  Keeper v${VERSION:-latest} 安装完成！${NC}"
echo -e "${BOLD}${GREEN}========================================${NC}"
echo ""
echo -e "  ${BOLD}安装目录:${NC} $KEEPER_DIR"
echo -e "  ${BOLD}配置目录:${NC} $KEEPER_BASE"
echo ""
echo -e "${BOLD}快速开始：${NC}"
echo -e "  ${CYAN}keeper${NC}                       进入交互模式"
echo -e "  ${CYAN}keeper config set --api-key ...${NC}  配置 LLM API Key"
echo -e "  ${CYAN}keeper --help${NC}                 查看所有命令"
echo ""
if [ "$MODE" = "upgrade" ]; then
    echo -e "${BOLD}升级成功！${NC}"
else
    echo -e "${BOLD}一键升级：${NC}"
    echo -e "  ${CYAN}curl -sSL https://raw.githubusercontent.com/seventhocean/Keeper/main/install.sh | bash -s -- --upgrade${NC}"
fi
echo ""
