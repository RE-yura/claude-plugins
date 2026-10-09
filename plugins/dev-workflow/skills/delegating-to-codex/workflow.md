# Claude Code Operating Procedure: Codex Delegation via Herdr + `/goal`

この文書は、Claude Code が詳細な実装計画を作成し、Herdr 経由で Codex CLI の `/goal` に実装を委譲し、Claude Code がレビューし、必要に応じて Codex に修正を繰り返させるための運用手順である。

Claude Code は、この文書を「実装委譲ワークフローの実行規約」として扱うこと。

> 検証済み環境の正は同ディレクトリの [versions.json](versions.json)（herdr 0.9.1 / codex-cli 0.156.1 / superpowers 6.4.1 / Claude Code 2.1.281、2026-09-24 実機再検証・E2E 委譲一巡。過去: 0.9.0 / 0.8.2 / 0.8.0 / 0.7.5 / 0.7.1）。委譲開始前に必ず `check-versions.sh` を実行し、実機バージョンとのズレを検出すること（§5）。herdr の CLI はバージョンで大きく変わる（実例: 0.7.5 で `agent start` の署名変更・トップレベル `wait` 廃止・`agent prompt` 追加。0.8.0 で `prompt --wait` が主経路化・`--json` 廃止（JSON がデフォルト）・idle alternate-screen の自動履歴読み。0.9.0 は本書が使うコマンドの引数・出力は不変だが、`prompt --wait` の stalled 判定が厳密化（§2.3）、`workspace close --group` 追加（§17）、worktree 系に `--trust-repository` 追加、`--no-session` 廃止、client/server の protocol が 20→22 で分離・`herdr status` の出力キー変更。0.9.1 は SSH マシン操作・Windows・UI 中心で本書のコマンドは不変。Codex の状態検出が改善（入力欄の装飾で idle を blocked と誤判定しない #4092/#4099）、`worktree create --no-focus` は引き続き尊重される）。動かない場合はまず引数なし実行で usage を確認し、`herdr --skill`（0.8.0+、同梱の公式エージェント向け説明）と公式 https://herdr.dev/docs/agent-automation/ に突き合わせること。ただし **`herdr worktree create` だけは引数なしでも既定値で即実行される**ので usage 確認目的で叩かないこと（0.7.4 実測）。

---

## 1. 目的

Claude Code と Codex の役割を分離する。

```text
Claude Code = 設計者・計画作成者・レビュアー・承認者
Codex CLI   = 実装担当・テスト実行担当・修正担当
Herdr       = Codex pane/agent の起動、入力送信、進捗可視化、状態検知
Git worktree = Codex が安全に編集する隔離された作業領域
Task files  = Claude Code ↔ Codex 間の契約・状態・成果物
```

このワークフローのゴールは、Codex の画面出力をその場限りで読むことではない。`PLAN.md`、`CODEX_GOAL.md`、`PROGRESS.md`、`CODEX_DONE.md`、`REVIEW-N.md`、`FIX-N.md`、`git diff` を残し、Claude Code が確実にレビュー・修正指示・承認を行える状態にすることである。

---

## 2. 基本方針

### 2.1 Herdr の使い分け

Claude Code は、原則として次の順で Herdr を使う。

```text
第一選択: herdr agent ...
  Codex を名前付き agent として扱う。
  start / get / read / wait / prompt / send-keys / focus / rename に使う。
  ターゲットは agent 名と、agent が居る pane の id。

補助: herdr pane ...
  pane の用意（worktree create の root pane / pane split）、shell コマンド実行（pane run）、
  キー送信（send-keys）、Enter なしの文字列配置（send-text）、
  marker 検出（pane wait-output）、pane close に使う。
  pane コマンドのターゲットは pane id のみ（agent 名は不可）。

後回し: socket API
  常駐 orchestrator、イベント購読、Herdr plugin 化、複数 agent の大規模制御が必要になるまで使わない。
```

使い分けの実務ルール:

```text
/goal・プロンプトを送って完了まで待つ -> herdr agent prompt <agent> "<text>" --wait --timeout <ms>
  （0.8.0 の主経路。text + エンコード済み Enter を送信し、idle|done|blocked の
    settled state 到達で返る。bracketed paste 尊重・複数行も1メッセージ。
    送信後5秒以内に working|blocked が観測できないと agent_prompt_stalled エラー。
    0.9.0 で厳密化: 無関係な idle/done 遷移では満たされない。caller timeout が
    先に切れれば timeout エラー。どちらも「未送達」の証明ではない → §2.3）
送信だけして待たない -> herdr agent prompt <agent> "<text>"（--wait なし）
Codex TUI に文字列だけ置く（Enter なし） -> herdr pane send-text <pane_id> "<text>"
Codex の直近出力を読む -> herdr agent read <agent> --source recent-unwrapped --lines 200
  （plain text がそのまま出る。jq 不要）
Codex の semantic state を待つ -> herdr agent wait <agent> [--until <status>]...
  （--until なしは idle|done|blocked のいずれかを待つ。--wait と同じ既定）
完了 marker を探す -> herdr pane wait-output <pane_id> --regex ... --timeout ...
  （0.8.0 の --match は substring なので marker には使わない。§2.3）
ダイアログ操作のキー送信 -> herdr agent send-keys <agent> enter（0.8.0。pane send-keys でも可）
普通の shell pane に command を打つ -> herdr pane run <pane_id> "<cmd>"
```

JSON とテキストの区別（0.8.0 実測）:

- `agent get` / `agent start` / `agent prompt` / `worktree create` / `workspace create` /
  `pane move` / `pane wait-output` / `workspace list` は
  `{"id":...,"result":{...}}` の JSON エンベロープを返す。pane id は
  `jq -r '.result.agent.pane_id'` のように取り出す。0.8.0 で JSON がデフォルトに
  なり **`--json` フラグは廃止**（worktree 系のみ互換のため受理されるが付けない。
  `workspace list --json` 等は usage エラーになる）。
