import fcntl
import os
from contextlib import ExitStack
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


SOURCE = Path(__file__).resolve().parent


def pre_commit_available(command):
    try:
        return subprocess.run(
            [command, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def ensure_pre_commit(bin_dir, share_dir):
    command = bin_dir / "pre-commit"
    if pre_commit_available(command) or pre_commit_available("pre-commit"):
        return

    venv = share_dir / "pre-commit-venv"
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    subprocess.run([venv / "bin" / "python", "-m", "pip", "install", "pre-commit"], check=True)
    venv_command = venv / "bin" / "pre-commit"
    subprocess.run([venv_command, "--version"], check=True)
    if not pre_commit_available(command):
        command.symlink_to(venv_command)


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
        install_files(bin_dir, share_dir)

    print(f"已安装 {bin_dir / 'xbotgo'}")
    if str(bin_dir) not in os.get_exec_path():
        print(f"请将 {bin_dir} 加入 PATH。")


def main():
    try:
        prefix = Path(os.environ.get("XBOTGO_INSTALL_PREFIX") or Path.home() / ".local")
        install(prefix.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"xbotgo 安装失败：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("xbotgo 安装已取消。", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
