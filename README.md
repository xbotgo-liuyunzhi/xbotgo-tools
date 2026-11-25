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

macOS 上安装或更新时，如果在 `/Applications` 或 `~/Applications` 检测到 Fork，安装器会添加以下全局自定义命令，并保留已有命令。重新打开 Fork 后，按 `⌘P` 搜索命令。

- **XBotGo Commit All** 暂存当前仓库的全部改动，自动生成说明并创建本地提交。
- **XBotGo Push** 在当前仓库运行 `xbotgo push`，有改动时先自动提交，再按 Git 配置推送，并显示结果。
- **XBotGo Pull Request** 输入要合入的目标分支，可选填一位审核人的飞书姓名或完整邮箱，然后在当前仓库运行 `xbotgo pr`。
- **XBotGo Update** 运行 `xbotgo update`，更新当前安装的 XBotGo Tools。更新输出可在 Fork 的 Activity Manager 查看。

### 代理

macOS 上，`xbotgo` 和安装器优先使用已有的终端代理变量，缺失时读取系统网络设置中的 HTTP、HTTPS 和 SOCKS 代理。Fork 的自定义命令也使用这套规则。普通 Git SSH 连接使用 SOCKS，已有的 SSH 跳板、自定义命令和身份配置继续生效。Linux 继承现有代理环境。

`NO_PROXY` 优先于系统排除项。Web 请求按各工具支持的格式应用排除规则，短主机名可以在 `NO_PROXY` 中明确列出。Git SSH 也会按系统设置识别短主机名和 IP 网段。此版本支持静态代理配置。

## `xbotgo update`

在任意目录运行以下命令，将当前安装更新到 GitHub `main` 分支的最新版本。

```sh
xbotgo update
```

更新会使用当前命令所在的安装前缀，并补齐缺失的安装依赖。如果旧版尚无 `update` 子命令，请先运行一次上面的 HTTPS 一键安装命令。使用自定义前缀的用户需在这次安装时设置原来的 `XBOTGO_INSTALL_PREFIX`。

macOS 上更新成功后，如果 Fork 正在运行，系统会询问是否重启 Fork。按回车选择 **重启 Fork**，Fork 正常退出后会重新打开。按 Esc 选择 **稍后**，可继续当前工作。

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

在目标 Git 仓库中运行 `xbotgo push`。有未提交改动时，等同于 `xbotgo commit -p`，自动暂存改动、生成提交信息，并在提交成功后按 Git 配置推送。工作区干净时，直接推送已有提交。

## `xbotgo pr`

![1. 一条命令创建 PR。](docs/assets/pr-1-one-command-text-b45980.svg) 按需提交工作区改动并推送当前分支，再创建 GitHub PR。

![2. 自动写 PR 标题和正文。](docs/assets/pr-2-auto-description-text-b45980.svg) Codex 根据本次要合入的改动生成中文标题和 Markdown 正文。

![3. 指定审核人并发送通知。](docs/assets/pr-3-notify-reviewer-text-b45980.svg) 加 `-r` 可按飞书姓名或完整邮箱指定一位审核人，发起 GitHub 审核请求并发送飞书私信。

![4. 重试时复用已有 PR。](docs/assets/pr-4-reuse-on-retry-text-b45980.svg) 同一源分支和目标分支已有开放 PR 时，直接复用并继续执行指定的审核步骤。

在要提交 PR 的 Git 分支上运行，传入要合入的远端分支名。

```sh
xbotgo pr <目标分支>
xbotgo pr develop -r "张三"
xbotgo pr develop --reviewer zhangsan@example.com
```

- 需要登录 GitHub CLI（`gh auth login`），自动生成 PR 文案时还需要登录 Codex CLI。源分支和目标分支都位于当前分支的推送仓库。
- 有未提交改动时按 `xbotgo commit` 的规则提交，有未推送提交时根据当前分支的 Git 配置推送。当前分支没有远程跟踪关系时，推送会建立该关系。
- 创建 PR 时，Codex 根据远端目标分支与已推送的源分支之间的改动撰写文案。创建或复用 PR 后，标准输出的最后一行是 PR 链接。
- 指定 `-r` 或 `--reviewer` 时，需要以当前用户身份登录 `lark-cli`，并授权通讯录查询和私聊发送权限。命令在提交和推送前核对飞书联系人及 GitHub 账号。GitHub 账号需要公开与飞书通讯录一致的邮箱。遇到同名或联系人有多个邮箱时，请用唯一的完整邮箱指定审核人。
- 创建或复用 PR 后，先发起 GitHub 审核请求，再以当前飞书用户身份发送包含 PR 链接的私信。已有待处理的 GitHub 审核请求时，直接发送飞书通知。对同一审核人、PR 和提交，一小时内重试会使用同一个飞书幂等键。
- 中途失败时，已完成的提交和推送会保留。通知失败时，命令以非零状态退出，并在标准错误中指出失败渠道。处理报错后，可重新运行同一命令，继续通知已有的开放 PR。
