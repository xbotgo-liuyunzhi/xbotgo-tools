#!/bin/sh

if [ "$#" -ne 2 ] || [ "${1#branch=}" = "$1" ] || [ "${2#reviewer=}" = "$2" ]; then
    printf '%s\n' '无法读取 Fork 的 PR 参数。' >&2
    exit 2
fi

branch=${1#branch=}
reviewer=${2#reviewer=}
case $branch in
    *[![:space:]]*) ;;
    *) printf '%s\n' '请输入目标分支。' >&2; exit 2 ;;
esac

share_dir=${0%/*}
bin_dir=${share_dir%/share/xbotgo}/bin
export PATH="$bin_dir:/opt/homebrew/bin:/usr/local/bin:$PATH"

set -- pr
case $reviewer in
    *[![:space:]]*) set -- "$@" "--reviewer=$reviewer" ;;
esac
exec "$bin_dir/xbotgo" "$@" -- "$branch" 2>&1
