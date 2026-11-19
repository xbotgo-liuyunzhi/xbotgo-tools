---
name: git-chinese-commit
description: "生成符合目标 GitHub 仓库规范的中英结合 Git 提交信息：技术性名词使用英文，其余叙述使用中文；普通提交必须以具体业务模块作为 scope，未指定格式时默认使用 Conventional Commits，merge commit 保留默认 message。在撰写、建议、修改 commit message，或执行用户已授权的 Git commit、amend、merge、squash 且需要处理提交信息时使用，包括开发任务收尾阶段的提交。单纯查询 Git 状态、日志或编写 PR 描述时不触发。"
---

# Git 提交信息：中文叙述，英文技术名词

## 合并提交例外

- 创建真正的 merge commit 时，包括解决冲突后继续完成合并的情况，直接使用 Git 或合并平台自动生成的默认 message，保留标题与正文。不要翻译、添加 Conventional Commits 前缀或根据 diff 另写一条 message，也不要仅为本技能的语言或格式偏好 amend 已有 merge commit。
- 下文的中英结合与默认 Conventional Commits 规则适用于普通提交。squash 生成的普通 commit 仍按这些规则处理；fast-forward 不创建新 commit，无需另拟 message。
- 默认 merge message 若与仓库实际强制校验冲突，如实说明冲突，不自动改写默认 message 或绕过校验。

## 前提：符合 GitHub 与目标仓库规范

- GitHub 没有对所有仓库统一强制的 commit message 格式。Conventional Commits 是本技能的默认约定，不要将其、全英文要求或 50 / 72 字符建议宣称为 GitHub 的统一硬性规则。
- 先检查目标仓库相关的 AGENTS.md、CONTRIBUTING、commitlint 配置、commit-msg hook 和 CI 要求，确认 type、scope、长度、正则、issue 引用与 trailers 等实际约束；沿用明确的仓库规范。需要核对远程 ruleset 时使用 `gh`，规则不可见或未核验时如实说明，不阻碍先交付草稿。
- 仓库没有另行规定时，默认使用 Conventional Commits：`type(scope): 描述`。普通提交的 scope 必填，并遵循下文业务模块规则；type 使用小写英文，ASCII 冒号后留一个空格，描述遵循下文语言规则。常见 type 为 feat、fix、refactor、perf、docs、test、build、ci、chore、style；根据实际变更选择，不把功能变更归为仅格式调整的 style。
- 新功能使用 feat，缺陷修复使用 fix；只有真实的破坏性变更才使用 `type(scope)!:` 或 `BREAKING CHANGE: 说明`。正文与标题之间留空行，footer 与前面的正文之间也留空行；保留机器可读关键字的原始英文及必要大小写。
- GitHub issue 引用使用真实编号。同仓库可用 `#123`，跨仓库用 `owner/repo#123`；普通关联使用 `Refs: #123`。只有确实解决该 issue 且符合用户意图时才用 `Fixes #123` / `Closes #123` 等关闭关键词，不声称仅创建 commit 就已关闭 issue；关闭取决于 commit 合入默认分支等 GitHub 条件。
- 有实际可用的仓库 message 校验入口时按其规范验证，不临时安装校验依赖、修改 hooks / ruleset 或使用 `--no-verify` 来绕过要求。未执行校验时不声称已通过；如果语言偏好或指定原文与仓库硬性校验冲突，明确指出具体冲突，不悄悄违反规则或伪称两者兼容。

## scope：必须是具体业务模块

