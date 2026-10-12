# Codex レーンを委譲元 workspace のタブに置く（delegating-to-codex 改訂）

- 日付: 2026-10-13
- 対象: `plugins/dev-workflow/skills/delegating-to-codex/`（workflow.md / SKILL.md）と関連メタデータ
- 状態: 設計承認済み（brainstorming）→ 本 spec のレビュー待ち

## 1. 背景と問題

現行 workflow.md §6 は Codex レーンを `herdr worktree create --cwd "$ROOT"` で作る。herdr の worktree グループは**リポジトリ単位**で、親 workspace は「同じ `repo_key` を持つ非 linked workspace のうちサイドバー順で最初のもの」が選ばれる（herdr v0.9.3 `src/app/api/worktrees.rs` の `find_parent_workspace_by_key`）。子 workspace の membership にはリポジトリのキーしか記録されず、親 workspace ID を持たない（`src/workspace.rs` の `WorktreeSpaceMembership`）。

そのため同じリポジトリの workspace が複数あると、Codex レーンは委譲した Claude が居る workspace ではなく、先頭の workspace の子として表示される。実例: macmini の chum リポジトリでは workspace が 6 つあり、`wHT` から委譲しても子は先頭の `w7R` の下に表示される。

`--workspace <呼び元>` を指定しても解決しない。呼び元も同じリポジトリの primary として登録され、サイドバーは 1 リポジトリにつき親を 1 つしか描かないので、呼び元が子のようにインデントされる。preview 版の修正（herdr #4736 / PR #4772）も「repo root を全部トップレベルに並べる」だけで、PR 本文に「新しい parent ID は追加しない」と明記されている。

## 2. 目的と成功条件

**目的:** Codex レーンが委譲した Claude と同じ workspace に表示され、委譲元が見た目で分かること。同じリポジトリの workspace が複数あっても成り立つこと。

**成功条件:**

1. herdr 内の Claude から委譲すると、Codex は呼び元 workspace の新しいタブで動く。新しい workspace も worktree グループも作られない。
2. herdr の外から委譲した場合（`HERDR_PANE_ID` なし）は、グループに属さない単独 workspace に Codex が置かれる。
3. 片付け後に、タブ・workspace・worktree チェックアウト・ブランチのいずれも残らない（ブランチは merge / reject の決定どおりに処理）。
4. `/goal` 投入・完了検知・marker・REVIEW/FIX ループ・安全ルールは現行のまま動く。

**非目標:**

- herdr の worktree グループ表示の改善（upstream の領分）。
- macmini 上の既存レーンや既存 workspace の整理。
- socket API・プラグイン・`workspace report-metadata` による表示の追加。

## 3. 設計

### 3.1 レーン作成（workflow.md §6 を置き換え）

worktree は herdr を介さず `git worktree add` で作る。パスとブランチ名の規約は現行どおり。

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$(git rev-parse --show-toplevel)"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"

git -C "$ROOT" worktree add -b "$BRANCH" "$WT" HEAD
echo ".ai/" >> "$(git -C "$WT" rev-parse --git-path info/exclude)"
```

呼び元 workspace を特定し、そこにタスク専用タブを作る。

```bash
# herdr 外では pane current がフォーカス中の pane を返す（エラーにならない。
# herdr v0.9.3 src/cli/pane.rs の pane_current は caller_pane_id なしだと
# focused pane にフォールバックする）ので、HERDR_PANE_ID の有無で判定する。
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
test -n "$PANE_ID"
```

- `HERDR_PANE_ID` が設定されていれば `pane current` は caller context で解決される。pane move 後の旧 ID もこの経路なら解決できる。
- `HERDR_PANE_ID` はあるが `pane current` が失敗した場合（stale ID 等）は `CALLER_WS` が空になり、単独 workspace にフォールバックする。
- `tab create` と `workspace create` の応答はどちらも `.result.root_pane.pane_id` を持つ（CLI reference 記載）。herdr のエラー JSON（protocol_mismatch 等は exit 0 で返る）で文字列 `null` を拾わないよう `// empty` を付ける。
- `|| true` は `set -euo pipefail` のスクリプトで `pane current` が失敗しても止まらず、フォールバックへ進むため。
- 専用タブにする理由: 呼び元の作業中タブを分割すると、ユーザーの画面を狭め、並列委譲で破綻する。タブ名（TASK_ID）で委譲を見分けられ、片付けもペイン 1 つを閉じるだけで済む。

### 3.2 Codex 起動以降（§9〜§14）

変更しない。`agent start "$AGENT" --kind codex --pane "$PANE_ID"`、起動確認（生存 + visible read でダイアログ確認）、`agent prompt --wait`、marker 確認、REVIEW/FIX ループはそのまま。変わるのは `PANE_ID` の取得元が `worktree create` の応答から §3.1 の応答になることだけ。

§9 の補足「1 レーン = 1 workspace、サイドバーで workspace ごとの状態が見える」は次のように書き換える: 1 レーン = 呼び元 workspace のタブ 1 つ。Codex の状態は呼び元 workspace の行に集約され、Agents パネルには Codex agent が個別に表示される。

§13.1（hunk）の「worktree workspace の root pane を split」は「Codex タブの root pane を split」に改める。

