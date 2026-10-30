# Claude Code Operating Procedure: Codex Delegation via herdr-core (hc) + `/goal`

この文書は、Claude Code が詳細な実装計画を作成し、herdr-core (`hc`) 経由で Codex CLI の `/goal` に実装を委譲し、レビュー・修正を繰り返すための運用手順である。Claude Code は「実装委譲ワークフローの実行規約」として扱うこと。

> 検証済み環境の正は同ディレクトリの [versions.json](versions.json)（hc 0.1.14 / herdr-app 0.1.8 / codex-cli 0.164.0 / superpowers 7.0.0 / Claude Code 2.1.314、2026-10-30）。委譲開始前に `check-versions.sh` を実行する（§5）。正確な引数は `hc --skill`・`herdr-app --skill`・`hc <command> --help`・`herdr-app commands` で確認する。以下の実機確認済みの記述は 2026-10-30 時点。2026-10-30 E2E で child / space の両モードの初回実装・修正・片付けを確認した。child ではタグ無し送信と background terminals の対処が必要だった（§2.1・§18.7）。

---

## 1. 目的

Claude Code と Codex の役割を分離する。

```text
Claude Code  = 設計者・計画作成者・レビュアー・承認者
Codex CLI    = 実装担当・テスト実行担当・修正担当
hc           = Codex の起動・状態取得・入力送信・待ち・ログ取得・片付け
Herdr アプリ = Claude の子、またはタスク用 space として Codex を見せる
Git worktree = Codex が安全に編集する隔離された作業領域（git worktree add）
Task files   = Claude Code ↔ Codex 間の契約・状態・成果物
```

`PLAN.md`、`CODEX_GOAL.md`、`PROGRESS.md`、`CODEX_DONE.md`、`REVIEW-N.md`、`FIX-N.md`、`git diff` を残し、Claude Code が確実にレビュー・修正指示・承認を行える状態にする。

---

## 2. 基本方針

### 2.1 hc と herdr-app の使い分け

プログラムの制御は hc、画面の変更は herdr-app に分ける。Codex への送信には、ここで一度だけ定義する `hc_raw` を使う。

```bash
# エージェントのターミナルの中から hc send すると <hc from="tN"> で包まれ、slash command が効かない。
# Codex への送信はタグを付けないこれを使う（2026-10-30 E2E で確認）
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }
```

Claude Code の Bash ツールは呼び出しをまたいでシェル関数を引き継がないので、`hc_raw` を使う以下のコードブロックには毎回この定義の行を入れてある。`hc_raw send` は `/goal`・`/goal clear`・`/goal pause`・`/stop` を slash command のまま届ける。`hc keys`・`get`・`read`・`wait`・`run` は通常の hc を使う。呼び出し元を外すので、Claude の入力欄への入力で待ちが返る `reason: message` の挙動は期待できない。300秒のチェックインで確認する。`~/.config/herdr-core/config.toml` の `notes = false` でもタグを消せるが、全エージェントに効くので使わない。

| 操作 | コマンド |
|---|---|
| 起動 | `hc run --bg`（§9） |
| 状態 | `hc get <codex> --json` |
| 送信とそのターンの待ち | `hc_raw send --wait --timeout 300 <codex> "<text>"` |
| 作業中の待ち直し | `hc wait <codex> --timeout 300` |
| 読み取り | `hc read <codex> --lines N`（画面全体 + その上の履歴N行。テキスト。jq に通さない） |
| キー | `hc keys <codex> enter` / `esc` |
| 送信のみ | `hc_raw send <codex> "<text>"` |
| 現在のターンを止める | `hc interrupt <codex>` |
| 片付け | `hc kill <codex>` → `hc rm <codex>` |

`herdr-app do` は画面を変える。委譲ではタスク用 space の作成（§6・§9）、その space を閉じる操作（§15）、レビューの可視化（§13.1）に限る。`herdr-app ls` / `status` / `commands` は読むだけ。ユーザーの他のターミナルや space は操作しない。

hc の出力は pipe 先では JSON（`run`・`exec`・`read`・`file read` はテキスト）。`run --bg` の起動応答は JSON なので §9 で保存する。明示的に JSON が必要なら `--json` を使う。エラーは stderr の `{error: {kind, message, hint}}`。主な exit code は 3 not_found / 9 blocked / 10 status_mismatch / 11 finished。終了コードとエラーを読み、失敗した起動や送信を成功扱いしない。

### 2.2 `/goal` には長文を貼り付けない

詳細はファイルに書き、Codex には **1行の `/goal`** でそのファイルを読ませる。

```text
/goal Read .ai/tasks/<TASK_ID>/CODEX_GOAL.md and implement it exactly. Write CODEX_DONE.md when complete, or BLOCKED.md if blocked.
```

計画全文を貼らない。ファイル参照なら Codex が読み直せ、Claude Code が後から `PLAN.md` / `FIX-N.md` / `REVIEW-N.md` を検証できる。

`/goal` の usage は `/goal [<objective>|clear|edit|pause|resume]`（2026-10-30 E2E で確認）。引数なしは状態表示、objective は設定、`edit` は編集である。

### 2.3 完了判定は二重にする

次の2つを照合する。状態だけで実装完了とみなさない。

1. `hc get <codex> --json` の `.state`（`live` / `finished`）と `.status.state`（`working` / `idle` / `done` / `blocked` / `error`）。Codex 自身が OSC 7501 で報告し、hc は画面から推測しない。報告が無ければ `status` は null。起動確認後は `.foreground.name` も確認し、codex でなくなったら Codex の終了として §18.6 へ進む（space モードではターミナルが live のまま zsh に戻る）。
2. `CODEX_DONE.md`（**先頭行**の `Round: initial` / `Round: fix-NN` が今回のラウンドか、かつ送信マーカー `$SENT` より新しいか）と `BLOCKED.md`。レビューではさらに `PROGRESS.md`・git diff・テスト結果を読む。

**完了の確認**（待ちが返った後、毎回行う）:

```bash
hc get "$CODEX" --json | tee "$TASK_DIR/logs/get.json" | jq -c '{state, status, exit_code, foreground: .foreground.name}'
ls -l "$TASK_DIR/CODEX_DONE.md" "$TASK_DIR/BLOCKED.md" 2>/dev/null
if [ -f "$TASK_DIR/CODEX_DONE.md" ]; then
  head -n1 "$TASK_DIR/CODEX_DONE.md"   # initial / fix-NN を今回と照合する
fi
```

- `working` のまま今回の `CODEX_DONE.md` が送信マーカーより新しい: §18.7 で画面を確認する。background terminals が残っている場合があり、無条件に待ち続けない。
- `working` で今回の新しい報告が無い: §10 のループで待ち直す。`reason: timeout` は完了ではない。`hc_raw` では Claude の入力欄への入力による `reason: message` は期待しない。
- `done` / `idle` で今回の `CODEX_DONE.md` がある: §18.7 の画面確認で background process / terminal の申告も確かめ、ログを保存してレビューへ（§12・§13）。これはレビュー開始の条件であり、停止の条件ではない。
- `done` / `idle` で `CODEX_DONE.md` が無い: 画面を読む。ダイアログに goal が飲まれたか、goal がまだ続いているかを確認し、すぐに送り直さない（§18.2）。2026-10-30 E2E で自動継続ターンの境目は起きたが、background terminals が残っている間は done / idle を出さなかった。ループは今回の CODEX_DONE.md の新しさで抜けるので、どちらでも動く。background terminals が無いときの境目で一度 done になった場合は、ループを抜けて §2.3 → §18.2 で画面を読む（この経路は未確認）。
- `blocked`: `BLOCKED.md` と画面を読み、§18.1 へ。
- `error`: `hc read` で理由を確認する。
- `.state: finished` または起動確認後の `.foreground.name` が codex でなくなった: 状態報告より終了を優先し、§18.6 へ。
- `status: null`: 起動中のダイアログでは正常（§9）。goal 送信後も報告が無ければ §18.4 へ。

