#!/usr/bin/env bash
# UserPromptSubmit hook: prompt の内容に応じて運用ルールを just-in-time で注入する。
# - 設計/実装/計画系 -> brainstorming → writing-plans ルール
# - Codex 委譲系     -> delegating-to-codex スキル使用ルール
# 英語キーワードは -w（単語境界）で判定し、"explain" が "plan" に誤マッチする類を防ぐ。
set -uo pipefail

prompt=$(jq -r '.prompt // empty' 2>/dev/null || true)

matches() {
  printf '%s' "$prompt" | grep -qiE "$1"
}

matches_word() {
  printf '%s' "$prompt" | grep -qwiE "$1"
}

out=""

if matches '設計|実装|計画|プラン|仕様|要件|アーキテクチャ|リファクタ|機能|開発|考え|作って|作ろう|作りたい|作り直' \
  || matches_word 'design|implement|implementation|plan|plans|planning|spec|architecture|refactor|feature|build'; then
  out+="Reminder: 設計ドキュメント・実装計画を書くときは、必ず superpowers:brainstorming で要件・設計を探索してから superpowers:writing-plans に従って書くこと。実装タスクでも、着手前に計画が要るなら同様。"$'\n'
fi

if matches 'codex|herdr|委譲|任せ|やらせ|投げて'; then
  out+="Reminder: Codex への実装委譲タスクでは、必ず delegating-to-codex スキルを起動し、workflow.md の規約（brainstorming→writing-plans で PLAN.md、pane run で 1行 /goal、idle+marker 待ち、REVIEW/FIX ループ）に従うこと。"$'\n'
fi

[ -n "$out" ] && printf '%s' "$out"

exit 0
