#!/usr/bin/env bash
# dev-workflow: 委譲ワークフローの外部依存を versions.json の検証済み値と突き合わせる。
# 委譲開始前の Step 0 として実行する。常に exit 0（警告であってブロックではない）。
# WARN が出た場合は、止まるのではなく指示された確認（herdr --skill / usage 照合）を
# してから進むこと。
set -u

QUIET=0
case "${1:-}" in
  "") ;;
  --quiet|-q) QUIET=1 ;;
  *)
    echo "usage: check-versions.sh [--quiet|-q]" >&2
    exit 2
    ;;
esac

DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$DIR/versions.json"

# major.minor.patch を数値比較する（$1 >= $2 なら 0）
version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

major_minor() { echo "$1" | cut -d. -f1-2; }
major_of()    { echo "$1" | cut -d. -f1; }

# OK 行・ヘッダ行・全OK時の結論行に使う。quiet では出さない。
# WARN / MISSING と件数付き結論行は素の echo のまま（quiet でも出す）。
say() { [ "$QUIET" -eq 1 ] || echo "$@"; }

if ! command -v jq >/dev/null 2>&1; then
  echo "MISSING jq — versions.json をパースできないためチェックを中断。jq を導入して再実行すること（brew install jq）"
  exit 0
fi

if [ ! -f "$MANIFEST" ]; then
  echo "MISSING versions.json（${MANIFEST}）— プラグインの導入が壊れている可能性"
  exit 0
fi

VERIFIED_AT=$(jq -r '.verified_at' "$MANIFEST")
warn_count=0

say "[dev-workflow] 依存バージョンチェック（versions.json: ${VERIFIED_AT} 検証）"

# --- herdr: same-minor ---
HERDR_VERIFIED=$(jq -r '.dependencies.herdr.verified' "$MANIFEST")
if command -v herdr >/dev/null 2>&1; then
  herdr_ver=$(herdr --version 2>/dev/null | awk '{print $2}')
  if [ -z "$herdr_ver" ]; then
    echo "WARN    herdr — バージョンを取得できない（herdr --version の出力形式が変わった可能性。検証済みは ${HERDR_VERIFIED}）"
    warn_count=$((warn_count + 1))
  elif [ "$(major_minor "$herdr_ver")" = "$(major_minor "$HERDR_VERIFIED")" ]; then
    say "OK      herdr ${herdr_ver}（検証済み ${HERDR_VERIFIED} と same-minor 一致）"
  else
    echo "WARN    herdr ${herdr_ver} — 検証済み ${HERDR_VERIFIED} と minor が異なる。CLI が破壊的に変わっている可能性が高い（0.7.4→0.7.5→0.8.0 で実証）。herdr --skill と各コマンドの usage を workflow.md と突き合わせてから進むこと"
    warn_count=$((warn_count + 1))
  fi

  # --- herdr client/server 整合 ---
  # herdr --version は PATH 上の client しか見ない。0.9.0 で protocol が 20→22 に
  # 上がった際、mise で入れ替えた後も既存シェルの PATH に旧 client が残り、
  # agent/workspace 系が全て protocol_mismatch（exit 0 の JSON エラー）になった（実測）。
  # herdr status の server セクションを見て検出する。
  if [ -n "$herdr_ver" ]; then
    status_out=$(herdr status 2>/dev/null)
    server_status=$(printf '%s\n' "$status_out" | awk '/^server:/{s=1; next} /^[^ ]/{s=0} s && $1=="status:"{sub(/^ *status: */, ""); print}')
    server_ver=$(printf '%s\n' "$status_out" | awk '/^server:/{s=1; next} /^[^ ]/{s=0} s && $1=="version:"{print $2}')
    if [ "$server_status" = "running" ]; then
      if printf '%s\n' "$status_out" | grep -Eq '^ *[a-z_]*compatible: *no'; then
        echo "WARN    herdr client ${herdr_ver} / server ${server_ver:-?} — protocol が不一致（herdr status: compatible: no）。この状態では herdr agent/workspace 系が全て protocol_mismatch エラー（exit 0 の JSON）になる。新しいシェルを開くか mise shims の herdr を使い、client を server に揃えてから進むこと"
        warn_count=$((warn_count + 1))
      elif [ -n "$server_ver" ] && [ "$server_ver" != "$herdr_ver" ]; then
        echo "WARN    herdr client ${herdr_ver} / server ${server_ver} — バージョンが異なる（protocol は互換）。新機能や挙動差は server 側に依存する。herdr status の update 行を確認し、必要なら herdr を再起動して揃えること"
        warn_count=$((warn_count + 1))
      else
        say "OK      herdr server ${server_ver:-?} running（client と一致）"
      fi
    else
      echo "WARN    herdr server が起動していない（herdr status: ${server_status:-取得不可}）。委譲ワークフローは server の socket API 経由で動くため、herdr を起動してから進むこと"
      warn_count=$((warn_count + 1))
    fi
  fi