前のラウンドの `done` を拾わないため、送信直後の待ちは単独の `hc wait` で始めず、`hc_raw send --wait` で「この送信が始めたターン」を待つ。`not_started` は未送達の証明ではない。画面を読み、盲目的に再送しない（§10）。

---

## 3. ディレクトリ構成

Codex が作業する Git worktree の中に、次の task directory を作る。

```text
.ai/tasks/<TASK_ID>/
  PLAN.md                 # Claude Code が作る詳細実装計画
  CODEX_GOAL.md           # Codex が最初に読む実装契約
  PROGRESS.md             # Codex が checkpoint ごとに更新する進捗ログ
  CODEX_DONE.md           # 先頭行 Round: initial / Round: fix-NN
  BLOCKED.md              # Codex が blocked のときに書く任意ファイル
  REVIEW-01.md
  FIX-01.md
  REVIEW-02.md
  FIX-02.md
  REVIEW-FINAL.md
  logs/
    lane.json             # task_id / mode / caller_terminal / codex / created_at
                          # space / tab は作ったときだけ
    run.json
    get.json
    goal-initial.sent
    send-wait.json
    wait-last.json
    fix-NN.sent
    send-wait-fix-NN.json
    codex-*.txt
    final.diff
    final-status.txt
    test-results.txt
```

main checkout の未コミット task files は別 worktree に自動では存在しない。必ず **Codex worktree 内**に作る。`.ai/` が diff/status やコミットに混ざらないよう、作成直後に Git の info/exclude に足す（§6）。

---

## 4. 推奨ライフサイクル

```text
0. check-versions.sh で依存バージョンと core を確認する（§5）
1. TASK_ID と git worktree を作り、.ai/ を exclude する（§6）
2. child / space / hidden を選び、logs/lane.json に委譲元を記録する
3. brainstorming → writing-plans で PLAN.md、CODEX_GOAL.md を worktree 内に書く（§7・§8）
4. Codex を --no-daemon で起動し、状態と画面を確認してダイアログを処理する（§9）
5. 1行 /goal を hc_raw send --wait で送り、working かつ今回の新しい報告が無い間は hc wait。報告がある working は画面を確認する（§10・§18.7）
6. Codex が実装し、PROGRESS.md と CODEX_DONE.md を書く
7. 状態・今回の Round を確認し、ログと差分を保存する（§2.3・§12）
8. Claude Code がレビューして REVIEW-01.md を書く（§13）
9. 必要なら FIX-01.md を同じ Codex に再 /goal。修正は最大3ラウンド（§14）
10. APPROVED → REVIEW-FINAL.md → ログ保存 → Codex の停止・片付け（§15）
11. Claude Code がコミットし、finishing-a-development-branch で merge / PR / reject を確認する（§16）
12. merge / reject 後に worktree を消す。PR 中は残す（§17）
```

---

## 5. 初期セットアップ確認

**Step 0（必須）**: 委譲開始前にチェッカーを実行する。

```bash
"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh
# CLAUDE_PLUGIN_ROOT が未設定なら workflow.md と同じディレクトリのスクリプトを使う
```

[versions.json](versions.json) と hc / herdr-app / codex / superpowers / claude / jq を照合する。hc は same-minor と `hc server status --json` の `.version` を確認する。CLI だけ更新して稼働中 core が古ければ WARN。**core の再起動はユーザーに確認してから**行う。勝手に `hc server stop` / 再起動をしない。hc が無ければ MISSING、core に繋がらなければ WARN、herdr-app が無くても INFO のみで委譲できる（見せ方だけ変わる）。

チェック結果は OK / WARN / MISSING / INFO、exit は常に 0 でブロックしない（不明な引数は usage error）。WARN の次アクションを確認してから進む。`--quiet` / `-q` は WARN / MISSING とその件数のみを出す。版を上げて再検証したら versions.json を更新する。

hc の integration install は不要。Codex は OSC 7501 を自分で出す。`/goal` は codex-cli 0.144+ で既定有効。slash command list に出ない場合だけ `codex features enable goals` または設定を確認する。

```toml
[features]
goals = true
```

Codex の起動時にはアップデート確認が出ることがある。2026-10-30 の codex-cli 0.164.0 では「1. Update now / 2. Skip / 3. Skip until next version」。起動直後に goal を送ると Enter が Update now を選び得るため、必ず §9 の画面確認を先に行う。自己更新で終了していた場合は §18.6 へ。

挙動の実験では **ユーザーの既定の core にターミナルを作らない・消さない**。`HC_SESSION=codex-plan-test` と一時の `XDG_STATE_HOME` / `XDG_RUNTIME_DIR` / `XDG_CONFIG_HOME` を使い、終わったらその環境の `hc server stop` だけを行う。`--help` / `--skill` / `herdr-app commands` は読むだけで確認できる。

---

## 6. TASK_ID・worktree・Codex のレーン

まず task id と隔離された Git worktree を作る。

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$(git rev-parse --show-toplevel)"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"
CODEX="codex-$TASK_ID"
# 名前は 1〜32 文字の a-z 0-9 - _。既定 TASK_ID + codex- はちょうど32文字。
[ "${#CODEX}" -le 32 ] || CODEX="codex-$(printf '%s' "$TASK_ID" | cut -c1-15)"

# 同じ秒の委譲や兄弟リポジトリと名前・場所が衝突しないことを先に確認する。
test ! -e "$WT" || { printf 'worktree path already exists: %s\n' "$WT" >&2; exit 1; }
NAME_EXIT=0
NAME_CHECK="$(hc get "$CODEX" --json 2>&1)" || NAME_EXIT=$?
if [ "$NAME_EXIT" -ne 3 ]; then
  printf 'terminal name must be not_found (exit 3): %s\n%s\n' "$CODEX" "$NAME_CHECK" >&2
  exit 1
fi

git -C "$ROOT" worktree add -b "$BRANCH" "$WT" HEAD
EX="$(git -C "$WT" rev-parse --git-path info/exclude)"
grep -qxF '.ai/' "$EX" || echo '.ai/' >> "$EX"
TASK_DIR="$WT/.ai/tasks/$TASK_ID"
mkdir -p "$TASK_DIR/logs"

CALLER_TERMINAL="${HC_TERMINAL_ID:-}"
if [ -n "$CALLER_TERMINAL" ]; then
  MODE=child                # Claude の子。ここではまだ起動しない（§9）
elif herdr-app status >/dev/null 2>&1; then
  MODE=space                # §9 でタスク用 space の最初のタブに起動する