- **`agent read` と `pane read` は plain text をそのまま出力する**（0.7.5 で
  agent read も plain text 化。旧版の `jq -r '.result.read.text'` は parse error
  になるので使わない）。

`--source` の使い分け: `recent-unwrapped` は履歴バッファで、バッファ末尾に空行が
並びがちなため **`--lines` が小さいと空に見える**（`--lines 200` 以上を推奨。
0.8.0 でも実測で再現）。「いま画面に映っているもの」が欲しいときは
`--source visible` を使う。送信直後は recent バッファへの反映に数秒の遅延が
あり得るので、marker 待ちの timeout を極端に短くしないこと。Codex 等の全画面 TUI
は代替画面（alternate screen）に描画するが、**0.8.0 は idle になった agent の
代替画面からテキスト履歴を自動収集する**ため、完了後の read で全トランスクリプト
が取れる（実測: goal エコーから最終 marker まで取得できた）。working 中の読み
取りは従来どおり不完全なことがある。成果物をファイル（CODEX_DONE.md 等）を正と
する方針は維持する（公式もフォールバックとして同パターンを推奨）。

その他の実測挙動:

- `herdr pane run` は成功時に**何も出力しない**（exit 0 のみ）。出力が空でも失敗と
  みなさないこと。
- **terminal id（`term_...`）は herdr 再起動で変わる**。スクリプトやログに terminal
  id を保存して使い回さず、ターゲットは agent 名を正とする。

### 2.2 `/goal` には長文を貼り付けない

Codex の `/goal` に巨大な計画全文を貼り付けない。Claude Code は詳細をファイルに書き、Codex には **1行の `/goal`** でそのファイルを読ませる。

良い例:

```text
/goal Read .ai/tasks/<TASK_ID>/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:<TASK_ID>; if blocked print HERDR_TASK_BLOCKED:<TASK_ID>.
```

悪い例:

```text
/goal <PLAN.md の全文を長大に貼り付ける>
```

理由:

- 画面出力だけを source of truth にするとレビュー不能になる。
- ファイル参照にすれば Codex が読み直せる。
- Claude Code が後から `PLAN.md` / `FIX-N.md` / `REVIEW-N.md` を検証できる。

（0.7.5+ の `agent prompt` は bracketed paste を尊重し、複数行テキストも1メッセージ
として送れることを実測済み。旧版にあった「改行が Enter として解釈される」問題は
解消されたが、上記の理由によりファイル契約は維持する。）

`/goal` のサブコマンドは `/goal <objective>`（設定）、`/goal`（状態表示）、`/goal pause`、`/goal resume`、`/goal clear`（codex-cli 0.128+、公式ドキュメント確認済み）。

### 2.3 完了判定は三重化する

`HERDR_TASK_DONE` または Herdr の `done` / `idle` だけで実装完了とみなさない。

Claude Code は次の3つを組み合わせて判断する。

```text
1. Herdr semantic state
   - idle / working / blocked / done / unknown
   - 0.8.0 で公式定義が明文化: idle = 入力可能 かつ その tab が focused UI で
     既読。done = 未読のままバックグラウンド作業が終わった同じ idle 状態。
     CLI read では既読にならない。→ CLI 駆動の本フローでは完了は done になる
     （実測）。人間が Codex タブを見ていると idle になり得る。
     完了待ちは `agent prompt --wait` または `agent wait`（--until なし =
     idle|done|blocked のいずれか到達で返る）で行い、返ってきた JSON の
     .result.agent.agent_status で分岐する。

2. 明示 marker
   - HERDR_TASK_DONE:<TASK_ID>
   - HERDR_TASK_BLOCKED:<TASK_ID>
   - HERDR_TASK_DONE:<TASK_ID>:fix-01
   - 注意（実測）: /goal 本文に marker 文字列を含めるため、pane wait-output は
     goal のエコー行（"• Goal active Objective: ... HERDR_TASK_DONE:..."）に
     即マッチする。marker 検出は行頭アンカー付き regex
     （--regex '^• HERDR_TASK_DONE:<TASK_ID>'。Codex の実 print は
     "• HERDR_TASK_DONE:<TASK_ID>" の形で行頭に出る）を使い、
     応答の matched_line がエコー行でないことを確認する。

3. ファイルと Git 差分
   - CODEX_DONE.md
   - PROGRESS.md
   - git diff
   - test/lint 結果
```

`HERDR_TASK_DONE` は「Codex の1回の goal が止まった」という意味であり、Claude Code の承認完了ではない。

送信直後のレース（0.7.5 の「送信後すぐ完了待ちに入ると前ラウンドの done/idle で
即 return する」問題）は、0.8.0 では `agent prompt --wait` が内部で処理する:
working でない状態から送ったプロンプトは **送信後5秒以内に `working` または
`blocked` が観測できなければ `agent_prompt_stalled` エラーが返る**（公式仕様。偽 done で
即返しない。実測: 送信→working 遷移→1分27秒ブロック→done で返却）。0.9.0 で
この判定は厳密化され、無関係な idle/done/session 変化ではゲートを通過しない
（#3506, #3685）。また caller の `--timeout` は送信時間を含み、先に切れれば
`timeout` エラーになる。あわせて 0.8.0 は送信テキストの後 Enter まで短い待ちを
入れるようになり、旧版の「TUI 初期化中のプロンプトが composer に残ったまま無音で
消える」問題も修正された（release notes #1878）。したがって `--until working`
による開始確認は不要。

**`agent_prompt_stalled` / `timeout` はプロンプト未送達の証明ではない**（0.9.0
`--skill` の明記）。返ったら盲目的に再送せず、まず visible read で画面を確認する:
(a) ダイアログ表示中（§9）→ 対処してから再送、(b) goal が composer に残っている
（Enter が効いていない）→ `agent send-keys <agent> enter` のみ、(c) 既に working で
実行中 → 再送せず `agent wait` で合流。round ごとに marker を変える設計（`:fix-N`）は
引き続き取り違えの保険になる。

---

## 3. ディレクトリ構成

Codex が作業する Git worktree の中に、次の task directory を作る。