- 除上述 merge commit 例外，普通提交必须填写 scope，指向实际受影响的具体业务模块。此要求是用户约定，不宣称 GitHub 或 Conventional Commits 对所有项目都强制要求 scope。
- 根据实际 diff、项目模块结构与业务文档确定归属，沿用项目已有的英文模块名或标识；例如项目确有对应模块时可使用 `account-login`、`match-config`、`camera-pairing`、`training-report`。已有 scope 也要核实是否准确代表本次业务模块，不机械沿用历史泛称。
- 不单独使用 `ui`、`api`、`core`、`common`、`misc`、`all` 等泛称，也不以 `storage`、`cache` 等技术分层、框架名称、文件类型或改动类型替代业务模块。应表达具体业务归属，例如比赛配置的存储变更使用 `match-config`。
- 多模块变更有共同且具体的业务归属时，使用该业务模块；没有共同归属时说明范围并建议拆分，不用泛称凑 scope，也不擅自拆分提交或调整暂存区。无法从现有信息确认业务模块时，询问模块名称，不编造归属。
- 仓库仅允许省略 scope 时仍需填写；仓库采用其他格式时沿用其模块标记方式。若仓库强制格式无法表达业务模块 scope，说明具体冲突，不默默省略 scope 或修改仓库规则。

## 语言规则

- 标题和正文均以中文叙述变更、原因与影响；技术性名词使用原文或标准英文表达，不生成整句英文后再附中文翻译。
- 保留编程语言、框架、库、协议、工具和产品名，例如 C++、Swift、Qt、React、SQLite、GitHub、WebSocket、OAuth、JSON、REST API。
- 类名、函数名、变量名、配置键、命令、参数、路径、版本号、错误码和缩写保持准确拼写与大小写，例如 ConfigStore、refreshToken、TTL、HTTP 401。已有英文技术术语沿用项目中的表达，不音译或为其创造中文替代名。
- 修复、新增、移除、调整、重构、补充等动作及普通叙述使用中文。句子自然易读，不为混合语言而刻意插入英文，不把普通动词改写为 add / fix / update。
- 中文与英文术语之间通常留一个空格；标识符、路径、URL 及机器可读字段内部不加空格。提交信息使用纯文本，不添加 Markdown 代码围栏作为实际 message 的一部分。
- 用户当次明确指定其他语言或要求逐字使用某条 message 时，遵循该次要求；与仓库硬性校验冲突时按上述规则说明。

## 格式与内容

- 保留仓库已有格式和必要的 issue 编号。使用 Conventional Commits 时，type 与具体业务模块 scope 使用英文，冒号后的说明使用中文叙述与英文技术名词。
- 未规定格式时使用上述默认 Conventional Commits 格式，不另加固定字符上限或双语对照结构。仓库明确使用其他格式时遵循该格式。
- 根据实际 diff 撰写，突出做了什么及必要的原因，避免“更新代码”“修复问题”等空泛标题。实际提交以暂存区为准，可用 `git diff --cached` 核对；草拟未暂存改动时确认相应 diff 的范围，不把无关改动写入同一 message。
- 小改动通常只需标题；需要解释兼容性、迁移或设计取舍时再补正文，标题与正文之间留空行。正文遵循同一语言规则，不虚构测试结果、问题编号或未实现的功能。
- BREAKING CHANGE、Fixes、Co-authored-by、Signed-off-by 等仓库要求的机器可读标记保留原样，仅添加真实且有依据的内容。

## 示例

默认格式或仓库使用 Conventional Commits 时：

```text
fix(account-login): 修复 OAuth token 刷新失败时的重复请求
feat(match-config): 新增比赛配置的 SQLite 存储支持
refactor(camera-pairing): 统一 CameraPairingState 的 JSON 字段映射
test(training-report): 补充训练报告缓存的 TTL 过期用例
docs(video-export): 补充视频导出 REST API 的参数说明
```

这些示例只说明语言与格式；业务模块名必须以目标项目实际模块为准，不作为未查看 diff 时的提交内容。

## 规范依据

- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)：默认结构、type 和破坏性变更标记。
- [GitHub ruleset 可用规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)：仓库 / 组织可施加的 commit metadata 约束，以目标仓库实际启用规则为准。
- [GitHub issue 关联与关闭关键词](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)：引用及关闭条件。

## 执行边界

本技能规范提交信息，不额外授权暂存文件、合并分支、创建或修改 commit、改写历史、push，或更改 Git 配置与 hooks。用户只要求生成 message 时只交付文本；用户已授权提交时，在该范围内完成操作，不因使用本技能重复索要确认。