else
  echo "MISSING herdr — 委譲ワークフローは実行できない（https://herdr.dev、導入後 herdr integration install codex）"
  warn_count=$((warn_count + 1))
fi

# --- codex: minimum ---
CODEX_VERIFIED=$(jq -r '.dependencies.codex.verified' "$MANIFEST")
CODEX_MINIMUM=$(jq -r '.dependencies.codex.minimum' "$MANIFEST")
if command -v codex >/dev/null 2>&1; then
  codex_ver=$(codex --version 2>/dev/null | awk '{print $2}')
  if [ -z "$codex_ver" ]; then
    echo "WARN    codex — バージョンを取得できない（codex --version の出力形式が変わった可能性。検証済みは ${CODEX_VERIFIED}）"
    warn_count=$((warn_count + 1))
  elif version_ge "$codex_ver" "$CODEX_MINIMUM"; then
    if [ "$(major_minor "$codex_ver")" = "$(major_minor "$CODEX_VERIFIED")" ]; then
      say "OK      codex-cli ${codex_ver}（minimum ${CODEX_MINIMUM} 以上・検証済み ${CODEX_VERIFIED} と same-minor）"
    else
      say "OK      codex-cli ${codex_ver}（minimum ${CODEX_MINIMUM} 以上。ただし検証済み ${CODEX_VERIFIED} と minor が異なる — 起動時ダイアログ等の挙動差に注意。workflow.md §14）"
    fi
  else
    echo "WARN    codex-cli ${codex_ver} — minimum ${CODEX_MINIMUM} 未満。/goal が既定で使えない可能性（codex features enable goals を検討）"
    warn_count=$((warn_count + 1))
  fi
else
  echo "MISSING codex — 委譲ワークフローは実行できない（https://developers.openai.com/codex/cli）"
  warn_count=$((warn_count + 1))
fi

# --- superpowers: same-major（プラグインキャッシュから最新版を検出） ---
SP_VERIFIED=$(jq -r '.dependencies.superpowers.verified' "$MANIFEST")
sp_ver=$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers/*/ 2>/dev/null \
  | awk -F/ '{print $(NF-1)}' | grep -E '^[0-9]+\.[0-9]+' | sort -V | tail -n1)
if [ -n "$sp_ver" ]; then
  if [ "$(major_of "$sp_ver")" = "$(major_of "$SP_VERIFIED")" ]; then
    say "OK      superpowers ${sp_ver}（検証済み ${SP_VERIFIED} と same-major 一致）"
  else
    echo "WARN    superpowers ${sp_ver} — 検証済み ${SP_VERIFIED} と major が異なる。brainstorming / writing-plans スキルの名前・挙動が変わっていないか確認してから進むこと"
    warn_count=$((warn_count + 1))
  fi
else
  echo "MISSING superpowers — brainstorming / writing-plans が使えない（claude plugin install superpowers@claude-plugins-official）"
  warn_count=$((warn_count + 1))
fi

# --- claude (Claude Code CLI): info（報告のみ。warn_count は増やさない） ---
# hook の実行環境。頻繁に更新されるため WARN にはしない。CI や Claude Code 外から
# 実行した場合は存在しないのが正常なので、未導入も INFO 扱い。
CLAUDE_VERIFIED=$(jq -r '.dependencies.claude.verified' "$MANIFEST")
if command -v claude >/dev/null 2>&1; then
  claude_ver=$(claude --version 2>/dev/null | awk '{print $1}' | grep -E '^[0-9]+\.[0-9]+' || true)
  if [ -z "$claude_ver" ]; then
    say "INFO    claude — バージョンを取得できない（claude --version の出力形式が変わった可能性。検証済みは ${CLAUDE_VERIFIED}）"
  elif [ "$(major_minor "$claude_ver")" = "$(major_minor "$CLAUDE_VERIFIED")" ]; then
    say "OK      claude ${claude_ver}（検証済み ${CLAUDE_VERIFIED} と same-minor）"
  else
    say "OK      claude ${claude_ver}（検証済み ${CLAUDE_VERIFIED} と minor が異なる — hook（SessionStart / UserPromptSubmit）が発火しているか確認し、問題なければ versions.json を更新）"
  fi
else
  say "INFO    claude — 見つからない（Claude Code 外から実行している場合は無視してよい。検証済みは ${CLAUDE_VERIFIED}）"
fi

# --- jq: presence（この行に到達している時点で存在は確認済み） ---
say "OK      $(jq --version)"

if [ "$warn_count" -eq 0 ]; then
  say "→ すべて許容範囲。委譲ワークフローを続行してよい。"
else
  echo "→ ${warn_count} 件の WARN/MISSING。各行の指示に従って確認してから進むこと（このチェックはブロックしない）。"
fi
exit 0
