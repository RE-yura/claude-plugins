# Codex レーンを委譲元 workspace のタブに置く Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** delegating-to-codex の Codex レーンを、herdr の worktree グループではなく委譲元 workspace のタブ（herdr 外からなら単独 workspace）に置くよう、手順書とメタデータを改訂し、herdr 0.9.3 で実機検証する。

**Architecture:** worktree は `git worktree add` で作り、`HERDR_PANE_ID` がある場合だけ `herdr pane current` で呼び元 workspace を特定して `herdr tab create --workspace` でタブを作る。Codex 起動以降（§9〜§14）は不変で、片付けは「pane close → git worktree remove」に一本化する。成果物は Markdown 手順書と JSON メタデータで、検証は scratchpad の使い捨てリポジトリでの実機 E2E と既存テスト。

**Tech Stack:** bash, git worktree, herdr 0.9.3 CLI, jq, codex-cli（`/goal`）

**Spec:** `docs/superpowers/specs/2026-10-13-codex-lane-caller-tab-design.md`

## Global Constraints

- 対象ディレクトリ: `plugins/dev-workflow/skills/delegating-to-codex/`（`workflow.md` / `SKILL.md` / `versions.json`）と `plugins/dev-workflow/.claude-plugin/plugin.json`、`README.md`、`plugins/dev-workflow/README.md`
- worktree のパス `WT="$(dirname "$ROOT")/worktrees/$TASK_ID"`、ブランチ `BRANCH="ai/$TASK_ID"`、TASK_ID 形式 `YYYYMMDD-HHMMSS-codex-task` は現行のまま
- `herdr worktree create` は本流で使わない（記述は冒頭注記と §17.1 旧方式小節にだけ残す）
- 呼び元判定は `HERDR_PANE_ID` が空でないときだけ `herdr pane current` を使う
- タブ作成: `herdr tab create --workspace "$CALLER_WS" --cwd "$WT" --label "$TASK_ID" --no-focus`
- フォールバック: `herdr workspace create --cwd "$WT" --label "$TASK_ID" --no-focus`
- §9〜§14（agent start / 起動確認 / prompt --wait / marker / REVIEW / FIX）の手順は変えない
- 片付け順序: `herdr pane close` → merge / PR / reject → `git worktree remove` → `git branch -d`（reject は `-D`）
- `git worktree remove --force` は `logs/final.diff` 保存済み かつ 人間が破棄を選んだときだけ
- SKILL.md frontmatter `version` 1.3.0 → 1.4.0、plugin.json `version` 1.4.0 → 1.5.0
- versions.json: `herdr.verified` → 0.9.3、`verified_at` → 2026-10-13
- コミットは feature ブランチ `feat/codex-lane-caller-tab` に。push しない

## Review Focus

1. **herdr がエラー JSON を返す（protocol_mismatch 等。exit 0 で stdout に出る）** — `jq -r '.result.root_pane.pane_id'` が文字列 `null` を返して `test -n` を通ってしまわないこと。`// empty` を付け、Task 1 Step 2 で error JSON を流して空になることを確認する。
2. **`set -euo pipefail` のスクリプト（§21 wrapper と同じ流儀）で §6 を実行し、`pane current` が失敗する** — スクリプトが落ちずに単独 workspace へフォールバックすること。`|| true` を付け、Task 1 Step 2 で stale な `HERDR_PANE_ID` を使って確認する。
3. **`HERDR_PANE_ID` はあるが stale（herdr 再起動後など）** — フォールバックすること。Task 1 Step 2 で確認する。
4. **hunk 等で Codex タブに pane を split したまま Codex pane を閉じる** — タブが残る。§15 に明記し、Task 2 Step 4 で split した shell pane を使って実挙動を確認する。
5. **`.ai/`（info/exclude で無視されたファイル）が残ったままの `git worktree remove`** — `--force` なしで成功すること（成功しないと通常経路で毎回 `--force` が要る）。Task 2 Step 5 で確認する。

---

### Task 1: レーン作成（§6）の書き換えと作成経路の実機検証

**Files:**
- Modify: `plugins/dev-workflow/skills/delegating-to-codex/workflow.md`（§1 の役割表 15-21 行、§2.1 の 40 行・72 行、§4 の 222・225 行、§6 全体 306-355 行）
- Test: scratchpad の使い捨てリポジトリ（コミットしない）

**Interfaces:**
- Produces: §6 が定義するシェル変数 `TASK_ID` / `ROOT` / `WT` / `BRANCH` / `CALLER_WS` / `LANE_KIND`（`tab` | `workspace`）/ `CREATED` / `PANE_ID` / `TASK_DIR`。§9 以降と Task 2 はこの名前を使う。`WS_ID` は廃止する。

