# claude-plugins

yura の Claude Code プラグイン marketplace。

## dev-workflow

**Claude を「設計・レビュー担当」、Codex を「実装担当」として分業させ、その運用ルールを Claude に確実に守らせる**プラグイン。

Claude Code は放っておくと設計も実装も自分でやってしまい、計画を書かずに手を動かし始めることもある。このプラグインを入れると、次の2つのルールが**モデルの気分に依存せず**毎回適用される：

1. **設計ドキュメント・実装計画を書くときは、必ず superpowers の brainstorming（要件・設計の探索）→ writing-plans（計画書の執筆）を通す** — いきなり書き始めない
2. **実装・修正は Codex CLI に委譲する** — Claude が計画ファイルを書き、herdr 経由で Codex に `/goal` を送り、完了を待ってレビューし、必要なら修正を依頼するループを回す。手順書（`workflow.md`、実機検証済み）を同梱

### 仕組み

| コンポーネント | 役割 |
|---|---|
| SessionStart hook | 上記ルール2本を**毎セッション開始時に無条件で注入**（CLAUDE.md をどのプロジェクトにも持ち歩くのと同じ効果） |
| UserPromptSubmit hook | プロンプトのキーワードに応じて**その瞬間にルールを再注入**。設計/実装/計画/考え/design/plan 等 → ルール1、codex/herdr/委譲/任せ 等 → ルール2。長いセッションで文脈が薄れても効く |
| `delegating-to-codex` スキル | 委譲ワークフローの正本。worktree 隔離、タスク専用タブ、1行 `/goal`、完了検知（idle+marker）、REVIEW/FIX ループ（最大3回）、安全ルールまでの完全な手順書 |

### 使い方

インストール後は hook が自動で誘導するので、普段どおり話すだけでよい：

```
認証まわりの設計を考えたい     → brainstorming → writing-plans に誘導される
Codex に実装を委譲して         → delegating-to-codex スキルが起動する
```

明示的に呼ぶなら「delegating-to-codex スキルで進めて」または `/dev-workflow:delegating-to-codex`。

### 前提環境

このプラグイン自体は設定なしで動くが、委譲ワークフローを実際に走らせるには以下が必要：

| 必要なもの | 何のために | 導入方法 |
|---|---|---|
| superpowers プラグイン | ルール1が参照する brainstorming / writing-plans スキルの提供元 | `claude plugin install superpowers@claude-plugins-official`（公式 marketplace、デフォルトで登録済み） |
| [herdr](https://herdr.dev) | Codex を pane として起動・監視・操作するターミナルワークスペースマネージャ | [herdr.dev/docs/install](https://herdr.dev/docs/install/) 参照。導入後 `herdr integration install codex` で状態検知を有効化 |
| [Codex CLI](https://developers.openai.com/codex/cli) | 実装担当。`/goal`（長時間自律実行モード）を使う | 0.144+ は `/goal` 既定有効。slash command list に出ない場合のみ `codex features enable goals` |
| jq | herdr の JSON 出力のパース | `brew install jq` |

## 導入

ターミナルから（推奨）:

```bash
claude plugin marketplace add RE-yura/claude-plugins
claude plugin install dev-workflow@re-yura
```

Claude Code セッション内なら:

```
/plugin marketplace add RE-yura/claude-plugins
/plugin install dev-workflow@re-yura
```

Claude に日本語で頼むなら:

```
RE-yura/claude-plugins の marketplace を追加して dev-workflow プラグインを入れて
```

リポジトリ側の `.claude/settings.json` に書いておくと、開いた人に自動でインストール提案が出る:

```json
{
  "extraKnownMarketplaces": {
    "re-yura": {
      "source": { "source": "github", "repo": "RE-yura/claude-plugins" }
    }
  },
  "enabledPlugins": {
    "dev-workflow@re-yura": true
  }
}
```

### 旧 marketplace（RE-yura/claude-marketplace）から移行する場合

以前は `RE-yura/claude-marketplace` + npm パッケージ経由で配布していた（現在は更新停止）。そちらで入れた環境は marketplace を登録し直す（marketplace 名・インストール名は同じ）:

```bash
claude plugin marketplace remove re-yura
claude plugin marketplace add RE-yura/claude-plugins
claude plugin install dev-workflow@re-yura
```

## リリース手順

`plugins/dev-workflow/.claude-plugin/plugin.json` の `version` を bump して main に push する。利用者は下の「更新」で取り込む。

## 更新

```bash
claude plugin marketplace update re-yura
claude plugin update dev-workflow@re-yura
```

## アンインストール

```bash
claude plugin uninstall dev-workflow@re-yura      # プラグインを削除
claude plugin marketplace remove re-yura          # marketplace 登録ごと削除する場合
```

一時的に止めるだけなら `claude plugin disable dev-workflow@re-yura`（再開は `enable`）。settings.json 経由で導入した環境では、`enabledPlugins` の該当行を削除（そのリポジトリのみ無効にしたい場合は `.claude/settings.local.json` に `"dev-workflow@re-yura": false`）。いずれも反映には再起動が必要。
