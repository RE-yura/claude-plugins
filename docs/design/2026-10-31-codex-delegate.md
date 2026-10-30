# codex-delegate: `cdx` CLI と `codex exec` による委譲 (dev-workflow の作り直し)

dotfiles のロードマップ 段階 3 (`docs/plans/2026-10-31-rebuild-roadmap.md`)。後方互換は不要。dev-workflow は消す。

## 背景

- dev-workflow 2.0.x の委譲は、959 行の `workflow.md` に書いた bash を Claude が写して実行する。判断 (待ち・ラウンド照合・
  片付け対象) がコードになっておらず、テストは文書の § 参照の整合だけ。Bash の呼び出しをまたぐと変数・関数が消えるので
  `hc_raw` を 7 回書き直し、`$HUNK_TAB` に頼る片付けには実際のバグがあった。
- Codex の対話 TUI に `/goal` を打ち込む方式のために、上流の不具合の回避が本線に積み重なっていた: 起動時のアップデート /
  trust / hooks のダイアログ、`hc send` の `<hc from>` タグで slash command が効かない、background terminals が残ると
  working のまま止まる (`/stop`)、送信が composer に残る。
- 2026-10-31 の spike: `codex exec --json -o <file> --output-schema <schema> "<prompt>"` を hc のターミナルで動かすと、
  ダイアログ無しで動き、完了 = プロセスの終了 (exit 0)、最終回答は schema どおりの JSON。`thread.started` event の
  `thread_id` で `codex exec resume <thread_id> "<prompt>"` が同じセッションの続きとして動く (修正ラウンドに使える)。

## 決めたこと

- プラグイン名は `codex-delegate` (1.0.0)。marketplace `re-yura` はこれだけを載せる。dev-workflow は消す。
- 委譲は `codex exec` で行う。対話 TUI・`/goal`・`hc send`・ダイアログ処理は使わない。
- 手順はすべて CLI `cdx` (Python 標準ライブラリ、3.11+) に入れる。Claude の仕事は PLAN を書く・REVIEW を書く・
  `cdx` の exit code に従う・人に聞く、に絞る。
- 状態は task dir の `state.json` だけに置く。シェル変数には何も頼らない。
- ラウンドはディレクトリで分ける: `rounds/01/` が初回、`02/`〜`04/` が修正 (修正は最大 3 回)。
  各ラウンドに `PROMPT.md` (Codex への依頼)、`DONE.json` (schema どおりの最終回答)、`events.jsonl`、`REVIEW.md` を置く。
  そのラウンドの `DONE.json` があれば完了。先頭行の解析や mtime 比較はしない。
- 守るべき条件は CLI が強制する: `cdx finish` は最新ラウンドの `REVIEW.md` が `Status: APPROVED` でなければ拒否し、
  コミットは `cdx finish` だけが行う (Codex にはさせない)。`cdx cleanup` は state.json に記録した自分のターミナルと
  worktree だけを消す。修正 4 回目は `cdx fix` が拒否する。
- hook は持たない。全エージェント共通の方針 (設計は brainstorming → writing-plans、実装は Codex に委譲) は dotfiles の
  `AGENTS.md` (Claude は CLAUDE.md、Codex は AGENTS.md として読む) に置く。
- 版の互換は CLI の定数で強制する (`hc` 0.1.x、`codex` ≥ 0.164)。範囲外なら `cdx start` が止まる (`--allow-untested` で通す)。
  検証した版と E2E の記録は CHANGELOG.md に書く。versions.json と check-versions.sh は持たない。
- 版は `plugin.json` の 1 か所だけ。CI がプラグインの中身の変更に版の bump を求める。

## `cdx` のコマンド

すべて JSON 1 行を stdout に出し、exit code で結果を返す (0 成功、2 Codex が blocked、3 人の判断が要る、1 失敗)。
`--task <task_dir>` を省くと、カレントの worktree から task dir を探す。

| コマンド | すること |
|---|---|
| `cdx doctor` | hc・codex・herdr-app の版、hc core の稼働、Claude プラグインの scope の重複を確かめる |
| `cdx start [--repo P] [--name N]` | worktree (`../worktrees/<task_id>`, branch `ai/<task_id>`)・`.ai/` の exclude・task dir・`state.json` を作る。mode は `HC_TERMINAL_ID` があれば child、Herdr が動いていれば space、どちらでもなければ hidden |
| `cdx run [--wait]` | 今のラウンドの Codex を起動する。01 は `codex exec`、02 以降は `codex exec resume <thread_id>`。hc のターミナル (child: `hc run --bg --outlive-parent --no-notify`、space: `herdr-app do space.new --argv`) で動かし、出力は `cdx render` で人が読める形にしてターミナルに出し、生の JSONL は `events.jsonl` に保存する。`--wait` なら終了まで待つ |
| `cdx wait` | 今のラウンドのターミナルが終わるまで `hc wait` で待ち、`thread_id`・exit code・`DONE.json` を state に記録する |
| `cdx fix` | 最新の `REVIEW.md` が `CHANGES_REQUESTED` のとき、次のラウンドの dir と `PROMPT.md` (FIX の雛形) を作る |
| `cdx finish [-m MSG]` | 最新 REVIEW が APPROVED なら、final diff を保存し、worktree でコミットし、自分のターミナルを片付ける |
| `cdx abort` | Codex を止め、記録を残して state を aborted にする |
| `cdx cleanup` | finished / aborted の task の worktree と branch を消す (merge 済みでなければ `--force` が要る) |
| `cdx status` | state.json と今のラウンドの要約 |
| `cdx render` | stdin の `codex exec --json` を人向けの行に変換する (Herdr のターミナルに出す用) |

`PROMPT.md` には PLAN.md (またはそのラウンドの FIX の指示) の読み先、範囲の制限、禁止事項 (deploy・secret・ネットワーク・
破壊的操作・コミット・subagent)、最終回答の形を書く。最終回答の schema (`done.schema.json`) は
`{status: done|blocked, summary, changed_files[], tests, risks}`。

## 構成

```
claude-plugins/
├─ .claude-plugin/marketplace.json
├─ plugins/codex-delegate/
│  ├─ .claude-plugin/plugin.json
│  ├─ skills/delegating-to-codex/
│  │  ├─ SKILL.md            # 120 行以内: いつ使う・役割・cdx の流れと exit code の表・レビュー観点・人に聞く条件
│  │  ├─ cdx                 # エントリポイント (SKILL.md は「Base directory」からの相対で呼ぶ)
│  │  ├─ cdx_lib/            # state・hc・codex・herdr・render・git の各モジュール
│  │  └─ templates/          # PLAN.md・REVIEW.md・done.schema.json
│  └─ tests/                 # unittest。偽の hc / codex / herdr-app / git worktree で全コマンドを通す
├─ docs/design/              # このファイル
├─ CHANGELOG.md
└─ .github/workflows/ci.yml  # unittest・py_compile・manifest の検証・版 bump の検査
```

## 消すもの

dev-workflow 一式 (workflow.md・SKILL.md・hooks・check-versions.sh・versions.json・tests・README)、
`docs/superpowers/` の spec と plan (要点はこのファイルと CHANGELOG に残した)、ルートの README の重複部分と旧 marketplace の移行手順。
