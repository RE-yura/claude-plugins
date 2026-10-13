#!/usr/bin/env bash
# place-lane.sh のテスト。スタブの herdr（workspace list の応答を返す）と nc（送られた
# リクエストを記録し、決めた応答を返す）を使い、サイドバーの描画順に沿った移動先・
# 失敗時に委譲を止めないことを検証する。実物の herdr は不要。要 bash + jq。
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$TESTS_DIR/../skills/delegating-to-codex/place-lane.sh"
REAL_JQ="$(command -v jq)" || { echo "SKIP: jq がないためテストを実行できない"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
OK_RESP='{"id":"lane_move","result":{"type":"workspace_list","workspaces":[]}}'

# workspace list の JSON を作る。引数は "id:label:repo_key:linked"（repo_key が "-" なら worktree なし）
ws_json() {
  printf '%s\n' "$@" | "$REAL_JQ" -R 'split(":") | {workspace_id: .[0], label: .[1],
    worktree: (if .[2] == "-" then null else {repo_key: .[2], is_linked_worktree: (.[3] == "1")} end)}' \
    | "$REAL_JQ" -s '{id: "cli:workspace:list", result: {type: "workspace_list", workspaces: .}}'
}

# $1=workspace list の応答 $2=nc の応答 $3=caller $4=lane
run_case() {
  ENV_DIR="$TMP/case-$((pass + fail))"
  mkdir -p "$ENV_DIR/bin"
  ln -s "$REAL_JQ" "$ENV_DIR/bin/jq"
  printf '%s\n' "$1" > "$ENV_DIR/list.json"
  printf '%s\n' "$2" > "$ENV_DIR/resp.json"
  printf '#!/bin/sh\n[ "$1 $2" = "workspace list" ] && cat "%s/list.json"\n' "$ENV_DIR" > "$ENV_DIR/bin/herdr"
  printf '#!/bin/sh\ncat > "%s/req.json"\ncat "%s/resp.json"\n' "$ENV_DIR" "$ENV_DIR" > "$ENV_DIR/bin/nc"
  chmod +x "$ENV_DIR/bin/herdr" "$ENV_DIR/bin/nc"
  STDERR="$(PATH="$ENV_DIR/bin:/usr/bin:/bin" HERDR_SOCKET_PATH="$ENV_DIR/sock" "$SCRIPT" "$3" "$4" 2>&1 >/dev/null)"
  EXIT_CODE=$?
  REQ="$(cat "$ENV_DIR/req.json" 2>/dev/null)"
}

result() { # $1=テスト名 $2=条件の結果（0 なら ok） $3=失敗時の詳細
  if [ "$2" -eq 0 ]; then
    echo "ok   - $1"
    pass=$((pass + 1))
  else
    echo "FAIL - $1"
    printf '%s\n' "$3" | sed 's/^/  /'
    fail=$((fail + 1))
  fi
}

assert_anchor() { # $1=テスト名 $2=期待する before_workspace_id（"" なら末尾へ）
  local got
  got="$(printf '%s' "$REQ" | "$REAL_JQ" -r '.params.before_workspace_id // ""' 2>/dev/null)"
  [ "$(printf '%s' "$REQ" | "$REAL_JQ" -r '.method' 2>/dev/null)" = "workspace.move_block" ] \
    && [ "$got" = "$2" ] && [ "$EXIT_CODE" -eq 0 ] && [ -z "$STDERR" ]
  result "$1" $? "期待: before=$2 / 実際: before=$got exit=$EXIT_CODE stderr=$STDERR req=$REQ"
}

assert_no_move_warned() { # $1=テスト名
  [ -z "$REQ" ] && [ "$EXIT_CODE" -eq 0 ] && printf '%s' "$STDERR" | grep -q '^warning:'
  result "$1" $? "期待: 送信なし・warning・exit 0 / 実際: exit=$EXIT_CODE stderr=$STDERR req=$REQ"
}

# --- ケース1: 委譲元が真ん中 → 次の行の前へ ----------------------------------
run_case "$(ws_json A:a:-: B:b:-: C:c:-: L:'└ t':-:)" "$OK_RESP" B L
assert_anchor "真ん中の委譲元: 次の行の前" C

# --- ケース2: 委譲元が末尾 → 末尾へ（anchor なし） ------------------------------
run_case "$(ws_json A:a:-: B:b:-: L:'└ t':-:)" "$OK_RESP" B L
assert_anchor "末尾の委譲元: 末尾へ" ""

# --- ケース3: 委譲元の後ろに既存のレーンがある → その後ろへ ---------------------
run_case "$(ws_json A:a:-: B:b:-: L1:'└ one':-: L2:'└ two':-: C:c:-: L:'└ t':-:)" "$OK_RESP" B L
assert_anchor "既存のレーンの後ろ" C

# --- ケース4: 委譲元が worktree グループの親 → グループのかたまりの後ろ -----------
# 並び [A(親), X, C1(A の linked)] はサイドバーで A, C1, X と描かれる
run_case "$(ws_json A:a:k:0 X:x:-: C1:c1:k:1 L:'└ t':-:)" "$OK_RESP" A L
assert_anchor "グループの親: かたまりの後ろ（X の前）" X

# --- ケース5: 委譲元がグループの子 → グループのかたまりの後ろ --------------------
run_case "$(ws_json A:a:k:0 X:x:-: C1:c1:k:1 L:'└ t':-:)" "$OK_RESP" C1 L
assert_anchor "グループの子: かたまりの後ろ（X の前）" X

# --- ケース6: 次の行がグループ → そのかたまりが描かれる位置（最初のメンバー）の前 --
run_case "$(ws_json B:b:-: G1:g1:k:1 G0:g0:k:0 L:'└ t':-:)" "$OK_RESP" B L
assert_anchor "次がグループ: 最初のメンバーの前" G1

# --- ケース7: メンバーが1つだけの repo はグループにならない -----------------------
run_case "$(ws_json A:a:k:0 X:x:-: L:'└ t':-:)" "$OK_RESP" A L
assert_anchor "単独メンバー: グループ扱いしない" X

# --- ケース8: 委譲元が一覧にない → 送らずに警告・exit 0 ---------------------------
run_case "$(ws_json A:a:-: L:'└ t':-:)" "$OK_RESP" Z L
assert_no_move_warned "委譲元なし: 送らない"

# --- ケース9: herdr がエラー JSON（exit 0）を返す → 送らずに警告・exit 0 -----------
run_case '{"id":"x","error":{"code":"protocol_mismatch","message":"m"}}' "$OK_RESP" A L
assert_no_move_warned "herdr エラー: 送らない"

# --- ケース10: socket の応答がエラー → 警告・exit 0 -------------------------------
run_case "$(ws_json A:a:-: B:b:-: L:'└ t':-:)" '{"id":"lane_move","error":{"code":"invalid_params"}}' A L
[ -n "$REQ" ] && [ "$EXIT_CODE" -eq 0 ] && printf '%s' "$STDERR" | grep -q '^warning:'
result "socket エラー: 警告して続行" $? "exit=$EXIT_CODE stderr=$STDERR"

# --- 結果 --------------------------------------------------------------------
echo ""
echo "結果: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