else
  MODE=hidden               # §9 でラベル無し起動。ユーザーには hc attach を案内する
fi

jq -n --arg task "$TASK_ID" --arg mode "$MODE" --arg caller "$CALLER_TERMINAL" \
  --arg codex "$CODEX" --arg created "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
  '{task_id: $task, mode: $mode, caller_terminal: $caller, codex: $codex, created_at: $created}' \
  > "$TASK_DIR/logs/lane.json"
```

- `child`: `HC_TERMINAL_ID` がある Claude の子として起動する。Herdr のエージェント一覧で Claude の下に出る。
- `space`: hc の外からなら、アプリが動いている場合にタスク用 space を作る。`space.new --argv` で最初のタブが Codex になる（§9）。
- `hidden`: アプリが動いていなければラベル無しで起動する。画面には出ないので `hc attach "$CODEX"` を案内する。space を作らないため片付けでも閉じない。

以後の task files は `$TASK_DIR` に作る。どの Claude が起動したかの正は **logs/lane.json**。space モードの `.codex`・`.space`・`.tab` は §9 の応答で更新する。起動に失敗したら既存 worktree とこの記録を使って原因を直す。新しい TASK_ID を作って孤児 worktree を増やさない。

---

## 7. `PLAN.md` の作成規約

Claude Code は Codex に渡す前に、必ず詳細な `PLAN.md` を作る。

**PLAN.md の作成には Superpowers スキルを使うこと（運用ルール）:**

```text
1. superpowers:brainstorming
   PLAN.md を書き始める前に必ず起動する。
   要件・意図・設計選択肢をユーザーと（または自律的に）探索し、
   Scope / Non-goals / Expected behavior を固める。

2. superpowers:writing-plans
   PLAN.md の執筆自体はこのスキルの規約に従う。
   下のテンプレートは writing-plans の出力を Codex 向けに
   整形するときの最低限の構成である。
```

`PLAN.md` は次の構成にする。

```md
# Implementation Plan: <TASK_ID>

## Objective
何を実装するか。

## Background
なぜ必要か。関連 issue / 仕様 / 現状挙動。

## Scope
今回必ず実装するもの。

## Non-goals
今回やらないもの。Codex が広げてはいけない範囲。

## Files to inspect first
- path/to/file
- path/to/test

## Expected behavior
ユーザー視点・API 視点・エラー時挙動。

## Implementation steps
1. ...
2. ...
3. ...

## Validation commands
- npm test
- npm run lint
- <project-specific command>

## Done criteria
- 仕様を満たす。
- 必須テストが通る。
- CODEX_DONE.md が作られている。
- 関係ないファイルを変更していない。
- CODEX_DONE.md の先頭行が今回の Round: initial / Round: fix-NN である。

## Risks / edge cases
- ...

## Notes for Codex
- 不明点は推測で広げず BLOCKED.md に書く。
- secret / credentials / deploy / destructive operation は行わない。
```

---

## 8. `CODEX_GOAL.md` の作成規約

`CODEX_GOAL.md` は、Codex が `/goal` 開始後に最初に読む契約書である。Claude Code は `PLAN.md` より短く、実行規約に寄せて書く。

テンプレート:

```md
# Codex Goal: <TASK_ID>

You are Codex CLI working inside this Git worktree.

## Read first
1. .ai/tasks/<TASK_ID>/PLAN.md
2. AGENTS.md, CLAUDE.md, README, or project-specific contribution docs if present
3. Files listed in PLAN.md

## Objective
Implement exactly what PLAN.md requires.

## Scope control
- Implement only the Required scope in PLAN.md.
- Do not implement optional ideas or future work.
- Do not rewrite unrelated modules.
- Do not modify generated files unless PLAN.md explicitly requires it.
- Do not deploy, publish, rotate credentials, or run destructive commands.

## Progress reporting
- Keep .ai/tasks/<TASK_ID>/PROGRESS.md updated after each checkpoint.
- Record commands run and whether they passed.
- If blocked, write .ai/tasks/<TASK_ID>/BLOCKED.md.

## Validation
Run the commands listed in PLAN.md.
If a command cannot be run, explain why in CODEX_DONE.md.

## Done condition
- Do not start subagents.
- Stop every background process or terminal you started before writing CODEX_DONE.md. Write CODEX_DONE.md as your last action.

Before stopping, create .ai/tasks/<TASK_ID>/CODEX_DONE.md with first line `Round: initial` and:
- Summary
- Changed files
- Tests run
- Results
- Known risks
- Any remaining follow-ups

```

---

## 9. Codex の起動

§6 のモードで起動し、応答を保存する。起動に失敗したらエラーを読んで止める。失敗したまま送信へ進まない。

```bash
case "$MODE" in
  child)
    hc run --bg --name "$CODEX" --cwd "$WT" --outlive-parent --no-notify codex --no-daemon \
      > "$TASK_DIR/logs/run.json" || { cat "$TASK_DIR/logs/run.json"; false; }
    ;;
  space)
    herdr-app do space.new --name "codex $TASK_ID" --folder "$WT" --tab codex \
      --argv '["codex","--no-daemon"]' > "$TASK_DIR/logs/run.json"
    CODEX="$(jq -r '.terminal // empty' "$TASK_DIR/logs/run.json")"
    SPACE="$(jq -r '.space // empty' "$TASK_DIR/logs/run.json")"
    TAB="$(jq -r '.tab // empty' "$TASK_DIR/logs/run.json")"
    test -n "$CODEX" && test -n "$SPACE" && test -n "$TAB"
    # 名前は付けられないので .terminal のアドレスを以後のターゲットにする。
    jq --arg codex "$CODEX" --arg space "$SPACE" --arg tab "$TAB" \
      '.codex = $codex | .space = $space | .tab = $tab' "$TASK_DIR/logs/lane.json" \
      > "$TASK_DIR/logs/lane.tmp.json" && mv "$TASK_DIR/logs/lane.tmp.json" "$TASK_DIR/logs/lane.json"
    ;;
  hidden)
    hc run --bg --name "$CODEX" --cwd "$WT" --no-notify codex --no-daemon \
      > "$TASK_DIR/logs/run.json"
    printf 'Codex の画面: hc attach "%s"\n' "$CODEX"
    ;;