```text
.ai/tasks/<TASK_ID>/
  PLAN.md                 # Claude Code が作る詳細実装計画
  CODEX_GOAL.md           # Codex が最初に読む実装契約
  PROGRESS.md             # Codex が checkpoint ごとに更新する進捗ログ
  CODEX_DONE.md           # Codex が完了時に書く完了報告
  BLOCKED.md              # Codex が blocked のときに書く任意ファイル
  REVIEW-01.md            # Claude Code のレビュー
  FIX-01.md               # Claude Code から Codex への修正依頼
  REVIEW-02.md
  FIX-02.md
  REVIEW-FINAL.md         # Claude Code の最終承認または中止理由
  logs/
    agent-start.json
    agent-get.json
    codex-pane-*.txt
    final.diff
    final-status.txt
    test-results.txt
```

重要: main checkout に未コミットで作った task files は、別 worktree には自動では存在しない。Claude Code は worktree を作成した後、Codex が読む task files を **Codex worktree 内**に作成すること。

また、`.ai/` は untracked のまま Codex の `git status` / diff に混ざり、Codex が誤ってコミットに巻き込むリスクがある。worktree 作成直後に `.git/info/exclude` へ `.ai/` を追加して Git から隠すこと（§6 参照）。

---

## 4. 推奨ライフサイクル

```text
0. Claude Code が check-versions.sh で依存バージョンを検証する（§5）
1. Claude Code が TASK_ID を作る
2. Claude Code が Git worktree を作る（応答 JSON の root pane id を控え、.ai/ を exclude する）
3. Claude Code が Codex worktree 内に PLAN.md / CODEX_GOAL.md を作る
   （brainstorming → writing-plans。§7 参照）
4. Claude Code が worktree workspace の root pane に Codex agent を起動する
   （agent start --kind codex --pane。pane move による回収は不要になった）
5. 起動確認を行う（agent get で生存確認 + visible read でダイアログの有無と
   入力プロンプト表示を確認）
6. Claude Code が Codex TUI に 1行の /goal を agent prompt --wait で送る
   （stalled / timeout エラーなら画面確認→送達済みか判断→対処。§2.3）
7. Codex が実装し、PROGRESS.md を更新する
8. Codex が CODEX_DONE.md を作り、HERDR_TASK_DONE:<TASK_ID> を出す（状態は done になる）
9. Claude Code が pane output / git diff / CODEX_DONE.md / test 結果を保存する
10. Claude Code がレビューし、REVIEW-01.md を書く
11. 問題があれば FIX-01.md を書き、同じ Codex pane に再 /goal する
12. 修正ループを最大3回まで繰り返す
13. 承認できたら REVIEW-FINAL.md に APPROVED を書く
14. ログと差分を保存する
15. Codex pane を閉じる
16. Claude Code が worktree でコミットし、finishing-a-development-branch で
    merge / PR / reject を人間に確認する
17. worktree は merge / PR / reject が終わるまで残す
```

---

## 5. 初期セットアップ確認

**Step 0（必須）**: 委譲を開始する前に、依存バージョンチェッカーを実行する。

```bash
"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh
# CLAUDE_PLUGIN_ROOT が未設定の文脈では、この workflow.md と同じディレクトリの
# check-versions.sh を実行する
```

チェッカーは [versions.json](versions.json)（検証済みバージョンの正）と実機の
herdr / codex / superpowers / jq を突き合わせ、ツールごとに OK / WARN / MISSING を
出力する。herdr については `herdr status` で **client と server の整合**も見る
（0.9.0 で protocol 20→22。mise 等で client を入れ替えた直後は既存シェルの PATH に
旧 client が残り、`herdr --version` は旧版・server は新版という状態になる。この
とき agent/workspace 系は全て `protocol_mismatch` の JSON エラーを返す — exit 0
なのでスクリプトは気づけない。実測 2026-09-08。新しいシェルを開くか、mise shims の
herdr を使って揃える）。**exit は常に 0 でブロックはしない** — WARN が出たら各行に書かれた
次アクション（herdr --skill と usage の照合、goals feature の確認など）を実施し、
本書との差分を把握してから進むこと。バージョンを上げて再検証したら
versions.json を更新する。hook 等から低ノイズで呼ぶ場合は `--quiet`（全 OK なら
無出力、WARN / MISSING があるときだけその行と件数を出す）を使う。

続けて、必要に応じて次を確認する。

```bash
herdr integration status || true
```

未導入なら、一度だけ以下を案内または実行する（herdr の integration は自動では
入らない。これがないと `agent wait` の状態検知が働かない）。

```bash
herdr integration install codex
herdr integration install claude
```

`/goal` は codex-cli 0.144+ では feature `goals` が stable・既定有効のため、通常は追加設定不要（実測: `codex features list` で stage=stable / effective=true）。`/goal` が Codex の slash command list に出ない場合（古い codex 等）のみ、`codex features enable goals` を実行するか、Codex の `config.toml` に以下を入れる。

```toml
[features]
goals = true
```

注意（実測）: Codex CLI は起動時にアップデート系の割り込みを出すことがある。

- 自動アップデートして「Please restart Codex」で**即終了する**（0.145 実測。
  agent は `agent_not_found` になる → 同じ pane にもう一度 `agent start`）。
- **対話式アップデートダイアログ**を出して止まる（0.145→0.146 で実測:
  「1. Update now / 2. Skip / 3. Skip until next version — Press enter to
  continue」）。このとき status は `idle` のままで `blocked` にならず、
  **そのまま /goal を送ると Enter が「1. Update now」を選んでしまう**。
  visible read で検出し、`pane send-text <pane_id> "2"` + `agent send-keys
  <agent> enter` で Skip してから送信する。

いずれも `agent start` 直後の §9 起動確認（生存 + visible read）で検出できる。

---

## 6. TASK_ID と worktree の作成

