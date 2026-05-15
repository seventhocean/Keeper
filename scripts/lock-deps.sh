#!/bin/bash
# 重新生成依赖锁定文件
#
# 用法: ./scripts/lock-deps.sh
#
# 前置条件:
#   pip install pip-tools
#
# 原理: 从 pyproject.toml 解析依赖范围，
#        解析所有传递依赖并锁定到精确版本。

set -e

echo "🔒 生成 requirements.lock..."

# 检查 pip-compile 是否可用
if ! command -v pip-compile &> /dev/null; then
    echo "  需要 pip-tools，正在安装..."
    pip install pip-tools
fi

# 生成主依赖锁定文件
pip-compile \
    pyproject.toml \
    --output-file=requirements.lock \
    --strip-extras \
    --no-header \
    --annotation-style=line \
    --resolver=backtracking

echo "✓ requirements.lock 已更新"
echo ""
echo "  安装: pip install -r requirements.lock"
echo "  检查: pip-sync requirements.lock"
