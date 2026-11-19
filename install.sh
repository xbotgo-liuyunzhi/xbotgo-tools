#!/bin/sh
set -eu

xbotgo_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
xbotgo_prefix=${XBOTGO_INSTALL_PREFIX:-"$HOME/.local"}
xbotgo_bin="$xbotgo_prefix/bin"
xbotgo_share="$xbotgo_prefix/share/xbotgo"

install -d "$xbotgo_bin" "$xbotgo_share/git-chinese-commit"
install -m 644 "$xbotgo_source/share/xbotgo/xbotgo_commit.py" "$xbotgo_share/xbotgo_commit.py"
install -m 644 "$xbotgo_source/share/xbotgo/git-chinese-commit/SKILL.md" "$xbotgo_share/git-chinese-commit/SKILL.md"
install -m 755 "$xbotgo_source/bin/xbotgo" "$xbotgo_bin/xbotgo"

printf '已安装 %s\n' "$xbotgo_bin/xbotgo"
case ":${PATH:-}:" in
    *":$xbotgo_bin:"*) ;;
    *) printf '请将 %s 加入 PATH。\n' "$xbotgo_bin" ;;
esac