Claude Code は、ユーザーから実装委譲を求められたら、まず task id を作る。

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$(git rev-parse --show-toplevel)"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"
```

Codex 用の Git worktree を作る。応答 JSON から **root pane id と
workspace id を控える**（Codex はこの root pane に直接起動する。§9。
0.8.0 で JSON はデフォルト出力になり `--json` は不要 — worktree 系では互換の
ため受理されるが、他コマンド群では usage エラーになるので付けない習慣にする）。

```bash
CREATED="$(herdr worktree create \
  --cwd "$ROOT" \
  --branch "$BRANCH" \
  --base HEAD \
  --path "$WT" \
  --label "$TASK_ID" \
  --no-focus)"

PANE_ID="$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id')"
WS_ID="$(printf '%s' "$CREATED" | jq -r '.result.workspace.workspace_id')"
test -n "$PANE_ID" && test -n "$WS_ID"
```

root pane の cwd は worktree checkout そのものなので、`--cwd` の指定なしで
そのまま Codex の作業ディレクトリになる（実測）。

補足（実測）: `--cwd` の base リポジトリが herdr 上で未オープンだと、worktree
create は base リポジトリ用の workspace も一緒に開く。通常運用（対象プロジェクトの
workspace 内から実行する場合）では起きないが、herdr 外のリポジトリを対象にした
場合は cleanup 時に base 側 workspace の close も忘れないこと。

worktree の Git から task files を隠す（Codex の diff/status 汚染と誤コミットを防ぐ）。

```bash
echo ".ai/" >> "$(git -C "$WT" rev-parse --git-path info/exclude)"
```

以後、Codex に読ませる task files は `$WT/.ai/tasks/$TASK_ID/` に作る。

```bash
TASK_DIR="$WT/.ai/tasks/$TASK_ID"
mkdir -p "$TASK_DIR/logs"
```

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
- HERDR_TASK_DONE:<TASK_ID> を出している。

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
Before stopping, create .ai/tasks/<TASK_ID>/CODEX_DONE.md with:
- Summary
- Changed files
- Tests run
- Results
- Known risks
- Any remaining follow-ups

When complete, print exactly:
HERDR_TASK_DONE:<TASK_ID>

If blocked, print exactly:
HERDR_TASK_BLOCKED:<TASK_ID>
```

---

## 9. Codex agent の起動

Claude Code は、§6 で控えた **worktree workspace の root pane** に Codex を起動する。
0.7.5+ の `agent start` は既存 pane への起動が必須で（`--kind` と `--pane` が必須、
`--cwd` / `--no-focus` / pane 自動生成は廃止）、cwd は pane から引き継がれる。

```bash
AGENT="codex-$TASK_ID"
# agent 名は「小文字始まり・小文字/数字/-/_ のみ・1〜32文字」（invalid_agent_name。
# 0.9.0 実測）。§6 の既定 TASK_ID（YYYYMMDD-HHMMSS-codex-task）なら "codex-" 込みで
# ちょうど 32 文字。TASK_ID に長い suffix を付けた場合は短縮する。
[ "${#AGENT}" -le 32 ] || AGENT="codex-$(printf '%s' "$TASK_ID" | cut -c1-15)"

herdr agent start "$AGENT" --kind codex --pane "$PANE_ID" \
  | tee "$TASK_DIR/logs/agent-start.json"
```

応答は `.result.agent` に agent 情報を含む JSON（`pane_id` / `agent_status` /
`interactive_ready` 等）。`agent start` は **Herdr が同一 pane に期待どおりの
agent を検出し対話入力可能と判断してから返る**（公式仕様。既定 30 秒タイムアウト。
実測 ~3 秒）。追加の引数（モデル指定等）は `-- <args...>` で渡せる
（例: `-- -m gpt-5.4`）。

**起動確認（必ず行う）。** start が返っても、Codex が**ダイアログを表示したまま
`idle` で止まっている**ことがあるため、visible read で画面を見てから送信する。
どのダイアログも status は `idle` のままで `blocked` にならず、状態待ちでは
検出できない（0.8.0 実測）。

1. self-update 即終了（§5）→ `agent get` が `agent_not_found` → 再 start。
2. **対話式アップデートダイアログ**（§5）→ そのまま送信すると Enter が
   「Update now」を選んでしまう。`pane send-text "$PANE_ID" "2"` +
   `agent send-keys "$AGENT" enter` で Skip。
3. fresh worktree での **trust 確認ダイアログ**（"Do you trust the contents of
   this directory?"）→ enter で承認（"Yes, continue" が既定選択）。親リポジトリ
   が trust 済みだと出ないこともある（実測）。
   codex-cli 0.156 で trust プロンプトの文言・判定タイミングが変わった（#44732 /
   #44746 / #44755）。2026-09-24 の E2E（permissions: YOLO mode）では trust も
   アップデートダイアログも出ずに「›」が表示された。文言が変わっても「visible read
   で画面を見てから送る」原則は同じ。

```bash
# 生存確認（self-update 終了なら agent_not_found が返る → 再 start）
herdr agent get "$AGENT" | tee "$TASK_DIR/logs/agent-get.json"

# 画面確認（ダイアログの有無と入力プロンプト「›」の表示を見る）
herdr agent read "$AGENT" --source visible --lines 40

# ダイアログ承認が必要な場合のみ（agent 名ターゲットの send-keys は 0.8.0+）
herdr agent send-keys "$AGENT" enter
```

なお旧版（0.7.5）にあった「TUI 初期化中のプロンプトが無音で消える」罠は 0.8.0 で
修正済み — 送信が届かない状況では `agent prompt` が `agent_prompt_stalled`
エラーで教えてくれる（§2.3）。

補足:

- 0.7.4 まで必要だった「pane move --new-tab --workspace による自 workspace への
  回収」は不要になった。worktree create が作る workspace（1レーン = 1 workspace）
  がそのまま Codex の置き場所になり、herdr のサイドバーで workspace ごとの
  working / blocked / done が見える。
- ID は `w1`（workspace）/ `w1:t1`（tab）/ `w1:p1`（pane）形式の opaque handle
  （0.8.0 公式）。閉じた tab/pane の ID は再利用されない。**別 workspace へ move
  した pane は新しい workspace 修飾 ID を受け取る** — 旧 ID は移動したプロセスの
  caller context 経由でしか解決されないので、一般のターゲットに使わない。移動後は
  `pane move` の応答 `.result.move_result.pane.pane_id` か agent 名を正とする。
