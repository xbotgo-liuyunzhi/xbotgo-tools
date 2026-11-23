import json
from pathlib import Path
import re
from shutil import which
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from urllib.parse import quote, urlsplit

from xbotgo_commit import (
    commit_current_repository, find_codex, push_repository, replay_diagnostics, run_codex_json,
)


BRANCH_REF = "refs/heads/"
PUSH_OPTIONS = ("--no-follow-tags", "--no-recurse-submodules")
PR_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"],
    "additionalProperties": False,
}


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=repo, stdout=subprocess.PIPE, text=True, errors="surrogateescape", check=check,
    )


def git_config(repo, key):
    result = git(repo, "config", "--get", key, check=False)
    if result.returncode == 1:
        return ""
    result.check_returncode()
    return result.stdout.removesuffix("\n")


def push_remote(repo, branch):
    remote = (
        git_config(repo, f"branch.{branch}.pushRemote")
        or git_config(repo, "remote.pushDefault")
        or git_config(repo, f"branch.{branch}.remote")
    )
    remotes = git(repo, "remote").stdout.splitlines()
    if not remote:
        remote = remotes[0] if len(remotes) == 1 else "origin"
    if remote not in remotes:
        raise RuntimeError("找不到当前分支的推送远端，请检查 Git 远端配置。")
    urls = git(repo, "remote", "get-url", "--push", "--all", "--", remote).stdout.splitlines()
    if len(urls) != 1:
        raise RuntimeError(f"远端 {remote} 必须配置一个推送地址。")
    return remote, urls[0]


def github_repository(url):
    if "://" in url:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http", "ssh") or parsed.query or parsed.fragment:
            raise RuntimeError("推送远端需要使用 GitHub 的 HTTPS 或 SSH 地址。")
        hostname, path = parsed.hostname, parsed.path.strip("/")
    else:
        match = re.fullmatch(r"(?:[^@/:]+@)?([^@/:]+):([^:]+)", url)
        if not match:
            raise RuntimeError("推送远端需要使用 GitHub 的 HTTPS 或 SSH 地址。")
        hostname, path = match[1].lower(), match[2].strip("/")

    repository = path.removesuffix(".git")
    if not hostname or not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repository):
        raise RuntimeError("无法从推送地址识别 GitHub 仓库。")
    if hostname == "ssh.github.com":
        hostname = "github.com"
    return hostname, repository


def push_target_ref(repo, remote, branch, source_ref, upstream_ref):
    if git_config(repo, f"remote.{remote}.push"):
        result, updates = preview_push(repo, remote)
        targets = {target for source, target, _, _ in updates if source == source_ref}
        if len(targets) == 1:
            return targets.pop()
        if targets or result.returncode:
            raise RuntimeError(f"无法确定当前分支的推送目标：{result.stderr.strip() or remote}")
    if (
        upstream_ref and git_config(repo, "push.default") == "upstream"
        and git_config(repo, f"branch.{branch}.remote") == remote
    ):
        return upstream_ref
    return source_ref


def preview_push(repo, remote, *refspecs):
    result = subprocess.run(
        ["git", "push", "--dry-run", "--porcelain", "--no-verify", *PUSH_OPTIONS,
         "--", remote, *refspecs],
        cwd=repo, capture_output=True, text=True, errors="surrogateescape",
    )
    updates = []
    for line in result.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) == 3:
            status, mapping, summary = fields
            source, _, target = mapping.partition(":")
            updates.append((source, target, status, summary))
    return result, updates


def needs_push(repo, remote, refspec):
    result, updates = preview_push(repo, remote, refspec)
    for source, target, status, summary in updates:
        if f"{source}:{target}" != refspec:
            continue
        if result.returncode == 0 and status in ("=", " ", "*"):
            return status != "="
        raise RuntimeError(f"无法推送当前分支：{summary}")
    raise RuntimeError(f"无法确定当前分支的推送状态：{result.stderr.strip() or remote}")


def github_get(gh, repo, hostname, path, *fields):
    result = subprocess.run(
        [gh, "api", "--hostname", hostname, "--method", "GET", path, *fields],
        cwd=repo, capture_output=True, text=True,
    )
    if result.returncode:
        diagnostics = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise RuntimeError(f"GitHub 查询失败：{diagnostics}")
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("GitHub API 返回的 JSON 无效。") from error


def github_branch_commit(gh, repo, hostname, repository, branch):
    ref = github_get(gh, repo, hostname, f"repos/{repository}/git/ref/heads/{quote(branch)}")
    if isinstance(ref, dict) and ref.get("ref") == f"{BRANCH_REF}{branch}":
        commit = (ref.get("object") or {}).get("sha")
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            return commit
    raise RuntimeError(f"GitHub 未返回分支 {branch} 的提交。")


def existing_pull_request(gh, repo, hostname, repository, head, base):
    owner = repository.split("/", 1)[0]
    pull_requests = github_get(
        gh, repo, hostname, f"repos/{repository}/pulls", "--raw-field", "state=open",
        "--raw-field", f"head={owner}:{head}", "--raw-field", f"base={base}",
    )
    if not isinstance(pull_requests, list):
        raise RuntimeError("GitHub API 返回的 PR 列表无效。")
    for pull_request in pull_requests:
        source = pull_request["head"]
        target = pull_request["base"]
        if (
            source["ref"] == head and target["ref"] == base
            and (source.get("repo") or {}).get("full_name", "").lower() == repository.lower()
        ):
            return pull_request["html_url"]
    return None


