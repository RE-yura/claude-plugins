#!/usr/bin/env bash
# SessionStart hook: 開発運用ルールを毎セッション無条件でコンテキストに注入する。
# （CLAUDE.md 相当の常時層。詳細手順はスキル側に置き、ここは短いルールのみ）
cat <<'EOF'
[dev-workflow 運用ルール]
- 設計ドキュメント・実装計画を書くときは、常に superpowers:brainstorming で要件・設計を探索してから、superpowers:writing-plans に従って書くこと（Codex 委譲用 PLAN.md に限らず全般）。
- 実装・修正を Codex に委譲するとき（herdr / /goal）は、必ず先に delegating-to-codex スキルを起動し、その workflow.md の規約に従うこと。
EOF
exit 0
