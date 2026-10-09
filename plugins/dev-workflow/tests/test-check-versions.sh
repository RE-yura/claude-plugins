#!/usr/bin/env bash
# check-versions.sh のテスト。スタブの herdr / codex と fixture の versions.json を
# 組み合わせ、OK / WARN / MISSING の各経路と exit code を検証する。
# 実物の herdr / codex は不要（CI でも走る）。要 bash + jq。
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECKER_SRC="$TESTS_DIR/../skills/delegating-to-codex/check-versions.sh"
REAL_JQ="$(command -v jq)" || { echo "SKIP: jq がないためテストを実行できない"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

# herdr 0.9.0 の `herdr status` 出力を模す。$1=client ver $2=server ver $3=compatible(yes|no)
# server ver に "-" を渡すと server 未起動の出力にする。
status_block() {
  if [ "$2" = "-" ]; then
    printf 'client:\n  version: %s\n  channel: stable\n  protocol: 22\n\nserver:\n  status: not running\n  socket: /tmp/herdr.sock\n' "$1"
  else
    printf 'client:\n  version: %s\n  channel: stable\n  protocol: 22\n\nserver:\n  status: running\n  version: %s\n  endpoint_compatible: %s\n  private_protocol: 22\n  private_protocol_compatible: %s\n  socket: /tmp/herdr.sock\n\nupdate:\n  restart_needed: no\n' "$1" "$2" "$3" "$3"
  fi
}

# --- スタブ環境の構築 -------------------------------------------------------
# stub bin には jq と、ケースごとに herdr / codex を置く。
# superpowers はスタブ HOME のプラグインキャッシュディレクトリで擬似する。
# herdr スタブは `herdr status` にも応答する。$4 を省略すると client と同じ
# バージョンの server が running・互換ありの status を返す（正常系）。
setup_env() { # $1=herdr出力("-"で未導入) $2=codex出力("-") $3=superpowersバージョン("-") [$4=herdr status 出力]
  ENV_DIR="$TMP/case-$((pass + fail))"
  mkdir -p "$ENV_DIR/bin" "$ENV_DIR/home"
  ln -s "$REAL_JQ" "$ENV_DIR/bin/jq"
  cp "$CHECKER_SRC" "$ENV_DIR/check-versions.sh"
  cp "$TESTS_DIR/fixtures/versions.json" "$ENV_DIR/versions.json"
  if [ "$1" != "-" ]; then
    local ver status_out
    ver="$(printf '%s' "$1" | awk '{print $2}')"
    status_out="${4:-$(status_block "$ver" "$ver" yes)}"
    {
      printf '#!/bin/sh\n'
      printf 'if [ "$1" = "status" ]; then\n'
      printf "  cat <<'EOF'\n%s\nEOF\n" "$status_out"
      printf 'else\n  echo "%s"\nfi\n' "$1"
    } > "$ENV_DIR/bin/herdr"
    chmod +x "$ENV_DIR/bin/herdr"
  fi
  if [ "$2" != "-" ]; then
    printf '#!/bin/sh\necho "%s"\n' "$2" > "$ENV_DIR/bin/codex"
    chmod +x "$ENV_DIR/bin/codex"
  fi
  if [ "$3" != "-" ]; then
    mkdir -p "$ENV_DIR/home/.claude/plugins/cache/official/superpowers/$3"
  fi
}

run_checker() { # $@=checker への引数
  OUTPUT="$(PATH="$ENV_DIR/bin:/usr/bin:/bin" HOME="$ENV_DIR/home" "$ENV_DIR/check-versions.sh" "$@" 2>&1)"
  EXIT_CODE=$?
}

add_claude_stub() { # $1=claude --version の出力。setup_env の後に呼ぶ
  printf '#!/bin/sh\necho "%s"\n' "$1" > "$ENV_DIR/bin/claude"
  chmod +x "$ENV_DIR/bin/claude"
}

assert_contains() { # $1=テスト名 $2=期待する部分文字列
  if printf '%s' "$OUTPUT" | grep -qF "$2"; then
    echo "ok   - $1"
    pass=$((pass + 1))
  else
    echo "FAIL - $1"
    echo "  期待: $2"
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

assert_not_contains() { # $1=テスト名 $2=含まれてはいけない部分文字列
  if printf '%s' "$OUTPUT" | grep -qF "$2"; then
    echo "FAIL - $1"
    echo "  含まれてはいけない: $2"
    fail=$((fail + 1))
  else
    echo "ok   - $1"
    pass=$((pass + 1))
  fi
}

# fixture: verified herdr 0.8.0 (same-minor) / codex 0.145.0 (minimum 0.144.0) /
#          superpowers 6.3.0 (same-major)。実物の versions.json とは独立
#          （実物を更新してもテストの期待値が壊れないよう固定する）。

# --- ケース1: すべて検証済みと一致 → 全 OK ---------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
run_checker
assert_contains "全一致: herdr OK" "OK      herdr 0.8.0"
assert_contains "全一致: codex OK" "OK      codex-cli 0.145.0（minimum 0.144.0 以上・検証済み 0.145.0 と same-minor）"
assert_contains "全一致: superpowers OK" "OK      superpowers 6.3.0"
assert_contains "全一致: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "全一致"

# --- ケース2: patch のみズレ（実運用で最頻）→ 全 OK -------------------------
setup_env "herdr 0.8.2" "codex-cli 0.145.9" "6.4.1"
run_checker
assert_contains "patchズレ: herdr same-minor OK" "OK      herdr 0.8.2"
assert_contains "patchズレ: superpowers same-major OK" "OK      superpowers 6.4.1"
assert_contains "patchズレ: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "patchズレ"

# --- ケース3: herdr の minor ズレ → WARN + 次アクション ---------------------
setup_env "herdr 0.9.1" "codex-cli 0.145.0" "6.3.0"
run_checker
assert_contains "herdr minorズレ: WARN" "WARN    herdr 0.9.1"
assert_contains "herdr minorズレ: 次アクション" "herdr --skill と各コマンドの usage を workflow.md と突き合わせてから進むこと"
assert_contains "herdr minorズレ: 件数表示" "1 件の WARN/MISSING"
assert_exit_zero "herdr minorズレ"

# --- ケース4: codex が minimum 未満 → WARN ----------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.143.0" "6.3.0"
run_checker
assert_contains "codex minimum未満: WARN" "WARN    codex-cli 0.143.0 — minimum 0.144.0 未満"
assert_contains "codex minimum未満: 次アクション" "codex features enable goals"
assert_exit_zero "codex minimum未満"

# --- ケース5: codex が minimum 以上・minor 違い → 注意付き OK ---------------
setup_env "herdr 0.8.0" "codex-cli 0.146.0" "6.3.0"
run_checker
assert_contains "codex minor先行: 注意付き OK" "OK      codex-cli 0.146.0（minimum 0.144.0 以上。ただし検証済み 0.145.0 と minor が異なる"
assert_contains "codex minor先行: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "codex minor先行"

# --- ケース6: superpowers の major ズレ → WARN ------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "7.0.0"
run_checker
assert_contains "superpowers majorズレ: WARN" "WARN    superpowers 7.0.0"
assert_contains "superpowers majorズレ: 次アクション" "brainstorming / writing-plans スキルの名前・挙動が変わっていないか"
assert_exit_zero "superpowers majorズレ"

# --- ケース7: superpowers 複数バージョンキャッシュ → 最新を採用 -------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
mkdir -p "$ENV_DIR/home/.claude/plugins/cache/official/superpowers/6.2.0"
run_checker
assert_contains "superpowers複数: 最新版を採用" "OK      superpowers 6.3.0"
assert_exit_zero "superpowers複数"

# --- ケース8: 全ツール未導入 → MISSING ×3 -----------------------------------
setup_env "-" "-" "-"
run_checker
assert_contains "未導入: herdr MISSING" "MISSING herdr"
assert_contains "未導入: codex MISSING" "MISSING codex"
assert_contains "未導入: superpowers MISSING" "MISSING superpowers"
assert_contains "未導入: 件数表示" "3 件の WARN/MISSING"
assert_exit_zero "未導入"

# --- ケース9: jq 未導入 → 早期 MISSING（他チェックはしない） ----------------
# bash と dirname だけを持つ PATH を作る（/usr/bin を含めると Linux では
# /usr/bin/jq が見つかってしまうため、必要コマンドを個別に symlink する）
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
NOJQ_BIN="$ENV_DIR/nojq-bin"
mkdir -p "$NOJQ_BIN"
ln -s "$(command -v bash)" "$NOJQ_BIN/bash"
ln -s "$(command -v dirname)" "$NOJQ_BIN/dirname"
OUTPUT="$(PATH="$NOJQ_BIN" HOME="$ENV_DIR/home" "$ENV_DIR/check-versions.sh" 2>&1)"
EXIT_CODE=$?
assert_contains "jq未導入: MISSING" "MISSING jq"
assert_exit_zero "jq未導入"

# --- ケース10: バージョン出力形式の変化（2列目が無い）→ WARN（取得失敗） ----
setup_env "herdr" "codex-cli 0.145.0" "6.3.0"
run_checker
assert_contains "herdr出力形式変化: WARN" "WARN    herdr — バージョンを取得できない"
assert_exit_zero "herdr出力形式変化"

# --- ケース11: --quiet + 全 OK → 完全に無出力 --------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
run_checker --quiet
assert_empty_output "quiet全OK: 無出力"
assert_exit_zero "quiet全OK"

# --- ケース12: -q + WARN あり → WARN 行と結論行のみ --------------------------
setup_env "herdr 0.9.1" "codex-cli 0.145.0" "6.3.0"
run_checker -q
assert_contains "quietWARN: WARN 行は出る" "WARN    herdr 0.9.1"
assert_contains "quietWARN: 結論行は出る" "1 件の WARN/MISSING"
assert_not_contains "quietWARN: OK 行は出ない" "OK      "
assert_not_contains "quietWARN: ヘッダ行は出ない" "依存バージョンチェック"
assert_exit_zero "quietWARN"

# --- ケース13: 不明な引数 → usage を出して exit 2 ----------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
run_checker --bogus
assert_contains "不明引数: usage" "usage: check-versions.sh"
if [ "$EXIT_CODE" -eq 2 ]; then
  echo "ok   - 不明引数 (exit 2)"
  pass=$((pass + 1))
else
  echo "FAIL - 不明引数 (exit $EXIT_CODE, 期待 2)"
  fail=$((fail + 1))
fi

# --- ケース14: versions.json 欠如 → MISSING（set -u クラッシュの回帰テスト） --
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
rm "$ENV_DIR/versions.json"
run_checker
assert_contains "manifest欠如: MISSING" "MISSING versions.json"
assert_exit_zero "manifest欠如"

# --- ケース15: client と server が一致 → OK 行 -------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
run_checker
assert_contains "server一致: OK" "OK      herdr server 0.8.0 running（client と一致）"
assert_contains "server一致: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "server一致"

# --- ケース16: 旧 client が PATH に残り server と protocol 不一致 → WARN -----
# （0.8.2→0.9.0 で実測。herdr --version だけ見ると same-minor OK で通ってしまう）
setup_env "herdr 0.8.2" "codex-cli 0.145.0" "6.3.0" "$(status_block 0.8.2 0.9.0 no)"
run_checker
assert_contains "protocol不一致: herdr 自体は OK" "OK      herdr 0.8.2"
assert_contains "protocol不一致: WARN" "WARN    herdr client 0.8.2 / server 0.9.0 — protocol が不一致"
assert_contains "protocol不一致: 次アクション" "新しいシェルを開くか mise shims の herdr を使い"
assert_contains "protocol不一致: 件数表示" "1 件の WARN/MISSING"
assert_exit_zero "protocol不一致"

# --- ケース17: 0.8.2 client の旧形式 status（compatible: no）も検出する -------
OLD_STATUS="$(printf 'client:\n  version: 0.8.2\n  channel: stable\n  protocol: 20\n\nserver:\n  status: running\n  version: 0.9.0\n  protocol: 22\n  compatible: no\n  socket: /tmp/herdr.sock\n\nupdate:\n  restart_needed: yes\n')"
setup_env "herdr 0.8.2" "codex-cli 0.145.0" "6.3.0" "$OLD_STATUS"
run_checker
assert_contains "旧形式status: WARN" "WARN    herdr client 0.8.2 / server 0.9.0 — protocol が不一致"
assert_exit_zero "旧形式status"

# --- ケース18: protocol 互換だが version が異なる → WARN（再起動を促す） ------
setup_env "herdr 0.8.2" "codex-cli 0.145.0" "6.3.0" "$(status_block 0.8.2 0.8.0 yes)"
run_checker
assert_contains "version差: WARN" "WARN    herdr client 0.8.2 / server 0.8.0 — バージョンが異なる（protocol は互換）"
assert_exit_zero "version差"

# --- ケース19: server 未起動 → WARN -------------------------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0" "$(status_block 0.8.0 - yes)"
run_checker
assert_contains "server未起動: WARN" "WARN    herdr server が起動していない（herdr status: not running）"
assert_exit_zero "server未起動"

# --- ケース20: --quiet + protocol 不一致 → WARN 行は出る ----------------------
setup_env "herdr 0.8.2" "codex-cli 0.145.0" "6.3.0" "$(status_block 0.8.2 0.9.0 no)"
run_checker --quiet
assert_contains "quiet不一致: WARN 行は出る" "protocol が不一致"
assert_not_contains "quiet不一致: OK 行は出ない" "OK      "
assert_exit_zero "quiet不一致"

# --- ケース21: claude が検証済みと same-minor → OK ---------------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
add_claude_stub "2.1.281 (Claude Code)"
run_checker
assert_contains "claude same-minor: OK" "OK      claude 2.1.281（検証済み 2.1.200 と same-minor）"
assert_contains "claude same-minor: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "claude same-minor"

# --- ケース22: claude の minor 違い → 注意付き OK（WARN にしない） -----------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
add_claude_stub "2.2.0 (Claude Code)"
run_checker
assert_contains "claude minor違い: 注意付き OK" "OK      claude 2.2.0（検証済み 2.1.200 と minor が異なる"
assert_contains "claude minor違い: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "claude minor違い"

# --- ケース23: claude 未導入 → INFO のみ（件数に数えない） -------------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
run_checker
assert_contains "claude未導入: INFO" "INFO    claude — 見つからない"
assert_contains "claude未導入: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "claude未導入"

# --- ケース24: claude --version の形式変化 → INFO（件数に数えない） ----------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
add_claude_stub "Claude Code"
run_checker
assert_contains "claude形式変化: INFO" "INFO    claude — バージョンを取得できない"
assert_contains "claude形式変化: 続行メッセージ" "すべて許容範囲"
assert_exit_zero "claude形式変化"

# --- ケース25: --quiet + claude 導入済み全 OK → 完全に無出力 -----------------
setup_env "herdr 0.8.0" "codex-cli 0.145.0" "6.3.0"
add_claude_stub "2.1.281 (Claude Code)"
run_checker --quiet
assert_empty_output "quiet claude: 無出力"
assert_exit_zero "quiet claude"

# --- 結果 --------------------------------------------------------------------
echo ""
echo "結果: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
