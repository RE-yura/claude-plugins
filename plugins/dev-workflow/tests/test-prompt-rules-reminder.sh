#!/usr/bin/env bash
# prompt-rules-reminder.sh（UserPromptSubmit hook）のテスト。
# JSON を stdin に流し、キーワードごとに正しい Reminder 行が出ること・
# 誤マッチしないこと・常に exit 0 であることを検証する。要 bash + jq。
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$TESTS_DIR/../hooks/prompt-rules-reminder.sh"
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq がないためテストを実行できない"; exit 1; }

pass=0
fail=0

DESIGN_LINE="Reminder: 設計ドキュメント・実装計画を書くときは"
CODEX_LINE="Reminder: Codex への実装委譲タスクでは"

run_hook() { # $1=prompt 文字列（jq で JSON 化して渡す）
  OUTPUT="$(jq -n --arg p "$1" '{prompt: $p}' | "$HOOK" 2>&1)"
  EXIT_CODE=$?
}

run_hook_raw() { # $1=stdin にそのまま流す生データ
  OUTPUT="$(printf '%s' "$1" | "$HOOK" 2>&1)"
  EXIT_CODE=$?
}

assert_contains() { # $1=テスト名 $2=期待する部分文字列
  if printf '%s' "$OUTPUT" | grep -qF -- "$2"; then
    echo "ok   - $1"
    pass=$((pass + 1))
  else
    echo "FAIL - $1"
    echo "  期待: $2"
    printf '%s\n' "$OUTPUT" | sed 's/^/  出力: /'
    fail=$((fail + 1))
  fi
}

assert_not_contains() { # $1=テスト名 $2=含まれてはいけない部分文字列
  if printf '%s' "$OUTPUT" | grep -qF -- "$2"; then
    echo "FAIL - $1"
    echo "  含まれてはいけない: $2"
    printf '%s\n' "$OUTPUT" | sed 's/^/  出力: /'
    fail=$((fail + 1))
  else
    echo "ok   - $1"
    pass=$((pass + 1))
  fi
}

assert_empty_output() { # $1=テスト名
  if [ -z "$OUTPUT" ]; then
    echo "ok   - $1 (無出力)"
    pass=$((pass + 1))
  else
    echo "FAIL - $1 (出力が空でない)"
    printf '%s\n' "$OUTPUT" | sed 's/^/  出力: /'
    fail=$((fail + 1))
  fi
}

assert_exit_zero() { # $1=テスト名
  if [ "$EXIT_CODE" -eq 0 ]; then
    echo "ok   - $1 (exit 0)"
    pass=$((pass + 1))
  else
    echo "FAIL - $1 (exit $EXIT_CODE)"
    fail=$((fail + 1))
  fi
}

# --- ケース1: 日本語の設計キーワード → 設計 Reminder のみ ---------------------
run_hook "この機能の設計を考えたい"
assert_contains "日本語設計: 設計 Reminder" "$DESIGN_LINE"
assert_not_contains "日本語設計: Codex Reminder は出ない" "$CODEX_LINE"
assert_exit_zero "日本語設計"

# --- ケース2: 英語の設計キーワード（単語一致）→ 設計 Reminder のみ -----------
run_hook "Let's plan the new feature"
assert_contains "英語設計: 設計 Reminder" "$DESIGN_LINE"
assert_not_contains "英語設計: Codex Reminder は出ない" "$CODEX_LINE"
assert_exit_zero "英語設計"

# --- ケース3: "explain" は "plan" に誤マッチしない → 無出力 -------------------
run_hook "Please explain this function"
assert_empty_output "explain誤マッチ防止"
assert_exit_zero "explain誤マッチ防止"

# --- ケース4: 委譲キーワード → Codex Reminder のみ ---------------------------
run_hook "Codex にやらせて"
assert_contains "委譲: Codex Reminder" "$CODEX_LINE"
assert_not_contains "委譲: 設計 Reminder は出ない" "$DESIGN_LINE"
assert_exit_zero "委譲"

# --- ケース5: 委譲キーワードは大文字小文字を区別しない ------------------------
run_hook "use HERDR for this"
assert_contains "委譲大文字: Codex Reminder" "$CODEX_LINE"
assert_exit_zero "委譲大文字"

# --- ケース6: 設計 + 委譲の両方 → 2 行とも出る --------------------------------
run_hook "herdr 経由で実装を委譲して"
assert_contains "両方: 設計 Reminder" "$DESIGN_LINE"
assert_contains "両方: Codex Reminder" "$CODEX_LINE"
assert_exit_zero "両方"

# --- ケース7: キーワードなし → 無出力 -----------------------------------------
run_hook "今日の天気は？"
assert_empty_output "キーワードなし"
assert_exit_zero "キーワードなし"

# --- ケース8: stdin が空 → 無出力・exit 0 ------------------------------------
run_hook_raw ""
assert_empty_output "stdin空"
assert_exit_zero "stdin空"

# --- ケース9: stdin が JSON でない → 無出力・exit 0 ---------------------------
run_hook_raw "not json at all"
assert_empty_output "非JSON"
assert_exit_zero "非JSON"

# --- ケース10: prompt キーがない JSON → 無出力・exit 0 -----------------------
run_hook_raw '{"other": "設計"}'
assert_empty_output "promptキーなし"
assert_exit_zero "promptキーなし"

# --- 結果 --------------------------------------------------------------------
echo ""
echo "結果: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
