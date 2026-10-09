---
name: delegating-to-codex
description: Use when delegating implementation, fixes, or refactoring to Codex CLI — e.g. the user says 「Codex に実装を委譲して」「Codex にやらせて」「herdr 経由で」, or Claude has finished planning a task whose implementation belongs to Codex per the team's role split (Claude = plan/review/verify, Codex = implement).
version: "1.3.0"
---

# Delegating to Codex via Herdr + `/goal`

## Overview

Claude Code が実装計画を書き、Herdr 経由で Codex CLI の `/goal` に実装を委譲し、レビュー・修正ループを回すための運用規約。**実行前に必ず同ディレクトリの [workflow.md](workflow.md) を読むこと** — 完全な手順・テンプレート・チェックリストはそこが正本である。

役割分担: Claude = 設計・PLAN.md 作成・レビュー・検証・承認 / Codex = 実装・テスト実行・修正。

## When to Use

- ユーザーが Codex への委譲を指示したとき（「Codex に実装させて」等）
- 実装計画が固まり、実装フェーズを Codex に渡すとき
- Codex の実装をレビューして修正を依頼するとき

使わない場合: 調査・設計・検証・デプロイ（Claude 担当）、Codex が rate limit 等で使えないとき（Workflows で代行）。

## Quick Reference（herdr 0.9.1 / codex-cli 0.156.1 実測済み）

検証済みバージョンの正は同ディレクトリの [versions.json](versions.json)。本文中の「0.8.0 実測」等の注記は検証当時の記録である。

| 操作 | コマンド |
|---|---|
| **Step 0: 依存バージョン確認**（委譲開始前に必ず） | `"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh`（versions.json と実機を突き合わせ。WARN が出たら各行の指示どおり確認してから進む。ブロックはしない） |
| worktree 作成 + root pane 取得 | `herdr worktree create --cwd <root> --branch <br> --path <wt> --label <task_id> --no-focus` → 応答 JSON（0.8.0 でデフォルト。`--json` は付けない）の `.result.root_pane.pane_id` / `.result.workspace.workspace_id` を控える |
| Codex 起動（既存 pane に） | `herdr agent start <name> --kind codex --pane <pane_id>`（ready 検出まで待って返る。cwd は pane から引き継ぎ） |
| 起動確認 | `herdr agent get <name>`（self-update 終了なら `agent_not_found` → 再 start）+ `agent read --source visible` でダイアログ有無と入力プロンプト「›」確認 |
| /goal 送信 + 完了待ち | `herdr agent prompt <name> "/goal Read .ai/tasks/<id>/CODEX_GOAL.md ..." --wait --timeout 1800000`（0.8.0 主経路。settled state 到達で返り、`.result.agent.agent_status` で分岐。送信後5秒以内に working|blocked が観測できなければ `agent_prompt_stalled` エラー → 画面確認し、未送達か・composer 残留か・実行中かを判断してから対処。盲目的に再送しない） |
| 待ち直し | `herdr agent wait <name> --timeout 1800000`（--until なし = idle\|done\|blocked 到達で返る。完了は通常 `done`） |
| marker 確認 | `herdr pane wait-output <pane_id> --regex "^• HERDR_TASK_DONE:<id>" --source recent-unwrapped --lines 500 --timeout 15000`（`--match` は substring 偽マッチするので使わない） |
| 出力読取 | `herdr agent read <name> --source recent-unwrapped --lines 200`（plain text。jq 不要。idle/done 後は alternate screen の履歴も自動収集される） |
| ダイアログ操作 | `herdr agent send-keys <name> enter`（0.8.0。pane send-keys でも可） |
| レビュー可視化（任意） | root pane を `pane split` → `pane run <pane> "hunk diff"` で人間に見せ、`hunk session comment apply` で REVIEW 指摘をインライン注釈（要 hunk CLI のみ。workflow.md §13.1） |

## Common Mistakes（すべて実測で確認済みの罠）

