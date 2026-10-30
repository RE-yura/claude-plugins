---
name: delegating-to-codex
description: Use when delegating implementation, fixes, or refactoring to Codex CLI, when Claude has finished an implementation plan, or when the user says 「Codex に実装を委譲して」「Codex にやらせて」「herdr 経由で」「herdr-core (hc) 経由で」.
---

# Codex への実装委譲

Claude は設計・計画・レビュー・検証・承認、Codex は実装・テスト・修正を担当する。
Python 3.11+、hc 0.1.x、codex-cli 0.164.0 以降が必要。hook はない。
skill loader が表示する Base directory を以下の `<Base directory>` に入れる。
`cdx` は各コマンドの結果を JSON 1 行、進行表示は Herdr の terminal に出す。
状態は `<worktree>/.ai/tasks/<task_id>/state.json`。シェル変数に頼らない。

## 手順

1. 依存の版、hc core の接続・版、プラグイン scope の重複を確認する。

   ```bash
   "<Base directory>/cdx" doctor
   "<Base directory>/cdx" start --name <n>
   ```

   n は a-z0-9- の1〜20文字。返った worktree に移動する。
   hc 内なら child、外なら hidden。hidden は記録された terminal を `hc attach` で見られる。
   以後は worktree 内で task を自動探索する。候補が複数なら `--task <task_dir>` を付ける。
   未検証版を使う判断を人がした場合だけ start / run に `--allow-untested` を付ける。

2. superpowers:brainstorming → superpowers:writing-plans で task の PLAN.md を記入する。
   雛形の Scope、Validation commands、Done criteria を具体化してから実行する。

   ```bash
   "<Base directory>/cdx" run --wait
   ```

   Claude の Bash ツールでは `run_in_background: true` で呼ぶ。
   終了通知の後に Bash の出力と exit code を読む。途中の確認は次を使う。

   ```bash
   "<Base directory>/cdx" status
   "<Base directory>/cdx" wait
   ```

3. 最新の `rounds/NN/DONE.json`、events.jsonl、stderr.txt、git diff を読む。
   PLAN の検証コマンドを Claude 自身でも実行する。
   `templates/REVIEW.md` から最新の `rounds/NN/REVIEW.md` を作る。
   先頭行を `Status: APPROVED`、`Status: CHANGES_REQUESTED`、`Status: ABORTED` のいずれかに確定する。

4. 修正が必要なら Required fixes に具体的な修正と検証を書く。

   ```bash
   "<Base directory>/cdx" fix
   ```

   返った PROMPT.md を必要なら編集し、同じ run --wait → レビューを繰り返す。
   初回は rounds/01、修正は 02〜04。同じ thread を resume し、修正は最大3回。

5. 最新ラウンドを承認したらコミットする。Codex 自身にはコミットさせない。

   ```bash
   "<Base directory>/cdx" finish -m "変更内容"
   ```

   final/diff.patch と final/status.txt が残る。
   superpowers:finishing-a-development-branch を使い、merge / PR / reject は人に判断してもらう。
   PR 中は worktree を残し、merge 後に片付ける。

   ```bash
   "<Base directory>/cdx" cleanup
   ```

   中止するときは REVIEW の先頭行を ABORTED にし、次を実行する。

   ```bash
   "<Base directory>/cdx" abort
   ```

   破棄が人に承認された場合だけ cleanup --force を使う。稼働中の terminal は先に abort で止める。
   CLI は state に記録した terminal とその task の worktree / branch だけを片付ける。

## Exit code

| code | 結果 | 対応 |
|---|---|---|
| 0 | 成功 | 次の手順へ |
| 1 | 実行失敗 | stderr_tail とログを確認し、原因を解消する |
| 2 | Codex が blocked | DONE.json の質問を確認する |
| 3 | 前提未成立・人の判断が必要 | JSON の理由を読み、人に確認する |

原因を解消し、failed かつ terminal 削除済みの同じラウンドをやり直す場合だけ `"<Base directory>/cdx" run --retry --wait` を使う。

## レビュー観点

- PLAN の範囲・完了条件を全て満たすか。余計な変更がないか。
- 最新ラウンドの DONE と diff を照合し、テストを自分でも実行したか。
- 非0終了・DONE欠落を完了と見なしていないか。
- 権限・秘密情報・ネットワーク・破壊的操作・deploy・publish の要求がないか。
- 自分以外の terminal や worktree を片付け対象にしていないか。

## 人に確認して止まる条件

- exit 3。前提を無視して繰り返し起動しない。
- blocked が権限・秘密情報など人の判断を要する質問を含む。
- 修正ラウンド3回でも承認できない。5ラウンド目は作らない。
