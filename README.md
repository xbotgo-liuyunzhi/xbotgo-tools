# XBotGo Tools

XBotGo 团队命令行工具。用 `xbotgo --help` 查看可用子命令。

## 安装

需要 Git 和 Python 3.9 或更新版本。自动生成提交信息还需要已登录的 Codex CLI，以及能使用 `gpt-6-luna` 的账号或工作区。每位使用者使用自己的 Codex 登录。[Codex CLI 安装说明](https://learn.chatgpt.com/docs/codex/cli)

在任意目录运行以下命令即可通过 HTTPS 安装，无需 GitHub 登录或 SSH 密钥。

```sh
(install_dir=$(mktemp -d) && trap 'rm -rf "$install_dir"' EXIT && git clone --depth 1 --branch main https://github.com/xbotgo-liuyunzhi/xbotgo-tools.git "$install_dir" && "$install_dir/install.sh")
```

如果已经克隆仓库，可以在仓库根目录运行 `./install.sh`。安装后可用以下命令验证。

```sh
xbotgo --help
pre-commit --version
gh --version
lark-cli --version
```

安装脚本会复用已安装且可用的 `pre-commit`。找不到可用命令时，脚本通过 pip 将它安装到 `xbotgo` 专用的 Python 虚拟环境中，并将 `pre-commit` 命令放到与 `xbotgo` 相同的 bin 目录。这一步需要 Python 提供 `venv` 和 `ensurepip`，并且能访问 pip 软件包源。

安装和更新会复用 `PATH` 或安装前缀的 `bin` 目录中可用的 `gh` 和 `lark-cli`。缺少命令时，macOS 和 Linux 的 x86_64、ARM64 环境会从官方发行页下载对应二进制，校验 SHA-256 后放到 `xbotgo` 的 `bin` 目录。首次使用 PR 功能时，请按下文完成登录和授权。[GitHub CLI 发行页](https://github.com/cli/cli/releases) · [飞书 CLI 发行页](https://github.com/larksuite/cli/releases)

默认将命令安装到 `~/.local/bin`，将工具和提交规范安装到 `~/.local/share/xbotgo`。如果 shell 找不到命令，把下面这行加入 shell 配置后重新打开终端：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

可通过 `XBOTGO_INSTALL_PREFIX` 指定其他安装前缀。

## `xbotgo update`

在任意目录运行以下命令，将当前安装更新到 GitHub `main` 分支的最新版本。

```sh
xbotgo update
```

更新会使用当前命令所在的安装前缀，并补齐缺失的安装依赖。如果旧版尚无 `update` 子命令，请先运行一次上面的 HTTPS 一键安装命令。使用自定义前缀的用户需在这次安装时设置原来的 `XBOTGO_INSTALL_PREFIX`。

## `xbotgo commit`

![1. 自动写提交说明。](docs/assets/commit-1-auto-message-text-b45980.svg) Codex 根据暂存区 diff 撰写说明，也可以用 `-m` 提供自己的说明。

![2. 统一团队提交格式。](docs/assets/commit-2-consistent-format-text-b45980.svg) 优先遵循仓库规则，默认使用 `type(scope): 中文说明`，技术名词保留英文。

![3. 一条命令完成提交。](docs/assets/commit-3-one-command-text-b45980.svg) 自动暂存整个仓库的改动，沿用 Git hooks，提交后分两行输出完整哈希和标题。加 `-p` 可在提交成功后推送。

![4. 节省 token 和等待时间。](docs/assets/commit-4-save-time-text-b45980.svg) 使用 `gpt-6-luna` 和中等（`medium`）推理强度，聚焦暂存区 diff 和必要的提交规则。

![把琢磨 commit message 的脑力活交给 AI。](docs/assets/commit-ai-summary-text-b45980.svg) 可以运行 `git log --oneline`，参考本仓库的提交历史。

在目标 Git 仓库中运行：

```sh
xbotgo commit
xbotgo commit -m "提交说明"
xbotgo commit -p
xbotgo commit -p -m "提交说明"
```

- 通过 `git add -A` 纳入已暂存和未暂存的改动，包括未忽略的新文件和删除项。
- 指定 `-m` 时直接使用提供的提交信息，无需 Codex。未指定 `-m` 的 merge commit 使用 Git 默认提交信息。
- 自动生成提交信息时，用 `gpt-6-luna` 和 `medium` 推理强度按随包提供的 `git-chinese-commit` 规范拟定。Codex 会读取暂存区 diff 和必要的本地提交规则。生成失败时自动重试一次。重试时，无法确认具体 scope 且仓库允许省略时可用无 scope 的提交信息。重试失败后保留暂存改动，并提示用 `-m` 手动提交。
- 创建一次本地提交。终端分两行显示黄色加粗的完整 SHA 和粉色加粗的提交标题。通过管道或重定向时输出两行纯文本。跳过审查、测试、构建和额外校验，沿用仓库现有 Git hooks。
- 指定 `-p` 或 `--push` 时，在提交成功后执行 `git push`，推送目标由 Git 配置决定。推送失败时保留本地提交，可单独运行 `xbotgo push` 重试。

## `xbotgo push`

在目标 Git 仓库中运行 `xbotgo push`，按 Git 配置将已有提交推送到远端。命令保留工作区和暂存区的改动。

## `xbotgo pr`

在要提交 PR 的 Git 分支上运行，参数是要合入的远端分支名。

```sh
xbotgo pr <目标分支>
xbotgo pr develop -r "张三"
xbotgo pr develop --reviewer zhangsan@example.com
```

需要已登录的 GitHub CLI（`gh auth login`）和 Codex CLI。源分支和目标分支位于当前分支的推送仓库。若有未提交改动，先按 `xbotgo commit` 的规则提交。若有未推送的提交，再通过 `xbotgo push` 推送当前分支。首次推送会建立远程跟踪关系。

Codex 根据目标分支与已推送提交之间的改动生成中文标题和 Markdown 正文，随后直接创建 PR。已有相同源分支和目标分支的开放 PR 时，复用该 PR。取得 PR 链接后，标准输出的最后一行是该链接。

`-r` 或 `--reviewer` 接受一位审核人的飞书姓名或完整邮箱。使用时需要以当前用户身份登录 `lark-cli`，并授权通讯录查询和私聊发送权限。命令在提交和推送前核对飞书联系人及 GitHub 账号。GitHub 账号需公开与飞书通讯录一致的邮箱。同名或联系人有多个邮箱时，请用唯一的完整邮箱指定审核人。

创建或复用 PR 后，命令发起 GitHub 审核请求，再以当前飞书用户身份发送包含 PR 链接的私信。已有待处理的 GitHub 审核请求时，直接进入飞书通知步骤。对同一审核人、PR 和提交，一小时内重试使用同一个飞书幂等键。

如果中途失败，已完成的提交和推送会保留。通知失败时，命令以非零状态退出，并在标准错误中说明失败渠道。处理报错后，可以重新运行同一命令，继续通知已有的开放 PR。
