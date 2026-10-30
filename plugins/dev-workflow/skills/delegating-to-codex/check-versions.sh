#!/usr/bin/env bash
# dev-workflow: 委譲ワークフローの外部依存を versions.json の検証済み値と突き合わせる。
# 委譲開始前の Step 0 として実行する。常に exit 0（警告であってブロックではない）。
# WARN が出た場合は、止まるのではなく指示された確認（hc --skill / --help 照合）を
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

# --- hc: same-minor と稼働中 core の版 ---
HC_VERIFIED=$(jq -r '.dependencies.hc.verified' "$MANIFEST")
if command -v hc >/dev/null 2>&1; then
  hc_ver=$(hc --version 2>/dev/null | awk '{print $2}')
  if [ -z "$hc_ver" ]; then
    echo "WARN    hc — バージョンを取得できない（hc --version の出力形式が変わった可能性。検証済みは ${HC_VERIFIED}）"
    warn_count=$((warn_count + 1))
  else
    if [ "$(major_minor "$hc_ver")" = "$(major_minor "$HC_VERIFIED")" ]; then
      say "OK      hc ${hc_ver}（検証済み ${HC_VERIFIED} と same-minor 一致）"
    else
      echo "WARN    hc ${hc_ver} — 検証済み ${HC_VERIFIED} と minor が異なる。hc --skill と各コマンドの --help を workflow.md と突き合わせてから進むこと"
      warn_count=$((warn_count + 1))
    fi

    # CLI だけ更新されて core が古いままのケースも検出する。勝手に再起動しない。
    if core_status=$(hc server status --json 2>/dev/null) \
      && core_ver=$(printf '%s' "$core_status" | jq -er '.version | select(type == "string" and length > 0)' 2>/dev/null); then
      if [ "$core_ver" = "$hc_ver" ]; then
        say "OK      hc core ${core_ver} running（CLI と一致）"
      else
        echo "WARN    hc CLI ${hc_ver} / core ${core_ver} — バージョンが異なる。core の再起動はユーザーに確認してから（他のターミナルにも影響する）"
        warn_count=$((warn_count + 1))
      fi
    else
      echo "WARN    hc core に接続できない（hc server status --json）。接続先を確認してから進むこと。core の再起動はユーザーに確認してから"
      warn_count=$((warn_count + 1))
    fi
  fi
else
  echo "MISSING hc — 委譲ワークフローは実行できない（herdr-core を導入すること）"
  warn_count=$((warn_count + 1))
fi

# --- herdr-app: info（無くても委譲可能。見せ方が変わるだけ） ---
APP_VERIFIED=$(jq -r '.dependencies["herdr-app"].verified' "$MANIFEST")
if command -v herdr-app >/dev/null 2>&1; then
  app_ver=$(herdr-app --version 2>/dev/null | awk '{print $2}')
  if [ -n "$app_ver" ]; then
    say "OK      herdr-app ${app_ver}（検証済み ${APP_VERIFIED}。見せ方だけに使う任意のアプリ）"
  else
    say "INFO    herdr-app — バージョンを取得できない（検証済み ${APP_VERIFIED}。無くても委譲可能）"
  fi
else
  say "INFO    herdr-app — 見つからない（無くても委譲可能。hc attach で画面を見られる）"
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
      say "OK      codex-cli ${codex_ver}（minimum ${CODEX_MINIMUM} 以上。ただし検証済み ${CODEX_VERIFIED} と minor が異なる — 起動時ダイアログ等の挙動差に注意。workflow.md §9）"
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
    say "OK      claude ${claude_ver}（検証済み ${CLAUDE_VERIFIED} と minor が異なる — SessionStart hook が発火しているか確認し、問題なければ versions.json を更新）"
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