def draft_pull_request(repo, base_commit, head_commit):
    codex = find_codex()
    if not codex:
        raise RuntimeError("找不到 Codex CLI，请先安装并登录。")
    prompt = f"""为当前 Git 仓库的 GitHub PR 撰写中文标题和 Markdown 正文。
用 git diff {base_commit}...{head_commit} 和 git log {base_commit}..{head_commit} 阅读本次 PR 的改动和提交。
只读取这次 PR 的改动及所需的本地仓库规则。保留必要的英文技术名词，概括改动和目的。
正文只写有依据的信息，勿声称运行了未验证的测试。返回单行 title 和 Markdown body，由外层命令创建 PR。
"""
    print("正在生成 PR 标题和正文…", file=sys.stderr, flush=True)
    with TemporaryFile() as log:
        try:
            draft = run_codex_json(codex, repo, prompt, PR_SCHEMA, log)
        except (OSError, RuntimeError, ValueError) as error:
            replay_diagnostics(log)
            raise RuntimeError(f"Codex 生成 PR 文案失败：{error}") from error
    if not isinstance(draft, dict):
        raise RuntimeError("Codex 返回的 PR 文案格式无效。")
    title, body = draft.get("title"), draft.get("body")
    if not isinstance(title, str) or len(title.strip().splitlines()) != 1 or "\0" in title:
        raise RuntimeError("Codex 未返回有效的单行 PR 标题。")
    if not isinstance(body, str) or not body.strip() or "\0" in body:
        raise RuntimeError("Codex 未返回有效的 PR 正文。")
    return title.strip(), body


def publish_pull_request(gh, repo, hostname, repository, head, base, title, body):
    with TemporaryDirectory(prefix="xbotgo-pr-") as directory:
        body_file = Path(directory) / "body.md"
        body_file.write_text(body, encoding="utf-8")
        result = subprocess.run(
            [gh, "pr", "create", "--repo", f"{hostname}/{repository}", "--base", base,
             "--head", head, "--title", title, "--body-file", body_file],
            cwd=repo, capture_output=True, text=True,
        )
    if result.returncode:
        try:
            existing = existing_pull_request(gh, repo, hostname, repository, head, base)
        except (OSError, RuntimeError, ValueError):
            existing = None
        if existing:
            return existing
        diagnostics = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise RuntimeError(f"创建 GitHub PR 失败：{diagnostics}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError("GitHub CLI 未返回 PR 链接，请重新运行命令查询。")
    return lines[-1]


def create_pull_request(base):
    root = git(None, "rev-parse", "--show-toplevel").stdout.removesuffix("\n")
    repo = Path(root)
    current = git(repo, "symbolic-ref", "--quiet", "HEAD", check=False)
    if current.returncode == 1:
        raise RuntimeError("当前处于 detached HEAD，请先切换到要提交 PR 的分支。")
    current.check_returncode()
    source_ref = current.stdout.strip()
    branch = source_ref.removeprefix(BRANCH_REF)
    if git(repo, "check-ref-format", f"{BRANCH_REF}{base}", check=False).returncode:
        raise RuntimeError(f"目标分支名无效：{base}")

    gh = which("gh")
    if not gh:
        raise RuntimeError("找不到 GitHub CLI（gh），请先安装并登录。")
    remote, url = push_remote(repo, branch)
    hostname, repository = github_repository(url)
    upstream_ref = git_config(repo, f"branch.{branch}.merge")
    target_ref = push_target_ref(repo, remote, branch, source_ref, upstream_ref)
    if not target_ref.startswith(BRANCH_REF):
        raise RuntimeError("当前分支的推送目标需要是远端分支。")
    head = target_ref.removeprefix(BRANCH_REF)
    if head == base:
        raise RuntimeError("PR 源分支和目标分支相同。")
    try:
        github_branch_commit(gh, repo, hostname, repository, base)
    except RuntimeError as error:
        raise RuntimeError(f"无法验证目标分支 {base}：{error}") from error

    dirty = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=normal").stdout
    merge = git(repo, "rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False)
    if merge.returncode not in (0, 1):
        merge.check_returncode()
    if dirty or merge.returncode == 0:
        commit_current_repository()

    head_commit = git(repo, "rev-parse", "--verify", source_ref).stdout.strip()
    refspec = f"{source_ref}:{target_ref}"
    if needs_push(repo, remote, refspec) or not upstream_ref:
        tracking = () if upstream_ref else ("--set-upstream",)
        push_repository(repo, push_args=[*PUSH_OPTIONS, *tracking, "--", remote, refspec])

    existing = existing_pull_request(gh, repo, hostname, repository, head, base)
    if existing:
        print(existing)
        return
    if github_branch_commit(gh, repo, hostname, repository, head) != head_commit:
        raise RuntimeError("远端源分支在执行期间发生变化，请重新运行命令。")
    base_commit = github_branch_commit(gh, repo, hostname, repository, base)
    if git(repo, "cat-file", "-e", f"{base_commit}^{{commit}}", check=False).returncode:
        result = git(repo, "fetch", "--no-tags", "--no-write-fetch-head", "--", url, base_commit,
                     check=False)
        if result.returncode:
            raise RuntimeError(f"无法获取目标分支 {base} 的提交。")
    commits = git(repo, "rev-list", "--max-count=1", f"{base_commit}..{head_commit}").stdout
    if not commits:
        raise RuntimeError(f"当前分支没有可以合入 {base} 的提交。")
    if git(repo, "merge-base", base_commit, head_commit, check=False).returncode:
        raise RuntimeError(f"无法找到与目标分支 {base} 的共同提交，请检查分支历史。")

    title, body = draft_pull_request(repo, base_commit, head_commit)
    if (
        github_branch_commit(gh, repo, hostname, repository, head) != head_commit
        or github_branch_commit(gh, repo, hostname, repository, base) != base_commit
    ):
        raise RuntimeError("远端分支在生成 PR 文案期间发生变化，请重新运行命令。")
    print(publish_pull_request(gh, repo, hostname, repository, head, base, title, body))
