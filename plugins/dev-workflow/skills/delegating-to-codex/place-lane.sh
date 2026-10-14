#!/usr/bin/env bash
# dev-workflow: Codex 用 workspace（レーン）を、サイドバーで委譲元 workspace の直下へ移す
# （疑似ツリー。workflow.md §6）。
#   usage: place-lane.sh <caller_workspace_id> <lane_workspace_id>
#
# サイドバーは worktree グループ（同じ repo_key の workspace の集まり）を、最初のメンバーの
# 位置にひとかたまりで描く（src/client/shell/sidebar.rs の workspace_entries）。グループに
# なる条件は herdr の版で違う:
#   0.9.3 まで: 2つ以上あり、linked でないものを含む
#   0.9.4 から: linked なものと linked でないものを両方含む（同じ repo を2回開いただけの
#               workspace は別々に描かれる。#4772）
# サイドバーを描くのは client なので、PATH の herdr（client）の版で選ぶ。版が取れなければ
# 新しい方の条件にする。グループに属さないレーンはその中に入れないので、移動先はこの
# 描画順で決める: 委譲元を含むかたまりの後ろ、さらに後ろに既存のレーン（ラベルが "└ " で
# 始まる行）が続いていればその後ろ。
#
# 並べ替えは CLI に無いので socket API の workspace.move_block を使う。
# 失敗しても exit 0（警告だけ出す。レーンが一番下に残るだけで、委譲は続けられる）。
set -u

CALLER="${1:?usage: place-lane.sh <caller_workspace_id> <lane_workspace_id>}"
LANE="${2:?usage: place-lane.sh <caller_workspace_id> <lane_workspace_id>}"
# herdr は管理下の pane に HERDR_SOCKET_PATH を渡す。無いときは既定のセッションの socket
SOCK="${HERDR_SOCKET_PATH:-$HOME/.config/herdr/herdr.sock}"

warn() {
  echo "warning: レーンを委譲元の直下へ移せなかった（$1）。サイドバーの一番下に残るが、委譲は続けてよい" >&2
  exit 0
}

LIST="$(herdr workspace list 2>/dev/null)" || warn "herdr workspace list に失敗"

HERDR_VER="$(herdr --version 2>/dev/null | awk '{print $2}')"
RULE=mixed
if [ -n "$HERDR_VER" ] \
  && [ "$(printf '%s\n%s\n' "$HERDR_VER" 0.9.4 | sort -V | head -n1)" != 0.9.4 ]; then
  RULE=count
fi

# 描画順のかたまり（emit = そのかたまりが描かれる位置の workspace）を作り、
# 委譲元を含むかたまりの次の、レーンでないかたまりを移動先にする
ANCHOR="$(printf '%s' "$LIST" | jq -r --arg c "$CALLER" --arg l "$LANE" --arg rule "$RULE" '
  [.result.workspaces[] | select(.workspace_id != $l)] as $w
  | ([$w[] | select(.worktree != null)] | group_by(.worktree.repo_key)
     | map(select(any(.[]; .worktree.is_linked_worktree == false)
                  and (if $rule == "count" then length >= 2
                       else any(.[]; .worktree.is_linked_worktree == true) end))
           | .[0].worktree.repo_key)) as $g
  | (reduce $w[] as $x ({seen: [], e: []};
      ($x.worktree.repo_key // "") as $k
      | if $k != "" and ($g | index($k)) != null then
          if (.seen | index($k)) != null then .
          else .seen += [$k]
            | .e += [{emit: $x.workspace_id, label: ($x.label // ""),
                      ids: [$w[] | select(.worktree.repo_key == $k) | .workspace_id]}]
          end
        else .e += [{emit: $x.workspace_id, label: ($x.label // ""), ids: [$x.workspace_id]}]
        end) | .e) as $e
  | ($e | map(.ids | index($c) != null) | index(true)) as $i
  | if $i == null then "NOT_FOUND"
    else ([$e[$i+1:][] | select(.label | startswith("└ ") | not)] | first | .emit) // ""
    end' 2>/dev/null)" || warn "herdr workspace list の応答を読めない（${LIST:0:120}）"

case "$ANCHOR" in
  NOT_FOUND)
    warn "委譲元 ${CALLER} が workspace list にない"
    ;;
  "")
    REQ="$(jq -nc --arg l "$LANE" \
      '{id: "lane_move", method: "workspace.move_block", params: {workspace_ids: [$l]}}')"
    ;;
  *)
    REQ="$(jq -nc --arg l "$LANE" --arg b "$ANCHOR" \
      '{id: "lane_move", method: "workspace.move_block",
        params: {workspace_ids: [$l], before_workspace_id: $b}}')"
    ;;
esac

# サーバーは1接続1リクエストで、JSON を1行返して閉じる。nc -U は macOS 標準の nc で動く
# （Linux の netcat-traditional には -U が無いので、その場合は socat 等に置き換える）
RESP="$(printf '%s\n' "$REQ" | nc -U -w 2 "$SOCK" 2>/dev/null)" || true
printf '%s' "$RESP" | jq -e '.result.type == "workspace_list"' >/dev/null 2>&1 \
  || warn "socket の応答: ${RESP:-なし}"