- タブはその pane を閉じると自動で消える（実測）ので、cleanup は従来どおり
  `herdr pane close` だけでよい。

---

## 10. `/goal` の投入

Claude Code は Codex TUI に、1行の `/goal` だけを送る。0.8.0 の主経路は
`herdr agent prompt --wait` — 送信と完了待ち（idle|done|blocked の settled state
到達）を1コマンドで行う（ターゲットは agent 名でよい。公式も「For normal agent
work, --wait is enough」）。

```bash
GOAL_TEXT="/goal Read .ai/tasks/$TASK_ID/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:$TASK_ID; if blocked print HERDR_TASK_BLOCKED:$TASK_ID."

RESULT="$(herdr agent prompt "$AGENT" "$GOAL_TEXT" --wait --timeout 1800000)" \
  && printf '%s\n' "$RESULT" | tee "$TASK_DIR/logs/prompt-wait-result.json" \
       | jq -r '.result.agent.agent_status' \
  || echo "prompt failed (agent_prompt_stalled? timeout?) — visible read で画面確認" >&2
```

- 返却 JSON の `.result.agent.agent_status` で `done` / `idle` / `blocked` に
  分岐する（実測: 送信 → working 遷移 → 完了で `done`。§2.3）。
- **`agent_prompt_stalled` エラー**（送信後5秒以内に working|blocked なし）が返ったら、
  visible read で画面を確認する — ダイアログ表示中（§9）が典型。未送達とは限らない
  ので、composer に goal が残っていれば Enter だけ、既に working なら再送せず
  `agent wait` で合流する（§2.3）。
- timeout エラーで返っても Codex は動き続けている。`agent wait` で待ち直せる
  （0.9.0: `--timeout` は送信時間込み。送信直後に切れた timeout も未送達の証明ではない）。
- Claude 側で並行作業をしたい場合は `--wait` なしで送り、後から
  `herdr agent wait "$AGENT" --timeout 1800000` で合流してもよい（同じ既定）。

完了後に直近出力を保存する（`agent read` は plain text。jq を通さない）。

```bash
herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  | tee "$TASK_DIR/logs/codex-after-goal.txt"
```

---

## 11. Codex の進捗監視

Claude Code は、Codex の進捗を Herdr の状態と marker の両方で確認する。

基本コマンド:

```bash
# Codex の直近出力を見る（plain text。jq 不要）
herdr agent read "$AGENT" --source recent-unwrapped --lines 200

# Herdr の semantic state を待つ
# （--until なし = idle|done|blocked のいずれか到達で返る。完了は通常 done。
#   返ってきた JSON の .result.agent.agent_status で分岐する）
herdr agent wait "$AGENT" --timeout 1800000

# 特定状態だけを待つ場合は --until（繰り返し指定可）
herdr agent wait "$AGENT" --until blocked --timeout 1000 || true

# 明示 marker を探す（行頭アンカー必須。素の substring だと goal 本文の
# エコー行に偽マッチする。§2.3）
herdr pane wait-output "$PANE_ID" \
  --regex "^• HERDR_TASK_DONE:$TASK_ID" \
  --source recent-unwrapped \
  --lines 500 \
  --timeout 15000
```

運用ルール:

```text
done（または idle）+ marker を検出したら、レビューに進む。
blocked を検出したら、BLOCKED.md と pane output を読み、必要な入力を与える。
unknown が続く場合は、herdr agent explain を使うか、pane output を保存して人間に状態を報告する。
marker がないが CODEX_DONE.md と diff が妥当なら、レビューに進んでよい。ただし REVIEW.md に marker missing と書く。
marker がエコー行（• Goal active Objective: ...）でしか見つからない場合は、marker 未達として扱う。
CODEX_DONE.md がない場合は、実装完了とみなさず、FIX-N.md で作成を求める。
```

---

## 12. Codex 完了後の保存

Codex が done（または idle）/ marker 到達になったら、Claude Code はレビュー前に必ずログと差分を保存する。

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"

herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  > "$TASK_DIR/logs/codex-pane-$STAMP.txt"

git -C "$WT" status --short \
  > "$TASK_DIR/logs/status-$STAMP.txt"

git -C "$WT" diff \
  > "$TASK_DIR/logs/diff-$STAMP.patch"
```

Claude Code は次を読む。

```text
.ai/tasks/<TASK_ID>/PLAN.md
.ai/tasks/<TASK_ID>/CODEX_GOAL.md
.ai/tasks/<TASK_ID>/PROGRESS.md
.ai/tasks/<TASK_ID>/CODEX_DONE.md
git diff
git status --short
テスト結果
```

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

hunk CLI が導入済みの環境（`which hunk` で確認）では、Claude Code はレビュー時に**人間向けの diff ビューを開き、REVIEW-N.md の指摘をインライン注釈**できる。hunk の TUI は人間用であり、Claude 自身の diff 読解は従来どおり `git diff` で行う。なお herdr-plugin-hunk（UI のコマンドパレットから diff を開く herdr プラグイン）はこの手順には不要 — 人間が手動で diff を開くための任意追加であり、その action は CLI から呼べない（実測）。

```bash
# Codex worktree の未コミット差分を人間用に表示。
# agent start は --kind（既知エージェント種別）必須のため、hunk のような
# 任意 TUI は agent start では起動できない。worktree workspace の root pane を
# split して pane run で起動する。
HUNK_PANE="$(herdr pane split "$PANE_ID" --direction right --cwd "$WT" --no-focus \
  | jq -r '.result.pane.pane_id')"
herdr pane run "$HUNK_PANE" "hunk diff"

# Claude は session CLI で構造把握と注釈を行う（TUI は操作しない）
hunk session review --repo "$WT" --json
printf '%s\n' '{"comments":[{"filePath":"src/x.ts","newLine":12,"summary":"REVIEW-01 #1: ..."}]}' \
  | hunk session comment apply --repo "$WT" --stdin