- [ ] **Step 1: 現状の確認（失敗するテスト相当）**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
grep -n "herdr worktree create" plugins/dev-workflow/skills/delegating-to-codex/workflow.md
```
Expected: §6（323 行付近）と冒頭 7 行にヒットする（= 本流がまだ worktree create を使っている）。

- [ ] **Step 2: 作成経路の実機検証（herdr 0.9.3）**

scratchpad に使い捨てリポジトリを作り、新しい §6 の手順をそのまま実行する。`S` は session の scratchpad 配下の `e2e` ディレクトリ。

```bash
S=/private/tmp/claude-501/-Users-yura-ghq-github-com-RE-yura-claude-marketplace/1483d166-5f3a-471c-816f-6481745ec62f/scratchpad/e2e
rm -rf "$S" && mkdir -p "$S"
git init -q -b main "$S/demo" && git -C "$S/demo" commit -q --allow-empty -m init

linked_before="$(herdr workspace list | jq '[.result.workspaces[] | select(.worktree.is_linked_worktree == true)] | length')"
active_tab_before="$(herdr workspace get "$HERDR_WORKSPACE_ID" | jq -r '.result.workspace.active_tab_id')"

TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$S/demo"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"
git -C "$ROOT" worktree add -q -b "$BRANCH" "$WT" HEAD
echo ".ai/" >> "$(git -C "$WT" rev-parse --git-path info/exclude)"

CALLER_WS=""
if [ -n "${HERDR_PANE_ID:-}" ]; then
  CALLER_WS="$(herdr pane current 2>/dev/null | jq -r '.result.pane.workspace_id // empty' || true)"
fi
if [ -n "$CALLER_WS" ]; then
  CREATED="$(herdr tab create --workspace "$CALLER_WS" --cwd "$WT" --label "$TASK_ID" --no-focus)"
  LANE_KIND=tab
else
  CREATED="$(herdr workspace create --cwd "$WT" --label "$TASK_ID" --no-focus)"
  LANE_KIND=workspace
fi
PANE_ID="$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id // empty')"
test -n "$PANE_ID" && echo "LANE_KIND=$LANE_KIND PANE_ID=$PANE_ID CALLER_WS=$CALLER_WS"

# 検証
herdr pane get "$PANE_ID" | jq -r '.result.pane.cwd'                      # → $WT
herdr tab list --workspace "$CALLER_WS" | jq -r '.result.tabs[].label'      # → $TASK_ID を含む
herdr workspace list | jq '[.result.workspaces[] | select(.worktree.is_linked_worktree == true)] | length'   # → $linked_before と同じ
herdr workspace get "$HERDR_WORKSPACE_ID" | jq -r '.result.workspace.active_tab_id'                         # → $active_tab_before と同じ（フォーカス不変）
```

Expected: `LANE_KIND=tab`、pane の cwd が `$WT`、タブ一覧に `$TASK_ID`、linked workspace 数が不変、active tab が不変。応答 JSON のキー名（`.result.tabs[].label` 等）が違ったら実際の JSON を見て検証コマンドと §6 の記述を合わせる。

続けて Review Focus 1〜3 を確認する:

```bash
# RF1: エラー JSON から PANE_ID が空になる
printf '%s' '{"id":"x","error":{"code":"protocol_mismatch","message":"m"}}' | jq -r '.result.root_pane.pane_id // empty'   # → 空行
# RF2+RF3: stale な HERDR_PANE_ID + errexit/pipefail でも落ちずに空になる
HERDR_PANE_ID=wzz:pzz bash -euo pipefail -c '
  CALLER_WS=""
  if [ -n "${HERDR_PANE_ID:-}" ]; then
    CALLER_WS="$(herdr pane current 2>/dev/null | jq -r ".result.pane.workspace_id // empty" || true)"
  fi
  echo "CALLER_WS=[$CALLER_WS] continued"'
```
Expected: 1 行目は空行。2 つ目は `CALLER_WS=[] continued`（stale ID がエラーにならずに別 pane を返した場合は、その事実を記録し §6 の注記を実態に合わせる）。

herdr 外経路（フォールバック）を確認し、作ったものを片付ける:

```bash
FB="$(env -u HERDR_PANE_ID -u HERDR_TAB_ID -u HERDR_WORKSPACE_ID herdr workspace create --cwd "$WT" --label "$TASK_ID-fb" --no-focus)"
FB_WS="$(printf '%s' "$FB" | jq -r '.result.workspace.workspace_id // empty')"
FB_PANE="$(printf '%s' "$FB" | jq -r '.result.root_pane.pane_id // empty')"
herdr workspace get "$FB_WS" | jq '.result.workspace.worktree'   # → null（グループに属さない）
herdr pane close "$FB_PANE"
herdr workspace get "$FB_WS" 2>&1 | head -c 200                 # → workspace_not_found（pane close で workspace も閉じる）

herdr pane close "$PANE_ID"
herdr tab list --workspace "$CALLER_WS" | jq -r '.result.tabs[].label'   # → $TASK_ID が消えている
git -C "$ROOT" worktree remove "$WT" && git -C "$ROOT" branch -D "$BRANCH"
```
Expected: フォールバック workspace は `worktree` が null、pane close 後に `workspace_not_found`。タブは pane close で消え、worktree とブランチも消える。

- [ ] **Step 3: workflow.md §6 を置き換える**

306-355 行（`## 6. TASK_ID と worktree の作成` から `mkdir -p "$TASK_DIR/logs"` のコードブロック終わりまで）を次の内容に置き換える。