esac
```

`--no-daemon` は必須。付けないと Codex のコマンドが hc の外で動く。`--outlive-parent` は Claude を閉じたり再開したりしても作業中の Codex が巻き添えで終わらないため。付けても `parent` は残り、Herdr では Claude の `sub_agents` に出る（2026-10-30 実機確認済み）。`--no-notify` は親の入力欄への通知を避けるため。Codex にも `hc send` で Claude へ報告させず、報告はファイルに書かせる（入力途中に文字が混ざったり、次のユーザー入力として割り込むため）。

space モードでは `space.new --argv` が Codex を起動するので、続けて `hc run` しない。`zsh -ic` 経由で PATH が通ることを **2026-10-30 E2E で確認**した。Codex の終了後は `exec zsh -i` でシェルが残るため `.foreground.name` も見る（§18.6）。

**起動確認（必須）:**

```bash
hc get "$CODEX" --json | tee "$TASK_DIR/logs/get.json"
hc read "$CODEX"
```

1. `.state: finished`、または本画面を確認した後に `.foreground.name` が codex でなくなった → `exit_code`・foreground と画面を読み、§18.6。
2. アップデート確認 → `hc keys "$CODEX" 2` だけで Skip。**Enter は不要（2026-10-30 E2E で確認）**。送った後に画面を読む。Skip してもアップデート確認は起動のたびに出る（2026-10-30 E2E）。
3. フォルダの trust 確認（`Folder access` / `Trust this folder?`）→ `1. Trust and continue / 2. Quit`、フッター `enter continue · esc quit` を確認し、`hc keys "$CODEX" enter`。**esc は Quit なので押さない。hooks 画面の esc と取り違えない。** worktree の中でも trust は repo の root（main checkout）に保存されるので、2回目からは出ない（2026-10-30 E2E で確認）。
4. hooks のレビュー画面 → `hc keys "$CODEX" esc`。trust all の `t` は押さない。閉じたことと、このターミナルで未承認の hooks が動かない影響を `REVIEW-N.md` と人への報告に書く。恒久的に有効にする判断は人が行う。`Running hook` / `hook timed out after 10s` によりターン開始が遅れることがある（2026-10-30 E2E）。

起動ダイアログの間は `status: null` が正常で、本画面では `idle` になる（2026-10-30 E2E で確認）。§18.4 は goal を送った後も報告が無い場合の話であり、起動中の null だけで異常としない。

画面の `permissions:` の行（例: `YOLO mode`）を読み、`REVIEW-N.md` と人への報告に残す。YOLO では §19 の禁止事項はプロンプトでしか守られない（2026-10-30 E2E で確認）。

`hc read` は画面全体を出すので、起動確認は `--lines` なしでよい。**入力欄 `›` は読み込み中にも先に出るので、それだけでは送らない。画面に `permissions:` の行が見え、`hc get` の `.status.state` が `idle` になってから §10 へ。** 両方がそろうまで `hc get` / `hc read` で読み直す（2026-10-30 E2E）。起動後に遅れてダイアログが出て goal を飲み込むこともあるため、状態だけに頼らない。`hc_raw send` が blocked で拒否しても `--force` を使わず画面を読み、権限など人の判断が要る質問は §18.1 へ。

---

## 10. `/goal` の投入

次の送信と待ちを **Bash の `run_in_background` で1コマンドとして実行**する。送信だけ済ませて単独の `hc wait` から始めない（前ラウンドの done で即座に返るため）。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
GOAL_TEXT="/goal Read .ai/tasks/$TASK_ID/CODEX_GOAL.md and implement it exactly. Write CODEX_DONE.md when complete, or BLOCKED.md if blocked."
SENT="$TASK_DIR/logs/goal-initial.sent"
touch "$SENT"
hc_raw send --wait --timeout 300 "$CODEX" "$GOAL_TEXT" > "$TASK_DIR/logs/send-wait.json" 2>&1
# 送信が始めたターンの終了、または5分のチェックインで返る。
# working かつ今回の報告がまだ新しくない間だけ待つ（sleep は使わない）。
while [ "$(hc get "$CODEX" --json 2>/dev/null | jq -r '.status.state // empty')" = working ] \
  && ! [ "$TASK_DIR/CODEX_DONE.md" -nt "$SENT" ]; do
  hc wait "$CODEX" --timeout 300 > "$TASK_DIR/logs/wait-last.json" 2>&1
done
hc get "$CODEX" --json | jq -c '{state, status, foreground: .foreground.name}'
jq -c '.wait | {reason, status}' "$TASK_DIR/logs/send-wait.json"
```

**`.wait.reason` が `not_started` なら**、`hc read "$CODEX"` で `Pursuing goal` / `Working (` / `Running hook` を確認する。見えたら §11 のループを回して合流する。見えなければ **送り直さず** §18.2 で画面と goal の状態を判断する。hook によりターン開始が送信の数秒後（実測6秒）になることがある（2026-10-30 E2E）。

バックグラウンドで送信を始めたら、別の Bash 呼び出しで `hc read "$CODEX"` を読み、入力行に `<hc from=` が無いことと **`Goal active` が出たこと**を確かめる。タグが見えたら slash command として効いていない。盲目的に再送せず、画面と goal の状態を確認する（2026-10-30 E2E で確認）。

- `send --wait` の JSON は、上位の `.status` が送信時の状態で、待ちの結果は **`.wait.reason` / `.wait.status` / `.wait.turn`**。判定には `.wait.*` を使う。`logs/send-wait.json` と §2.3 の現在の状態・成果物を照合する（2026-10-30 E2E で確認）。
- `reason: timeout` は5分のチェックイン。`hc_raw` では Claude の入力欄への入力による `reason: message` は期待できない。返ったときに working でも今回の報告が新しければループを抜け、§18.7 で画面を確認する。
- `not_started` は届いていない証明ではない。**送り直さず画面を読む。** 入力欄に goal が残っている場合は必要なら Enter だけ送り、既に作業中なら待ち直す。
- blocked による拒否は `--force` で飛ばさず §9 のダイアログを処理する。権限の判断なら人に聞く。
- `hc get` のエラーや接続失敗、goal 送信後の null status でループを抜けても完了とみなさない（§18.4）。新しい CODEX_DONE.md だけで完了を承認せず、Round と画面を確認する。
- 2026-10-30 E2E で自動継続ターンの境目は起きたが、background terminals が残っている間は done / idle を出さなかった。ループは今回の CODEX_DONE.md の新しさで抜けるので、どちらでも動く。background terminals が無いときの境目で一度 done になった場合は、ループを抜けて §2.3 → §18.2 で画面を読む（この経路は未確認）。

---

## 11. Codex の進捗監視

```bash
hc read "$CODEX" --lines 200
hc get "$CODEX" --json | jq -c '{state, status, foreground: .foreground.name}'
# まだ作業中なら、報告ファイルの有無では抜けずに待つ（§18.7 からも使う）。
# 次のループを run_in_background で実行する。
while [ "$(hc get "$CODEX" --json 2>/dev/null | jq -r '.status.state // empty')" = working ]; do
  hc wait "$CODEX" --timeout 300 > "$TASK_DIR/logs/wait-last.json" 2>&1
done
hc get "$CODEX" --json | jq -c '{state, status, foreground: .foreground.name}'
```

`hc read --lines N` は画面全体 + その上の履歴N行であり、「直近N行」ではない。Codex の TUI では履歴がほとんど取れないため、画面の記録として読む（2026-10-30 E2E で確認）。状態と task files を照合する（§2.3）。working のまま今回の新しい報告があれば §18.7、まだ作業中なら上の報告ファイル条件なしのループで待つ。done / idle は今回の Round の `CODEX_DONE.md` を確認してレビューへ。blocked は `BLOCKED.md` と画面を読む。成果物が無い場合や状態報告が無い場合は §18 へ。sleep でポーリングしない。

---

## 12. Codex 完了後の保存

