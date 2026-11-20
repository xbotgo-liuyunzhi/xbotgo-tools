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
```

安装脚本会复用已安装且可用的 `pre-commit`。找不到可用命令时，脚本通过 pip 将它安装到 `xbotgo` 专用的 Python 虚拟环境中，并将 `pre-commit` 命令放到与 `xbotgo` 相同的 bin 目录。这一步需要 Python 提供 `venv` 和 `ensurepip`，并且能访问 pip 软件包源。

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

更新会使用当前命令所在的安装前缀，并复用可用的 `pre-commit`。如果旧版尚无 `update` 子命令，请先运行一次上面的 HTTPS 一键安装命令。使用自定义前缀的用户需在这次安装时设置原来的 `XBOTGO_INSTALL_PREFIX`。

## `xbotgo commit`

在目标 Git 仓库中运行：

```sh
xbotgo commit
xbotgo commit -m "提交说明"
```

- 通过 `git add -A` 纳入已暂存和未暂存的改动，包括未忽略的新文件和删除项。
- 指定 `-m` 时直接使用提供的提交信息，无需 Codex。未指定 `-m` 的 merge commit 使用 Git 默认提交信息。
- 自动生成提交信息时，用 `gpt-6-luna` 和 `medium` 推理强度按随包提供的 `git-chinese-commit` 规范拟定。Codex 会读取暂存区 diff 和必要的本地提交规则。生成失败时自动重试一次。重试时，无法确认具体 scope 且仓库允许省略时可用无 scope 的提交信息。重试失败后保留暂存改动，并提示用 `-m` 手动提交。
- 创建一次本地提交并输出完整哈希和标题。跳过审查、测试、构建和额外校验，沿用仓库现有 Git hooks，不执行 push。
