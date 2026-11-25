from contextlib import ExitStack, contextmanager
import ipaddress
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit


def read_system_proxy():
    result = subprocess.run(
        ["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, check=True, timeout=5,
    )
    settings, exceptions = {}, []
    sections = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line == "}" and sections:
            sections.pop()
            continue
        key, separator, value = line.partition(" : ")
        if line.endswith(("<dictionary> {", "<array> {")):
            sections.append(key if separator else "")
        elif separator and len(sections) == 1:
            settings[key] = value
        elif separator and sections == ["", "ExceptionsList"] and key.isdecimal():
            exceptions.append(value)
    return settings, exceptions


def proxy_address(host, port):
    if not host or port is None:
        return None
    port = int(port)
    if not 0 < port < 65536:
        return None
    if ":" in host:
        if "%" in host:
            return None
        try:
            host = f"[{ipaddress.IPv6Address(host)}]"
        except ValueError:
            return None
    elif not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
        return None
    return f"{host}:{port}"


def system_proxy_address(settings, protocol):
    port = settings.get(f"{protocol}Port", "")
    if settings.get(f"{protocol}Enable") == "1" and port.isdecimal():
        return proxy_address(settings.get(f"{protocol}Proxy"), port)
    return None


def explicit_proxy(name):
    return os.environ.get(name) or os.environ.get(name.upper())


def parse_all_proxy():
    value = explicit_proxy("all_proxy")
    if value:
        try:
            parsed = urlsplit(value if "://" in value else f"http://{value}")
            if parsed.hostname:
                return parsed
        except ValueError:
            pass
    return None


def normalize_exception(rule):
    if "/" in rule:
        address, _, prefix = rule.partition("/")
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", address):
            address += ".0" * (3 - address.count("."))
        try:
            return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
        except ValueError:
            return rule
    return rule.removeprefix("*") if rule.startswith("*.") else rule


def ssh_bypasses_proxy(host, port, exceptions, exclude_simple):
    host = host.lower().rstrip(".").strip("[]")
    if exclude_simple and "." not in host and ":" not in host:
        return True

    for rule in map(normalize_exception, map(str.strip, exceptions.split(","))):
        if rule == "*":
            return True
        if "/" in rule:
            try:
                if ipaddress.ip_address(host) in ipaddress.ip_network(rule):
                    return True
            except ValueError:
                pass
            continue
        try:
            if rule.count(":") > 1 and not rule.startswith("["):
                rule = f"[{rule}]"
            candidate = urlsplit(f"//{rule}")
            rule_port = candidate.port
        except ValueError:
            continue
        if candidate.hostname and (rule_port is None or rule_port == port):
            suffix = candidate.hostname.strip(".")
            if host == suffix or host.endswith(f".{suffix}"):
                return True
    return False


def write_ssh_wrapper(directory, address, exclude_simple):
    config = directory / "ssh_config"
    user_config = str(Path.home() / ".ssh/config").replace("\\", "\\\\").replace('"', '\\"')
    config.write_text(
        f'Include "{user_config}"\nInclude /etc/ssh/ssh_config\nHost *\n'
        f"    ProxyCommand /usr/bin/nc -X 5 -x {shlex.quote(address)} %h %p\n",
        encoding="utf-8",
    )
    wrapper = directory / "ssh"
    command = shlex.join((sys.executable, str(Path(__file__).resolve()), str(config), str(int(exclude_simple))))
    wrapper.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o700)
    return wrapper


def run_ssh(config, exclude_simple, args):
    ssh = "/usr/bin/ssh"
    exceptions = os.environ.get("no_proxy", "")
    options = ["-F", config]
    if exceptions or exclude_simple:
        result = subprocess.run(
            [ssh, "-G", *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
        if result.returncode == 0:
            effective = dict(
                line.split(" ", 1) for line in result.stdout.splitlines()
                if line.startswith(("hostname ", "port "))
            )
            if "hostname" in effective and ssh_bypasses_proxy(
                effective["hostname"], int(effective.get("port", "22")), exceptions, exclude_simple,
            ):
                options = []
    os.execv(ssh, [ssh, *options, *args])


@contextmanager
def proxy_environment():
    if platform.system() != "Darwin":
        yield
        return

    try:
        settings, exceptions = read_system_proxy()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        settings, exceptions = {}, []

    all_proxy = parse_all_proxy()
    web_proxy = all_proxy.geturl() if all_proxy and all_proxy.scheme in ("http", "https") else None
    overrides = {}
    for scheme in ("http", "https"):
        address = system_proxy_address(settings, scheme.upper())
        name = f"{scheme}_proxy"
        proxy = explicit_proxy(name) or web_proxy or (f"http://{address}" if address else None)
        if proxy:
            overrides[name] = overrides[name.upper()] = proxy

    no_proxy = os.environ.get("no_proxy", os.environ.get("NO_PROXY"))
    exclude_simple = no_proxy is None and settings.get("ExcludeSimpleHostnames") == "1"
    if no_proxy is not None or exceptions:
        bypass = no_proxy if no_proxy is not None else ",".join(map(normalize_exception, exceptions))
        overrides["no_proxy"] = overrides["NO_PROXY"] = bypass

    with ExitStack() as resources:
        ssh_variant = os.environ.get("GIT_SSH_VARIANT", "")
        has_ssh_command = os.environ.get("GIT_SSH_COMMAND") or os.environ.get("GIT_SSH")
        if not has_ssh_command and ssh_variant in ("", "auto", "ssh"):
            socks = None
            if all_proxy and all_proxy.scheme in ("socks5", "socks5h") and all_proxy.username is None:
                try:
                    socks = proxy_address(all_proxy.hostname, all_proxy.port or 1080)
                except ValueError:
                    pass
            socks = socks or system_proxy_address(settings, "SOCKS")
            if socks:
                directory = Path(resources.enter_context(TemporaryDirectory(prefix="xbotgo-ssh-")))
                overrides["GIT_SSH"] = str(write_ssh_wrapper(directory, socks, exclude_simple))

        previous = {name: os.environ.get(name) for name in overrides}
        os.environ.update(overrides)
        try:
            yield
        finally:
            for name, old_value in previous.items():
                if old_value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old_value


if __name__ == "__main__":
    run_ssh(sys.argv[1], sys.argv[2] == "1", sys.argv[3:])