§2.3 で今回の goal が止まったことを確認したら、レビュー前に画面の記録と差分を保存する。`hc read --lines 500` は画面全体 + その上の履歴500行だが、Codex の TUI では履歴がほとんど取れず、全経過のログにはならない（2026-10-30 E2E で確認）。経過の正は `PROGRESS.md` / `CODEX_DONE.md` である。Codex の session ログは `~/.codex/sessions/` にある。

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
hc read "$CODEX" --lines 500 > "$TASK_DIR/logs/codex-$STAMP.txt"
git -C "$WT" status --short > "$TASK_DIR/logs/status-$STAMP.txt"
git -C "$WT" diff > "$TASK_DIR/logs/diff-$STAMP.patch"
```

Claude Code は `PLAN.md`・`CODEX_GOAL.md`・`PROGRESS.md`・`CODEX_DONE.md`・git diff・git status・テスト結果を読む。画面出力だけを正としない。

---

## 13. Claude Code のレビュー規約

Claude Code は、Codex の実装完了後に `REVIEW-N.md` を作る。

レビュー観点:

```text
1. PLAN.md の Scope を満たしているか
2. Non-goals を侵していないか
3. 変更ファイルが妥当か
4. テストが追加/更新されているか
5. 既存テスト・lint が通っているか
6. エラー処理・境界条件が妥当か
7. セキュリティ・secret・destructive operation の問題がないか
8. 不要なリファクタや unrelated change がないか
9. CODEX_DONE.md の内容と実際の diff が一致しているか
10. CODEX_DONE.md の background process / terminal の申告を画面で確かめたか（§18.7 の必須確認）
```

`REVIEW-N.md` のテンプレート:

```md
# Claude Review <N>: <TASK_ID>

Status: APPROVED | CHANGES_REQUESTED | BLOCKED | ABORTED

## Summary
Claude Code のレビュー要約。

## What matches the plan
- ...

## Problems
- ...

## Required fixes
1. ...
2. ...

## Validation performed by Claude Code
- command: <...>
  result: pass/fail/not-run

## Decision
APPROVED / CHANGES_REQUESTED / BLOCKED / ABORTED
```

Claude Code は、承認できるまでは `APPROVED` を書かない。

### 13.1 レビューの可視化（任意・hunk 併用）

hunk CLI がある場合（`which hunk`）、人間向けの diff を新しいタブで見せ、REVIEW-N.md の指摘を注釈にできる。Claude 自身は `git diff` を読む。hidden モードではタブを作らず、この可視化を省く。

child モードでは `herdr-app ls` で `logs/lane.json` の `caller_terminal` を含む space を次の式で探す（2026-10-30 E2E で確認）。フォーカス中の space を推測で使わない。space モードでは記録した `.space` を使う。アプリが無い、または委譲元が見つからない場合も可視化だけを省く。

```bash
REVIEW_SPACE=""
if [ "$MODE" = child ]; then
  REVIEW_SPACE="$(herdr-app ls | jq -r --arg t "$CALLER_TERMINAL" '.spaces[] | select(any(.tabs[].terminals[]; .terminal == $t)) | .id')"
elif [ "$MODE" = space ]; then
  REVIEW_SPACE="$(jq -r '.space // empty' "$TASK_DIR/logs/lane.json")"
fi
# hidden または委譲元が見つからない場合はタブを作らない。
if [ -n "$REVIEW_SPACE" ]; then
  herdr-app do tab.new --space "$REVIEW_SPACE" --name "review $TASK_ID" \
    --folder "$WT" --argv '["hunk","diff"]' > "$TASK_DIR/logs/review-tab.json"
  HUNK_TAB="$(jq -r '.tab // empty' "$TASK_DIR/logs/review-tab.json")"
  test -n "$HUNK_TAB"
  hc read "$(jq -r .terminal "$TASK_DIR/logs/review-tab.json")"
fi
```

`tab.new` の直後は hunk がまだ daemon に登録されていないことがある。タブを開いた場合は、上の `hc read` で **`working tree` を含む hunk のヘッダが出たことを確かめてから**、次の session CLI を使う。`No active Hunk sessions` で失敗したら、同じターミナルを `hc read "$(jq -r .terminal "$TASK_DIR/logs/review-tab.json")"` で読み直し、ヘッダを確かめ直して **失敗した session CLI を1回だけ再実行**する。再び失敗したら原因を確認し、繰り返さない（2026-10-30 E2E）。

```bash
# Claude は session CLI で構造把握と注釈を行う（TUI は操作しない）
hunk session review --repo "$WT" --json
printf '%s\n' '{"comments":[{"filePath":"src/x.ts","newLine":12,"summary":"REVIEW-01 #1: ..."}]}' \
  | hunk session comment apply --repo "$WT" --stdin
```

指摘の summary には `REVIEW-N.md` の項番を含める。session CLI の全コマンド（navigate / reload / comment 等）は `hunk skill path` の同梱スキルが正本。**REVIEW-N.md が正本**であり、注釈は補助である。

レビュー完了後（APPROVED / ABORTED）は、作ったタブを閉じ、そのターミナルも消す（§15）。`tab.close` の直後はまだ live のことがあり、すぐ `hc rm` すると `kind: live` で失敗する。自分で作ったターミナルだけを `hc kill` → `hc rm` する（2026-10-30 E2E で確認）。タブを開いた場合だけ次を実行する。

```bash
herdr-app do tab.close --id "$HUNK_TAB" --confirmed true
HT="$(jq -r .terminal "$TASK_DIR/logs/review-tab.json")"
hc kill "$HT"
hc rm "$HT"
HUNK_TAB=""
```

---

## 14. 修正ループ

Claude Code が `CHANGES_REQUESTED` と判断した場合、同じ Codex のターミナルを使い、`FIX-N.md` を作って再度 `/goal` を送る。

### 14.1 `FIX-N.md` テンプレート

```md
# Fix Request <N>: <TASK_ID>

Review result: CHANGES_REQUESTED

## Read first
- .ai/tasks/<TASK_ID>/PLAN.md
- .ai/tasks/<TASK_ID>/REVIEW-<N>.md
- .ai/tasks/<TASK_ID>/CODEX_DONE.md

## Must fix
1. <file path>
   - Problem: ...
   - Expected: ...
   - Test: ...

2. <file path>
   - Problem: ...
   - Expected: ...
   - Test: ...

## Do not
- Do not rewrite unrelated modules.
- Do not broaden scope beyond PLAN.md.
- Do not modify files unrelated to the review findings.

## Validation
- <command>
- <command>

## Done condition
- All Must fix items are addressed.
- Update .ai/tasks/<TASK_ID>/PROGRESS.md with this round's checkpoints.
- Do not start subagents.
- Stop every background process or terminal you started before writing CODEX_DONE.md. Write CODEX_DONE.md as your last action.
- CODEX_DONE.md is updated, with first line `Round: fix-<N>`.
```

### 14.2 修正 goal の投入

修正の goal の前には、**必ず**タグ無しで既存 goal を clear する。送った後に画面を読み、入力行に `<hc from=` が無いことと `Goal cleared`（既存 goal が消えたこと）を確かめる。消えていなければ修正 goal を送らない（2026-10-30 E2E で確認）。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
hc_raw send "$CODEX" "/goal clear"
hc read "$CODEX"
```

