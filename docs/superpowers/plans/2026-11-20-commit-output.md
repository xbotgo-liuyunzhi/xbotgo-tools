# 精简 `xbotgo commit` 的终端输出实施计划

> 在当前会话使用 `superpowers:executing-plans` 逐步实施，并使用 `- [ ]` 跟踪完成的步骤。

**目标**　自动生成期间显示简短进度，提交成功后输出一行完整哈希和标题，两次生成失败后再显示详细诊断。

**实现**　用临时文件暂存每次 Codex 执行的标准错误。将暂存和创建 Git 提交的输出也暂存起来，在对应步骤失败时输出诊断。

**环境**　Python 3.9+、Git、`unittest`。

**设计**　[精简 `xbotgo commit` 的终端输出](../specs/2026-11-20-commit-output-design.md)

## 约束

- 进度立即写入标准错误流。提交结果写入标准输出流。
- 两次都失败时按尝试顺序打印各自原因和日志，给出 `-m` 手动提交提示，并保留暂存改动。
- `-p` 的推送阶段使用 Git 的终端输出和凭据交互。

## 验证重点

- 重试成功时，两个尝试的诊断均从终端输出隐藏。
- Codex 进程退出成功但返回错误或无效 JSON 时，仍记录尝试失败及其诊断。
- Git 钩子成功时产生的输出应收起。钩子拒绝提交时，其诊断可见，且 Git 不再请求 Codex。
- `-m` 和合并提交成功时都只输出一行结果。
- 当仓库启用 `log.showSignature` 时，签名提交的结果仍只有一行。

## 实施步骤

- [x] 在 `tests/test_commit.py` 的 Codex 替身里为每次尝试写入可区分的标准错误信息。添加首次成功测试，精确比对标准错误的生成进度和标准输出的 `%H %s`。扩充已有重试成功及两次失败测试，断言进度、诊断顺序、退出状态和暂存状态。
- [x] 扩充已有手动提交和钩子失败测试，并添加合并提交测试。检查成功时钩子输出已收起、失败时其输出可见，以及合并提交由 Git 生成标题。
- [x] 运行 `python3 -m unittest discover -s tests -p test_commit.py -v`，确认新增断言能检测旧版输出。
- [x] 在 `share/xbotgo/xbotgo_commit.py` 为 `draft_message(codex, repo, diagnostic_log, *, allow_missing_scope=False)` 接入每次尝试的临时文件。`generate_message(repo)` 保留原有重试条件，在两次均失败时才回放各自的诊断。
- [x] 在 `share/xbotgo/xbotgo_commit.py` 收集 `git add` 和 `git commit` 的输出并在失败时回放。三个提交入口共用 Git 提交执行逻辑，成功后用 `git --no-pager log -1 --format=%H %s` 输出结果。
- [x] 用启用 `log.showSignature` 的临时仓库复现签名诊断进入结果行的问题，并为结果查询加入 `--no-show-signature`。
- [x] 运行 `python3 -m unittest discover -s tests -v` 和 `git diff --check`，确认 19 项测试通过，diff 没有空白错误。
