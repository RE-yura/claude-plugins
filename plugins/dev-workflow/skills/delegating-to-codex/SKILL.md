---
name: delegating-to-codex
description: Use when delegating implementation, fixes, or refactoring to Codex CLI — e.g. the user says 「Codex に実装を委譲して」「Codex にやらせて」「herdr 経由で」, or Claude has finished planning a task whose implementation belongs to Codex per the team's role split (Claude = plan/review/verify, Codex = implement).
version: "1.7.0"
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

## Quick Reference（herdr 0.9.4 / codex-cli 0.160.0 実測済み）

検証済みバージョンの正は同ディレクトリの [versions.json](versions.json)。本文中の「0.8.0 実測」等の注記は検証当時の記録である。

| 操作 | コマンド |
|---|---|
| **Step 0: 依存バージョン確認**（委譲開始前に必ず） | `"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh`（versions.json と実機を突き合わせ。WARN が出たら各行の指示どおり確認してから進む。ブロックはしない） |
| worktree 作成 | `git -C <root> worktree add -b <br> <wt> HEAD` + `.git/info/exclude` に `.ai/`（`herdr worktree create` は使わない） |
| Codex 用 workspace 作成（疑似ツリー）+ root pane 取得 | `HERDR_PANE_ID` があれば `herdr pane current` で委譲元 workspace を特定し、`herdr workspace create --cwd <wt> --label "└ <task_id>" --no-focus` → `"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/place-lane.sh <caller_ws> <lane_ws>` で委譲元の直下（サイドバーの描画順で、既存の `└` 行の後ろ）へ移す（socket API の `workspace.move_block`。失敗しても警告だけ）。なければ `└` なしの単独 workspace。応答 JSON の `.result.root_pane.pane_id // empty` を控え、`logs/lane.json` に委譲元とレーンを記録（`--json` は付けない。コマンドは workflow.md §6 からコピーする） |
| Codex 起動（既存 pane に） | `herdr agent start <name> --kind codex --pane <pane_id> -- --no-daemon`（ready 検出まで待って返る。cwd は pane から引き継ぎ。`--no-daemon` だと herdr の hook がターンの開始・終了を報告する。起動ダイアログで止まると `agent_not_ready`（exit 1）で返るが、そのまま起動確認へ進む） |
| 起動確認 | `herdr agent get <name>`（self-update 終了なら `agent_not_found` → 再 start）+ `agent read --source visible` でダイアログ有無と入力プロンプト「›」確認 |
| /goal 送信 + 完了待ち | `herdr agent prompt <name> "/goal Read .ai/tasks/<id>/CODEX_GOAL.md ..." --wait --until idle --until done --until blocked --until unknown` を timeout なしでバックグラウンド実行（working 以外になった時点で返る。`.result.agent.agent_status` で分岐。送信後5秒以内に working\|blocked が観測できなければ `agent_prompt_stalled` エラー → 画面確認し、未送達か・composer 残留か・実行中かを判断してから対処。盲目的に再送しない） |
| 待ち直し | 状態が working のときだけ `herdr agent wait <name> --until idle --until done --until blocked --until unknown`（現在の状態が一致していると即座に返る。完了は通常 `done`） |
| 完了の確認 | `agent get` の状態 → `CODEX_DONE.md`（主）→ marker（補助）。marker は `agent read` の出力から空白・改行を除いて `•HERDR_TASK_DONE:<id>` を探す（idle / done 以外では `--source visible`）。unknown で成果物も marker も無ければ、送り直さずに短い `agent wait --until working …` で作業中かを確かめる。コマンドは workflow.md §2.3 からコピーする |
| 出力読取 | `herdr agent read <name> --source recent-unwrapped --lines 200`（plain text。jq 不要。idle/done 後は alternate screen の履歴も自動収集される。working / blocked / unknown では履歴の読み取りが `agent_not_idle` になるので `--source visible`） |
| ダイアログ操作 | `herdr agent send-keys <name> enter`（0.8.0。pane send-keys でも可） |
| レビュー可視化（任意） | root pane を `pane split` → `pane run <pane> "hunk diff"` で人間に見せ、`hunk session comment apply` で REVIEW 指摘をインライン注釈（要 hunk CLI のみ。workflow.md §13.1） |

## Common Mistakes（実測またはソースで確認済みの罠）

