import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/xbotgo-liuyunzhi/xbotgo-tools.git"


class UpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.caller = self.root / "caller"
        self.caller.mkdir()
        self.remote = self.root / "remote"
        self.remote.mkdir()
        for name in ("bin", "share"):
            shutil.copytree(SOURCE / name, self.remote / name)
        for name in ("install.sh", "install.py"):
            if (SOURCE / name).exists():
                shutil.copy2(SOURCE / name, self.remote / name)

        tools = self.root / "tools"
        tools.mkdir()
        self.pre_commit = tools / "pre-commit"
        self.pre_commit.write_text("#!/bin/sh\nprintf 'pre-commit 1.2.3\\n'\n")
        self.pre_commit.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.remote.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": REPOSITORY,
        }
        self.env.pop("XBOTGO_INSTALL_PREFIX", None)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "-m", "Update fixture")

    def git(self, *args):
        self.run_command("git", "-C", self.remote, *args)

    def run_command(self, *args, env=None, check=True):
        return subprocess.run(
            args, cwd=self.caller, env=self.env if env is None else env,
            text=True, capture_output=True, check=check, timeout=30,
        )

    def install(self, prefix=None):
        env = self.env if prefix is None else {**self.env, "XBOTGO_INSTALL_PREFIX": str(prefix)}
        self.run_command(SOURCE / "install.sh", env=env)
        installed_prefix = self.home / ".local" if prefix is None else prefix
        return installed_prefix / "bin" / "xbotgo"

    def publish_new_version(self):
        cli = self.remote / "bin" / "xbotgo"
        cli.write_text(cli.read_text().replace("XBotGo 团队命令行工具", "XBotGo 更新测试版本"))
        payload = self.remote / "share/xbotgo/xbotgo_commit.py"
        payload.write_text(payload.read_text() + "\nUPDATED = True\n")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "-am", "New version")

    def test_updates_default_prefix_and_reuses_pre_commit(self):
        installed = self.install()
        self.publish_new_version()
        result = self.run_command(installed, "update", check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("已更新", result.stdout)
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)
        self.assertEqual(self.run_command(self.pre_commit, "--version").stdout.strip(), "pre-commit 1.2.3")
        self.assertFalse((self.home / ".local/share/xbotgo/pre-commit-venv").exists())
        self.assertEqual(self.run_command(installed, "commit", "--help").returncode, 0)
        self.assertEqual(self.run_command(installed, "update").returncode, 0)

    def test_updates_custom_prefix_through_symlink(self):
        prefix = self.root / "custom prefix"
        installed = self.install(prefix)
        alias = self.root / "xbotgo"
        alias.symlink_to(installed)
        self.publish_new_version()
        unrelated_prefix = self.root / "unrelated"
        env = {**self.env, "XBOTGO_INSTALL_PREFIX": str(unrelated_prefix)}
        result = self.run_command(alias, "update", env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("XBotGo 更新测试版本", self.run_command(alias, "--help").stdout)
        self.assertFalse(unrelated_prefix.exists())

    def test_installation_and_update_include_pr_command(self):
        installed = self.install()
        before = self.run_command(installed, "pr", "develop", check=False)
        self.assertEqual(before.returncode, 1, before.stderr)
        self.assertIn("xbotgo pr 失败", before.stderr)
        payload = installed.parent.parent / "share/xbotgo/xbotgo_pr.py"
        payload.unlink()

        self.assertEqual(self.run_command(installed, "update").returncode, 0)
        after = self.run_command(installed, "pr", "develop", check=False)
        self.assertEqual(after.returncode, 1, after.stderr)
        self.assertIn("xbotgo pr 失败", after.stderr)

    def test_clone_failure_preserves_installed_version(self):
        installed = self.install()
        before = installed.read_bytes()
        self.remote.rename(self.root / "missing")
        result = self.run_command(installed, "update", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("下载失败", result.stderr)
        self.assertEqual(installed.read_bytes(), before)
        self.run_command(installed, "commit", "--help")
        (self.root / "missing").rename(self.remote)
        self.run_command(installed, "update")

    def test_file_replacement_failure_rolls_back_and_can_retry(self):
        installed = self.install()
        payload = self.home / ".local/share/xbotgo/xbotgo_commit.py"
        previous_cli = installed.read_bytes()
        previous_payload = payload.read_bytes()
        self.publish_new_version()
        fault_dir = self.root / "fault"
        fault_dir.mkdir()
        observed = self.root / "published_before_failure"
        (fault_dir / "sitecustomize.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "replace = os.replace\n"
            "failed = False\n"
            "def fail_install(source, destination, *args, **kwargs):\n"
            "    global failed\n"
            "    if os.fspath(destination) == os.environ['FAIL_DESTINATION'] and not failed:\n"
            "        failed = True\n"
            "        Path(os.environ['OBSERVED']).write_bytes(Path(os.environ['PAYLOAD']).read_bytes())\n"
            "        if os.environ['INTERRUPT'] == 'yes':\n"
            "            replace(source, destination, *args, **kwargs)\n"
            "            raise KeyboardInterrupt\n"
            "        raise OSError('simulated replacement failure')\n"
            "    return replace(source, destination, *args, **kwargs)\n"
            "os.replace = fail_install\n"
        )
        env = {
            **self.env,
            "PYTHONPATH": str(fault_dir),
            "FAIL_DESTINATION": str(installed),
            "OBSERVED": str(observed),
            "PAYLOAD": str(payload),
        }
        for interrupt in ("no", "yes"):
            with self.subTest(interrupt=interrupt):
                result = self.run_command(installed, "update", env={**env, "INTERRUPT": interrupt}, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("安装失败", result.stderr)
                self.assertIn(b"UPDATED = True", observed.read_bytes())
                self.assertEqual(installed.read_bytes(), previous_cli)
                self.assertEqual(payload.read_bytes(), previous_payload)
                self.run_command(installed, "commit", "--help")
        self.run_command(installed, "update")
        self.assertIn(b"UPDATED = True", payload.read_bytes())

    def test_source_checkout_requires_installation(self):
        cli = SOURCE / "bin" / "xbotgo"
        before = cli.read_bytes()
        result = self.run_command(cli, "update", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("请先安装", result.stderr)
        self.assertEqual(cli.read_bytes(), before)

    def test_concurrent_updates_wait_for_installation_lock(self):
        installed = self.install()
        self.publish_new_version()
        lock_path = self.home / ".local/share/xbotgo/.install.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with subprocess.Popen([installed, "update"], cwd=self.caller, env=self.env) as first, \
                 subprocess.Popen([installed, "update"], cwd=self.caller, env=self.env) as second:
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        first.wait(timeout=0.5)
                    with self.assertRaises(subprocess.TimeoutExpired):
                        second.wait(timeout=0.5)
                    self.assertIn("XBotGo 团队命令行工具", self.run_command(installed, "--help").stdout)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                self.assertEqual(first.wait(timeout=30), 0)
                self.assertEqual(second.wait(timeout=30), 0)
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)

    def test_concurrent_updates_cannot_overwrite_newer_version(self):
        installed = self.install()
        started = self.root / "started"
        release = self.root / "release"
        installer = self.remote / "install.sh"
        script = installer.read_text()
        installer.write_text(
            script.replace(
                "exec python3",
                'if [ -n "${DELAY_INSTALL:-}" ]; then\n'
                '    touch "$DELAY_INSTALL"\n'
                '    until [ -e "$RELEASE_INSTALL" ]; do sleep 0.05; done\n'
                "fi\nexec python3",
            )
        )
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "-am", "Slow installer")
        delayed_env = {**self.env, "DELAY_INSTALL": str(started), "RELEASE_INSTALL": str(release)}
        with subprocess.Popen([installed, "update"], cwd=self.caller, env=delayed_env) as older:
            try:
                deadline = time.monotonic() + 5
                while not started.exists() and older.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(started.exists(), "The first update did not start installing")
                self.publish_new_version()
                with subprocess.Popen([installed, "update"], cwd=self.caller, env=self.env) as newer:
                    try:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            newer.wait(timeout=1)
                    finally:
                        release.touch()
                    self.assertEqual(newer.wait(timeout=30), 0)
            finally:
                release.touch()
            self.assertEqual(older.wait(timeout=30), 0)
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)