```

指摘の summary には `REVIEW-N.md` の項番を含め、対応関係を保つこと。session CLI の全コマンド（navigate / reload / comment 等）は `hunk skill path` で表示される同梱スキルが正本。**REVIEW-N.md が正本であることは変わらない** — hunk 注釈は人間が diff 上で指摘を追うための補助であり、レビュー記録の代替ではない。レビュー完了後（APPROVED / ABORTED）は hunk pane も `herdr pane close` で片付ける（split で増やした pane を閉じても Codex の root pane には影響しない）。

---

## 14. 修正ループ

Claude Code が `CHANGES_REQUESTED` と判断した場合、同じ Codex pane を使い、`FIX-N.md` を作って再度 `/goal` を送る。

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
- CODEX_DONE.md is updated.
- Print exactly: HERDR_TASK_DONE:<TASK_ID>:fix-<N>
```

### 14.2 修正 goal の投入

方向転換する前に、必要なら既存 goal を clear する。

```bash
herdr agent prompt "$AGENT" "/goal clear"
```

修正 goal を送り、完了まで待つ（§10 と同じ `prompt --wait` 型。stalled / timeout
エラーなら画面確認→送達済みか判断→対処。§2.3）。

```bash
FIX_N="01"
FIX_GOAL="/goal Read .ai/tasks/$TASK_ID/FIX-$FIX_N.md and apply only those fixes. Update CODEX_DONE.md. When complete print HERDR_TASK_DONE:$TASK_ID:fix-$FIX_N."

herdr agent prompt "$AGENT" "$FIX_GOAL" --wait --timeout 1800000 || true
```

marker 確認:

```bash
herdr pane wait-output "$PANE_ID" \
  --regex "^• HERDR_TASK_DONE:$TASK_ID:fix-$FIX_N" \
  --source recent-unwrapped \
  --lines 500 \
  --timeout 15000 || true
```

### 14.3 ループ上限

Claude Code は無限に修正ループを回さない。

```text
デフォルト上限: 3ラウンド
```

3ラウンドで収束しない場合:

```text
1. REVIEW-FINAL.md に ABORTED または BLOCKED を書く
2. 未解決点を箇条書きにする
3. 現在の diff / pane log / status を保存する
4. 同じ pane の文脈が汚れている可能性があれば pane を閉じる
5. 必要なら新しい Codex pane を起動し、PLAN.md + 最新 REVIEW/FIX + 現在 diff を読ませて再開する
```

---

## 15. pane を閉じるタイミング

Codex が `HERDR_TASK_DONE` を出した瞬間には pane を閉じない。

pane close の条件:

```text
Claude Code review: APPROVED または ABORTED
Codex status: done または idle
未処理の blocked 質問: なし
CODEX_DONE.md: あり
REVIEW-FINAL.md: あり
final diff / status / pane output: 保存済み
次の FIX-N.md を投げる予定: なし
```

閉じてはいけないタイミング:

```text
Codex が HERDR_TASK_DONE を出した直後
Claude Code のレビュー前
Codex が working
Codex が blocked
FIX-N.md を投げる予定がある
```

pane cleanup:

```bash
herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  > "$TASK_DIR/logs/codex-final-pane.txt"

git -C "$WT" status --short \
  > "$TASK_DIR/logs/final-status.txt"

git -C "$WT" diff \
  > "$TASK_DIR/logs/final.diff"

herdr pane close "$PANE_ID"
```

作業を中止する場合は、いきなり閉じずに可能なら Codex に pause を送る。

```bash
herdr agent prompt "$AGENT" "/goal pause"
```

その後にログ保存、`REVIEW-FINAL.md` 作成、pane close を行う。

---

## 16. 承認後の取り込み（commit → merge / PR）

`REVIEW-FINAL.md` に APPROVED を書いて pane を閉じたら、Claude Code が成果を取り込み可能な状態にする。レビューは未コミット diff に対して行うため、承認後のコミットが必要になる。

```text
1. Claude Code が Codex worktree でコミットする
   - コミットは Claude Code の担当（Codex にはさせない）。
   - PLAN.md の Objective を要約したメッセージに TASK_ID を含める。
   - .ai/ は info/exclude 済みだが、コミット前に git status で混入がないことを確認する。
2. superpowers:finishing-a-development-branch スキルを起動する
   - merge / PR / 保留 / 破棄 の選択肢を人間に提示し、決定に従う。
   - スキルが使えない環境では、同等の選択肢を人間に確認してから実行する。
3. 決定を実行したら（merge 完了 / PR 作成 / reject）、§17 の worktree cleanup に進む
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

---

## 17. worktree cleanup のタイミング

pane close と worktree remove は別物である。

```text
pane close:
  Codex のプロセス・画面を閉じる。
  Claude Code の最終レビュー後に行う。
  重要: workspace の最後の pane（tab）を閉じると workspace も自動で閉じる
  （0.8.0 で CLI/API からの close も TUI と同挙動になることが公式化。
  #1899）。checkout は残る。

workspace close:
  Herdr 側の workspace state を閉じる。
  Git checkout を削除するものではない。
  0.9.0: primary workspace（repo root で開いたもの）を、その linked worktree
  workspace が開いたまま閉じようとすると workspace_group_close_required で
  拒否される。本フローで閉じるのは linked 側だけなので通常は当たらない。
  --group は primary と linked 全部をまとめて閉じるフラグであり、
  エラー回避のために付けてはいけない（ユーザーが明示した場合のみ）。

worktree remove:
  Git worktree checkout を削除する。
  merge / PR / reject が終わった後だけ行う。
  0.9.0: --trust-repository（1リクエスト限りの Git trust）が全 worktree
  サブコマンドに追加された。失敗時の再試行フラグではなく、ユーザーが
  リポジトリを確認済みのときだけ使う。