- **委譲に `herdr worktree create` を使わない** — herdr の worktree グループはリポジトリ単位で親を選ぶので、同じリポジトリの workspace が複数あるとレーンが委譲元とは別の workspace の下に表示される（`--workspace` 指定でも直らない。2026-10-13 ソース確認）。`git worktree add` + 委譲元の直下に置く専用 workspace（疑似ツリー）を使う。
- **疑似ツリーの並びだけで対応関係を判断しない** — `└` の行はラベルと並び順で子に見せているだけで、委譲元を後からドラッグしても付いてこない。どの Claude が起動したかは `logs/lane.json` で確かめる。herdr 本体の「起動元の下に入れ子表示」（#3153 で planned）が入ったら乗り換える（`check-versions.sh` が herdr 更新時に知らせる）。
- **herdr の外で `pane current` を呼び元判定に使わない** — `HERDR_PANE_ID` がないとエラーにならずフォーカス中の pane を返す（0.9.3 実測）。`HERDR_PANE_ID` があるときだけ使い、なければ単独 workspace にする。
- **`herdr --version` だけで環境 OK と判断しない** — client と server は別プロセス。mise 等で client を上げた直後は既存シェルの PATH に旧 client が残り、agent/workspace 系が全て `protocol_mismatch`（exit 0 の JSON エラー）になる（0.8.2→0.9.0 で実測）。`check-versions.sh` が `herdr status` で検出する。新しいシェルを開くか mise shims の herdr を使う。
- **agent 名を 32 文字より長くしない** — `invalid_agent_name`（小文字始まり・小文字/数字/-/_・1〜32 文字。0.9.0 実測）。既定 TASK_ID + `codex-` でちょうど 32 なので、TASK_ID に suffix を足したら短縮する。
- **0.7.4 の起動手順を使わない** — `agent start --cwd ... -- codex` は 0.7.5+ で無効（`--kind` と `--pane` が必須）。Codex 用 workspace の root pane に起動する。pane move による回収も不要になった。
- **`--status` フラグを使わない** — 0.7.5 で `--until` に改名。`herdr wait output` / `herdr wait agent-status` も廃止（→ `pane wait-output` / `agent wait --until`）。
- **`--json` フラグを付けない** — 0.8.0 で JSON がデフォルト出力になり廃止（worktree 系のみ互換で受理。`workspace list --json` 等は usage エラー）。
- **起動直後にいきなり送信しない** — ①codex が self-update して即終了することがある（`agent_not_found`）。②**対話式アップデートダイアログ**（0.146 実測）や fresh worktree の **trust 確認ダイアログ**が出ても **status は `idle` のままで `blocked` にならない**（0.9.1 以前。0.9.3 + 検出 manifest 2026.10.11.1 と 0.9.4 では trust / アップデートは `blocked` と判定され、`agent start` は `agent_not_ready` で返る。どちらでも状態だけに頼らない）。visible read で検出し、アップデートは `pane send-text "2"` + `agent send-keys enter` で Skip（Enter 即送信は「Update now」を選んでしまう。codex-cli 0.160 は "2" だけで Skip）、trust は enter で承認。③codex-cli 0.160 では共有デーモンの設定不一致ダイアログ（`--no-daemon` で起動すれば出ない。出たら `pane send-text "1"` = 今回はデーモンなし。"2" の Restart は他の Codex セッションを中断し得る）と hooks レビュー画面（0.9.4 でも状態は `done` のまま）（`agent send-keys esc`。trust all の `t` は押さない。閉じたレーンでは hooks が動かないので、そのことを REVIEW-N.md と人間への報告に書く）も出る。**hooks 画面は起動確認の後に遅れて出て goal を飲み込み、`prompt --wait` が done を返す** — marker がなければ画面を確認する。なお旧版の「TUI 初期化中のプロンプトが無音で消えて偽 done」問題は 0.8.0 で修正され、届かない場合は `agent_prompt_stalled` エラーが返る。
- **完了を `idle` 前提で待たない** — CLI 駆動では完了は通常 `done`（0.8.0 公式: done = 未読のまま作業が終わった idle。CLI read では既読にならない）。`prompt --wait` / `agent wait` の返り値の状態で分岐。
- **待ちに `--until unknown` を付け忘れない** — Codex は応答後も `unknown` のまま残ることがあり、既定（idle\|done\|blocked）の待ちは返らないことがある（herdr 0.9.3 公式 Agents ページ。0.9.4 では idle に倒すようになったが、付けたままにする）。作業中に一瞬 unknown で早く返っても、working なら待ち直せばよい。
- **marker を待つループを書かない** — 待ちの抜け条件は状態だけにする。Codex は長い行を pane の幅で自分で折り返し、pane の幅はクライアント構成次第で狭くなる（公式 Configuration / Concepts）。2026-10-13 の macmini では約50桁の pane で marker が `…-p1c-ai-hand-` と `part1` に割れ、marker が1行で出るまで回るループが終わらず、Codex の完了に約4時間気付かなかった。
- **marker を `pane wait-output` や行頭アンカーの regex で探さない** — `pane wait-output` は1行ずつしか照合せず（公式 CLI reference。agent には `agent wait` を勧めている）、`recent-unwrapped` も Codex が入れた改行はつながない。`agent read` の出力から空白・改行を除き、`•HERDR_TASK_DONE:<id>` の形で探す。素の substring だと goal のエコー行に偽マッチする（空白を除くとエコー行は `printHERDR_…` になるので、`•` 付きで区別できる）。marker は単独のメッセージとして出させる（複数行のメッセージの途中だと `•` の直後にならず見つからない）。
- **`agent read` / `pane read` の出力を jq に通さない** — 0.7.5+ でどちらも plain text（`jq -r '.result.read.text'` は parse error）。`agent get` / `workspace create` 等は従来どおり JSON。
- **`--source recent-unwrapped` を小さい `--lines` で読まない** — 履歴バッファ末尾は空行がちで、空に見える（0.8.0 でも再現）。`--lines 200` 以上にするか、現在画面が欲しいなら `--source visible`。
- **pane コマンドに agent 名を渡さない** — `pane run`/`send-keys`/`close`/`wait-output` は pane id 必須。
- **terminal id（`term_...`）を保存して使い回さない** — herdr 再起動で変わる。ターゲットは agent 名を正とする。
- **`/goal` に計画全文を貼らない** — 計画はファイルに書き、1行の `/goal` で参照させる（bracketed paste で複数行送信は可能になったが、レビュー可能性のためファイル契約を維持）。
- **PLAN.md をスキル無しで書かない** — 事前に superpowers:brainstorming、執筆は superpowers:writing-plans（運用ルール）。
- **checkout は pane close の後に git で消す** — Codex pane を閉じると Codex 用 workspace（サイドバーの `└` の行）も消える（0.9.3 実測）。merge / reject が済んでから `git worktree remove` + `branch -d`（reject は `-D`）。hunk pane を split していたら先に閉じる（残ると workspace が消えない）。旧方式（2026-10-13 改訂（skill 1.4.0 / plugin 1.5.0）より前）の worktree グループの片付けは workflow.md §17.1。