````markdown
## 6. TASK_ID・worktree・Codex 用タブの作成

Claude Code は、ユーザーから実装委譲を求められたら、まず task id を作る。

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$(git rev-parse --show-toplevel)"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"
```

Codex 用の Git worktree を `git worktree add` で作り、task files を Git から隠す
（Codex の diff/status 汚染と誤コミットを防ぐ）。

```bash
git -C "$ROOT" worktree add -b "$BRANCH" "$WT" HEAD
echo ".ai/" >> "$(git -C "$WT" rev-parse --git-path info/exclude)"
```

**`herdr worktree create` は使わない。** herdr の worktree グループはリポジトリ単位で、
親 workspace は「同じリポジトリの workspace のうちサイドバー順で最初のもの」が
選ばれる（herdr 0.9.3 のソースで確認）。同じリポジトリの workspace が複数あると、
Codex レーンが委譲元とは別の workspace の下に表示される。`--workspace` で呼び元を
指定しても、呼び元が子のようにインデントされるだけで解決しない（2026-10-13 調査。
herdr #4736 / PR #4772 も parent ID は追加しない方針）。

次に、委譲元（Claude Code が居る）workspace に Codex 用のタブを作り、応答 JSON から
root pane id を控える（Codex はこの root pane に直接起動する。§9）。

```bash
# 呼び元 workspace の特定。herdr の外では pane current がエラーにならず
# フォーカス中の pane を返す（0.9.3 実測）ので、HERDR_PANE_ID の有無で判定する。
CALLER_WS=""
if [ -n "${HERDR_PANE_ID:-}" ]; then
  CALLER_WS="$(herdr pane current 2>/dev/null | jq -r '.result.pane.workspace_id // empty' || true)"
fi

if [ -n "$CALLER_WS" ]; then
  CREATED="$(herdr tab create --workspace "$CALLER_WS" --cwd "$WT" --label "$TASK_ID" --no-focus)"
  LANE_KIND=tab
else
  # herdr の外からの委譲。グループに属さない単独 workspace に置く
  CREATED="$(herdr workspace create --cwd "$WT" --label "$TASK_ID" --no-focus)"
  LANE_KIND=workspace
fi

# エラー JSON（protocol_mismatch 等は exit 0 で返る）で "null" を拾わないよう // empty を付ける
PANE_ID="$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id // empty')"
test -n "$PANE_ID"
```

- root pane の cwd は worktree checkout そのものなので、そのまま Codex の作業ディレクトリになる。
- `HERDR_PANE_ID` があれば `pane current` は caller context で解決される（pane move 後の
  旧 ID もこの経路なら解決できる）。`pane current` が失敗した場合（stale ID 等）は
  `CALLER_WS` が空になり、単独 workspace にフォールバックする。
- 作業中のタブを split しないのは、ユーザーの画面を狭め、並列委譲で破綻するため。
  タブ名（TASK_ID）で委譲を見分けられる。
- `--no-focus` なので、ユーザーのフォーカス（active tab）は動かない（0.9.3 実測）。
- `LANE_KIND` は §15 の片付けの説明で使う。

以後、Codex に読ませる task files は `$WT/.ai/tasks/$TASK_ID/` に作る。

```bash
TASK_DIR="$WT/.ai/tasks/$TASK_ID"
mkdir -p "$TASK_DIR/logs"
```
````

Step 2 の結果が上の記述（フォーカス不変、stale ID の扱い、フォールバックの挙動）と違った場合は、実測に合わせて該当の箇条書きを直す。

- [ ] **Step 4: §1・§2.1・§4 の関連箇所を直す**

§1 の役割表（15-21 行のコードブロック）の 2 行を置き換える:
```text
Herdr       = 委譲元 workspace に Codex 用タブを用意し、agent の起動・入力送信・進捗可視化・状態検知を行う
Git worktree = Codex が安全に編集する隔離された作業領域（git worktree add で作る。herdr の worktree 機能は使わない）
```

§2.1 の 40 行:
- 旧: `  pane の用意（worktree create の root pane / pane split）、shell コマンド実行（pane run）、`
- 新: `  pane の用意（tab create / workspace create の root pane、pane split）、shell コマンド実行（pane run）、`

§2.1 の 72 行:
- 旧: `` - `agent get` / `agent start` / `agent prompt` / `worktree create` / `workspace create` / ``
- 新: `` - `agent get` / `agent start` / `agent prompt` / `tab create` / `workspace create` / ``

§4 の 222 行:
- 旧: `2. Claude Code が Git worktree を作る（応答 JSON の root pane id を控え、.ai/ を exclude する）`
- 新: `2. Claude Code が git worktree add で Git worktree を作って .ai/ を exclude し、委譲元 workspace に Codex 用タブを作る（応答 JSON の root pane id を控える。§6）`

§4 の 225-226 行:
- 旧: `4. Claude Code が worktree workspace の root pane に Codex agent を起動する` / `   （agent start --kind codex --pane。pane move による回収は不要になった）`
- 新: `4. Claude Code が Codex 用タブの root pane に Codex agent を起動する` / `   （agent start --kind codex --pane）`

- [ ] **Step 5: 確認して commit**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
sed -n '/^## 6\./,/^## 7\./p' plugins/dev-workflow/skills/delegating-to-codex/workflow.md | grep -c "herdr worktree create"   # → 1（「使わない」の説明行のみ）
grep -n "WS_ID" plugins/dev-workflow/skills/delegating-to-codex/workflow.md   # → §17 にだけ残る（Task 2 で消す）
```
```bash
git add plugins/dev-workflow/skills/delegating-to-codex/workflow.md
git commit -m "feat(delegating-to-codex): Codex レーンを委譲元 workspace のタブに作る (§6)" -m "Co-Authored-By: ..."
```
（コミットメッセージ末尾には session の attribution 2 行を付ける）

