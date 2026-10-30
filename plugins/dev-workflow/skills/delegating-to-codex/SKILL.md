---
name: delegating-to-codex
description: Use when delegating implementation, fixes, or refactoring to Codex CLI — e.g. the user says 「Codex に実装を委譲して」「Codex にやらせて」「herdr 経由で」「herdr-core (hc) 経由で」, or Claude has finished planning a task whose implementation belongs to Codex per the team's role split (Claude = plan/review/verify, Codex = implement).
version: "2.0.1"
---

# Delegating to Codex via herdr-core (hc) + /goal

## Overview

Claude Code が実装計画を書き、herdr-core (`hc`) 経由で Codex CLI の `/goal` に実装を委譲し、レビュー・修正ループを回すための運用規約。**実行前に必ず同ディレクトリの [workflow.md](workflow.md) を読むこと** — 完全な手順・テンプレート・チェックリストはそこが正本である。

役割分担: Claude = 設計・PLAN.md 作成・レビュー・検証・承認 / Codex = 実装・テスト実行・修正。

## When to Use

- ユーザーが Codex への委譲を指示したとき（「Codex に実装させて」等）
- 実装計画が固まり、実装フェーズを Codex に渡すとき
- Codex の実装をレビューして修正を依頼するとき

使わない場合: 調査・設計・検証・デプロイ（Claude 担当）、Codex が rate limit 等で使えないとき（Workflows で代行）。

## Quick Reference（hc 0.1.14 / herdr-app 0.1.8 / codex-cli 0.164.0）

検証済みの版と日付（2026-10-30）の正は [versions.json](versions.json)。2026-10-30 E2E で child / space の初回実装・修正・片付けを確認した。Codex への送信には workflow.md §2.1 で定義する `hc_raw` を使う。

| 操作 | コマンド・判断 |
|---|---|
| **Step 0: 依存確認** | `"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh`。hc の版と稼働中 core の版も照合する。WARN の指示を確認してから進む（workflow.md §5） |
| worktree | 名前が `hc get` で not_found（exit 3）、`test ! -e "$WT"` を確認してから `git worktree add`。info/exclude の `.ai/` は重複させない（workflow.md §6） |
| レーンの3分岐 | `HC_TERMINAL_ID` あり → `child`、外で `herdr-app status` 成功 → `space`、それ以外 → `hidden`。委譲元とモードを `logs/lane.json` に記録（workflow.md §6） |
| child の起動 | `hc run --bg --name "$CODEX" --cwd "$WT" --outlive-parent --no-notify codex --no-daemon`。Claude の子として Herdr に出る（2026-10-30 実機確認） |
| space の起動 | `herdr-app do space.new --name "codex $TASK_ID" --folder "$WT" --tab codex --argv '["codex","--no-daemon"]'`。返った `.terminal` を CODEX にし、`.space` / `.tab` も lane.json に記録。zsh -ic 経由の PATH を2026-10-30 E2E で確認 |
| hidden の起動 | `hc run --bg --name "$CODEX" --cwd "$WT" --no-notify codex --no-daemon`。ユーザーに `hc attach "$CODEX"` を案内 |
| 起動確認・ダイアログ | `hc get "$CODEX" --json` + `hc read "$CODEX"`。アップデートは `hc keys "$CODEX" 2` だけで Skip（Enter 不要、2026-10-30 E2E で確認）。trust は `enter`（esc は Quit）、hooks は `esc`。ダイアログ中の null は正常。読み込み中の `›` だけで送らず、permissions の行と status.state=idle がそろったことを確認（workflow.md §9） |
| `/goal` 送信・待ち | 送信前に `logs/goal-initial.sent` を touch し、`hc_raw send --wait --timeout 300 "$CODEX" "$GOAL_TEXT"`。working かつ今回の CODEX_DONE.md が送信マーカーより新しくない間だけ `hc wait --timeout 300`。全体を `run_in_background`。送信後にタグ無しと Goal active、待ち結果は `.wait.*` を確認（workflow.md §10） |
| 完了確認 | `.state` / `.status.state` / `.foreground.name` + 今回の Round と送信後更新の CODEX_DONE.md。finished または foreground が codex でなくなったら終了を確認。background process / terminal の自己申告は状態にかかわらず §18.7 で画面確認。新しい報告があっても working なら停止条件を確認（workflow.md §2.3） |
| 読み取り・状態 | `hc read "$CODEX" --lines N` は画面全体 + 上の履歴N行。Codex の TUI では履歴がほとんど取れず、経過の正は PROGRESS.md / CODEX_DONE.md。`hc get --json` は JSON |
| 修正 | 毎回必ず `hc_raw send "$CODEX" "/goal clear"` を送り、画面で消えたことを確認。`fix-NN.sent` を touch して同じ Codex に `hc_raw send --wait --timeout 300`。待ちの条件は初回と同じ。タグ無し・Goal active と Round / 送信後更新を照合（workflow.md §14.2） |
| 片付け | 最終レビュー・画面の記録保存後、hunk タブを閉じてその terminal を `hc kill` → `hc rm`。`hc kill "$CODEX"`（即時 SIGKILL）→ `hc rm "$CODEX"`。作った space が `herdr-app ls` にまだある場合だけ `space.close`（workflow.md §15） |
| レビュー可視化（任意） | child は委譲元を含む space、space は同じ space に `herdr-app do tab.new --space <id> --name "review $TASK_ID" --folder "$WT" --argv '["hunk","diff"]'`。hidden は省く。ヘッダの working tree を確認してから session CLI。完了後 `tab.close` → 記録した terminal を `hc kill` → `hc rm`（workflow.md §13.1） |

## Common Mistakes

