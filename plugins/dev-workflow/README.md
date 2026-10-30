# dev-workflow

**Claude を「設計・レビュー担当」、Codex を「実装担当」として分業させ、その運用ルールを Claude に確実に守らせる** Claude Code プラグイン。

インストールすると、次の2つのルールがモデルの気分に依存せず毎回適用される：

1. **設計ドキュメント・実装計画は、必ず superpowers の brainstorming（要件・設計の探索）→ writing-plans（計画書の執筆）を通して書く** — いきなり書き始めない
2. **実装・修正は Codex CLI に委譲する** — Claude が計画ファイルを書き、herdr-core (`hc`) 経由で Codex に `/goal` を送り、完了を待ってレビューし、必要なら修正を依頼するループを回す（手順書 `workflow.md` を同梱。hc 版の委譲一巡は E2E で確認する）

## 仕組み

| コンポーネント | 役割 |
|---|---|
| SessionStart hook | 上記ルール2本を毎セッション開始時に無条件で注入 |
| `delegating-to-codex` スキル | 委譲ワークフローの正本。worktree 隔離、hc 内では Claude の子、外では Herdr アプリのタスク用 space（アプリが無ければ `hc attach`）、1行 `/goal`、完了検知（OSC 7501 の状態 + 今回の `Round:` の `CODEX_DONE.md`）、REVIEW/FIX ループ、安全ルールまでの完全な手順書 |

## インストール

ターミナルから:

```bash
claude plugin marketplace add RE-yura/claude-plugins
claude plugin install dev-workflow@re-yura
```

Claude Code セッション内なら:

```
/plugin marketplace add RE-yura/claude-plugins
/plugin install dev-workflow@re-yura
```

## 前提環境

プラグイン自体は設定なしで動くが、委譲ワークフローを実際に走らせるには以下が必要：

| 必要なもの | 検証済みバージョン | 何のために |
|---|---|---|
| [superpowers](https://github.com/obra/superpowers) プラグイン | 7.0.0（same-major） | brainstorming / writing-plans スキルの提供元（`claude plugin install superpowers@claude-plugins-official`） |
| herdr-core (`hc`) | 0.1.14（same-minor） | Codex の起動・監視・操作。OSC 7501 の状態報告を使う（integration install 不要） |
| Herdr アプリ (`herdr-app`) | 0.1.8（info、任意） | Codex の見せ方。無くても `hc attach` で委譲可能 |
| [Codex CLI](https://developers.openai.com/codex/cli) | 0.164.0（minimum 0.144.0） | 実装担当（0.144+ は `/goal` 既定有効。slash command list に出ない場合のみ `codex features enable goals`） |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | 2.1.314（info: 報告のみ） | hook（運用ルール注入）の実行環境。版が変わっても WARN にはしない |
| jq | 任意（presence） | hc / herdr-app の JSON 出力のパース |
| [yomiyasu](https://github.com/nanaism/yomiyasu) プラグイン | 任意（無ければその段を飛ばす。バージョン検査の対象外） | PR の本文の推敲（workflow.md §16.1。`claude plugin marketplace add nanaism/yomiyasu` → `claude plugin install yomiyasu@yomiyasu`） |

検証済みバージョンの正（source of truth）は [`skills/delegating-to-codex/versions.json`](skills/delegating-to-codex/versions.json)。検証日は 2026-10-30。委譲開始前に `check-versions.sh` で hc の same-minor と `hc server status --json` の core の版を確認する（WARN はブロックしない）。CLI と core の版が違うときも、core の再起動はユーザーに確認してから行う。herdr-app が無い場合は INFO のみ。版を上げて再検証したら versions.json を更新する。

E2E で確認する: `/goal` の自動継続ターンの境目の状態、`space.new --argv` の PATH、`hc keys <t> 2` だけでアップデート確認を Skip できるか。Claude から hc の中・外の両方で、初回実装 → 修正1回 → 片付けを確認する。

## 開発

```bash
# スクリプトと hook のテスト（スタブ使用。実物の hc / herdr-app / codex 不要）
tests/test-check-versions.sh && tests/test-section-refs.sh
```

同じテストが GitHub Actions（`.github/workflows/test.yml`）でも push / PR ごとに走る（シェル・JSON の構文チェック込み）。

## License

MIT
