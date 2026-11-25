import os
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from share.xbotgo import xbotgo_proxy


CLI = Path(__file__).resolve().parents[1] / "bin/xbotgo"
SYSTEM_SETTINGS = {
    "HTTPEnable": "1", "HTTPProxy": "127.0.0.1", "HTTPPort": "8118",
    "HTTPSEnable": "1", "HTTPSProxy": "127.0.0.1", "HTTPSPort": "8119",
    "SOCKSEnable": "1", "SOCKSProxy": "127.0.0.1", "SOCKSPort": "1080",
    "ExcludeSimpleHostnames": "1",
}


class ProxyTest(unittest.TestCase):
    def use_macos_settings(self, settings=SYSTEM_SETTINGS, exceptions=()):
        self.enter_patch(patch.object(xbotgo_proxy.platform, "system", return_value="Darwin"))
        self.enter_patch(patch.object(xbotgo_proxy, "read_system_proxy", return_value=(settings, exceptions)))

    def enter_patch(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_terminal_overrides_are_applied_per_protocol(self):
        self.use_macos_settings(exceptions=["*.system.invalid", "169.254/16"])
        terminal = {
            "http_proxy": "http://terminal.invalid:8000",
            "HTTP_PROXY": "http://other.invalid:8001",
            "NO_PROXY": "terminal.invalid",
            "GIT_SSH_COMMAND": "ssh -o ProxyJump=my-jump",
        }
        with patch.dict(os.environ, terminal, clear=True):
            with xbotgo_proxy.proxy_environment():
                self.assertEqual(os.environ["HTTP_PROXY"], terminal["http_proxy"])
                self.assertEqual(os.environ["https_proxy"], "http://127.0.0.1:8119")
                self.assertEqual(os.environ["no_proxy"], terminal["NO_PROXY"])
                self.assertEqual(os.environ["GIT_SSH_COMMAND"], terminal["GIT_SSH_COMMAND"])
                self.assertNotIn("GIT_SSH", os.environ)
            self.assertEqual(dict(os.environ), terminal)

    def test_macos_normalizes_exceptions_and_prefers_terminal_socks(self):
        self.use_macos_settings(exceptions=["*.local", "169.254/16"])
        with patch.dict(os.environ, {"ALL_PROXY": "socks5h://127.0.0.1:1081"}, clear=True):
            with xbotgo_proxy.proxy_environment():
                wrapper = Path(os.environ["GIT_SSH"])
                self.assertTrue(os.access(wrapper, os.X_OK))
                self.assertIn("127.0.0.1:1081", wrapper.with_name("ssh_config").read_text())
                self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:8119")
                self.assertEqual(os.environ["NO_PROXY"], ".local,169.254.0.0/16")
            self.assertNotIn("GIT_SSH", os.environ)
            self.assertFalse(wrapper.exists())

    def test_no_system_proxy_keeps_direct_connections(self):
        self.use_macos_settings(settings={})
        with patch.dict(os.environ, {}, clear=True), xbotgo_proxy.proxy_environment():
            self.assertEqual(dict(os.environ), {})

    def test_linux_keeps_its_existing_environment(self):
        terminal = {"http_proxy": "http://terminal.invalid:8000"}
        with patch.dict(os.environ, terminal, clear=True), \
             patch.object(xbotgo_proxy.platform, "system", return_value="Linux"), \
             patch.object(xbotgo_proxy, "read_system_proxy") as read:
            with xbotgo_proxy.proxy_environment():
                self.assertEqual(dict(os.environ), terminal)
            read.assert_not_called()

    def test_ssh_bypass_uses_effective_host_and_port(self):
        cases = [
            ("printer", 22, True), ("host.local", 22, True), ("169.254.1.2", 22, True),
            ("private.invalid", 443, True), ("private.invalid", 22, False), ("public.invalid", 22, False),
        ]
        for host, port, bypass in cases:
            with self.subTest(host=host, port=port), \
                 patch.dict(os.environ, {"no_proxy": ".local,169.254/16,private.invalid:443"}), \
                 patch.object(xbotgo_proxy.subprocess, "run") as run, \
                 patch.object(xbotgo_proxy.os, "execv") as execute:
                run.return_value = SimpleNamespace(returncode=0, stdout=f"hostname {host}\nport {port}\n")
                args = ["origin-alias", "git-upload-pack 'repo'"]

                xbotgo_proxy.run_ssh("/tmp/ssh-config", True, args)

                self.assertEqual(run.call_args.args[0], ["/usr/bin/ssh", "-G", *args])
                options = [] if bypass else ["-F", "/tmp/ssh-config"]
                execute.assert_called_once_with("/usr/bin/ssh", ["/usr/bin/ssh", *options, *args])

    @unittest.skipUnless(sys.platform == "darwin", "需要 macOS OpenSSH")
    def test_ssh_configuration_keeps_existing_jump_and_direct_routes(self):
        with TemporaryDirectory() as work:
            home = Path(work) / "test home"
            (home / ".ssh").mkdir(parents=True)
            (home / ".ssh/config").write_text(
                "Host with-jump.invalid\n  ProxyJump existing-jump.invalid\n  IdentityFile ~/.ssh/test-key\n"
                "Host direct.invalid\n  ProxyCommand none\n"
            )
            with patch.object(xbotgo_proxy.Path, "home", return_value=home):
                wrapper = xbotgo_proxy.write_ssh_wrapper(Path(work), "127.0.0.1:1080", False)
            config = wrapper.with_name("ssh_config")
            outputs = {
                host: subprocess.check_output(["/usr/bin/ssh", "-F", config, "-G", host], text=True,
                                              stderr=subprocess.DEVNULL)
                for host in ("with-jump.invalid", "direct.invalid", "default.invalid")
            }
        self.assertIn("proxyjump existing-jump.invalid", outputs["with-jump.invalid"])
        self.assertIn("identityfile ~/.ssh/test-key", outputs["with-jump.invalid"])
        self.assertNotIn("/usr/bin/nc", outputs["direct.invalid"])
        self.assertIn("proxycommand /usr/bin/nc -X 5 -x 127.0.0.1:1080", outputs["default.invalid"])

    def test_all_cli_paths_inherit_the_same_process_proxy(self):
        self.use_macos_settings(settings={**SYSTEM_SETTINGS, "SOCKSEnable": "0"})
        main = runpy.run_path(str(CLI))["main"]
        observed = []

        def record(*args, **kwargs):
            observed.append(os.environ.get("https_proxy"))

        modules = {
            "xbotgo_proxy": xbotgo_proxy,
            "xbotgo_commit": SimpleNamespace(commit_current_repository=record, push_current_repository=record),
            "xbotgo_pr": SimpleNamespace(create_pull_request=record),
        }
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, modules), \
             patch.object(sys, "path", list(sys.path)):
            for args in (["commit"], ["commit", "-p"], ["push"], ["pr", "develop"]):
                with patch.object(sys, "argv", [str(CLI), *args]):
                    self.assertEqual(main(), 0)
        self.assertEqual(observed, ["http://127.0.0.1:8119"] * 4)


if __name__ == "__main__":
    unittest.main()
