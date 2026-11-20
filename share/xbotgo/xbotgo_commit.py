import json
from pathlib import Path
from shutil import which
import subprocess
import sys
from tempfile import TemporaryDirectory


SKILL = Path(__file__).resolve().with_name("git-chinese-commit") / "SKILL.md"
APP_CODEX = Path(
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/"
    "CodexCLI.app/Contents/MacOS/codex"
)
MANUAL_COMMIT_HINT = '改动已暂存，可运行 xbotgo commit -m "提交说明" 手动提交。'
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": ["string", "null"]},
        "error": {"type": ["string", "null"]},
    },
    "required": ["message", "error"],
    "additionalProperties": False,
}


def draft_message(codex, repo, *, allow_missing_scope=False):
    with SKILL.open(encoding="utf-8"):
        pass
    scope_rule = (
        "本次是重试。仍优先使用能确认的具体业务 scope。"
        "无法确认且仓库没有强制要求 scope 时，可省略 scope，默认格式为 `type: 描述`。"
        "这个例外覆盖技能中 scope 必填的约定。若无法确认且仓库要求 scope，则返回错误。"
        if allow_missing_scope
        else "无法确定具体业务 scope 时，message 为 null，error 写明原因。"
    )
    prompt = f"""读取 {json.dumps(str(SKILL), ensure_ascii=False)}，按该技能为当前 Git 仓库的全部已暂存改动拟定一次提交的 message。
只读取暂存区 diff 和撰写 message 所需的本地仓库规则。跳过代码审查、测试、构建、额外校验和远端查询。
由外层命令执行 Git 提交。你只返回拟定的纯文本 message，保留必要的正文换行，error 为 null。
若技能文件无法读取或仓库规则冲突，message 为 null，error 写明原因。
{scope_rule}
"""
    with TemporaryDirectory(prefix="xbotgo-commit-") as directory:
        schema = Path(directory) / "schema.json"
        output = Path(directory) / "message.json"
        schema.write_text(json.dumps(RESULT_SCHEMA), encoding="utf-8")
        execution = subprocess.run(
            [
                codex, "exec", "--cd", str(repo), "--model", "gpt-6-luna",
                "--config", 'model_reasoning_effort="medium"',
                "--sandbox", "read-only", "--ephemeral", "--color", "never",
                "--output-schema", str(schema), "--output-last-message", str(output), "-",
            ],
            cwd=repo, input=prompt, encoding="utf-8", stdout=subprocess.DEVNULL,
        )
        if execution.returncode:
            raise RuntimeError(f"Codex CLI 退出码为 {execution.returncode}")
        result = json.loads(output.read_text(encoding="utf-8"))

    if not isinstance(result, dict):
        raise RuntimeError("Codex 返回的提交信息格式无效")
    if result.get("error"):
        raise RuntimeError(result["error"])
    message = result.get("message")
    if not isinstance(message, str) or not message.strip():
        raise RuntimeError("Codex 未返回提交信息")
    return message


def generate_message(repo):
    codex = which("codex")
    if not codex and APP_CODEX.is_file():
        codex = str(APP_CODEX)
    if not codex:
        raise RuntimeError(f"找不到 Codex CLI。{MANUAL_COMMIT_HINT}")

    try:
        return draft_message(codex, repo)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"首次生成提交信息失败（{error}），正在重试。", file=sys.stderr)

    try:
        return draft_message(codex, repo, allow_missing_scope=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(f"重试生成提交信息失败（{error}）。{MANUAL_COMMIT_HINT}") from error


def commit_current_repository(message=None, *, push=False):
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True)
    repo = Path(root.removesuffix("\n"))
    git = ["git", "-C", str(repo)]
    if subprocess.check_output([*git, "ls-files", "--unmerged", "-z"]):
        raise RuntimeError("暂存区存在未解决的冲突。")

    merging = subprocess.run(
        [*git, "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
        stdout=subprocess.DEVNULL,
    ).returncode
    if merging not in (0, 1):
        raise RuntimeError("无法读取 Git 合并状态。")

    subprocess.run([*git, "add", "-A"], check=True)
    if merging != 0:
        staged = subprocess.run([*git, "diff", "--cached", "--quiet"])
        if staged.returncode == 0:
            print("没有改动可提交。")
            return
        if staged.returncode != 1:
            staged.check_returncode()

    if message is not None:
        subprocess.run([*git, "commit", "-m", message], check=True)
    elif merging == 0:
        subprocess.run([*git, "commit", "--no-edit"], check=True)
    else:
        message = generate_message(repo)
        subprocess.run([*git, "commit", "-F", "-"], input=message, encoding="utf-8", check=True)

    subprocess.run([*git, "log", "-1", "--format=%H %s"], check=True)

    if push:
        try:
            subprocess.run([*git, "push"], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(
                f"本地提交已创建，推送失败（{error}）。处理 Git 报错后可运行 git push 重试。"
            ) from error
