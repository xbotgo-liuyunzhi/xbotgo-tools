from contextlib import ExitStack
import fcntl
import hashlib
from http.client import HTTPException
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


SOURCE = Path(__file__).resolve().parent
GH_VERSION = "2.105.0"
LARK_CLI_VERSION = "1.0.100"


def command_available(command, timeout=None):
    try:
        return subprocess.run(
            [command, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_pre_commit(bin_dir, share_dir):
    command = bin_dir / "pre-commit"
    if command_available(command) or command_available("pre-commit"):
        return

    venv = share_dir / "pre-commit-venv"
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    subprocess.run([venv / "bin" / "python", "-m", "pip", "install", "pre-commit"], check=True)
    venv_command = venv / "bin" / "pre-commit"
    subprocess.run([venv_command, "--version"], check=True)
    if not command_available(command):
        command.symlink_to(venv_command)


def cli_release(name):
    system = platform.system()
    machine = platform.machine().lower()
    architecture = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if system not in ("Darwin", "Linux") or not architecture:
        raise RuntimeError(f"{system} {machine} 不支持自动安装，请手动安装 {name} 后重试。")

    if name == "gh":
        os_name, extension = ("macOS", "zip") if system == "Darwin" else ("linux", "tar.gz")
        stem = f"gh_{GH_VERSION}_{os_name}_{architecture}"
        release_url = f"https://github.com/cli/cli/releases/download/v{GH_VERSION}"
        return release_url, f"{stem}.{extension}", f"gh_{GH_VERSION}_checksums.txt", f"{stem}/bin/gh"

    release_url = f"https://github.com/larksuite/cli/releases/download/v{LARK_CLI_VERSION}"
    filename = f"lark-cli-{LARK_CLI_VERSION}-{system.lower()}-{architecture}.tar.gz"
    return release_url, filename, "checksums.txt", "lark-cli"


def download_checked_archive(release_url, manifest, archive):
    with urlopen(f"{release_url}/{manifest}", timeout=60) as response:
        entries = [line.split(maxsplit=1) for line in response.read().decode("ascii").splitlines()]
    digests = [entry[0] for entry in entries if len(entry) == 2 and entry[1].strip().lstrip("*") == archive.name]
    if len(digests) != 1 or not re.fullmatch(r"[a-fA-F0-9]{64}", digests[0]):
        raise RuntimeError(f"找不到 {archive.name} 的有效 SHA-256 校验值。")

    digest = hashlib.sha256()
    with urlopen(f"{release_url}/{archive.name}", timeout=60) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != digests[0].lower():
        raise RuntimeError(f"{archive.name} SHA-256 校验失败。")


def extract_cli(archive, member, executable):
    with executable.open("wb") as output:
        if archive.suffix == ".zip":
            with ZipFile(archive) as package, package.open(member) as source:
                shutil.copyfileobj(source, output)
        else:
            with tarfile.open(archive, "r:gz") as package:
                entry = package.getmember(member)
                if not entry.isfile():
                    raise RuntimeError(f"{member} 不是普通文件。")
                with package.extractfile(entry) as source:
                    shutil.copyfileobj(source, output)
    executable.chmod(0o755)


def ensure_release_cli(bin_dir, name):
    destination = bin_dir / name
    if command_available(destination, timeout=5) or command_available(name, timeout=5):
        return
    try:
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"{destination} 已存在且无法运行，请修复该命令后重试。")
        release_url, filename, manifest, member = cli_release(name)
        print(f"正在下载 {filename}…", file=sys.stderr, flush=True)
        with TemporaryDirectory(prefix=f".{name}-", dir=bin_dir) as temporary:
            work = Path(temporary)
            archive = work / filename
            download_checked_archive(release_url, manifest, archive)
            executable = work / name
            extract_cli(archive, member, executable)
            if not command_available(executable, timeout=5):
                raise RuntimeError("下载的命令无法运行。")
            os.link(executable, destination)
    except (OSError, HTTPException, RuntimeError, ValueError, KeyError, EOFError, tarfile.TarError, BadZipFile) as error:
        raise RuntimeError(f"{name} 安装失败：{error}") from error


def install_files(bin_dir, share_dir):
    files = (
        (SOURCE / "share/xbotgo/xbotgo_commit.py", share_dir / "xbotgo_commit.py", 0o644),
        (SOURCE / "share/xbotgo/xbotgo_pr.py", share_dir / "xbotgo_pr.py", 0o644),
        (SOURCE / "share/xbotgo/git-chinese-commit/SKILL.md",
         share_dir / "git-chinese-commit" / "SKILL.md", 0o644),
        (None, share_dir / ".installed", 0o644),
        (SOURCE / "bin/xbotgo", bin_dir / "xbotgo", 0o755),
    )
    with ExitStack() as staging:
        ready = []
        for source, destination, mode in files:
            work = Path(staging.enter_context(
                TemporaryDirectory(prefix=".xbotgo-", dir=destination.parent)
            ))
            new = work / "new"
            if source is None:
                new.touch()
            else:
                shutil.copyfile(source, new)
            new.chmod(mode)

            backup = None
            if destination.is_symlink() or destination.exists():
                backup = work / "previous"
                shutil.copy2(destination, backup, follow_symlinks=False)
            ready.append((new, destination, backup))

        try:
            for new, destination, _ in ready:
                os.replace(new, destination)
        except (OSError, KeyboardInterrupt):
            for new, destination, backup in reversed(ready):
                try:
                    if new.exists():
                        continue
                    if backup is None:
                        destination.unlink()
                    else:
                        os.replace(backup, destination)
                except OSError as error:
                    print(f"还原 {destination} 失败：{error}", file=sys.stderr)
            raise


def install(prefix):
    if prefix == SOURCE:
        raise ValueError("请为 xbotgo 选择源码目录以外的安装位置。")

    bin_dir = prefix / "bin"
    share_dir = prefix / "share" / "xbotgo"
    share_dir.mkdir(parents=True, exist_ok=True)
    with (share_dir / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bin_dir.mkdir(parents=True, exist_ok=True)
        (share_dir / "git-chinese-commit").mkdir(exist_ok=True)
        ensure_pre_commit(bin_dir, share_dir)
        ensure_release_cli(bin_dir, "gh")
        ensure_release_cli(bin_dir, "lark-cli")
        install_files(bin_dir, share_dir)

    print(f"已安装 {bin_dir / 'xbotgo'}")
    if str(bin_dir) not in os.get_exec_path():
        print(f"请将 {bin_dir} 加入 PATH。")


def main():
    try:
        prefix = Path(os.environ.get("XBOTGO_INSTALL_PREFIX") or Path.home() / ".local")
        install(prefix.resolve())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"xbotgo 安装失败：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("xbotgo 安装已取消。", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