---

### Task 2: Codex 起動〜片付け（§9・§13.1・§15・§17）の書き換えと一巡の実機検証

**Files:**
- Modify: `plugins/dev-workflow/skills/delegating-to-codex/workflow.md`（§9 の 483 行・536-548 行、§13.1 の 716-719 行・730 行、§15 の 864 行付近、§17 全体 906-974 行）
- Test: scratchpad の使い捨てリポジトリ（コミットしない）

**Interfaces:**
- Consumes: Task 1 の §6 変数（`TASK_ID` / `ROOT` / `WT` / `BRANCH` / `LANE_KIND` / `PANE_ID` / `TASK_DIR`）
- Produces: §17 の片付け手順（`git -C "$ROOT" worktree remove "$WT"` → `git -C "$ROOT" branch -d|-D "$BRANCH"`）と §17.1 旧方式小節。Task 3 の SKILL.md / チェックリストはこの内容を要約する。

- [ ] **Step 1: 現状の確認（失敗するテスト相当）**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
grep -n -E "worktree workspace|herdr worktree remove|WS_ID" plugins/dev-workflow/skills/delegating-to-codex/workflow.md
```
Expected: §9・§13.1・§17 にヒットする。

- [ ] **Step 2: 一巡の実機検証 — レーン作成と Codex 起動**

Task 1 Step 2 と同じ手順でリポジトリとレーンを作る（`S` を再作成し、新しい TASK_ID で §6 を実行して `LANE_KIND=tab` と `PANE_ID` を得る）。続けて task files と Codex を用意する:

```bash
TASK_DIR="$WT/.ai/tasks/$TASK_ID"
mkdir -p "$TASK_DIR/logs"
cat > "$TASK_DIR/CODEX_GOAL.md" <<EOF
# Codex Goal: $TASK_ID
## Objective
Create a file named HELLO.txt at the repository root containing exactly one line: hello
## Scope control
Do not create or modify any other file outside .ai/.
## Done condition
Write .ai/tasks/$TASK_ID/CODEX_DONE.md with one line "done", then print exactly: HERDR_TASK_DONE:$TASK_ID
EOF