- **`--no-daemon` を忘れない** — 付けないと Codex のコマンドが hc の外で動く。
- **起動直後に送らない** — ダイアログ中の null は正常。読み込み中にも入力欄が出るため、permissions の行と status.state=idle がそろうまで送らない。trust の esc は Quit なので押さず enter、hooks の esc と区別する。permissions の行を REVIEW と人へ報告し、YOLO では安全ルールはプロンプトでしか守られないと認識する。hooks を esc で閉じたら、閉じたことと hooks が動かない影響を REVIEW と人への報告に書く。trust all の `t` は押さない。
- **slash command は必ずタグ無しで送る** — `hc_raw send` を使い、入力行に `<hc from=` が無く Goal active / コマンド応答が出たことを確認する。通常の hc send は child モードでタグが付き、slash command が効かない（2026-10-30 E2E で確認）。全エージェントに効く `notes = false` は使わない。
- **送信直後に単独の `hc wait` で始めない** — 前ラウンドの done を拾う。初回も修正も `hc_raw send --wait` でこの送信のターンを待つ。
- **sleep で待たない** — `hc wait --timeout 300` を使う。timeout はチェックイン。`hc_raw` では Claude の入力欄への入力による `reason: message` は期待できない。
- **新しい報告がある working を無条件に待ち続けない** — 今回の Round・送信後更新と、入力欄 ›・background terminal(s) running・Working ( のスピナー無しをすべて確認した場合だけ `hc_raw send "$CODEX" "/stop"` → `hc wait --timeout 300` で done / idle を確認する。まだ作業中なら /stop を送らず、報告条件なしで待つ（workflow.md §18.7）。
- **`not_started` で自動再送しない** — hook でターン開始が遅れることがある。画面の Pursuing goal / Working ( / Running hook を確認したら §11 のループで合流し、無ければ §18.2 で判断する。done / idle でも今回の CODEX_DONE.md が無ければ、継続中か・ダイアログに飲まれたかを確認する。
- **古い報告を今回の完了と取り違えない** — 初回も修正も送信マーカーを作り、CODEX_DONE.md の先頭行の Round と送信後更新を確認する。修正 goal 前の `/goal clear` は必須。
- **背景のプロセスを残して報告しない** — 契約テンプレートで subagent を禁止し、自分が起動した background process / terminal を止めてから CODEX_DONE.md を最後に書かせる。ただし指示が効かず申告と画面が違った実測があるため、§18.7 の画面確認は必須。
- **`hc_raw send --force` で判断を飛ばさない** — ダイアログを読んで処理し、権限など人の判断が要る質問はユーザーに聞く。
- **Codex に `hc send` で報告させない** — Claude の入力欄に割り込む。`--no-notify` を付け、CODEX_DONE.md / BLOCKED.md で報告させる。親が終わっても作業を残すため child に `--outlive-parent` を付ける（親の下への表示は維持される）。
- **ユーザーの他のターミナルを `hc kill` しない** — `hc ls` は全部を出す。lane.json に記録した今回の対象だけを片付ける。
- **`hc server stop` や core の再起動をユーザーに無断でしない** — 全ターミナルに影響する。実験は別の HC_SESSION と scratch XDG パスで行う。
- **名前は32文字まで** — `a-z 0-9 - _` の1〜32文字。既定 TASK_ID + `codex-` はちょうど32文字。長い suffix があれば短縮する（workflow.md §6）。
- **`herdr-app do` で関係ない space・タブを作らない** — 委譲用の作成・片付けとレビュー可視化だけ。child では委譲元の space を閉じず、hidden では `space.close` を呼ばない。
- **Codex を止めてから worktree を消す** — レビュー前に止めず、APPROVED / ABORTED とログ保存後に停止する。PR 中は worktree を残す（workflow.md §17）。

`space.new --argv` の PATH（zsh -ic 経由）と `hc keys <t> 2` だけの Skip は2026-10-30 E2E で確認した。2026-10-30 E2E で自動継続ターンの境目は起きたが、background terminals が残っている間は done / idle を出さなかった。ループは今回の CODEX_DONE.md の新しさで抜けるので、どちらでも動く。background terminals が無いときの境目で一度 done になった場合は、ループを抜けて §2.3 → §18.2 で画面を読む（この経路は未確認）。

## Workflow Summary

0. `check-versions.sh` で依存と core を確認する。
1. Git worktree を作って `.ai/` を exclude し、child / space / hidden と委譲元を lane.json に記録する。
2. brainstorming → writing-plans で PLAN.md、CODEX_GOAL.md を worktree 内に書く。
3. `codex --no-daemon` を起動し、ダイアログ・permissions を確認。送信マーカーを touch して `/goal` を `hc_raw send --wait --timeout 300` で送り、画面のタグ無しと Goal active を確認。working かつ今回の新しい報告が無い間は待ち直し、報告があれば §18.7 の画面確認へ。
4. 状態と今回の Round の CODEX_DONE.md を確認し、ログ・diff・テスト結果を保存して REVIEW-N.md を書く。
5. 修正時は必ずタグ無しの `/goal clear` を確認後、同じ Codex に FIX-NN.md を再 `/goal`（最大3回）。
6. APPROVED → REVIEW-FINAL.md → 画面の記録保存 → hunk タブを閉じ terminal を `hc kill` + `hc rm` → Codex を `hc kill` + `hc rm` → 作った space がまだあれば閉じる。
7. Claude がコミットし、finishing-a-development-branch で merge / PR / reject を人に確認する。PR 本文は yomiyasu があれば推敲（workflow.md §16.1）。PR 中は worktree を残す。
8. merge / reject 後、Codex 停止済みを確認して `git worktree remove` + `branch -d`（reject は `-D`）。

詳細手順・テンプレート・安全ルール・チェックリスト: **[workflow.md](workflow.md)**
