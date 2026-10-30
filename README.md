# claude-plugins

yura の Claude Code プラグイン marketplace。提供するプラグインは codex-delegate。
Claude が計画・レビューを担当し、Codex exec への実装委譲を cdx CLI で管理する。
起動・待機・最大3回の修正・承認後のコミット・片付けを状態ファイルで追跡する。hook はない。

## 導入

```bash
claude plugin marketplace add RE-yura/claude-plugins
claude plugin install codex-delegate@re-yura --scope user
```

Python 3.11+、hc 0.1.x、codex-cli 0.164.0 以降、superpowers スキルが必要。
「Codex に実装を委譲して」で delegating-to-codex スキルを使う。
詳しい手順は [SKILL.md](plugins/codex-delegate/skills/delegating-to-codex/SKILL.md)。

## 開発

```bash
python3 -m unittest discover -s plugins/codex-delegate/tests
```

テストは fake hc/codex と一時 Git repo を使う。外部通信はしない。
プラグインの変更時は `plugins/codex-delegate/.claude-plugin/plugin.json` の version を更新する。CI で検査する。
