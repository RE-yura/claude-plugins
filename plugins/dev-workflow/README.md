# dev-workflow

**Claude を「設計・レビュー担当」、Codex を「実装担当」として分業させ、その運用ルールを Claude に確実に守らせる** Claude Code プラグイン。

インストールすると、次の2つのルールがモデルの気分に依存せず毎回適用される：

1. **設計ドキュメント・実装計画は、必ず superpowers の brainstorming（要件・設計の探索）→ writing-plans（計画書の執筆）を通して書く** — いきなり書き始めない
2. **実装・修正は Codex CLI に委譲する** — Claude が計画ファイルを書き、herdr 経由で Codex に `/goal` を送り、完了を待ってレビューし、必要なら修正を依頼するループを回す（実機検証済みの手順書 `workflow.md` を同梱）

## 仕組み

| コンポーネント | 役割 |
|---|---|
| SessionStart hook | 上記ルール2本を毎セッション開始時に無条件で注入 |
| UserPromptSubmit hook | プロンプトのキーワード（設計/実装/plan/codex/委譲 等）に応じてルールを just-in-time で再注入 |
| `delegating-to-codex` スキル | 委譲ワークフローの正本。worktree 隔離、1行 `/goal`、完了検知（idle+marker）、REVIEW/FIX ループ、安全ルールまでの完全な手順書 |

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
| [superpowers](https://github.com/obra/superpowers) プラグイン | 6.4.1（same-major） | brainstorming / writing-plans スキルの提供元（`claude plugin install superpowers@claude-plugins-official`） |
| [herdr](https://herdr.dev) | 0.9.1（same-minor） | Codex を pane として起動・監視・操作（導入後 `herdr integration install codex`） |
| [Codex CLI](https://developers.openai.com/codex/cli) | 0.156.1（minimum 0.144.0） | 実装担当（0.144+ は `/goal` 既定有効。slash command list に出ない場合のみ `codex features enable goals`） |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | 2.1.281（info: 報告のみ） | hook（運用ルール注入）の実行環境。版が変わっても WARN にはしない |
| jq | 任意（presence） | herdr の JSON 出力のパース |

検証済みバージョンの正（source of truth）は [`skills/delegating-to-codex/versions.json`](skills/delegating-to-codex/versions.json)。herdr は minor バージョンで CLI が破壊的に変わるため、委譲ワークフローは開始前に同梱の `check-versions.sh` で実機バージョンとのズレを検出する（WARN は警告であってブロックではない）。herdr については `herdr status` で client と server の整合も確認する（client だけ入れ替わった直後は全 API が `protocol_mismatch` になるため）。バージョンを上げて再検証したら versions.json を更新する。

## 開発

```bash
# check-versions.sh と prompt-rules-reminder.sh（hook）のテスト（スタブ使用。実物の herdr / codex 不要）
tests/test-check-versions.sh && tests/test-prompt-rules-reminder.sh
```

同じテストが GitHub Actions（`.github/workflows/test.yml`）でも push / PR ごとに走る（シェル・JSON の構文チェック込み）。

## License

MIT