```

作業ブランチを採用する前に worktree を消さない。

merge / PR / reject が終わった後の checkout 削除は、**workspace が既に閉じているか
どうか**で手段が分かれる（本フローでは Codex が worktree workspace の唯一の
pane に居るため、§15 の pane close で workspace は自動的に閉じている・実測。
その状態で `herdr worktree remove --workspace` を叩くと `workspace_not_found`）。

```bash
# 通常経路: §15 の pane close 済み（workspace は消滅済み）→ git 側で消す
git -C "$ROOT" worktree remove "$WT"
git -C "$ROOT" branch -d "$BRANCH"   # merge 済みの場合。reject なら -D

# workspace がまだ開いている場合（pane を閉じずに中止した等）
# → herdr worktree remove が checkout 削除と workspace close を両方行う
herdr worktree remove --workspace "$WS_ID"
# pane 内でプロセスが生きていて拒否される場合のみ --force
herdr worktree remove --workspace "$WS_ID" --force
```

**workspace が開いたまま git 側だけで checkout を消してはいけない。**
herdr の spaces サイドバーに参照先のないゾンビ workspace が残り続ける
（実測: 20個以上溜まった事例あり）。その場合は `herdr workspace close "$WS_ID"`
で片付ける。

ゾンビ workspace の検出と一括掃除:

```bash
# linked worktree の workspace だけを対象にする。0.8.0 では repo root で開いた
# 通常の workspace にも worktree オブジェクトが付く（is_linked_worktree: false・
# 実測）ため、`.worktree != null` では通常 workspace まで対象に含めてしまう。
# is_linked_worktree == true で絞ること（true 判定なので jq の // は使わない —
# false // x は x になる）。
herdr workspace list \
  | jq -r '.result.workspaces[] | select(.worktree.is_linked_worktree == true) | [.workspace_id, .worktree.checkout_path] | @tsv' \
  | while IFS=$'\t' read -r ws path; do
      [ -n "$path" ] && [ ! -d "$path" ] && herdr workspace close "$ws"
    done
```

---

## 18. blocked / failed / unknown の扱い

### 18.1 Codex が blocked

Claude Code は pane を閉じない。

```text
1. herdr agent read で出力を読む
2. BLOCKED.md があれば読む
3. 必要な情報を Claude Code が判断できるなら、CLARIFICATION.md または FIX-N.md を作る
4. Codex に再 /goal または必要な回答を送る
5. 人間の判断が必要なら REVIEW-FINAL.md に BLOCKED を書いて報告する
```

codex-cli 0.155+ は、goal の自動継続ターンが3回続けて空（進捗なし）だと goal
自体を blocked にする（#44320）。この場合 BLOCKED.md が無いこともあるので、
agent read で「goal blocked」系の表示を確認し、FIX-N.md で具体的な次の一手を
与えて再 /goal する。

### 18.2 Codex が done / idle だが CODEX_DONE.md がない

実装完了とみなさない。

```text
Status: CHANGES_REQUESTED
Required fix: CODEX_DONE.md を作り、変更点・テスト・リスクを記録すること。
```

### 18.3 marker がない

`CODEX_DONE.md` と diff が妥当ならレビューに進んでよい。ただし、`REVIEW-N.md` に `Completion marker was missing` と記録する。

### 18.4 Herdr status が unknown

```bash
herdr agent explain "$AGENT" --json || true
herdr agent read "$AGENT" --source recent-unwrapped --lines 300
herdr pane get "$PANE_ID"
```

画面出力・diff・task files で判断し、不明なら `BLOCKED` として人間に報告する。

### 18.5 Codex が scope を広げた

Claude Code は `CHANGES_REQUESTED` とし、`FIX-N.md` で unrelated change の revert を要求する。

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

ユーザーが「Codex に実装を委譲して」「Herdr 経由で Codex にやらせて」などと言ったら、Claude Code は次を実行する。

```text
[ ] task id を作る
[ ] Git worktree を作る（応答 JSON から root pane id と workspace id を控える。--json は付けない）
[ ] worktree の .git/info/exclude に .ai/ を足す
[ ] Codex worktree 内に .ai/tasks/<TASK_ID>/ を作る
[ ] superpowers:brainstorming で要件・設計を固める
[ ] superpowers:writing-plans に従って PLAN.md を書く
[ ] CODEX_GOAL.md を書く
[ ] worktree の root pane に Codex を起動する（agent start --kind codex --pane）
[ ] 起動確認: agent get で生存確認（self-update 終了なら再 start）
[ ] 起動確認: visible read でダイアログの有無と入力プロンプト「›」を確認する
    （アップデートダイアログは "2" + enter で Skip、trust ダイアログは enter で承認。
      どちらも idle のままで blocked にならない）
[ ] 1行の /goal を agent prompt --wait --timeout 1800000 で送る
    （agent_prompt_stalled / timeout なら visible read で画面確認 → 送達済みか
      判断 → ダイアログ対処・Enter のみ・agent wait 合流のいずれか。§2.3）
[ ] 返却 JSON の agent_status（done / blocked）と marker を確認する（完了は通常 done）
[ ] 完了後に pane output / git diff / status を保存する
[ ] CODEX_DONE.md を読む
[ ] Claude Code がレビューして REVIEW-01.md を書く
[ ] 問題があれば FIX-01.md を書いて同じ pane に再 /goal
[ ] 最大3ラウンドまで繰り返す
[ ] APPROVED なら REVIEW-FINAL.md を書く
[ ] final logs を保存する
[ ] Codex pane を閉じる
[ ] Claude Code が worktree でコミットする（.ai/ 混入なしを git status で確認）
[ ] finishing-a-development-branch で merge / PR / reject を人間に確認する
[ ] worktree は merge / PR / reject まで残す
[ ] merge / reject 後の checkout 削除: pane close 済みなら workspace は消滅済みなので
    git worktree remove + branch -d で消す。workspace が開いたままなら
    herdr worktree remove --workspace で checkout と workspace を両方消す
    （workspace が開いたまま git 側だけ消すとゾンビ workspace が残る）
```

---

## 21. 参考 wrapper

必要なら、Claude Code は以下の薄い wrapper を `scripts/ai-codex-herdr.sh` として作って使ってよい。

```bash
#!/usr/bin/env bash
set -euo pipefail

