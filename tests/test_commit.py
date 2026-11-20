import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "bin" / "xbotgo"


class CommitTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.responses = root / "responses.json"
        self.responses.write_text("[]", encoding="utf-8")
        self.prompt_log = root / "prompts.jsonl"
        codex = root / "codex"
        codex.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "log = Path(os.environ['TEST_CODEX_PROMPTS'])\n"
            "attempt = len(log.read_text().splitlines()) if log.exists() else 0\n"
            "with log.open('a') as file:\n"
            "    file.write(json.dumps(sys.stdin.read()) + '\\n')\n"
            "responses = json.loads(Path(os.environ['TEST_CODEX_RESPONSES']).read_text())\n"
            "if attempt >= len(responses):\n"
            "    sys.exit(99)\n"
            "response = responses[attempt]\n"
            "if isinstance(response, int):\n"
            "    sys.exit(response)\n"
            "output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "output.write_text(response if isinstance(response, str) else json.dumps(response))\n",
            encoding="utf-8",
        )
        codex.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "TEST_CODEX_PROMPTS": str(self.prompt_log),
            "TEST_CODEX_RESPONSES": str(self.responses),
        }
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Initial commit")
        (self.repo / "settings.txt").write_text("settings\n", encoding="utf-8")

    def git(self, *args):
        return self.run_command("git", *args, check=True).stdout.strip()

    def run_command(self, *args, check=False):
        return subprocess.run(
            args, cwd=self.repo, env=self.env, text=True, capture_output=True,
            check=check, timeout=10,
        )

    def codex_responds_with(self, *responses):
        self.responses.write_text(json.dumps(responses), encoding="utf-8")

    def prompts(self):
        if not self.prompt_log.exists():
            return []
        return [json.loads(line) for line in self.prompt_log.read_text().splitlines()]

    def test_manual_message_commits_all_changes_without_codex(self):
        message = "fix(settings): 调整设置\n\n保留提交正文。"
        result = self.run_command(CLI, "commit", "-m", message)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%B"), message)
        self.assertEqual(self.git("show", "HEAD:settings.txt"), "settings")
        self.assertEqual(self.prompts(), [])

    def test_retries_cli_failure_with_optional_scope(self):
        message = "fix: 调整设置"
        self.codex_responds_with(42, {"message": message, "error": None})

        result = self.run_command(CLI, "commit")

        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = self.prompts()
        self.assertNotIn("`type: 描述`", first)
        self.assertIn("`type: 描述`", second)
        self.assertEqual(self.git("log", "-1", "--format=%s"), message)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")

    def test_retry_failure_keeps_index_and_suggests_manual_commit(self):
        self.codex_responds_with({"message": None, "error": "无法确定 scope"}, "invalid json")

        result = self.run_command(CLI, "commit")

        self.assertEqual(result.returncode, 1)
        self.assertIn("xbotgo commit -m", result.stderr)
        self.assertIn("无法确定 scope", result.stderr)
        self.assertEqual(len(self.prompts()), 2)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Initial commit")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "settings.txt")

    def test_git_hook_failure_does_not_regenerate_message(self):
        message = "fix(settings): 调整设置"
        self.codex_responds_with({"message": message, "error": None})
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\necho 'hook rejected message' >&2\nexit 1\n")
        hook.chmod(0o755)

        result = self.run_command(CLI, "commit")

        self.assertEqual(result.returncode, 1)
        self.assertIn("hook rejected message", result.stderr)
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Initial commit")
