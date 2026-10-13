#!/usr/bin/env bash
# workflow.md の節番号参照（§N / §N.M）のテスト。workflow.md 内の §参照と、
# 同じディレクトリの他ファイル内の「workflow.md §N」参照が、workflow.md の
# 見出し（## N. / ### N.M）に実在するかを確かめる。§9-5 のような項目番号付きの
# 参照は節（§9）の存在だけを見る。要 bash + grep + sed。
set -u
# glob 順・sort 順・grep のバイト一致を環境によらず揃える
export LC_ALL=C

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$TESTS_DIR/../skills/delegating-to-codex"
FIXTURE_DIR="$TESTS_DIR/fixtures/section-refs"

pass=0
fail=0

# workflow.md の見出しから節番号を1行ずつ出す（"## 9. ..." → 9、"### 13.1 ..." → 13.1）
section_numbers() { # $1=workflow.md のパス
  grep -E '^#{2,3} [0-9]+(\.[0-9]+)?\.? ' "$1" \
    | sed -E 's/^#{2,3} ([0-9]+(\.[0-9]+)?)\.? .*/\1/'
}

# ファイル中の workflow.md への §参照から節番号を重複なしで出す
# （workflow.md 自身は §N すべて、他のファイルは「workflow.md §N」の形だけ）
referenced_numbers() { # $1=ファイルのパス
  if [ "$(basename "$1")" = "workflow.md" ]; then
    grep -oE '§[0-9]+(\.[0-9]+)?' "$1"
  else
    grep -oE 'workflow\.md ?§[0-9]+(\.[0-9]+)?' "$1" | sed -E 's/^workflow\.md ?//'
  fi | sed 's/^§//' | sort -u
}

# ディレクトリ内で、存在しない節を指す参照を「ファイル名: §番号」で1行ずつ出す
dangling_refs() { # $1=workflow.md を含むディレクトリ
  local dir="$1" sections f num
  sections="$(section_numbers "$dir/workflow.md")"
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    referenced_numbers "$f" | while read -r num; do
      printf '%s\n' "$sections" | grep -qxF "$num" \
        || printf '%s: §%s\n' "$(basename "$f")" "$num"
    done
  done
}

assert_eq() { # $1=テスト名 $2=期待値 $3=実際の値
  if [ "$2" = "$3" ]; then
    echo "ok   - $1"
    pass=$((pass + 1))
  else
    echo "FAIL - $1"
    printf '%s\n' "$2" | sed 's/^/  期待: /'
    printf '%s\n' "$3" | sed 's/^/  実際: /'
    fail=$((fail + 1))
  fi
}

assert_at_least() { # $1=テスト名 $2=下限 $3=実際の値
  if [ "$3" -ge "$2" ]; then
    echo "ok   - $1"
    pass=$((pass + 1))
  else
    echo "FAIL - $1"
    echo "  期待: $2 以上"
    echo "  実際: $3"
    fail=$((fail + 1))
  fi
}

# --- ケース1: 実ファイルのパース健全性（見出し形式が変わって空振りしないこと） ---
assert_at_least "実ファイル: 節を 20 個以上認識する" 20 \
  "$(section_numbers "$SKILL_DIR/workflow.md" | wc -l | tr -d ' ')"
assert_at_least "実ファイル: workflow.md 内の §参照を 5 種類以上拾う" 5 \
  "$(referenced_numbers "$SKILL_DIR/workflow.md" | wc -l | tr -d ' ')"

# --- ケース2: 実ファイルに存在しない節への参照がない ---------------------------
assert_eq "実ファイル: §参照はすべて実在する節を指す" "" \
  "$(dangling_refs "$SKILL_DIR")"

# --- ケース3: fixture の節番号一覧（両方の見出し形式・コードフェンス内は対象外） ---
assert_eq "fixture: 節番号を正しく抜き出す" "$(printf '1\n2\n2.1\n3')" \
  "$(section_numbers "$FIXTURE_DIR/workflow.md")"

# --- ケース4: fixture の壊れた参照だけを検出する --------------------------------
assert_eq "fixture: 存在しない節への参照だけを検出する" \
  "$(printf 'SKILL.md: §42\nworkflow.md: §2.9\nworkflow.md: §99')" \
  "$(dangling_refs "$FIXTURE_DIR")"

# --- 結果 --------------------------------------------------------------------
echo ""
echo "結果: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