- **`herdr --version` だけで環境 OK と判断しない** — client と server は別プロセス。mise 等で client を上げた直後は既存シェルの PATH に旧 client が残り、agent/workspace 系が全て `protocol_mismatch`（exit 0 の JSON エラー）になる（0.8.2→0.9.0 で実測）。`check-versions.sh` が `herdr status` で検出する。新しいシェルを開くか mise shims の herdr を使う。
- **agent 名を 32 文字より長くしない** — `invalid_agent_name`（小文字始まり・小文字/数字/-/_・1〜32 文字。0.9.0 実測）。既定 TASK_ID + `codex-` でちょうど 32 なので、TASK_ID に suffix を足したら短縮する。
- **0.7.4 の起動手順を使わない** — `agent start --cwd ... -- codex` は 0.7.5+ で無効（`--kind` と `--pane` が必須）。worktree create の root pane に起動する。pane move による回収も不要になった。
- **`--status` フラグを使わない** — 0.7.5 で `--until` に改名。`herdr wait output` / `herdr wait agent-status` も廃止（→ `pane wait-output` / `agent wait --until`）。
- **`--json` フラグを付けない** — 0.8.0 で JSON がデフォルト出力になり廃止（worktree 系のみ互換で受理。`workspace list --json` 等は usage エラー）。
- **起動直後にいきなり送信しない** — ①codex が self-update して即終了することがある（`agent_not_found`）。②**対話式アップデートダイアログ**（0.146 実測）や fresh worktree の **trust 確認ダイアログ**が出ても **status は `idle` のままで `blocked` にならない**。visible read で検出し、アップデートは `pane send-text "2"` + `agent send-keys enter` で Skip（Enter 即送信は「Update now」を選んでしまう）、trust は enter で承認。なお旧版の「TUI 初期化中のプロンプトが無音で消えて偽 done」問題は 0.8.0 で修正され、届かない場合は `agent_prompt_stalled` エラーが返る。
- **完了を `idle` 前提で待たない** — CLI 駆動では完了は通常 `done`（0.8.0 公式: done = 未読のまま作業が終わった idle。CLI read では既読にならない）。`prompt --wait` / `agent wait` の返り値の状態で分岐。
- **marker を素の substring / `--match` で待たない** — goal 本文に marker を含めるため、エコー行（`• Goal active Objective: ...`）に即偽マッチする（0.8.0 実測で再確認）。行頭アンカー付き `--regex "^• HERDR_TASK_DONE:<id>"` を使い、matched_line を確認。
- **`agent read` / `pane read` の出力を jq に通さない** — 0.7.5+ でどちらも plain text（`jq -r '.result.read.text'` は parse error）。`agent get` / `worktree create` 等は従来どおり JSON。
- **`--source recent-unwrapped` を小さい `--lines` で読まない** — 履歴バッファ末尾は空行がちで、空に見える（0.8.0 でも再現）。`--lines 200` 以上にするか、現在画面が欲しいなら `--source visible`。
- **pane コマンドに agent 名を渡さない** — `pane run`/`send-keys`/`close`/`wait-output` は pane id 必須。
- **terminal id（`term_...`）を保存して使い回さない** — herdr 再起動で変わる。ターゲットは agent 名を正とする。
- **`herdr worktree create` を引数なしで実行しない** — usage は出ず、既定値で worktree が即作成される。
- **`/goal` に計画全文を貼らない** — 計画はファイルに書き、1行の `/goal` で参照させる（bracketed paste で複数行送信は可能になったが、レビュー可能性のためファイル契約を維持）。
- **PLAN.md をスキル無しで書かない** — 事前に superpowers:brainstorming、執筆は superpowers:writing-plans（運用ルール）。
- **cleanup は workspace の生死で手段を変える** — worktree workspace の唯一の pane を close すると **workspace も自動で閉じる**（実測。以後 `worktree remove --workspace` は `workspace_not_found`）。pane close 済みなら `git worktree remove` + `branch -d` で消す。workspace が開いたままなら `herdr worktree remove --workspace <id>`。workspace が開いたまま git 側だけ消すとゾンビ workspace が残る（→ `herdr workspace close <id>`）。

## Workflow Summary

0. `check-versions.sh` で依存バージョンを検証（WARN 時は指示された確認をしてから進む）
1. worktree 作成（応答 JSON から root pane id / workspace id を控える）+ `.git/info/exclude` に `.ai/` 追加
2. brainstorming → writing-plans で `PLAN.md`、契約書 `CODEX_GOAL.md` を worktree 内 `.ai/tasks/<TASK_ID>/` に作成
3. root pane に Codex 起動（`--kind codex --pane`）→ 起動確認（生存 + visible read でダイアログ有無を確認）→ 1行 `/goal` を `agent prompt --wait` で送信 → 返った agent_status（done/blocked）+ marker 確認（stalled エラーなら画面確認して再送）
4. `CODEX_DONE.md`・git diff・テスト結果でレビュー → `REVIEW-N.md`
5. 問題あれば `FIX-N.md` を書いて同じ pane に再 `/goal`（最大3ラウンド）
6. APPROVED → `REVIEW-FINAL.md` → ログ保存 → pane close → Claude がコミットし、finishing-a-development-branch で merge / PR / reject を人間に確認（worktree は merge/PR まで残す）
7. merge / reject 後: pane close 済みなら `git worktree remove` + `branch -d`（workspace は pane close で消滅済み）。workspace が開いたままなら `herdr worktree remove --workspace <id>` で両方片付ける

詳細手順・テンプレート・安全ルール・チェックリスト: **[workflow.md](workflow.md)**