修正も §10 と同じ送信・待ちのループを **Bash の `run_in_background` で1コマンドとして実行**する。`not_started`・blocked・timeout と待ち結果の `.wait.*` は §10 と同じ扱い。`hc_raw` では `reason: message` を期待しない。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
FIX_N="01"   # 2桁
FIX_GOAL="/goal Read .ai/tasks/$TASK_ID/FIX-$FIX_N.md and apply only those fixes. Update CODEX_DONE.md (first line: Round: fix-$FIX_N)."
SENT="$TASK_DIR/logs/fix-$FIX_N.sent"
touch "$SENT"
hc_raw send --wait --timeout 300 "$CODEX" "$FIX_GOAL" > "$TASK_DIR/logs/send-wait-fix-$FIX_N.json" 2>&1
while [ "$(hc get "$CODEX" --json 2>/dev/null | jq -r '.status.state // empty')" = working ] \
  && ! [ "$TASK_DIR/CODEX_DONE.md" -nt "$SENT" ]; do
  hc wait "$CODEX" --timeout 300 > "$TASK_DIR/logs/wait-last.json" 2>&1
done
hc get "$CODEX" --json | jq -c '{state, status, foreground: .foreground.name}'
jq -c '.wait | {reason, status}' "$TASK_DIR/logs/send-wait-fix-$FIX_N.json"
```

**`.wait.reason` が `not_started` なら**、`hc read "$CODEX"` で `Pursuing goal` / `Working (` / `Running hook` を確認し、見えたら §11 のループを回して合流する。見えなければ **送り直さず** §18.2 の判断をする（2026-10-30 E2E）。

修正 goal の送信をバックグラウンドで始めたら、`hc read "$CODEX"` で入力行に `<hc from=` が無いことと `Goal active` が出たことを確かめる。待ちが返ったら §2.3 を確認する。working のまま今回の報告が新しければ §18.7 へ。先頭行が `Round: fix-$FIX_N` であり、FIX 送信後に更新されたことも確認する。

```bash
[ "$(head -n1 "$TASK_DIR/CODEX_DONE.md")" = "Round: fix-$FIX_N" ]
[ "$TASK_DIR/CODEX_DONE.md" -nt "$TASK_DIR/logs/fix-$FIX_N.sent" ]
```

前ラウンドの CODEX_DONE.md を取り違えない。合わなければ §18.3。

### 14.3 ループ上限

Claude Code は無限に修正ループを回さない。

```text
デフォルト上限: 3ラウンド
```

3ラウンドで収束しない場合:

```text
1. REVIEW-FINAL.md に ABORTED または BLOCKED を書く
2. 未解決点を箇条書きにする
3. 現在の diff / terminal log / status を保存する
4. 同じターミナルの文脈が汚れている可能性があれば Codex を止める
5. 必要なら新しい Codex のターミナルを起動し、PLAN.md + 最新 REVIEW/FIX + 現在 diff を読ませて再開する
```

---

## 15. Codex を止めるタイミング

Codex が done になった直後には止めない。停止の条件:

```text
Claude Code review: APPROVED または ABORTED
Codex status: done または idle
未処理の blocked 質問: なし
CODEX_DONE.md: あり（今回の Round）
REVIEW-FINAL.md: あり
final diff / status / terminal output: 保存済み
次の FIX-N.md を投げる予定: なし
```

レビュー前、working、未処理の blocked、次の FIX がある間は止めない。中止時は、可能なら先に pause を送る。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
hc_raw send "$CODEX" "/goal pause"
```

画面の記録・差分の保存と `REVIEW-FINAL.md` 作成後に片付ける。`hc read --lines 500` は画面全体 + 上の履歴500行であり、Codex の TUI の全経過は取れない。経過の正は `PROGRESS.md` / `CODEX_DONE.md`（§12）。**`hc kill` は SIGKILL による即時終了**なので、作業中の中止は可能なら先にタグ無しの pause を送る（2026-10-30 E2E で確認）。下の操作は今回起動した Codex と作ったタブ・space だけを対象にする。

```bash
hc read "$CODEX" --lines 500 > "$TASK_DIR/logs/codex-final.txt"
git -C "$WT" status --short > "$TASK_DIR/logs/final-status.txt"
git -C "$WT" diff > "$TASK_DIR/logs/final.diff"

# §13.1 でまだ片付けていない hunk タブとそのターミナルだけ先に消す。
if [ -n "${HUNK_TAB:-}" ]; then
  herdr-app do tab.close --id "$HUNK_TAB" --confirmed true
  HT="$(jq -r .terminal "$TASK_DIR/logs/review-tab.json")"
  hc kill "$HT"
  hc rm "$HT"
  HUNK_TAB=""
fi
hc kill "$CODEX"
hc rm "$CODEX"

# 最後のターミナルを hc rm すると space も自動で消える（2026-10-30 E2E で確認）。
# 今回作った space が herdr-app ls にまだある場合だけ閉じる。
SPACE="$(jq -r '.space // empty' "$TASK_DIR/logs/lane.json")"
if [ -n "$SPACE" ] && herdr-app ls | jq -e --arg id "$SPACE" 'any(.spaces[]; .id == $id)' >/dev/null; then
  herdr-app do space.close --id "$SPACE" --confirmed true
fi
```

child モードでは委譲元の space を閉じない。hidden モードでは space を作っていないので `space.close` を呼ばない。checkout はまだ残し、取り込みは §16、worktree の削除は §17 で行う。

---

## 16. 承認後の取り込み（commit → merge / PR）

`REVIEW-FINAL.md` に APPROVED を書いて Codex のターミナルを片付けたら、Claude Code が成果を取り込み可能な状態にする。レビューは未コミット diff に対して行うため、承認後のコミットが必要になる。

```text
1. Claude Code が Codex worktree でコミットする
   - コミットは Claude Code の担当（Codex にはさせない）。
   - PLAN.md の Objective を要約したメッセージに TASK_ID を含める。
   - .ai/ は info/exclude 済みだが、コミット前に git status で混入がないことを確認する。
2. superpowers:finishing-a-development-branch スキルを起動する
   - merge / PR / 保留 / 破棄 の選択肢を人間に提示し、決定に従う。
   - スキルが使えない環境では、同等の選択肢を人間に確認してから実行する。
   - PR を作ると決まったら、gh pr create の前に本文を yomiyasu で推敲する（§16.1。任意）。
3. 決定を実行したら（merge 完了 / reject）、§17 の worktree cleanup に進む。PR を作った場合は、
   PR がマージ（またはクローズ）されるまで worktree を残し（レビュー対応の修正に使う）、その後 §17 に進む
```

```bash
git -C "$WT" status --short    # .ai/ や無関係ファイルが混ざっていないこと
git -C "$WT" add -A
git -C "$WT" commit -m "<type>: <PLAN.md の Objective 要約> ($TASK_ID)"
```

注意:

- §15 の final ログ保存を先に済ませること（`final.diff` は未コミット状態の記録として残す）。
- PR にする場合のブランチは §6 で作った `ai/<TASK_ID>`。push の可否・リモート・レビュー運用はプロジェクト規約に従う。
- 人間が破棄（reject）を選んだ場合、コミット済みのブランチごと §17 の cleanup で worktree を破棄してよい（変更内容は `logs/final.diff` にも保存済み）。人間が事前に破棄を明言している場合は、コミット自体を省略して §17 に進んでよい。

### 16.1 PR の本文の推敲（yomiyasu。任意）

PR を作ると決まったら、`gh pr create` の前に本文を [yomiyasu](https://github.com/nanaism/yomiyasu)（AI が書いた日本語を読みやすく直すスキル）で推敲してから使う。PR の本文は人間が読む文章なので、ここで使う。コミットメッセージ・`PLAN.md`・`CODEX_GOAL.md`・`REVIEW-N.md` には使わない。

```text
1. 本文を .ai/tasks/<TASK_ID>/PR_BODY.md に書く。
2. 次のどちらかに当たれば、この節の 3 を飛ばして 4 に進む。
   - 本文が日本語でない（yomiyasu は日本語専用）
   - スキル一覧に yomiyasu:yomiyasu（プラグインで入れた場合）も yomiyasu（npx skills などで
     入れた場合）も無い（dev-workflow は yomiyasu を必須にしない）
3. 一覧にあるほうの名前で yomiyasu を起動し、「PR_BODY.md を推敲し、最終稿を同じフォルダの
   PR_BODY.final.md に保存して」と頼む（ファイルを渡したときの保存先は yomiyasu が決めないので、
   名前を指定する）。PR_BODY.final.md ができたことを確かめる。
   - yomiyasu が「書き手に確かめたい点」を返したら、本文を書いた Claude Code が PLAN.md・
     REVIEW-*.md・会話から答えて推敲し直す。答えが決まらないものだけを人間に聞く。
   - 推敲の前後の差分は人間に見せない。
4. gh pr create --body-file .ai/tasks/<TASK_ID>/PR_BODY.final.md を実行する（3 を飛ばしたときは PR_BODY.md）。
```

yomiyasu は状態フォルダ `.yomiyasu/` を git リポジトリの最上位に作るが、中に自分で `.gitignore` を置くので、`.ai/` と違って `.git/info/exclude` に足さなくてよい（レビュー対応のコミットの `git add -A` にも混ざらない。yomiyasu 2.1.1 で確認）。

---

## 17. worktree cleanup のタイミング

Codex の停止と worktree remove は別である。**Codex を止めてから worktree remove** を行う。

```text
Codex の停止・片付け（§15）:
  最終レビュー後に hc kill + hc rm。作った space があれば閉じる。checkout は残す。
worktree remove:
  merge / reject 後に checkout を消す。PR はマージまたはクローズまで残す。
  Codex が中で動いたままディレクトリを消さない。
```

```bash
git -C "$ROOT" worktree remove "$WT"
git -C "$ROOT" branch -d "$BRANCH"   # merge 済み。reject は -D
```

- PR 中は worktree もブランチも残す。未マージでクローズしたら reject と同じ扱い。
- `.ai/` は info/exclude で無視されるが checkout と一緒に消えるため、残したいログは事前に退避する。
- 未コミット変更で拒否されたときに `worktree remove --force` を使うのは、`logs/final.diff` 保存済みで人間が破棄を選んだ場合だけ。
- 中止時も §15 のログ保存・停止・片付けを先に行う。

### 17.1 2.0.0 より前 (herdr TUI) のレーンの片付け

旧 herdr TUI のレーンが残っていたら、対象を確認して `herdr pane close <pane>` で閉じ、worktree は Git で消す。さらに古い worktree グループの片付けは plugin 1.8.0 の workflow.md §17.1 を Git 履歴から参照する。

---

## 18. blocked / failed / 状態報告なしの扱い

### 18.1 Codex が blocked

Codex を閉じず、`hc read "$CODEX" --lines 200` と `BLOCKED.md` を読む。起動ダイアログなら §9。権限など人の判断が要る質問はユーザーに聞く。`hc_raw send --force` で飛ばさない。

Claude が判断できる不足情報は `CLARIFICATION.md` または `FIX-N.md` に書き、画面を確認して必要な回答または再 `/goal` を送る。解決できなければ `REVIEW-FINAL.md` に BLOCKED と理由を書く。goal の進捗なしが続いて blocked になった場合も画面で原因を確認し、具体的な次の一手を渡す。

### 18.2 Codex が done / idle だが CODEX_DONE.md がない

実装完了とみなさず `hc read` で画面を確認する。ダイアログに goal が飲まれたか、goal が自動継続しているかを見分ける。まだ続いていれば送り直さず、working に戻ったら §10 の待ちに合流する。2026-10-30 E2E で自動継続ターンの境目は起きたが、background terminals が残っている間は done / idle を出さなかった。ループは今回の CODEX_DONE.md の新しさで抜けるので、どちらでも動く。background terminals が無いときの境目で一度 done になった場合は、ループを抜けて §2.3 → §18.2 で画面を読む（この経路は未確認）。

送り直すのは **ダイアログを閉じ、元の goal が実行されていないことを確認した後だけ**。この再送は修正ラウンドに数えない。実際に実装を終えたのに報告だけが無い場合は `CHANGES_REQUESTED` とし、CODEX_DONE.md の作成と変更点・テスト・リスクの記録を求める。

### 18.3 `Round:` がこのラウンドでない

古い CODEX_DONE.md を今回の完了と取り違えない。先頭行と §14.2 の送信時刻比較を確認する。working なら待ち直し、止まっていれば画面と成果物を読み、今回の報告への更新を求める。Round が違うままレビュー承認しない。

### 18.4 状態の報告が無い

**goal を送った後**も `status: null` なら、Codex が OSC 7501 を出していない状態として確認する。起動ダイアログ中の null は正常（§9）。hc は画面から状態を補完しない。

```bash
hc get "$CODEX" --json
hc read "$CODEX" --lines 200
```

`--no-daemon` での起動を確認し、画面・diff・task files を読む。未送達とは決めつけず、goal を自動再送しない。接続エラーも完了扱いせず、不明なら BLOCKED として人に報告する。

### 18.5 Codex が scope を広げた

Claude Code は `CHANGES_REQUESTED` とし、`FIX-N.md` で unrelated change の revert を要求する。

### 18.6 Codex が終わった (`state: finished` または foreground が変わった)

`hc get` の `.state`・`exit_code`・`.foreground.name` と `hc read` の画面を確認する。space モードは `zsh -ic '…; exec zsh -i'` の中で動くので、Codex が自分で終わってもターミナルは live のまま zsh になる。起動確認後に **`.foreground.name` が codex でなくなったら Codex は終了した**とみなす（2026-10-30 E2E で確認）。

自己更新などで起動し直す場合、今回の終了済みターミナルを `hc rm` する。space モードで zsh が live のままなら、そのシェルを `hc kill` してから `hc rm`。space は自動で消える場合があるため、§15 と同じく `herdr-app ls` に今回作った space がまだあるときだけ閉じる。§9 と同じ方法で起動し直し、返った ID を lane.json に更新する。ユーザーの他の space は触らない。新しい TASK_ID / worktree は作らず、ダイアログ確認から再開する。作業がどこまで進んだかをファイルで確認し、既に送達した goal を無条件に再送しない。

### 18.7 ターンが終わったのに working のまま (background terminals)

Codex 0.164 は background terminals が残ると、ターン終了後も OSC 7501 で working を出し続けることがある（2026-10-30 child E2E で初回・修正の両方で確認）。§10 / §14.2 のループを今回の新しい CODEX_DONE.md で抜けたら、`hc read "$CODEX"` の画面を確認する。

**§18.7 の画面確認はレビュー前に必ず行う。** §8 / §14.1 の background terminals を止める指示は残すが、効かないことがある。2026-10-30 E2E では Codex が閉じられず、CODEX_DONE.md に「残っていない」と申告したのに画面には14個出ていた。申告だけで片付け済みと判断せず、状態が done / idle の場合も画面を確認する。

**次の条件をすべて満たした場合だけ**、下の `/stop` を送る。

- CODEX_DONE.md の先頭行の Round が今回と一致し、送信マーカー `$SENT` より新しい。
- 画面に入力欄 `›` と `background terminal(s) running`（例: `8 background terminals running`）が見える。
- `Working (` のスピナーが無く、ターンが終わっている。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
hc_raw send "$CODEX" "/stop"
hc wait "$CODEX" --timeout 300
hc get "$CODEX" --json | jq -c '{state, status, foreground: .foreground.name}'
```

`done` / `idle` になったことを確かめて §2.3 の完了確認に戻る。条件を満たさずまだ作業中なら `/stop` を送らず、§11 の **CODEX_DONE.md の条件なし**のループ（`--timeout 300`）で待ち直す。作業中のテストやサーバーを止めないため、ファイルが新しいだけで `/stop` を送らない。

---

## 19. 安全ルール

Codex には次を許可しない。必要な場合は人間の明示承認を求める。

```text
- production deploy
- publish / release
- secret / credential の表示・変更・送信
- destructive DB operation
- rm -rf や大量削除
- unrelated large refactor
- dependency major upgrade
- security bypass
- network access が必要な操作
```

Codex がこれらを実行しようとして blocked になった場合、Claude Code は原則として拒否し、安全な代替を `FIX-N.md` に書く。

---

## 20. Claude Code 用の実行チェックリスト

```text
[ ] Step 0: check-versions.sh。core 再起動はユーザーに確認してから
[ ] TASK_ID・名前・worktree の場所の空きを確認し、Git worktree を作る。info/exclude の .ai/ は重複させない
[ ] HC_TERMINAL_ID → child、外でアプリ稼働 → space、それ以外 → hidden を選ぶ
[ ] logs/lane.json に委譲元・モード・Codex の名前を記録
[ ] brainstorming → writing-plans で PLAN.md、CODEX_GOAL.md を worktree 内に書く
[ ] child/hidden は hc run --bg、space は space.new --argv。必ず codex --no-daemon
[ ] child は --outlive-parent --no-notify。Codex に hc send で報告させない
[ ] 起動応答を run.json に保存。space は返った terminal / space / tab を lane.json に記録
[ ] hc get と hc read で起動確認。permissions の行と status.state=idle がそろうまで送らない（§9）
[ ] trust は enter（esc は Quit）、hooks は esc。permissions の行と hooks を閉じた影響を REVIEW と人への報告に記録
[ ] hidden ならユーザーに hc attach を案内
[ ] §2.1 の hc_raw を定義し、送信マーカーを touch。1行 /goal を hc_raw send --wait --timeout 300 で送る（run_in_background、§10）
[ ] 送信後の画面にタグが無く Goal active が出たことを確認。working かつ今回の報告が新しくない間だけ待つ
[ ] 待ち結果は .wait.*。timeout はチェックイン。hc_raw では message を期待しない。not_started は画面確認
[ ] working のまま今回の報告があれば §18.7 の条件を確認。作業中に無条件の /stop を送らない
[ ] §2.3 の状態と CODEX_DONE.md の先頭行 Round を確認
[ ] ログ・git diff・status・テスト結果を保存し、REVIEW-01.md を書く
[ ] 任意で hunk のタブにレビューを可視化（§13.1。hidden では省く）
[ ] 修正 goal の前に必ず hc_raw send で /goal clear を送り画面で確認。同じ Codex に FIX-NN.md を送り、Round と送信後の更新を照合（最大3回）
[ ] APPROVED / ABORTED を REVIEW-FINAL.md に書き、final logs を保存
[ ] hunk のタブを閉じてターミナルを hc kill → hc rm。Codex も hc kill → hc rm。作った space がまだあるときだけ閉じる
[ ] Claude がコミットし、finishing-a-development-branch で merge / PR / reject を確認
[ ] PR 本文は yomiyasu があれば推敲（§16.1）
[ ] worktree は PR 中も残す。merge / reject 後、Codex 停止済みを確認して Git で消す
```

---

## 21. 参考 wrapper

必要なら以下の小さな関数だけを使う。起動・送信・ラウンド確認は本文の手順を使う。

```bash
hc_raw() { env -u HC_TERMINAL_ID -u HC_SCOPE hc "$@"; }   # §2.1。Bash の呼び出しごとに定義し直す
codex_status() {
  hc get "$1" --json | jq -c '{state, status, exit_code, foreground: .foreground.name}'
  hc read "$1"   # 画面全体で起動ダイアログと入力欄を確認する
}

codex_wait() {
  # 送信には先に hc_raw send --wait を使う。この関数は working の待ち直し用。
  while [ "$(hc get "$1" --json 2>/dev/null | jq -r '.status.state // empty')" = working ]; do
    hc wait "$1" --timeout 300
  done
  hc get "$1" --json | jq -c '{state, status, foreground: .foreground.name}'
}
```

Bash の `run_in_background` で待ち、sleep は使わない。関数が返っただけで完了扱いせず、§2.3 の確認を行う。

---

## 22. Claude Code への最終指示

```text
- PLAN.md の前に brainstorming、執筆に writing-plans を使う。
- 詳細はファイル、Codex には1行 /goal で渡す。
- 起動・制御・待ちは hc、画面変更は限定した herdr-app do に分ける。
- child / space / hidden を判定し、どの Claude が起動したかを lane.json に残す。
- 必ず codex --no-daemon。親のある起動は --outlive-parent --no-notify を付ける。
- Codex に hc send で報告させない。報告は CODEX_DONE.md / BLOCKED.md。
- 起動直後に送信せず、hc get と hc read で入力欄とダイアログを確認する。
- Codex への送信はすべて hc_raw send。送信後の画面でタグ無しと Goal active / コマンド応答を確認する。
- 初回も修正も送信マーカーを touch し、hc_raw send --wait --timeout 300 で待つ。待ち結果は .wait.*。
- working かつ今回の報告が新しくない間は hc wait。新しい報告があれば §18.7 の条件を確認する。
- hc_raw では message を期待せず、timeout のチェックインで確認する。sleep で回さない。
- not_started や成果物なしの done / idle で盲目的に再送しない。画面を読む。
- hc_raw send --force でダイアログや権限の判断を飛ばさない。
- 完了は状態と今回の Round の CODEX_DONE.md で判断する。
- 完了確認はレビュー開始の条件であり、停止の条件ではない。
- 修正は同じ Codex のターミナルで最大3ラウンド。毎回必ず /goal clear をタグ無しで送り、消えたことを確認してから修正 goal を送る。
- APPROVED / ABORTED と画面の記録保存の後に、hunk タブとターミナルを消し、Codex を hc kill + hc rm。作った space がまだあるときだけ閉じる。
- ユーザーの他のターミナル・space・既定 core を止めない。
- 承認後のコミットは Claude が行い、merge / PR / reject は finishing-a-development-branch で確認する。
- Codex を止めてから worktree を消す。PR 中は残す。
- source of truth は task files と git diff とテスト結果。画面出力だけではない。
```
