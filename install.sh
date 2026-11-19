#!/bin/sh
set -eu

xbotgo_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
xbotgo_prefix=${XBOTGO_INSTALL_PREFIX:-"$HOME/.local"}
case "$xbotgo_prefix" in
    /*) ;;
    *) xbotgo_prefix="$PWD/$xbotgo_prefix" ;;
esac
xbotgo_bin="$xbotgo_prefix/bin"
xbotgo_share="$xbotgo_prefix/share/xbotgo"

install -d "$xbotgo_bin" "$xbotgo_share/git-chinese-commit"
if ! "$xbotgo_bin/pre-commit" --version >/dev/null 2>&1 &&
   ! pre-commit --version >/dev/null 2>&1; then
    xbotgo_venv="$xbotgo_share/pre-commit-venv"
    python3 -m venv "$xbotgo_venv"
    "$xbotgo_venv/bin/python" -m pip install pre-commit
    "$xbotgo_venv/bin/pre-commit" --version
    if ! "$xbotgo_bin/pre-commit" --version >/dev/null 2>&1; then
        ln -s "$xbotgo_venv/bin/pre-commit" "$xbotgo_bin/"
    fi
fi

install -m 644 "$xbotgo_source/share/xbotgo/xbotgo_commit.py" "$xbotgo_share/xbotgo_commit.py"
install -m 644 "$xbotgo_source/share/xbotgo/git-chinese-commit/SKILL.md" "$xbotgo_share/git-chinese-commit/SKILL.md"
install -m 755 "$xbotgo_source/bin/xbotgo" "$xbotgo_bin/xbotgo"

printf '已安装 %s\n' "$xbotgo_bin/xbotgo"
case ":${PATH:-}:" in
    *":$xbotgo_bin:"*) ;;
    *) printf '请将 %s 加入 PATH。\n' "$xbotgo_bin" ;;
esac
