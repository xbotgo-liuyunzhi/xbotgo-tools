import json
from pathlib import Path
import re
from shutil import which
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from urllib.parse import quote, urlsplit
from uuid import NAMESPACE_URL, uuid5

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


def find_pr_cli(name):
    bin_dir = Path(__file__).resolve().parents[2] / "bin"
    on_path = which(name)
    installed = which(str(bin_dir / name))
    if on_path and installed and on_path != installed:
        try:
            subprocess.run(
                [on_path, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return installed
    return on_path or installed


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


def github_api(gh, repo, hostname, path, *fields, payload=None):
    method = "GET" if payload is None else "POST"
    command = [gh, "api", "--hostname", hostname, "--method", method, path, *fields]
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command, cwd=repo, capture_output=True, text=True,
        input=json.dumps(payload) if payload is not None else None,
    )
    if result.returncode:
        diagnostics = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        operation = "查询" if payload is None else "请求"
        raise RuntimeError(f"GitHub {operation}失败：{diagnostics}")
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("GitHub API 返回的 JSON 无效。") from error


def github_branch_commit(gh, repo, hostname, repository, branch):
    ref = github_api(gh, repo, hostname, f"repos/{repository}/git/ref/heads/{quote(branch)}")
    if isinstance(ref, dict) and ref.get("ref") == f"{BRANCH_REF}{branch}":
        commit = (ref.get("object") or {}).get("sha")
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            return commit
    raise RuntimeError(f"GitHub 未返回分支 {branch} 的提交。")


def existing_pull_request(gh, repo, hostname, repository, head, base):
    owner = repository.split("/", 1)[0]
    pull_requests = github_api(
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


def lark_data(lark, repo, operation, *args):
    try:
        result = subprocess.run(
            [lark, *args, "--as", "user", "--format", "json"],
            cwd=repo, capture_output=True, text=True,
        )
    except OSError as error:
        raise RuntimeError(f"{operation}失败：{error}") from error

    output = result.stderr if result.returncode else result.stdout
    try:
        response = json.loads(output)
    except ValueError:
        response = None

    if isinstance(response, dict):
        data = response.get("data")
        if result.returncode == 0 and response.get("ok") is True and isinstance(data, dict):
            return data
        error = response.get("error")
        if isinstance(error, dict) and error.get("message"):
            detail = error["message"]
            if error.get("hint"):
                detail = f"{detail} {error['hint']}"
            raise RuntimeError(f"{operation}失败：{detail}")

    if result.returncode:
        detail = output.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
    else:
        detail = "lark-cli 返回的响应无效。"
    raise RuntimeError(f"{operation}失败：{detail}")


def feishu_reviewer(lark, repo, reviewer):
    query = reviewer.strip()
    if not query:
        raise RuntimeError("请用 -r 指定审核人的飞书姓名或完整邮箱。")
    data = lark_data(lark, repo, "飞书审核人查询", "contact", "+search-user", "--query", query)
    if data.get("has_more"):
        raise RuntimeError("飞书通讯录查询结果不完整，请用完整邮箱指定审核人。")
    users = data.get("users")
    if not isinstance(users, list) or any(not isinstance(user, dict) for user in users):
        raise RuntimeError("飞书通讯录返回的联系人列表无效。")

    term = query.casefold()
    by_email = "@" in query
    matches = []
    for user in users:
        emails = {
            address.strip().casefold(): address.strip()
            for address in (user.get("email"), user.get("enterprise_email"))
            if isinstance(address, str) and address.strip()
        }
        name = user.get("localized_name")
        matches_name = isinstance(name, str) and name.strip().casefold() == term
        matched = term in emails if by_email else matches_name
        if matched:
            matches.append((user.get("open_id"), emails))

    if not matches:
        raise RuntimeError(f"飞书通讯录未找到与 {query!r} 完全匹配的审核人，请核对姓名或完整邮箱。")
    if len(matches) > 1:
        candidates = ", ".join(sorted({email for _, emails in matches for email in emails.values()}))
        detail = f"（候选邮箱：{candidates}）" if candidates else ""
        raise RuntimeError(f"飞书通讯录中有多位审核人匹配 {query!r}{detail}，请提供唯一的完整邮箱。")

    open_id, emails = matches[0]
    if not isinstance(open_id, str) or not re.fullmatch(r"ou_[a-zA-Z0-9_-]+", open_id):
        raise RuntimeError("飞书通讯录未返回审核人的有效 open_id。")
    if by_email:
        return open_id, emails[term]
    if not emails:
        raise RuntimeError("飞书通讯录未返回审核人的邮箱，请检查通讯录权限或联系人资料。")
    if len(emails) > 1:
        candidates = ", ".join(emails.values())
        raise RuntimeError(f"飞书审核人有多个邮箱（{candidates}），请用 -r 指定 GitHub 公开邮箱。")
    return open_id, next(iter(emails.values()))


def github_reviewer(gh, repo, hostname, email):
    query = f"q={json.dumps(email, ensure_ascii=False)} in:email type:user"
    search = github_api(gh, repo, hostname, "search/users", "--raw-field", query)
    if not isinstance(search, dict) or search.get("incomplete_results") is not False:
        raise RuntimeError("GitHub 用户搜索结果不完整，请稍后重试。")
    items = search.get("items")
    if search.get("total_count") != 1 or not isinstance(items, list) or len(items) != 1:
        raise RuntimeError(f"GitHub 无法按公开邮箱 {email} 唯一匹配审核人，请核对该账号的公开邮箱。")
    user = items[0]
    login = user.get("login") if isinstance(user, dict) and user.get("type") == "User" else None
    if not isinstance(login, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", login):
        raise RuntimeError("GitHub 用户搜索未返回有效的审核人 login。")

    profile = github_api(gh, repo, hostname, f"users/{login}")
    public_email = profile.get("email") if isinstance(profile, dict) else None
    if not isinstance(public_email, str) or public_email.strip().casefold() != email.casefold():
        raise RuntimeError(f"GitHub 审核人的公开邮箱与 {email} 不匹配，请核对该账号的公开邮箱。")
    if profile.get("login") != login or profile.get("type") != "User":
        raise RuntimeError("GitHub 用户资料与搜索到的审核人不一致，请重试。")
    return login


def requested_reviewers(pull_request):
    reviewers = pull_request.get("requested_reviewers") if isinstance(pull_request, dict) else None
    if not isinstance(reviewers, list) or any(
        not isinstance(user, dict) or not isinstance(user.get("login"), str) for user in reviewers
    ):
        raise RuntimeError("GitHub 返回的审核请求列表无效。")
    return {user["login"].casefold() for user in reviewers}


def verified_pull_request_id(pull_request, head_commit):
    if not isinstance(pull_request, dict) or pull_request.get("state") != "open":
        raise RuntimeError("PR 已不处于开放状态。")
    head = pull_request.get("head")
    if not isinstance(head, dict) or head.get("sha") != head_commit:
        raise RuntimeError("PR 的最新提交发生变化，请重新运行命令。")
    pr_id = pull_request.get("id")
    if not isinstance(pr_id, int) or pr_id <= 0:
        raise RuntimeError("GitHub 未返回有效的 PR ID。")
    return pr_id


def request_github_review(gh, repo, hostname, repository, pr_url, head_commit, login):
    try:
        url = urlsplit(pr_url)
        match = re.fullmatch(r"/([^/]+/[^/]+)/pull/([1-9][0-9]*)/?", url.path)
        if (
            url.scheme not in ("http", "https") or url.hostname != hostname
            or not match or match[1].casefold() != repository.casefold()
        ):
            raise RuntimeError("PR 链接与当前 GitHub 仓库不匹配。")
        endpoint = f"repos/{repository}/pulls/{match[2]}"
        pull_request = github_api(gh, repo, hostname, endpoint)
        pr_id = verified_pull_request_id(pull_request, head_commit)
        if login.casefold() in requested_reviewers(pull_request):
            return pr_id

        updated = github_api(gh, repo, hostname, f"{endpoint}/requested_reviewers", payload={"reviewers": [login]})
        if verified_pull_request_id(updated, head_commit) != pr_id:
            raise RuntimeError("GitHub 返回的审核请求与当前 PR 不匹配。")
        if login.casefold() not in requested_reviewers(updated):
            raise RuntimeError(f"GitHub 未确认向 {login} 发起审核请求。")
        return pr_id
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(f"GitHub 审核请求失败：{error}") from error


def send_feishu_review(lark, repo, open_id, pr_url, head_commit, pr_identity):
    key = uuid5(NAMESPACE_URL, f"{pr_identity}\n{head_commit}\n{open_id}").hex
    data = lark_data(
        lark, repo, "飞书审核私信", "im", "+messages-send", "--user-id", open_id,
        "--text", f"你好，请帮我审核这个 GitHub PR，谢谢！\n\n{pr_url}", "--idempotency-key", key,
    )
    if not data.get("message_id"):
        raise RuntimeError("飞书审核私信发送结果缺少消息 ID，请核实后重试。")


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


def create_pull_request(base, reviewer=None):
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

    gh = find_pr_cli("gh")
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

    if reviewer is not None:
        lark = find_pr_cli("lark-cli")
        if not lark:
            raise RuntimeError("找不到飞书 CLI（lark-cli），请先安装并以用户身份登录。")
        open_id, email = feishu_reviewer(lark, repo, reviewer)
        login = github_reviewer(gh, repo, hostname, email)

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

    pr_url = existing_pull_request(gh, repo, hostname, repository, head, base)
    if not pr_url:
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
        pr_url = publish_pull_request(gh, repo, hostname, repository, head, base, title, body)

    print(pr_url, flush=True)
    if reviewer is not None:
        pr_id = request_github_review(gh, repo, hostname, repository, pr_url, head_commit, login)
        send_feishu_review(lark, repo, open_id, pr_url, head_commit, f"{hostname}:{pr_id}")
