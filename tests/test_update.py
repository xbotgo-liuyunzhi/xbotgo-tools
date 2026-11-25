import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile


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

        self.tools = self.root / "tools"
        self.tools.mkdir()
        for command in ("dirname", "git", "sleep", "touch"):
            (self.tools / command).symlink_to(shutil.which(command))
        (self.tools / "python3").symlink_to(sys.executable)
        self.pre_commit = self.write_tool("pre-commit", "pre-commit 1.2.3")
        self.write_tool("gh", "gh version existing")
        self.write_tool("lark-cli", "lark-cli version existing")
        self.write_tool("osascript", "osascript fixture")
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.tools),
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

    def write_tool(self, name, version, exit_code=0):
        tool = self.tools / name
        tool.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\nexit {exit_code}\n")
        tool.chmod(0o755)
        return tool

    def mock_cli_releases(self, system="Darwin"):
        release_dir = self.root / "releases"
        release_dir.mkdir()
        checksums = {"gh_2.105.0_checksums.txt": [], "checksums.txt": []}
        gh_stem = "gh_2.105.0_macOS_arm64" if system == "Darwin" else "gh_2.105.0_linux_amd64"
        gh_extension = ".zip" if system == "Darwin" else ".tar.gz"
        lark_platform = "darwin-arm64" if system == "Darwin" else "linux-amd64"
        for name, filename, member, manifest in (
            ("gh", gh_stem + gh_extension, f"{gh_stem}/bin/gh", "gh_2.105.0_checksums.txt"),
            ("lark-cli", f"lark-cli-1.0.100-{lark_platform}.tar.gz", "lark-cli", "checksums.txt"),
        ):
            script = "#!/bin/sh\n"
            if name == "gh":
                branch_ref = json.dumps({"ref": "refs/heads/develop", "object": {"sha": "0" * 40}})
                script += (
                    'if [ "$1" = api ]; then\n'
                    f"    printf '%s\\n' '{branch_ref}'\n"
                    '    exit 0\n'
                    'fi\n'
                )
            payload = (script + f"printf '%s\\n' '{name} version downloaded'\n").encode()
            archive = release_dir / filename
            if filename.endswith(".zip"):
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr(member, payload)
            else:
                with tarfile.open(archive, "w:gz") as output:
                    info = tarfile.TarInfo(member)
                    info.size = len(payload)
                    output.addfile(info, io.BytesIO(payload))
            checksums[manifest].append(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {filename}\n")
        for name, lines in checksums.items():
            (release_dir / name).write_text("".join(lines))

        self.downloads = self.root / "downloads"
        fake_network = self.root / "fake_network"
        fake_network.mkdir()
        (fake_network / "sitecustomize.py").write_text('''import os
from pathlib import Path
import platform
import urllib.request
from urllib.parse import urlsplit

def download(url, **kwargs):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith((
        "/cli/cli/releases/download/v2.105.0/", "/larksuite/cli/releases/download/v1.0.100/",
    )):
        raise AssertionError(f"Unexpected release URL: {url}")
    filename = parsed.path.rsplit("/", 1)[-1]
    with Path(os.environ["TEST_DOWNLOADS"]).open("a") as log:
        print(filename, file=log)
    return (Path(os.environ["TEST_RELEASES"]) / filename).open("rb")

platform.system = lambda: os.environ["TEST_RELEASE_SYSTEM"]
platform.machine = lambda: "arm64" if platform.system() == "Darwin" else "x86_64"
urllib.request.urlopen = download
''')
        self.env.update(PYTHONPATH=str(fake_network), TEST_RELEASES=str(release_dir),
                        TEST_DOWNLOADS=str(self.downloads), TEST_RELEASE_SYSTEM=system)
        return release_dir

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

    def mock_fork(self):
        contents = self.home / "Applications/Fork.app/Contents"
        contents.mkdir(parents=True)
        (contents / "Info.plist").touch()
        return self.home / "Library/Application Support/com.DanPristupov.Fork/custom-commands.json"

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

    @unittest.skipUnless(sys.platform == "darwin", "需要 macOS")
    def test_update_requests_fork_restart_only_after_success(self):
        installed = self.install()
        request = self.root / "fork-restart-request"
        osascript = self.tools / "osascript"
        osascript.write_text(r'''#!/bin/sh
printf '%s\n' "$@" > "$TEST_FORK_RESTART_REQUEST"
''', encoding="utf-8")
        env = {**self.env, "TEST_FORK_RESTART_REQUEST": str(request)}
        self.remote.rename(self.root / "offline")

        result = self.run_command(installed, "update", env=env, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(request.exists())
        (self.root / "offline").rename(self.remote)
        result = self.run_command(installed, "update", env=env)

        self.assertIn("已更新", result.stdout)
        deadline = time.monotonic() + 3
        while not request.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(request.is_file())
        helper = installed.parent.parent / "share/xbotgo/fork_restart.js"
        self.assertTrue(helper.is_file())
        self.assertEqual(request.read_text(encoding="utf-8").splitlines(), ["-l", "JavaScript", str(helper)])

    @unittest.skipUnless(sys.platform == "darwin", "需要 macOS")
    def test_fork_restart_uses_process_exit_even_when_app_state_is_stale(self):
        helper = (SOURCE / "share/xbotgo/fork_restart.js").read_text(encoding="utf-8")
        fixture = """
function exercise(modalResponse) {
    let running = true;
    let opened = false;
    const buttons = [];
    const fork = {processIdentifier: 42, isTerminated: false, terminate: true, bundleURL: {path: "/Fork.app"}};
    const runningApps = {count: 1, firstObject: fork, objectAtIndex() { return fork; }};
    const objc = {import() {}, bindFunction() {}, unwrap(value) { return value; }};
    const bridge = Object.assign(values => values, {
        kill(pid, signal) { return pid === 42 && signal === 0 && running ? 0 : -1; },
        NSRunningApplication: {runningApplicationsWithBundleIdentifier() { return runningApps; }},
        NSApplication: {sharedApplication: {setActivationPolicy() {}, activateIgnoringOtherApps() {}}},
        NSApplicationActivationPolicyAccessory: "1",
        NSAlertFirstButtonReturn: "1000",
        NSAlertSecondButtonReturn: "1001",
        NSAlert: {alloc: {init: {
            runModal: modalResponse,
            addButtonWithTitle(title) {
                const button = {title};
                buttons.push(button);
                return button;
            }
        }}},
        NSDate: {dateWithTimeIntervalSinceNow() {
            return {get timeIntervalSinceNow() { return running ? 1 : 0; }};
        }},
        NSRunLoop: {currentRunLoop: {runUntilDate() { running = false; }}},
        NSTask: {alloc: {init: {
            setLaunchPath(path) { if (path !== "/usr/bin/open") throw Error("bad launcher"); },
            setArguments(args) { if (args[0] !== "-a" || args[1] !== "/Fork.app") throw Error("bad launch"); },
            get launch() { opened = true; }
        }}}
    });
    new Function("ObjC", "$", SOURCE + "\\nrun();")(objc, bridge);
    return {opened, buttons};
}
function run() {
    return JSON.stringify([exercise(1000), exercise(1001)]);
}
"""
        script = "const SOURCE = " + json.dumps(helper) + ";\n" + fixture
        result = self.run_command("/usr/bin/osascript", "-l", "JavaScript", "-e", script)
        confirmed, deferred = json.loads(result.stdout)
        self.assertEqual(confirmed["buttons"], [
            {"title": "重启 Fork"}, {"title": "稍后", "keyEquivalent": "\x1b"},
        ])
        self.assertTrue(confirmed["opened"])
        self.assertFalse(deferred["opened"])

    def test_installer_and_updater_pass_macos_proxy_to_children(self):
        hooks = self.root / "proxy-fixture"
        hooks.mkdir()
        events = self.root / "proxy-events"
        (hooks / "sitecustomize.py").write_text('''import json
import os
import platform
import subprocess

run = subprocess.run
platform.system = lambda: "Darwin"

def run_with_proxy_fixture(args, **kwargs):
    if args == ["/usr/sbin/scutil", "--proxy"]:
        settings = """<dictionary> {
  ExceptionsList : <array> {
    0 : *.example.invalid
  }
  HTTPEnable : 1
  HTTPProxy : 127.0.0.1
  HTTPPort : 8118
  HTTPSEnable : 1
  HTTPSProxy : 127.0.0.1
  HTTPSPort : 8119
}
"""
        return subprocess.CompletedProcess(args, 0, stdout=settings)
    clone = args[:2] == ["git", "clone"]
    retry = args[:4] == ["git", "-c", "http.version=HTTP/1.1", "clone"]
    if clone or retry or args[:2] == ["pre-commit", "--version"]:
        env = kwargs.get("env", os.environ)
        keys = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        with open(os.environ["TEST_PROXY_EVENTS"], "a", encoding="utf-8") as log:
            operation = "git retry" if retry else args[0]
            print(json.dumps([operation, [env.get(key) for key in keys]]), file=log)
    if clone:
        return subprocess.CompletedProcess(args, 128, stderr="Error in the HTTP2 framing layer")
    return run(args, **kwargs)

subprocess.run = run_with_proxy_fixture
''', encoding="utf-8")
        self.env = {key: value for key, value in self.env.items() if not key.lower().endswith("_proxy")}
        self.env.update(PYTHONPATH=str(hooks), TEST_PROXY_EVENTS=str(events))

        installed = self.install()
        self.run_command(installed, "update")

        values = ["http://127.0.0.1:8118", "http://127.0.0.1:8119"] * 2 + [".example.invalid"]
        observed = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        self.assertIn(["pre-commit", values], observed)
        self.assertIn(["git", values], observed)
        self.assertIn(["git retry", values], observed)

    def test_install_creates_fork_commands_for_custom_prefix_once(self):
        self.mock_cli_releases()
        config = self.mock_fork()
        prefix = self.root / "custom 'prefix $name"

        installed = self.install(prefix)
        self.assertTrue(config.is_file())
        original = config.read_bytes()
        commands = json.loads(original)
        self.assertEqual(len(commands), 5)
        version, commit, push, update, pull_request = commands
        self.assertEqual(version, {"version": 2})
        self.assertEqual(commit["name"], "XBotGo Commit All")
        self.assertEqual(push["name"], "XBotGo Push")
        self.assertEqual(update["name"], "XBotGo Update")
        self.assertEqual(pull_request["name"], "XBotGo Pull Request")
        for command in (commit, push, update):
            self.assertEqual(command["target"], "repository")
            self.assertEqual(command["action"]["type"], "sh")
            self.assertTrue(command["action"]["waitForExit"])
        self.assertTrue(commit["action"]["showOutput"])
        self.assertTrue(push["action"]["showOutput"])
        self.assertFalse(update["action"]["showOutput"])
        result = subprocess.run(
            ["/bin/bash", "-c", commit["action"]["script"]], cwd=self.remote, env=self.env,
            text=True, capture_output=True, check=True, timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "没有改动可提交。")

        destination = self.root / "push-destination.git"
        self.run_command("git", "init", "--quiet", "--bare", destination)
        self.git("remote", "add", "origin", str(destination))
        self.git("config", "remote.origin.push", "refs/heads/main:refs/heads/main")
        subprocess.run(
            ["/bin/bash", "-c", push["action"]["script"]], cwd=self.remote, env=self.env,
            text=True, capture_output=True, check=True, timeout=30,
        )
        self.assertEqual(
            self.run_command("git", "--git-dir", destination, "rev-parse", "refs/heads/main").stdout,
            self.run_command("git", "-C", self.remote, "rev-parse", "HEAD").stdout,
        )

        self.publish_new_version()
        result = self.run_command("/bin/bash", "-c", update["action"]["script"])
        self.assertIn("已更新", result.stdout)
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)
        self.assertEqual(config.read_bytes(), original)

        self.install(prefix)
        self.assertEqual(config.read_bytes(), original)

    def test_fork_pull_request_passes_native_dialog_text_to_cli(self):
        self.mock_cli_releases()
        config = self.mock_fork()
        installed = self.install(self.root / "custom 'prefix $name")
        commands = json.loads(config.read_bytes())
        command = next((item for item in commands if item.get("name") == "XBotGo Pull Request"), None)
        self.assertIsNotNone(command)
        self.assertEqual(command["target"], "repository")
        dialog = command["ui"]
        self.assertEqual(dialog["title"], "XBotGo Pull Request")
        self.assertEqual(
            [(field["title"], field["type"], field["textBoxType"], field["text"]) for field in dialog["controls"]],
            [("目标分支", "textBox", "generic", ""), ("审核人", "textBox", "generic", "")],
        )
        self.assertEqual(dialog["controls"][1]["placeholder"], "飞书姓名或完整邮箱（可选）")
        confirm, cancel = dialog["buttons"]
        self.assertEqual(cancel["action"], {"type": "cancel"})
        action = confirm["action"]
        self.assertEqual(action["type"], "process")
        self.assertTrue(action["waitForExit"])

        installed.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n', encoding="utf-8")
        for reviewer in ("", "   ", "周明", "Alex Chen", "reviewer@example.invalid", "O'Connor $name"):
            with self.subTest(reviewer=reviewer):
                arguments = [token.replace("$1{text}", "release/1.2").replace("$2{text}", reviewer)
                             for token in action["args"].split()]
                result = self.run_command(action["path"], *arguments)
                reviewer_args = [f"--reviewer={reviewer}"] if reviewer.strip() else []
                self.assertEqual(result.stdout.splitlines(), [str(self.caller), "pr", *reviewer_args, "--", "release/1.2"])

        for branch in ("", "   "):
            with self.subTest(branch=branch):
                arguments = [token.replace("$1{text}", branch).replace("$2{text}", "")
                             for token in action["args"].split()]
                result = self.run_command(action["path"], *arguments, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("请输入目标分支", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_update_adds_fork_command_and_preserves_existing_commands(self):
        self.mock_cli_releases("Linux")
        config = self.mock_fork()
        installed = self.install()
        self.assertFalse(config.exists())
        self.env["TEST_RELEASE_SYSTEM"] = "Darwin"
        existing = [
            {"version": 2},
            {"name": "查看状态", "target": "repository", "action": {"type": "sh", "script": "git status"}},
            {"name": "XBotGo Commit All", "target": "repository",
             "action": {"type": "sh", "script": "echo customized commit"}},
        ]
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        config.chmod(0o640)

        self.run_command(installed, "update")
        commands = json.loads(config.read_bytes())
        self.assertEqual(commands[:-3], existing)
        push, update, pull_request = commands[-3:]
        self.assertEqual([push["name"], update["name"], pull_request["name"]],
                         ["XBotGo Push", "XBotGo Update", "XBotGo Pull Request"])
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)

        update["action"]["script"] = "echo customized"
        update["action"]["showOutput"] = True
        pull_request["ui"]["title"] = "自定义 PR 对话框"
        pull_request["ui"]["controls"][1].update(title="审核人 Reviewer（可选）", placeholder="飞书姓名或完整邮箱")
        customized = json.dumps(commands).encode()
        config.write_bytes(customized)
        self.run_command(installed, "update")
        self.assertEqual(config.read_bytes(), customized)

    def test_update_migrates_existing_managed_fork_commands(self):
        self.mock_cli_releases()
        config = self.mock_fork()
        installed = self.install()
        current = config.read_bytes()
        commands = json.loads(current)
        update = next(item for item in commands if item.get("name") == "XBotGo Update")
        update["action"]["showOutput"] = True
        pull_request = next(item for item in commands if item.get("name") == "XBotGo Pull Request")
        pull_request["ui"]["controls"][1].update(title="审核人 Reviewer（可选）", placeholder="飞书姓名或完整邮箱")
        config.write_text(json.dumps(commands), encoding="utf-8")

        self.run_command(installed, "update")

        self.assertEqual(json.loads(config.read_bytes()), json.loads(current))

    def test_install_warns_and_preserves_invalid_fork_config(self):
        self.mock_cli_releases()
        config = self.mock_fork()
        config.parent.mkdir(parents=True)
        config.write_bytes(b"invalid JSON")

        result = self.run_command(SOURCE / "install.sh")

        self.assertIn("Fork 自定义命令安装失败", result.stderr)
        self.assertEqual(config.read_bytes(), b"invalid JSON")
        installed = self.home / ".local/bin/xbotgo"
        self.assertEqual(self.run_command(installed, "commit", "--help").returncode, 0)

    def test_install_only_downloads_missing_cli_and_reuses_it_on_update(self):
        self.mock_cli_releases("Linux")
        (self.tools / "lark-cli").unlink()
        installed = self.install()
        downloaded = installed.parent / "lark-cli"

        self.assertEqual(self.run_command(downloaded, "--version").stdout.strip(), "lark-cli version downloaded")
        self.assertFalse((installed.parent / "gh").exists())
        requests = self.downloads.read_text().splitlines()
        self.assertCountEqual(requests, ["checksums.txt", "lark-cli-1.0.100-linux-amd64.tar.gz"])

        self.run_command(installed, "update")
        self.assertEqual(self.downloads.read_text().splitlines(), requests)

    def test_update_repairs_missing_clis_in_custom_prefix(self):
        self.mock_cli_releases()
        installed = self.install(self.root / "custom prefix")
        self.assertFalse(self.downloads.exists())
        for name in ("gh", "lark-cli"):
            (self.tools / name).unlink()
        self.publish_new_version()

        self.run_command(installed, "update")

        for name in ("gh", "lark-cli"):
            self.assertEqual(self.run_command(installed.parent / name, "--version").stdout.strip(),
                             f"{name} version downloaded")
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)
        for name in ("gh", "lark-cli"):
            self.write_tool(name, "broken PATH wrapper", exit_code=1)
        self.git("remote", "add", "team", "git@github.com:xbotgo/team.git")
        pr = subprocess.run([installed, "pr", "develop", "-r", "张三"], cwd=self.remote, env=self.env,
                            text=True, capture_output=True, timeout=30)
        self.assertIn("飞书审核人查询失败", pr.stderr)
        self.assertIn("lark-cli 返回的响应无效", pr.stderr)

    def test_install_repairs_broken_external_command(self):
        self.mock_cli_releases()
        outside = self.write_tool("lark-cli", "broken PATH wrapper", exit_code=1)
        previous = outside.read_bytes()

        installed = self.install()

        self.assertTrue((installed.parent / "lark-cli").is_file())
        self.assertEqual(outside.read_bytes(), previous)

    def test_install_preserves_occupied_dependency_path(self):
        self.mock_cli_releases()
        (self.tools / "gh").unlink()
        prefix = self.root / "custom prefix"
        bin_dir = prefix / "bin"
        bin_dir.mkdir(parents=True)
        occupied = bin_dir / "gh"
        occupied.write_text("existing file")
        env = {**self.env, "XBOTGO_INSTALL_PREFIX": str(prefix)}

        result = self.run_command(SOURCE / "install.sh", env=env, check=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn(str(occupied), result.stderr)
        self.assertEqual(occupied.read_text(), "existing file")
        self.assertFalse(self.downloads.exists())

    def test_invalid_cli_archive_preserves_installed_xbotgo_for_retry(self):
        release_dir = self.mock_cli_releases()
        installed = self.install()
        previous_cli = installed.read_bytes()
        self.publish_new_version()
        for name in ("gh", "lark-cli"):
            (self.tools / name).unlink()
        manifest = release_dir / "checksums.txt"
        valid = manifest.read_text()
        manifest.write_text(f"{'0' * 64}  lark-cli-1.0.100-darwin-arm64.tar.gz\n")

        result = self.run_command(installed, "update", check=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("lark-cli", result.stderr)
        self.assertIn("SHA-256", result.stderr)
        self.assertEqual(installed.read_bytes(), previous_cli)
        self.assertTrue((installed.parent / "gh").is_file())
        self.assertFalse((installed.parent / "lark-cli").exists())

        manifest.write_text(valid)
        self.run_command(installed, "update")
        lark = installed.parent / "lark-cli"
        self.assertEqual(self.run_command(lark, "--version").stdout.strip(), "lark-cli version downloaded")
        self.assertEqual(self.downloads.read_text().splitlines().count("gh_2.105.0_macOS_arm64.zip"), 1)

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

    def test_update_retries_http2_failure_with_http11(self):
        installed = self.install()
        self.publish_new_version()
        transport = self.root / "transport"
        transport.mkdir()
        git = transport / "git"
        git.write_text(r'''#!/bin/sh
if [ "$1" = clone ]; then
    printf '%s\n' default >> "$TEST_CLONE_ATTEMPTS"
    /bin/mkdir "$7"
    touch "$7/partial"
    printf '%s\n' 'fatal: Error in the HTTP2 framing layer' >&2
    exit 128
fi
if [ "$1" = -c ] && [ "$2" = http.version=HTTP/1.1 ] && [ "$3" = clone ]; then
    printf '%s\n' HTTP/1.1 >> "$TEST_CLONE_ATTEMPTS"
fi
exec "$TEST_REAL_GIT" "$@"
''')
        git.chmod(0o755)
        attempts = self.root / "clone-attempts"
        env = {
            **self.env,
            "PATH": f"{transport}{os.pathsep}{self.env['PATH']}",
            "TEST_CLONE_ATTEMPTS": str(attempts),
            "TEST_REAL_GIT": str(self.tools / "git"),
        }

        result = self.run_command(installed, "update", env=env, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP/1.1", result.stderr)
        self.assertEqual(attempts.read_text().splitlines(), ["default", "HTTP/1.1"])
        self.assertIn("XBotGo 更新测试版本", self.run_command(installed, "--help").stdout)

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