resolve_pane_id() {
  local agent="$1"
  herdr agent get "$agent" | jq -r '.result.agent.pane_id? // empty' | head -n 1
}

read_agent_text() {
  # agent read は plain text（0.7.5+。jq を通さない）
  local agent="$1"
  local lines="$2"
  herdr agent read "$agent" --source recent-unwrapped --lines "$lines"
}

usage() {
  cat >&2 <<'USAGE'
usage:
  ai-codex-herdr start <task_id> <pane_id> <task_dir>
  ai-codex-herdr send-goal <task_id> <task_dir>
  ai-codex-herdr wait <task_id> <task_dir> [marker_regex]
  ai-codex-herdr read <task_id>
  ai-codex-herdr close <task_id> <task_dir>
USAGE
}

cmd="${1:-}"
shift || true

case "$cmd" in
  start)
    task_id="${1:?task_id required}"
    pane_id="${2:?pane_id required (worktree create の .result.root_pane.pane_id)}"
    task_dir="${3:?task_dir required}"
    agent="codex-$task_id"
    mkdir -p "$task_dir/logs"

    # agent start は既存 pane への起動（--kind --pane 必須）。ready 検出まで
    # 待ってから返る（既定 30s）。cwd は pane から引き継がれる。
    herdr agent start "$agent" --kind codex --pane "$pane_id" \
      | tee "$task_dir/logs/agent-start.json"

    # 起動確認: self-update 即終了なら agent_not_found。ダイアログ
    # （アップデート/trust）は idle のまま止まるので画面を目視確認する。
    herdr agent get "$agent" | tee "$task_dir/logs/agent-get.json"
    herdr agent read "$agent" --source visible --lines 40
    ;;

  send-goal)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    agent="codex-$task_id"

    goal_text="/goal Read .ai/tasks/$task_id/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:$task_id; if blocked print HERDR_TASK_BLOCKED:$task_id."

    # 0.8.0 主経路: 送信 + settled state（idle|done|blocked）待ちを1コマンドで。
    # 送信後5秒以内に working|blocked が観測できなければ agent_prompt_stalled が
    # 返る（→ visible read で画面確認。未送達とは限らないので §2.3 の判断に従う）。
    herdr agent prompt "$agent" "$goal_text" --wait --timeout 1800000 \
      | tee "$task_dir/logs/prompt-wait-result.json" \
      || echo "warning: prompt failed (stalled/timeout) — check visible screen" >&2

    read_agent_text "$agent" 500 \
      | tee "$task_dir/logs/codex-after-goal.txt"
    ;;

  wait)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    marker="${3:-^• HERDR_TASK_DONE:$task_id}"
    agent="codex-$task_id"
    pane_id="$(resolve_pane_id "$agent")"
    test -n "$pane_id"

    # send-goal の --wait が timeout した場合などの待ち直し用。
    # 完了 = 通常 done（CLI 駆動では未読完了が done になる。§2.3）。
    herdr agent wait "$agent" --timeout 1800000 || true

    # Explicit marker wait（行頭アンカー付き regex。substring/--match だと
    # goal エコーに偽マッチ）
    herdr pane wait-output "$pane_id" \
      --regex "$marker" \
      --source recent-unwrapped \
      --lines 500 \
      --timeout 15000 || true

    stamp="$(date +%Y%m%d-%H%M%S)"
    read_agent_text "$agent" 500 \
      > "$task_dir/logs/codex-pane-$stamp.txt"
    ;;

  read)
    task_id="${1:?task_id required}"
    agent="codex-$task_id"
    read_agent_text "$agent" 200
    ;;

  close)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    agent="codex-$task_id"
    pane_id="$(resolve_pane_id "$agent")"
    test -n "$pane_id"

    mkdir -p "$task_dir/logs"
    read_agent_text "$agent" 500 \
      > "$task_dir/logs/codex-final-pane.txt"

    herdr pane close "$pane_id"
    ;;

  *)
    usage
    exit 2
    ;;
esac
```

---

## 22. Claude Code への最終指示

Claude Code は、このワークフローでは次を厳守する。

```text
- Codex にいきなり実装させず、先に PLAN.md を作る。
- PLAN.md の前に superpowers:brainstorming、執筆に superpowers:writing-plans を使う。
- Codex に長文を直接 paste せず、1行の /goal で CODEX_GOAL.md を読ませる。
- Herdr は agent CLI を主軸にし、/goal は agent prompt --wait で送って待つ。
  pane CLI は pane 用意 / wait-output / send-text / close に使う。
- socket API は初期実装では使わない。
- Codex は worktree create の root pane に起動する（agent start --kind codex --pane）。
- 起動直後に送信しない。生存確認と visible read（ダイアログ有無）を先に行う。
  アップデート/trust ダイアログは idle のまま止まり blocked にならない。
- 完了待ちは agent prompt --wait（= agent wait の --until なしと同じ既定）。
  完了状態は通常 done（CLI 駆動では未読完了が done。0.8.0 公式セマンティクス）。
- agent_prompt_stalled / timeout が返ったら画面確認 → 送達済みか判断 → 対処
  （盲目的な再送はしない。§2.3）。偽 done は 0.8.0 以降ない。
- agent read / pane read は plain text。jq を通さない（agent get 等の JSON とは別）。
  JSON がデフォルトなので --json は付けない。
- marker 検出は行頭アンカー付き regex。substring / --match だと goal エコー行に
  偽マッチする。
- Codex の done+marker はレビュー開始トリガーであり、pane close トリガーではない。
- pane は Claude Code が APPROVED または ABORTED を書いた後に閉じる。
- 修正が必要なら同じ Codex pane に FIX-N.md を再 /goal する。
- 3ラウンド以上は自動で回し続けない。
- 承認後のコミットは Claude Code が行い、merge / PR / reject は
  finishing-a-development-branch で人間に確認する。勝手に merge しない。
- source of truth は task files と git diff と test 結果であり、画面出力だけではない。
```