### 3.3 片付け（§15・§17）

**pane close（§15）:** 現行どおり `herdr pane close "$PANE_ID"`。

- `LANE_KIND=tab`: タブの最後のペインなのでタブが消える。呼び元タブ（Claude 自身）が残っているので呼び元 workspace は閉じない。
- `LANE_KIND=workspace`: workspace の最後のペインなので workspace も閉じる。
- §13.1 で hunk ペインを分割した場合は、それも閉じないとタブ（または workspace）が残る。これを明記する。

**チェックアウト削除（§17）:** レーンの種類によらず git で行う。

```bash
# 必ず pane close の後に行う（Codex が中で動いたままディレクトリを消さない）
git -C "$ROOT" worktree remove "$WT"
git -C "$ROOT" branch -d "$BRANCH"   # merge 済み。reject なら -D
```

- Git が未コミットの変更を理由に拒否した場合、`git worktree remove --force` を使うのは `logs/final.diff` を保存済みで、かつ人間が破棄を選んだときだけ。
- 「workspace が開いているかで手段を変える」記述と、ゾンビ workspace の説明は本筋から外す。

**旧方式レーンの片付け（§17 内に小節を新設）:** 1.4.x 以前の手順で作られた worktree グループの子 workspace を片付けるための手順として、以下を残す。

- `is_linked_worktree == true` で絞り込むゾンビ workspace の検出・一括 close スクリプト
- `herdr worktree remove --workspace` の使い方
- `workspace close --group` をエラー回避のために付けない、という注意

### 3.4 ドキュメント・メタデータの更新範囲

| ファイル | 変更 |
|---|---|
| `workflow.md` | 冒頭の検証環境注記（0.9.3 検証と本改訂の要約）、§1（役割表）、§2.1（pane の用意 = tab create の root pane）、§4（ライフサイクル 2・4・15・17）、§6（§3.1 で置き換え）、§9 補足、§13.1、§15、§17（§3.3 で書き直し）、§20 チェックリスト、§21 wrapper のコメント、§22 |
| `SKILL.md` | Quick Reference の作成行、Common Mistakes、Workflow Summary、frontmatter `version` 1.3.0 → 1.4.0 |
| `SKILL.md` Common Mistakes 追加 | 「委譲に `herdr worktree create` を使わない（委譲元とは別の workspace の下にまとめられる）」「herdr 外で `pane current` を呼び元判定に使わない（フォーカス中の pane が返る）」 |
| `SKILL.md` Common Mistakes 更新 | 「cleanup は workspace の生死で手段を変える」を「pane close → git worktree remove の順」に置き換え。「`herdr worktree create` を引数なしで実行しない」は SKILL.md から削除し、workflow.md 冒頭注記と §17 旧方式小節の注意としてだけ残す（本流で使わなくなるため） |
| `README.md`（ルート）/ `plugins/dev-workflow/README.md` | スキル説明を「worktree 隔離、呼び元 workspace のタスク専用タブ、…」に揃える |
| `versions.json` | `herdr.verified` を 0.9.3、`verified_at` を検証日に。note に 0.9.3 での確認内容を追記 |
| `plugins/dev-workflow/.claude-plugin/plugin.json` | `version` 1.4.0 → 1.5.0 |

## 4. 検証

1. **静的確認:** `plugins/dev-workflow/tests/*.sh` を実行して全部通ること（tests は fixture の versions.json を使うので、実 versions.json の更新の影響を受けない）。`worktree create` という記述が旧方式の小節と変更履歴以外に残っていないことを grep で確認する。
2. **実機 E2E（herdr 0.9.3、ローカル）:** scratchpad に作った使い捨てのリポジトリを対象に、このセッション（呼び元 = 自 workspace）から §6〜§17 を一巡する。
   - `git worktree add` → `tab create` → `agent start` → 小さな `/goal`（ファイルを 1 つ作る）→ done と行頭 marker を確認
   - `pane close` 後に確認: タブが消える、呼び元 workspace が残る、`workspace list` に `is_linked_worktree` の workspace が増えていない
   - `git worktree remove` と `branch -D` で片付け、残骸がないこと
3. **herdr 外経路:** `env -u HERDR_PANE_ID` で §6 を実行し、単独 workspace ができること、`pane close` でそれも消えることを確認する（Codex は起動しなくてよい）。
4. **人間による確認（UI）:** Codex タブを開いたときに、呼び元 workspace のラベルやブランチ表示が worktree 側に変わらないか。macmini `wHT` での確認は次の実委譲時に行う。

## 5. リスク

- **呼び元の表示が変わる可能性:** workspace の identity cwd がアクティブタブのペインに追従する場合、Codex タブを開いている間だけラベルやブランチ表示が worktree 側になるかもしれない（§4-4 で確認）。起きた場合は既知の挙動として §9 に記録する。動作には影響しない。
- **呼び元タブを先に閉じた場合:** Codex タブが workspace の最後のタブになり、Codex のペインを閉じると workspace ごと閉じる。中身は Codex だけなので実害はない。
- **呼び元 workspace が旧方式グループの primary の場合:** タブを閉じても最後のタブではないので、グループ close の確認（`confirmation_required`）には当たらない。