## Workflow Summary

0. `check-versions.sh` で依存バージョンを検証（WARN 時は指示された確認をしてから進む）
1. `git worktree add` で worktree 作成 + `.git/info/exclude` に `.ai/` 追加 → Codex 用 workspace を作って委譲元の直下へ移す（疑似ツリー。応答 JSON から root pane id を控え、logs/lane.json に記録。herdr 外からなら単独 workspace）
2. brainstorming → writing-plans で `PLAN.md`、契約書 `CODEX_GOAL.md` を worktree 内 `.ai/tasks/<TASK_ID>/` に作成
3. root pane に Codex 起動（`--kind codex --pane`）→ 起動確認（生存 + visible read でダイアログ有無を確認）→ 1行 `/goal` を `agent prompt --wait --until idle --until done --until blocked --until unknown` でバックグラウンド送信 → 返ったら「完了の確認」（状態・CODEX_DONE.md・折り返しに強い marker 検索。stalled エラーなら画面確認して対処）
4. `CODEX_DONE.md`・git diff・テスト結果でレビュー → `REVIEW-N.md`
5. 問題あれば `FIX-N.md` を書いて同じ pane に再 `/goal`（最大3ラウンド）
6. APPROVED → `REVIEW-FINAL.md` → ログ保存 → pane close（Codex 用 workspace も消える）→ Claude がコミットし、finishing-a-development-branch で merge / PR / reject を人間に確認（PR なら本文を yomiyasu で推敲。workflow.md §16.1。worktree は merge/PR まで残す）
7. merge / reject 後: `git worktree remove` + `branch -d`（reject は `-D`）。必ず pane close の後に行う

詳細手順・テンプレート・安全ルール・チェックリスト: **[workflow.md](workflow.md)**