AGENT="codex-$TASK_ID"
[ "${#AGENT}" -le 32 ] || AGENT="codex-$(printf '%s' "$TASK_ID" | cut -c1-15)"
herdr agent start "$AGENT" --kind codex --pane "$PANE_ID" | tee "$TASK_DIR/logs/agent-start.json" | jq -c '.result.agent | {pane_id, agent_status}'
herdr agent get "$AGENT" | jq -c '.result.agent | {pane_id, agent_status}'
herdr agent read "$AGENT" --source visible --lines 40
```
Expected: agent が `PANE_ID` 上で起動。visible read でダイアログ（trust / アップデート）が出ていれば §9 の手順で処理してから次へ（trust は `herdr agent send-keys "$AGENT" enter`、アップデートは `pane send-text "$PANE_ID" "2"` + `agent send-keys "$AGENT" enter`）。入力プロンプト「›」が見えること。

- [ ] **Step 3: 一巡の実機検証 — /goal と完了検知**

```bash
GOAL_TEXT="/goal Read .ai/tasks/$TASK_ID/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:$TASK_ID; if blocked print HERDR_TASK_BLOCKED:$TASK_ID."
herdr agent prompt "$AGENT" "$GOAL_TEXT" --wait --timeout 600000 | jq -r '.result.agent.agent_status'
herdr pane wait-output "$PANE_ID" --regex "^• HERDR_TASK_DONE:$TASK_ID" --source recent-unwrapped --lines 500 --timeout 15000 | jq -r '.result.matched_line // .'
cat "$WT/HELLO.txt"; cat "$TASK_DIR/CODEX_DONE.md"
git -C "$WT" status --short
```
Expected: `done`（または `idle`）、marker の matched_line が `• HERDR_TASK_DONE:<id>`（エコー行ではない）、`HELLO.txt` が `hello`、status に `?? HELLO.txt` だけが出て `.ai/` は出ない。`agent_prompt_stalled` / `timeout` が返ったら §2.3 に従い visible read で判断する。

- [ ] **Step 4: 一巡の実機検証 — pane close とタブの消え方（Review Focus 4）**

```bash
# hunk の代わりに shell pane を split して、Codex pane だけ閉じてもタブが残ることを確認
EXTRA="$(herdr pane split "$PANE_ID" --direction right --cwd "$WT" --no-focus | jq -r '.result.pane.pane_id // empty')"
TAB_ID="$(herdr pane get "$PANE_ID" | jq -r '.result.pane.tab_id')"
herdr agent read "$AGENT" --source recent-unwrapped --lines 500 > "$TASK_DIR/logs/codex-final-pane.txt"
herdr pane close "$PANE_ID"
herdr tab get "$TAB_ID" | jq -r '.result.tab.label'      # → $TASK_ID（split した pane が残っているのでタブは残る）
herdr pane close "$EXTRA"
herdr tab get "$TAB_ID" 2>&1 | head -c 200                # → tab_not_found 等（タブが消える）
herdr workspace get "$CALLER_WS" | jq -r '.result.workspace.workspace_id'   # → $CALLER_WS（委譲元 workspace は残る）
herdr workspace list | jq '[.result.workspaces[] | select(.worktree.is_linked_worktree == true)] | length'   # → Task 1 の linked_before と同じ
```
Expected: コメントどおり。

- [ ] **Step 5: 一巡の実機検証 — commit と git での片付け（Review Focus 5）**

```bash
git -C "$WT" add -A && git -C "$WT" commit -q -m "test: hello ($TASK_ID)"
git -C "$WT" status --short --ignored | head          # → !! .ai/ （無視ファイルとして残っている）
git -C "$ROOT" worktree remove "$WT" && echo "removed without --force"
git -C "$ROOT" branch -D "$BRANCH"                    # reject 相当（未 merge なので -D）
git -C "$ROOT" worktree list; git -C "$ROOT" branch --list 'ai/*'
```
Expected: `.ai/` が無視ファイルとして残っていても `removed without --force`。worktree 一覧は `$ROOT` だけ、`ai/*` ブランチなし。`--force` が必要だった場合は §17 の記述をその実測に合わせて直す。

- [ ] **Step 6: §9 を直す**

483 行:
- 旧: `Claude Code は、§6 で控えた **worktree workspace の root pane** に Codex を起動する。`
- 新: `Claude Code は、§6 で控えた **Codex 用タブ（herdr 外からなら単独 workspace）の root pane** に Codex を起動する。`

536-548 行の「補足:」の箇条書き 1 つ目と 3 つ目を置き換える（2 つ目の ID の説明は残す）:

```markdown
- 0.7.4 まで必要だった「pane move --new-tab --workspace による自 workspace への
  回収」は不要。§6 で委譲元 workspace に作ったタブ（1レーン = 委譲元 workspace の
  タブ 1 つ）がそのまま Codex の置き場所になる。Codex の状態は委譲元 workspace の
  行に集約され、Agents パネルには Codex agent が個別に表示される。
```
```markdown
- タブはその中の最後の pane を閉じると自動で消える（0.9.3 実測）ので、cleanup は
  `herdr pane close` だけでよい（§15）。
```

- [ ] **Step 7: §13.1 を直す**

716-719 行のコメント:
- 旧: `# 任意 TUI は agent start では起動できない。worktree workspace の root pane を` / `# split して pane run で起動する。`
- 新: `# 任意 TUI は agent start では起動できない。Codex タブの root pane を` / `# split して pane run で起動する。`

730 行の末尾の文:
- 旧: `レビュー完了後（APPROVED / ABORTED）は hunk pane も `herdr pane close` で片付ける（split で増やした pane を閉じても Codex の root pane には影響しない）。`
- 新: `レビュー完了後（APPROVED / ABORTED）は hunk pane も `herdr pane close` で片付ける（split で増やした pane を閉じても Codex の root pane には影響しない。逆に hunk pane を閉じ忘れると、Codex pane を閉じてもタブが残る。§15）。`

- [ ] **Step 8: §15 を直す**

pane cleanup のコードブロック（`herdr pane close "$PANE_ID"` で終わるブロック）の直後に次を追加する:

````markdown
pane close の結果（§6 の `LANE_KIND` 別。0.9.3 実測）:

```text
tab:       タブの最後の pane なのでタブが消える。委譲元のタブ（Claude Code 自身）が
           残っているので、委譲元 workspace は閉じない。
workspace: workspace の最後の pane なので workspace も閉じる。
```

§13.1 で hunk pane を split した場合は、先にそれも閉じる（残っているとタブが消えない）。
````

- [ ] **Step 9: §17 を置き換える**

906-974 行（`## 17. worktree cleanup のタイミング` から、ゾンビ掃除スクリプトのコードブロック終わりまで）を次の内容に置き換える。

````markdown
## 17. worktree cleanup のタイミング

pane close と worktree remove は別物である。

```text
pane close（§15）:
  Codex のプロセス・画面を閉じる。Claude Code の最終レビュー後に行う。
  Codex 用タブ（単独 workspace の場合は workspace）も一緒に消える。checkout は残る。

worktree remove:
  Git worktree checkout を削除する。merge / PR / reject が終わった後だけ行う。
  必ず pane close の後に行う（Codex が中で動いたままディレクトリを消さない）。
```

作業ブランチを採用する前に worktree を消さない。

```bash
git -C "$ROOT" worktree remove "$WT"
git -C "$ROOT" branch -d "$BRANCH"   # merge 済みの場合。reject なら -D
```

- `.ai/` は info/exclude で無視されているので、残っていても `worktree remove` は
  `--force` なしで通る（0.9.3 環境で実測）。消えるのは checkout ごとなので、残したい
  ログは事前に退避しておく。
- Git が未コミットの変更を理由に拒否した場合、`git -C "$ROOT" worktree remove --force "$WT"`
  を使うのは、`logs/final.diff` を保存済みで、かつ人間が破棄を選んだときだけにする。
- pane を閉じずに中止した場合（§14.3 等）も、先に `herdr pane close "$PANE_ID"` してから
  上記を行う。

### 17.1 旧方式（1.4.x 以前）のレーンの片付け

1.4.x 以前の本手順は `herdr worktree create` でレーンを作っていた。そのとき作られた
worktree グループの子 workspace（`is_linked_worktree: true`）が残っている場合は、
次のルールで片付ける。

```text
workspace がまだ開いている:
  herdr worktree remove --workspace <id> で checkout と workspace を両方消す
  （pane 内でプロセスが生きていて拒否される場合のみ --force）。
workspace は閉じている:
  git worktree remove + branch -d で消す（herdr worktree remove は workspace_not_found）。
workspace が開いたまま git 側だけ消した:
  参照先のないゾンビ workspace が残る → herdr workspace close <id>。
workspace close --group:
  primary と linked をまとめて閉じるフラグ。workspace_group_close_required の
  エラー回避のために付けてはいけない（ユーザーが明示した場合のみ）。
--trust-repository:
  1リクエスト限りの Git trust。失敗時の再試行フラグではなく、ユーザーが
  リポジトリを確認済みのときだけ使う。
herdr worktree create:
  引数なしでも既定値で worktree を即作成する（0.7.4 実測）。usage 確認目的で叩かない。
```

ゾンビ workspace の検出と一括掃除:

```bash
# linked worktree の workspace だけを対象にする。repo root で開いた通常の
# workspace にも worktree オブジェクトが付く（is_linked_worktree: false）ため、
# `.worktree != null` では通常 workspace まで対象に含めてしまう。
# is_linked_worktree == true で絞ること（true 判定なので jq の // は使わない —
# false // x は x になる）。
herdr workspace list \
  | jq -r '.result.workspaces[] | select(.worktree.is_linked_worktree == true) | [.workspace_id, .worktree.checkout_path] | @tsv' \
  | while IFS=$'\t' read -r ws path; do
      [ -n "$path" ] && [ ! -d "$path" ] && herdr workspace close "$ws"
    done
```
````

Step 5 で `--force` が必要だった場合は、1 つ目の箇条書きを実測に合わせて直す。

- [ ] **Step 10: 確認して commit**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
F=plugins/dev-workflow/skills/delegating-to-codex/workflow.md
grep -n -E "worktree workspace|WS_ID" "$F"                      # → ヒットなし
grep -n "herdr worktree remove" "$F"                            # → §17.1 のみ
```
```bash
git add plugins/dev-workflow/skills/delegating-to-codex/workflow.md
git commit -m "feat(delegating-to-codex): タブ方式の起動・片付け手順に更新 (§9/§13.1/§15/§17)" -m "Co-Authored-By: ..."
```
（コミットメッセージ末尾には session の attribution 2 行を付ける）

---

### Task 3: 残りの手順書・SKILL.md・メタデータの整合と静的検証

**Files:**
- Modify: `plugins/dev-workflow/skills/delegating-to-codex/workflow.md`（冒頭 7 行、§20 1048-1080 行、§21 1121 行、§22 1220 行）
- Modify: `plugins/dev-workflow/skills/delegating-to-codex/SKILL.md`
- Modify: `plugins/dev-workflow/skills/delegating-to-codex/versions.json`
- Modify: `plugins/dev-workflow/.claude-plugin/plugin.json`
- Modify: `plugins/dev-workflow/README.md`（16 行・41 行）、`README.md`（20 行）

**Interfaces:**
- Consumes: Task 1 の §6 変数名と手順、Task 2 の §15/§17 の片付け手順
- Produces: 配布物としての整合（バージョン、要約、チェックリスト）

- [ ] **Step 1: 現状の確認（失敗するテスト相当）**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
git grep -n -E "herdr worktree create|worktree create の|0\.9\.1（same-minor）|herdr 0\.9\.1 /" -- plugins README.md | grep -v "workflow.md:7:"
```
Expected: SKILL.md（30・44・54 行）、workflow.md（§21・§22・§17.1）、plugin README（41 行）などにヒットする。

- [ ] **Step 2: 実機のバージョンを記録する**

Run:
```bash
"/Users/yura/ghq/github.com/RE-yura/claude-plugins/plugins/dev-workflow/skills/delegating-to-codex/check-versions.sh"
herdr --version; codex --version; claude --version
```
Expected: herdr は 0.9.3 で WARN（versions.json がまだ 0.9.1 のため）。codex / claude の実バージョンを控える（Task 2 の E2E で実際に使ったバージョン）。

- [ ] **Step 3: workflow.md 冒頭 7 行の注記を直す**

7 行目の blockquote を次の方針で書き換える（既存の版ごとの変更履歴は残す）:
- 冒頭の括弧内を `herdr 0.9.3 / codex-cli <Step 2 の値> / superpowers 6.4.1 / Claude Code <Step 2 の値>、2026-10-13 実機再検証・E2E 委譲一巡。過去: 0.9.1 / 0.9.0 / 0.8.2 / 0.8.0 / 0.7.5 / 0.7.1` にする。
- `0.9.1 は SSH マシン操作・…尊重される）` の後に次を追加: `。0.9.3 は本書が使うコマンドの引数は不変。**2026-10-13 改訂: Codex レーンは `herdr worktree create` ではなく `git worktree add` + 委譲元 workspace のタブ（`herdr tab create --workspace`）に作る**（herdr の worktree グループはリポジトリ単位で親を選び、同じリポジトリの workspace が複数あると委譲元とは別の workspace の下に表示されるため。§6）`
- 末尾の `ただし **`herdr worktree create` だけは引数なしでも既定値で即実行される**ので usage 確認目的で叩かないこと（0.7.4 実測）。` を `ただし **`herdr worktree create` は引数なしでも既定値で即実行される**ので（本流では使わないが）usage 確認目的で叩かないこと（0.7.4 実測。§17.1）。` にする。

- [ ] **Step 4: workflow.md §20・§21・§22 を直す**

§20 のチェックリストで次の行を置き換える:

- 旧 2 行:
  ```text
  [ ] Git worktree を作る（応答 JSON から root pane id と workspace id を控える。--json は付けない）
  [ ] worktree の .git/info/exclude に .ai/ を足す
  ```
  新 2 行:
  ```text
  [ ] git worktree add で Git worktree を作り、.git/info/exclude に .ai/ を足す（herdr worktree create は使わない）
  [ ] 委譲元 workspace に Codex 用タブを作る（HERDR_PANE_ID があれば pane current → tab create --workspace、なければ workspace create。応答 JSON の root pane id を // empty 付きで控える。--json は付けない）
  ```
- 旧: `[ ] worktree の root pane に Codex を起動する（agent start --kind codex --pane）`
  新: `[ ] Codex 用タブの root pane に Codex を起動する（agent start --kind codex --pane）`
- 旧: `[ ] Codex pane を閉じる`
  新: `[ ] Codex pane を閉じる（hunk pane を split していれば先に閉じる。タブも消える）`
- 旧 4 行（`[ ] merge / reject 後の checkout 削除: …` から `（workspace が開いたまま git 側だけ消すとゾンビ workspace が残る）` まで）
  新 1 行:
  ```text
  [ ] merge / reject 後: git worktree remove + branch -d（reject は -D）で checkout とブランチを消す（必ず pane close の後）
  ```

§21 の 1121 行:
- 旧: `    pane_id="${2:?pane_id required (worktree create の .result.root_pane.pane_id)}"`
- 新: `    pane_id="${2:?pane_id required (tab create / workspace create の .result.root_pane.pane_id)}"`

§22 の 1220 行:
- 旧: `- Codex は worktree create の root pane に起動する（agent start --kind codex --pane）。`
- 新: `- Codex レーンは git worktree add + 委譲元 workspace のタブ（tab create --workspace）に作り、その root pane に起動する（agent start --kind codex --pane）。herdr worktree create は使わない。`

- [ ] **Step 5: SKILL.md を直す**

1. frontmatter: `version: "1.3.0"` → `version: "1.4.0"`
2. 23 行: `## Quick Reference（herdr 0.9.1 / codex-cli 0.156.1 実測済み）` → `## Quick Reference（herdr 0.9.3 / codex-cli <Step 2 の値> 実測済み）`
3. 30 行の表の行（`| worktree 作成 + root pane 取得 | …`）を次の 2 行に置き換える:
   ```markdown
   | worktree 作成 | `git -C <root> worktree add -b <br> <wt> HEAD` + `.git/info/exclude` に `.ai/`（`herdr worktree create` は使わない） |
   | Codex 用タブ作成 + root pane 取得 | `HERDR_PANE_ID` があれば `herdr pane current` の `.result.pane.workspace_id` に `herdr tab create --workspace <ws> --cwd <wt> --label <task_id> --no-focus`、なければ `herdr workspace create --cwd <wt> --label <task_id> --no-focus` → 応答 JSON の `.result.root_pane.pane_id // empty` を控える（`--json` は付けない） |
   ```
4. Common Mistakes:
   - 44 行の末尾 `worktree create の root pane に起動する。pane move による回収も不要になった。` → `Codex 用タブの root pane に起動する。pane move による回収も不要になった。`
   - 50 行の `` `agent get` / `worktree create` 等は従来どおり JSON。`` → `` `agent get` / `tab create` 等は従来どおり JSON。``
   - 54 行（`- **`herdr worktree create` を引数なしで実行しない** — …`）を削除する。
   - 57 行（`- **cleanup は workspace の生死で手段を変える** — …`）を次に置き換える:
     ```markdown
     - **checkout は pane close の後に git で消す** — Codex pane を閉じるとタブ（単独 workspace なら workspace）も消える（0.9.3 実測）。merge / reject が済んでから `git worktree remove` + `branch -d`（reject は `-D`）。hunk pane を split していたら先に閉じる（残るとタブが消えない）。旧方式（1.4.x 以前）の worktree グループの片付けは workflow.md §17.1。
     ```
   - リストの先頭（`- **`herdr --version` だけで…` の前）に次の 2 項目を追加する:
     ```markdown
     - **委譲に `herdr worktree create` を使わない** — herdr の worktree グループはリポジトリ単位で親を選ぶので、同じリポジトリの workspace が複数あるとレーンが委譲元とは別の workspace の下に表示される（`--workspace` 指定でも直らない。2026-10-13 調査）。`git worktree add` + 委譲元 workspace のタブを使う。
     - **herdr の外で `pane current` を呼び元判定に使わない** — `HERDR_PANE_ID` がないとエラーにならずフォーカス中の pane を返す（0.9.3 実測）。`HERDR_PANE_ID` があるときだけ使い、なければ単独 workspace にする。
     ```
5. Workflow Summary:
   - 1: `1. worktree 作成（応答 JSON から root pane id / workspace id を控える）+ `.git/info/exclude` に `.ai/` 追加` → `1. `git worktree add` で worktree 作成 + `.git/info/exclude` に `.ai/` 追加 → 委譲元 workspace に Codex 用タブを作成（応答 JSON から root pane id を控える。herdr 外からなら単独 workspace）`
   - 6: `… → pane close → Claude がコミットし、…` の `pane close` を `pane close（タブも消える）` に。
   - 7: 行全体を `7. merge / reject 後: `git worktree remove` + `branch -d`（reject は `-D`）。必ず pane close の後に行う` に置き換える。

- [ ] **Step 6: versions.json・plugin.json・README を直す**

versions.json:
- `"verified_at": "2026-09-24"` → `"verified_at": "2026-10-13"`
- `herdr.verified`: `"0.9.1"` → `"0.9.3"`
- `herdr.note` の `0.9.1 は SSH/Windows/UI 中心で使用コマンドの引数は不変）。` の後に `0.9.3 で委譲レーンを tab create --workspace 方式に変更して E2E 確認（pane current は HERDR_PANE_ID なしだと focused pane を返す）。` を追加
- Step 2 で codex / claude の実バージョンが `verified` と違えば、E2E で実際に使ったその値に更新する（同じなら触らない）

plugin.json: `"version": "1.4.0"` → `"version": "1.5.0"`

plugins/dev-workflow/README.md:
- 16 行: `委譲ワークフローの正本。worktree 隔離、1行 `/goal`、` → `委譲ワークフローの正本。worktree 隔離、委譲元 workspace のタスク専用タブ、1行 `/goal`、`
- 41 行: `| 0.9.1（same-minor） |` → `| 0.9.3（same-minor） |`

README.md:
- 20 行: `worktree 隔離、タスク専用タブ、` → `worktree 隔離、委譲元 workspace のタスク専用タブ、`

- [ ] **Step 7: 静的検証**

Run:
```bash
cd /Users/yura/ghq/github.com/RE-yura/claude-plugins
find plugins/dev-workflow -name '*.sh' -print0 | xargs -0 -n1 bash -n && echo "bash -n OK"
find plugins/dev-workflow -name '*.json' -print0 | xargs -0 -n1 jq empty && echo "json OK"
plugins/dev-workflow/tests/test-check-versions.sh | tail -3
plugins/dev-workflow/tests/test-prompt-rules-reminder.sh | tail -3
plugins/dev-workflow/skills/delegating-to-codex/check-versions.sh
git grep -n "herdr worktree create" -- plugins README.md
```
Expected: 構文チェック OK、両テスト全 PASS、check-versions.sh で herdr が OK、`herdr worktree create` のヒットは workflow.md の冒頭 7 行・§6 の「使わない」説明・§17.1・§22（「使わない」）と SKILL.md の「使わない」項目と Quick Reference だけ。

- [ ] **Step 8: commit**

```bash
git add plugins/dev-workflow README.md
git commit -m "docs(dev-workflow): タブ方式に合わせて SKILL.md・チェックリスト・バージョンを更新" -m "Co-Authored-By: ..."
```
（コミットメッセージ末尾には session の attribution 2 行を付ける）

---

### 最終レビュー

- [ ] Fable モデルのサブエージェントに、spec・本計画・`git diff main...feat/codex-lane-caller-tab` を渡してブランチ全体をレビューさせる（観点: spec との整合、§6〜§17 の手順として実行可能か、変数名の一貫性、旧方式の記述の残り、Review Focus 1〜5 が手順書に反映されているか）。
- [ ] 指摘を superpowers:receiving-code-review の流儀で検証し、妥当なものだけ直して commit する。
- [ ] 人間に UI 確認を依頼する（spec §4-4: Codex タブを開いたときに委譲元 workspace のラベル・ブランチ表示が変わらないか）。
