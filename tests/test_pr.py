import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "bin" / "xbotgo"
REMOTE_URL = "git@github.com:xbotgo/team.git"
PR_URL = "https://github.com/xbotgo/team/pull/42"
REVIEWER = {"localized_name": "张三", "open_id": "ou_zhangsan", "email": "zhangsan@example.com"}
REVIEWER_LOGIN = "reviewer-zhang"


class PullRequestTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.remote = self.root / "remote.git"
        self.git_program = shutil.which("git")
        self.responses = self.root / "codex.json"
        self.responses.write_text(json.dumps([{"title": "更新设置", "body": "## 改动\n\n更新设置。"}]))
        self.events_file = self.root / "events.jsonl"
        self.prs = self.root / "prs.json"
        self.prs.write_text("[]")
        self.reviewers = self.root / "reviewers.json"
        self.reviewers.write_text("[]")
        self.env = {
            **os.environ,
            "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.remote.resolve().as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": REMOTE_URL,
            "TEST_REAL_GIT": self.git_program,
            "TEST_EVENTS": str(self.events_file),
            "TEST_CODEX_RESPONSES": str(self.responses),
            "TEST_PRS": str(self.prs),
            "TEST_PR_URL": PR_URL,
            "TEST_REMOTE": str(self.remote),
            "TEST_REVIEWERS": str(self.reviewers),
            "TEST_LARK_CONTACT": json.dumps({"ok": True, "data": {"users": [REVIEWER], "has_more": False}}),
            "TEST_GH_SEARCH": json.dumps({
                "total_count": 1, "incomplete_results": False, "items": [{"login": REVIEWER_LOGIN, "type": "User"}],
            }),
            "TEST_GH_USER": json.dumps({"login": REVIEWER_LOGIN, "type": "User", "email": REVIEWER["email"]}),
        }
        self.write_executable(self.root / "git", '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[:2] == ["remote", "get-url"]:
    os.environ["GIT_CONFIG_COUNT"] = "0"
if args[:1] == ["push"] and "--dry-run" not in args:
    with Path(os.environ["TEST_EVENTS"]).open("a") as log:
        print(json.dumps(["push", args]), file=log)
os.execv(os.environ["TEST_REAL_GIT"], ["git", *args])
''')
        self.write_executable(self.root / "codex", '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

log = Path(os.environ["TEST_EVENTS"])
events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
attempt = sum(event[0] == "codex" for event in events)
with log.open("a") as file:
    print(json.dumps(["codex", sys.stdin.read(), sys.argv[1:]]), file=file)
responses = json.loads(Path(os.environ["TEST_CODEX_RESPONSES"]).read_text())
if attempt >= len(responses):
    sys.exit("Codex fixture failed")
output = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text(json.dumps(responses[attempt]), encoding="utf-8")
if os.environ.get("TEST_NEW_BASE"):
    subprocess.run(["git", "--git-dir", os.environ["TEST_REMOTE"], "update-ref",
                    "refs/heads/develop", os.environ["TEST_NEW_BASE"]], check=True)
''')
        self.write_executable(self.root / "gh", '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote

args = sys.argv[1:]
prs = Path(os.environ["TEST_PRS"])
reviewers = Path(os.environ["TEST_REVIEWERS"])

def current_pull_request():
    pull = json.loads(prs.read_text())[0]
    pull["id"] = 1234
    ref = "refs/heads/" + pull["head"]["ref"]
    sha = subprocess.check_output([os.environ["TEST_REAL_GIT"], "--git-dir", os.environ["TEST_REMOTE"],
                                   "rev-parse", "--verify", ref], text=True).strip()
    pull["head"]["sha"] = os.environ.get("TEST_PR_HEAD", sha)
    pull["state"] = os.environ.get("TEST_PR_STATE", "open")
    pull["requested_reviewers"] = json.loads(reviewers.read_text())
    return pull

ref_prefix = "repos/xbotgo/team/git/ref/heads/"
ref_endpoint = next((arg for arg in args if arg.startswith(ref_prefix)), None)
if args[:1] == ["api"] and ref_endpoint:
    if os.environ.get("TEST_UNKNOWN_REPO"):
        sys.exit("GitHub repository could not be verified")
    ref = "refs/heads/" + unquote(ref_endpoint.removeprefix(ref_prefix))
    result = subprocess.run([os.environ["TEST_REAL_GIT"], "--git-dir", os.environ["TEST_REMOTE"],
                             "rev-parse", "--verify", ref], capture_output=True, text=True)
    if result.returncode:
        sys.exit("gh: Not Found (HTTP 404)")
    print(json.dumps({"ref": ref, "object": {"sha": result.stdout.strip()}}))
    sys.exit()

if args[:1] == ["api"]:
    method_index = args.index("--method")
    method, endpoint = args[method_index + 1:method_index + 3]
    event = {
        "search/users": "github_search",
        "users/reviewer-zhang": "github_user",
        "repos/xbotgo/team/pulls/42": "pull_request",
        "repos/xbotgo/team/pulls/42/requested_reviewers": "request_review",
    }.get(endpoint)
    if event:
        payload = json.load(sys.stdin) if method == "POST" else None
        with Path(os.environ["TEST_EVENTS"]).open("a") as log:
            print(json.dumps([event, args, payload]), file=log)
        if event == "github_search":
            print(os.environ["TEST_GH_SEARCH"])
        elif event == "github_user":
            print(os.environ["TEST_GH_USER"])
        elif event == "pull_request":
            print(json.dumps(current_pull_request()))
        elif event == "request_review":
            if os.environ.get("TEST_GH_REVIEW_FAILURE"):
                sys.exit("GitHub rejected review request")
            pull = current_pull_request()
            pending = pull["requested_reviewers"]
            pending.extend({"login": login} for login in payload["reviewers"])
            reviewers.write_text(json.dumps(pending))
            pull["head"]["sha"] = os.environ.get("TEST_PR_HEAD_AFTER_REQUEST", pull["head"]["sha"])
            pull["state"] = os.environ.get("TEST_PR_STATE_AFTER_REQUEST", pull["state"])
            print(json.dumps(pull))
        sys.exit()

with Path(os.environ["TEST_EVENTS"]).open("a") as log:
    if args[:2] == ["pr", "create"]:
        body = Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
        print(json.dumps(["create", args, body]), file=log)
    else:
        print(json.dumps(["lookup", args]), file=log)

if args[:1] == ["api"]:
    print(prs.read_text())
    sys.exit()
if args[:2] != ["pr", "create"]:
    sys.exit("Unsupported gh command")
if os.environ.get("TEST_GH_FAILURE") == "reject":
    sys.exit("GitHub failed to create PR")
url = os.environ["TEST_PR_URL"]
head = args[args.index("--head") + 1]
base = args[args.index("--base") + 1]
repo = {"full_name": "xbotgo/team"}
prs.write_text(json.dumps([{"html_url": url, "head": {"ref": head, "repo": repo},
                           "base": {"ref": base, "repo": repo}}]))
if os.environ.get("TEST_GH_FAILURE") == "race":
    sys.exit("A pull request already exists")
print(url)
''')
        self.write_executable(self.root / "lark-cli", '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[:2] == ["contact", "+search-user"]:
    event = "lark_contact"
elif args[:2] == ["im", "+messages-send"]:
    event = "lark_send"
else:
    sys.exit("Unsupported lark-cli command")
with Path(os.environ["TEST_EVENTS"]).open("a") as log:
    print(json.dumps([event, args]), file=log)

if event == "lark_contact":
    response = json.loads(os.environ["TEST_LARK_CONTACT"])
else:
    response = {"ok": True, "data": {"message_id": "om_review"}}
    if os.environ.get("TEST_LARK_SEND_FAILURE"):
        response = {"ok": False, "error": {"message": "缺少发消息权限"}}
print(json.dumps(response), file=sys.stdout if response["ok"] else sys.stderr)
sys.exit(0 if response["ok"] else 1)
''')
        self.git("init", "--quiet", "--initial-branch=develop")
        self.git("init", "--bare", "--quiet", "--initial-branch=develop", self.remote)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Base")
        self.git("remote", "add", "team", REMOTE_URL)
        self.git("push", "--quiet", "--set-upstream", "team", "develop")
        self.git("switch", "--quiet", "-c", "feature/settings")

    def write_executable(self, path, content):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def git(self, *args):
        return subprocess.run(
            [self.git_program, *args], cwd=self.repo, env=self.env, text=True,
            capture_output=True, check=True, timeout=10,
        ).stdout.strip()

    def run_pr(self, base="develop", *options, **env):
        return subprocess.run(
            [CLI, "pr", base, *options], cwd=self.repo, env={**self.env, **env}, text=True,
            capture_output=True, timeout=10,
        )

    def events(self):
        if not self.events_file.exists():
            return []
        return [json.loads(line) for line in self.events_file.read_text().splitlines()]

    def commit_change(self):
        (self.repo / "settings.txt").write_text("updated\n")
        self.git("add", "settings.txt")
        self.git("commit", "--quiet", "-m", "feat(settings): 更新设置")

    def track_branch(self):
        self.git("push", "--quiet", "--set-upstream", "team", "feature/settings")

    def make_remote_base_commit(self, base):
        return self.git(
            "--git-dir", self.remote, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit-tree", f"{base}^{{tree}}", "-p", base, "-m", "Remote target updated",
        )

    def assert_success(self, result, url=PR_URL):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], url)

    def test_multiple_reviewer_options_fail_before_lookup(self):
        result = self.run_pr("develop", "-r", "张三", "--reviewer", "李四")

        self.assertEqual(result.returncode, 2)
        self.assertIn("一位审核人", result.stderr)
        self.assertEqual(self.events(), [])

    def test_new_pr_resolves_name_and_notifies_both_services(self):
        self.responses.write_text(json.dumps([
            {"message": "feat(settings): 更新设置", "error": None},
            {"title": "更新设置", "body": "## 改动\n\n更新设置。"},
        ]))
        (self.repo / "settings.txt").write_text("local\n")

        self.assert_success(self.run_pr("develop", "-r", REVIEWER["localized_name"]))

        events = self.events()
        self.assertEqual([event[0] for event in events], [
            "lark_contact", "github_search", "github_user", "codex", "push", "lookup", "codex", "create",
            "pull_request", "request_review", "lark_send",
        ])
        self.assertEqual(events[0][1][2:], ["--query", "张三", "--as", "user", "--format", "json"])
        self.assertIn('q="zhangsan@example.com" in:email type:user', events[1][1])
        self.assertIn("github.com", events[1][1])
        self.assertIn("github.com", events[9][1])
        self.assertEqual(events[9][2], {"reviewers": [REVIEWER_LOGIN]})
        send = events[-1][1]
        self.assertEqual(send[send.index("--as") + 1], "user")
        self.assertEqual(send[send.index("--user-id") + 1], REVIEWER["open_id"])
        self.assertIn(PR_URL, send[send.index("--text") + 1])
        self.assertLessEqual(len(send[send.index("--idempotency-key") + 1]), 50)

    def test_existing_pr_resolves_email_and_skips_pending_github_request(self):
        self.commit_change()
        self.assert_success(self.run_pr())
        self.events_file.unlink()
        self.reviewers.write_text(json.dumps([{"login": REVIEWER_LOGIN}, {"login": "another-reviewer"}]))
        enterprise_contact = {**REVIEWER, "enterprise_email": "work@example.com"}
        contacts = {"ok": True, "data": {"users": [enterprise_contact], "has_more": False}}

        self.assert_success(self.run_pr(
            "develop", "--reviewer", " ZHANGSAN@example.com ", TEST_LARK_CONTACT=json.dumps(contacts),
        ))

        events = self.events()
        self.assertEqual([event[0] for event in events], [
            "lark_contact", "github_search", "github_user", "lookup", "pull_request", "lark_send",
        ])
        self.assertIn('q="zhangsan@example.com" in:email type:user', events[1][1])

    def test_reviewer_lookup_errors_leave_commit_push_and_pr_pending(self):
        (self.repo / "settings.txt").write_text("local\n")
        head = self.git("rev-parse", "HEAD")
        cases = [
            ("同名", "飞书", {"users": [
                REVIEWER, {**REVIEWER, "open_id": "ou_other", "email": "other@example.com"},
            ]}, None, None),
            ("双邮箱", "work@example.com", {"users": [{**REVIEWER, "enterprise_email": "work@example.com"}]},
             None, None),
            ("查询不完整", "飞书", {"users": [REVIEWER], "has_more": True}, None, None),
            ("邮箱未公开", "公开邮箱", {"users": [REVIEWER]},
             {"total_count": 0, "incomplete_results": False, "items": []}, None),
            ("GitHub 匹配不唯一", "GitHub", {"users": [REVIEWER]},
             {"total_count": 2, "incomplete_results": False, "items": [{"login": REVIEWER_LOGIN}]}, None),
            ("GitHub 邮箱不匹配", "公开邮箱", {"users": [REVIEWER]}, None,
             {"login": REVIEWER_LOGIN, "type": "User", "email": "other@example.com"}),
        ]
        for label, diagnostic, data, search, profile in cases:
            with self.subTest(label=label):
                env = {"TEST_LARK_CONTACT": json.dumps({"ok": True, "data": {"has_more": False, **data}})}
                if search:
                    env["TEST_GH_SEARCH"] = json.dumps(search)
                if profile:
                    env["TEST_GH_USER"] = json.dumps(profile)
                result = self.run_pr("develop", "-r", "张三", **env)

                self.assertEqual(result.returncode, 1)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertTrue({event[0] for event in self.events()}
                                <= {"lark_contact", "github_search", "github_user"})
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), "?? settings.txt")
        self.assertEqual(self.prs.read_text(), "[]")

    def test_github_request_failure_keeps_pr_link_and_skips_feishu(self):
        self.commit_change()
        result = self.run_pr("develop", "-r", "张三", TEST_GH_REVIEW_FAILURE="yes")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.splitlines()[-1], PR_URL)
        self.assertIn("GitHub 审核请求", result.stderr)
        self.assertIn("GitHub rejected review request", result.stderr)
        self.assertEqual([event[0] for event in self.events()][-2:], ["pull_request", "request_review"])

    def test_feishu_retry_reuses_pr_request_and_idempotency_key(self):
        self.commit_change()
        failed = self.run_pr("develop", "-r", "张三", TEST_LARK_SEND_FAILURE="yes")

        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout.splitlines()[-1], PR_URL)
        self.assertIn("飞书审核私信", failed.stderr)
        self.assertIn("缺少发消息权限", failed.stderr)
        alias = PR_URL.replace("/team/", "/TEAM/")
        prs = json.loads(self.prs.read_text())
        prs[0]["html_url"] = alias
        self.prs.write_text(json.dumps(prs))
        self.assert_success(self.run_pr("develop", "-r", "张三"), url=alias)
        self.git("commit", "--quiet", "--allow-empty", "-m", "Update PR head")
        self.assert_success(self.run_pr("develop", "-r", "张三"), url=alias)

        events = self.events()
        names = [event[0] for event in events]
        self.assertEqual(names.count("create"), 1)
        self.assertEqual(names.count("request_review"), 1)
        self.assertEqual(names.count("codex"), 1)
        keys = [args[args.index("--idempotency-key") + 1] for name, args, *_ in events if name == "lark_send"]
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[1], keys[2])

    def test_closed_or_changed_pr_skips_notifications(self):
        self.commit_change()
        self.assert_success(self.run_pr())
        self.events_file.unlink()
        for env in ({"TEST_PR_HEAD": "0" * 40}, {"TEST_PR_STATE": "closed"}):
            with self.subTest(env=env):
                result = self.run_pr("develop", "-r", "张三", **env)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.splitlines()[-1], PR_URL)
                self.assertIn("GitHub 审核请求", result.stderr)
        self.assertFalse({"request_review", "lark_send"} & {event[0] for event in self.events()})

    def test_pr_closed_or_changed_during_review_request_skips_feishu(self):
        self.commit_change()
        self.assert_success(self.run_pr())
        for env in ({"TEST_PR_HEAD_AFTER_REQUEST": "0" * 40}, {"TEST_PR_STATE_AFTER_REQUEST": "closed"}):
            with self.subTest(env=env):
                self.events_file.unlink()
                self.reviewers.write_text("[]")
                result = self.run_pr("develop", "-r", "张三", **env)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.splitlines()[-1], PR_URL)
                self.assertIn("GitHub 审核请求", result.stderr)
                self.assertEqual(self.events()[-1][0], "request_review")

    def test_uncommitted_changes_are_committed_and_pushed_before_creating_pr(self):
        self.responses.write_text(json.dumps([
            {"message": "feat(settings): 更新设置", "error": None},
            {"title": "更新设置", "body": "## 改动\n\n更新设置。"},
        ]))
        (self.repo / "settings.txt").write_text("staged\n")
        self.git("add", "settings.txt")
        (self.repo / "settings.txt").write_text("updated\n")
        (self.repo / "new.txt").write_text("new\n")

        self.assert_success(self.run_pr())

        head = self.git("rev-parse", "HEAD")
        base = self.git("rev-parse", "develop")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("--git-dir", self.remote, "show", "feature/settings:settings.txt"), "updated")
        self.assertEqual(self.git("--git-dir", self.remote, "show", "feature/settings:new.txt"), "new")
        self.assertEqual(self.git("rev-parse", "@{upstream}"), head)
        events = self.events()
        self.assertEqual([event[0] for event in events], ["codex", "push", "lookup", "codex", "create"])
        self.assertIn(f"{base}...{head}", events[3][1])
        self.assertIn("gpt-6-luna", events[3][2])
        self.assertIn('model_reasoning_effort="medium"', events[3][2])
        self.assertIn("read-only", events[3][2])
        for value in ("github.com/xbotgo/team", "develop", "feature/settings", "更新设置"):
            self.assertIn(value, events[4][1])
        self.assertEqual(events[4][2], "## 改动\n\n更新设置。")

    def test_existing_unpushed_commit_is_pushed_without_creating_a_commit(self):
        self.track_branch()
        self.commit_change()
        head = self.git("rev-parse", "HEAD")

        self.assert_success(self.run_pr())

        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("--git-dir", self.remote, "rev-parse", "feature/settings"), head)
        self.assertEqual([e[0] for e in self.events()], ["push", "lookup", "codex", "create"])

    def test_configured_push_uses_remote_branch_name_and_leaves_other_branches_unchanged(self):
        self.track_branch()
        self.commit_change()
        self.git("push", "--quiet", "team", "HEAD:refs/heads/unrelated")
        unrelated = self.git("rev-parse", "HEAD")
        self.git("branch", "unrelated", "develop")
        self.git("config", "--add", "remote.team.push", "refs/heads/feature/settings:refs/heads/published")
        self.git("config", "--add", "remote.team.push", "refs/heads/unrelated:refs/heads/unrelated")

        self.assert_success(self.run_pr())

        self.assertEqual(self.git("--git-dir", self.remote, "rev-parse", "published"), self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("--git-dir", self.remote, "rev-parse", "unrelated"), unrelated)
        create = self.events()[-1][1]
        self.assertEqual(create[create.index("--head") + 1], "published")

    def test_first_push_tracks_configured_remote_branch_name(self):
        self.commit_change()
        self.git("config", "remote.team.push", "refs/heads/feature/settings:refs/heads/published")

        self.assert_success(self.run_pr())
        self.assert_success(self.run_pr())

        self.assertEqual(self.git("rev-parse", "--symbolic-full-name", "@{upstream}"), "refs/remotes/team/published")
        self.assertEqual(self.git("--git-dir", self.remote, "branch", "--list", "feature/settings"), "")
        self.assertEqual([event[0] for event in self.events()], ["push", "lookup", "codex", "create", "lookup"])
        create = next(event[1] for event in self.events() if event[0] == "create")
        self.assertEqual(create[create.index("--head") + 1], "published")

    def test_short_configured_refspec_is_resolved_as_git_push_would(self):
        self.commit_change()
        self.git("config", "remote.team.push", "feature/settings:published")

        self.assert_success(self.run_pr())

        self.assertEqual(self.git("rev-parse", "--symbolic-full-name", "@{upstream}"), "refs/remotes/team/published")

    def test_draft_uses_new_target_commit_even_when_local_target_is_stale(self):
        self.commit_change()
        base = self.git("rev-parse", "develop")
        updated_base = self.make_remote_base_commit(base)
        self.git("--git-dir", self.remote, "update-ref", "refs/heads/develop", updated_base)
        head = self.git("rev-parse", "HEAD")

        self.assert_success(self.run_pr())

        self.assertEqual(self.git("rev-parse", "develop"), base)
        self.assertEqual(self.git("cat-file", "-t", updated_base), "commit")
        prompt = next(event[1] for event in self.events() if event[0] == "codex")
        self.assertIn(f"{updated_base}...{head}", prompt)

    def test_target_moved_during_drafting_requires_retry(self):
        self.commit_change()
        updated_base = self.make_remote_base_commit(self.git("rev-parse", "develop"))

        result = self.run_pr(TEST_NEW_BASE=updated_base)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重新运行", result.stderr)
        self.assertEqual(self.git("--git-dir", self.remote, "rev-parse", "develop"), updated_base)
        self.assertEqual([event[0] for event in self.events()], ["push", "lookup", "codex"])

    def test_clean_merge_in_progress_is_committed_before_push(self):
        self.commit_change()
        self.git("switch", "--quiet", "-c", "peer", "develop")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Peer commit")
        self.git("switch", "--quiet", "feature/settings")
        self.git("merge", "--no-ff", "--no-commit", "peer")
        self.assertEqual(self.git("status", "--porcelain"), "")

        self.assert_success(self.run_pr())

        parents = self.git("show", "-s", "--format=%P", "HEAD").split()
        self.assertEqual(len(parents), 2)
        self.assertEqual(self.git("rev-parse", "@{upstream}"), self.git("rev-parse", "HEAD"))
        self.assertEqual([event[0] for event in self.events()], ["push", "lookup", "codex", "create"])

    def test_synced_branch_and_existing_pr_are_reused_on_repeated_runs(self):
        self.commit_change()
        self.track_branch()

        self.assert_success(self.run_pr())
        self.assert_success(self.run_pr())

        self.assertEqual([e[0] for e in self.events()], ["lookup", "codex", "create", "lookup"])

    def test_missing_target_branch_stops_before_committing(self):
        (self.repo / "settings.txt").write_text("local\n")
        result = self.run_pr("missing")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("目标分支", result.stderr)
        self.assertIn("missing", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "?? settings.txt")
        self.assertEqual(self.events(), [])

    def test_detached_head_is_rejected(self):
        self.git("switch", "--quiet", "--detach")
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("detached HEAD", result.stderr)
        self.assertEqual(self.events(), [])

    def test_same_source_and_target_are_rejected(self):
        self.git("switch", "--quiet", "develop")
        (self.repo / "settings.txt").write_text("local\n")
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("相同", result.stderr)
        self.assertEqual(self.events(), [])

    def test_push_mapping_to_target_is_rejected_before_committing(self):
        self.git("config", "remote.team.push", "refs/heads/feature/settings:refs/heads/develop")
        (self.repo / "settings.txt").write_text("local\n")
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("相同", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "?? settings.txt")
        self.assertEqual(self.events(), [])

    def test_unverified_github_repository_stops_before_committing_or_pushing(self):
        (self.repo / "settings.txt").write_text("local\n")
        result = self.run_pr(TEST_UNKNOWN_REPO="yes")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub repository could not be verified", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "?? settings.txt")
        self.assertEqual(self.events(), [])

    def test_commit_hook_failure_stops_before_push_or_pr_lookup(self):
        self.responses.write_text(json.dumps([{"message": "feat(settings): 更新设置", "error": None}]))
        self.write_executable(self.repo / ".git/hooks/pre-commit", "#!/bin/sh\necho commit-rejected >&2\nexit 1\n")
        (self.repo / "settings.txt").write_text("local\n")
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit-rejected", result.stderr)
        self.assertEqual([e[0] for e in self.events()], ["codex"])

    def test_rejected_push_preserves_local_commit_and_skips_pr_lookup(self):
        self.track_branch()
        before = self.git("rev-parse", "HEAD")
        self.commit_change()
        self.write_executable(self.remote / "hooks/pre-receive", "#!/bin/sh\necho push-rejected >&2\nexit 1\n")
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("push-rejected", result.stderr)
        self.assertNotEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.git("--git-dir", self.remote, "rev-parse", "feature/settings"), before)
        self.assertEqual([e[0] for e in self.events()], ["push"])

    def test_invalid_codex_draft_leaves_pushed_commits_and_skips_creation(self):
        self.commit_change()
        self.responses.write_text(json.dumps([{"title": "    ", "body": "有改动。"}]))
        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PR 标题", result.stderr)
        self.assertEqual(self.git("rev-parse", "@{upstream}"), self.git("rev-parse", "HEAD"))
        self.assertEqual([e[0] for e in self.events()], ["push", "lookup", "codex"])

    def test_github_creation_failure_reports_diagnostic(self):
        self.commit_change()
        result = self.run_pr(TEST_GH_FAILURE="reject")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub failed to create PR", result.stderr)
        self.assertEqual(self.git("rev-parse", "@{upstream}"), self.git("rev-parse", "HEAD"))
        self.assertEqual([e[0] for e in self.events()], ["push", "lookup", "codex", "create", "lookup"])

    def test_concurrent_creation_returns_existing_pr_link(self):
        self.commit_change()

        self.assert_success(self.run_pr(TEST_GH_FAILURE="race"))

        self.assertEqual([e[0] for e in self.events()], ["push", "lookup", "codex", "create", "lookup"])
