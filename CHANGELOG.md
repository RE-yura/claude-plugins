# CHANGELOG

## 1.0.0 — 2026-10-31

- codex-delegate が dev-workflow を置き換える (replaces dev-workflow)。hook と対話 TUI の /goal 手順を削除。
- Python 標準ライブラリの cdx CLI に状態・起動・待機・修正・承認・片付けを集約。
- 2026-10-31 の spike で codex-cli 0.164.0 / hc 0.1.14 を検証。
  hc terminal 内の `codex exec --json -o <file> --output-schema <schema>` はダイアログなしで完了し、
  exit 0 と schema に従う JSON を確認。`thread.started` の thread_id を使う `codex exec resume` で同じセッションの続きを確認。
- 対応範囲は hc 0.1.x / codex-cli 0.164.0 以降。hc core と CLI の版も doctor で照合。
- 今回の回帰検証は fake hc/codex と一時 Git repo。実コマンドで spike を再実行していない。
