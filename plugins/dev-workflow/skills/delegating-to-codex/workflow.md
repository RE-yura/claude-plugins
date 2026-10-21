# Claude Code Operating Procedure: Codex Delegation via Herdr + `/goal`

この文書は、Claude Code が詳細な実装計画を作成し、Herdr 経由で Codex CLI の `/goal` に実装を委譲し、Claude Code がレビューし、必要に応じて Codex に修正を繰り返させるための運用手順である。

Claude Code は、この文書を「実装委譲ワークフローの実行規約」として扱うこと。

> 検証済み環境の正は同ディレクトリの [versions.json](versions.json)（herdr 0.9.4 / codex-cli 0.160.0 / superpowers 6.4.1 / Claude Code 2.1.300、2026-10-15 実機再検証・E2E 委譲一巡。過去: 0.9.3 / 0.9.1 / 0.9.0 / 0.8.2 / 0.8.0 / 0.7.5 / 0.7.1）。委譲開始前に必ず `check-versions.sh` を実行し、実機バージョンとのズレを検出すること（§5）。herdr の CLI はバージョンで大きく変わる（実例: 0.7.5 で `agent start` の署名変更・トップレベル `wait` 廃止・`agent prompt` 追加。0.8.0 で `prompt --wait` が主経路化・`--json` 廃止（JSON がデフォルト）・idle alternate-screen の自動履歴読み。0.9.0 は本書が使うコマンドの引数・出力は不変だが、`prompt --wait` の stalled 判定が厳密化（§2.3）、`workspace close --group` 追加（§17）、worktree 系に `--trust-repository` 追加、`--no-session` 廃止、client/server の protocol が 20→22 で分離・`herdr status` の出力キー変更。0.9.1 は SSH マシン操作・Windows・UI 中心で本書のコマンドは不変。Codex の状態検出が改善（入力欄の装飾で idle を blocked と誤判定しない #4092/#4099）、`worktree create --no-focus` は引き続き尊重される。0.9.3 は本書が使うコマンドの引数は不変。0.9.4 も引数は不変だが、Codex が応答後に unknown のまま残らなくなり（タイトルに spinner がなければ idle）、`--no-daemon` で起動した Codex は hook でターンの開始・終了を報告するようになった。サイドバーの worktree グループの条件も変わった（§6）。**2026-10-15 追記（skill 1.6.0 / plugin 1.7.0）: Codex は `--no-daemon` で起動する**（§9）。**2026-10-13 改訂: Codex レーンは `herdr worktree create` ではなく `git worktree add` + 委譲元 workspace の直下に置く専用 workspace（疑似ツリー。skill 1.5.0 / plugin 1.6.0 で、同日導入のタブ方式から変更）に作る**（herdr の worktree グループはリポジトリ単位で親を選び、同じリポジトリの workspace が複数あると委譲元とは別の workspace の下に表示されるため。§6）。**2026-10-13 追記（skill 1.4.1 / plugin 1.5.1）: 完了待ちは状態だけで抜け（Codex は応答後に unknown のまま残ることがあるので `--until unknown` も足す）、marker は Codex の折り返しで割れても拾える方法で探す**（marker が1行で出るまで回るループが終わらず、完了に約4時間気付かなかったため。§2.3・§10））。動かない場合はまず引数なし実行で usage を確認し、`herdr --skill`（0.8.0+、同梱の公式エージェント向け説明）と公式 https://herdr.dev/docs/agent-automation/ に突き合わせること。ただし **`herdr worktree create` は引数なしでも既定値で即実行される**ので（本流では使わないが）usage 確認目的で叩かないこと（0.7.4 実測。§17.1）。

---

## 1. 目的

Claude Code と Codex の役割を分離する。

```text
Claude Code = 設計者・計画作成者・レビュアー・承認者
Codex CLI   = 実装担当・テスト実行担当・修正担当
Herdr       = 委譲元 workspace の直下に Codex 用 workspace を用意し、agent の起動・入力送信・進捗可視化・状態検知を行う
Git worktree = Codex が安全に編集する隔離された作業領域（git worktree add で作る。herdr の worktree 機能は使わない）
Task files  = Claude Code ↔ Codex 間の契約・状態・成果物
```

このワークフローのゴールは、Codex の画面出力をその場限りで読むことではない。`PLAN.md`、`CODEX_GOAL.md`、`PROGRESS.md`、`CODEX_DONE.md`、`REVIEW-N.md`、`FIX-N.md`、`git diff` を残し、Claude Code が確実にレビュー・修正指示・承認を行える状態にすることである。

---

## 2. 基本方針

### 2.1 Herdr の使い分け

Claude Code は、原則として次の順で Herdr を使う。

```text
第一選択: herdr agent ...
  Codex を名前付き agent として扱う。
  start / get / read / wait / prompt / send-keys / focus / rename に使う。
  ターゲットは agent 名と、agent が居る pane の id。

補助: herdr pane ...
  pane の用意（workspace create の root pane、pane split）、shell コマンド実行（pane run）、
  キー送信（send-keys）、Enter なしの文字列配置（send-text）、pane close に使う。
  完了 marker の検出に pane wait-output は使わない（§2.3）。
  pane コマンドのターゲットは pane id のみ（agent 名は不可）。

後回し: socket API
  §6 のレーンの並べ替え（place-lane.sh の workspace.move_block。CLI に無いため）だけに使う。
  常駐 orchestrator、イベント購読、Herdr plugin 化、複数 agent の大規模制御には、必要になるまで使わない。
```

使い分けの実務ルール:

```text
/goal・プロンプトを送って完了まで待つ ->
  herdr agent prompt <agent> "<text>" --wait --until idle --until done --until blocked --until unknown
  （0.8.0 の主経路。text + エンコード済み Enter を送信し、指定した settled state
    到達で返る。bracketed paste 尊重・複数行も1メッセージ。
    送信後5秒以内に working|blocked が観測できないと agent_prompt_stalled エラー。
    0.9.0 で厳密化: 無関係な idle/done 遷移では満たされない。--timeout を省くと
    activity 観測後は無期限に待つ。付けた場合は先に切れれば timeout エラー。
    どちらのエラーも「未送達」の証明ではない → §2.3。unknown を足す理由も §2.3）
送信だけして待たない -> herdr agent prompt <agent> "<text>"（--wait なし）
Codex TUI に文字列だけ置く（Enter なし） -> herdr pane send-text <pane_id> "<text>"
Codex の直近出力を読む -> herdr agent read <agent> --source recent-unwrapped --lines 200
  （plain text がそのまま出る。jq 不要）
Codex の semantic state を待つ -> herdr agent wait <agent> --until idle --until done --until blocked --until unknown
  （--until なしの既定は idle|done|blocked で unknown を含まない。現在の状態が
    既に一致していると即座に返るので、working のときだけ使う。§2.3）
完了 marker を探す -> agent read の出力から空白・改行を除いて探す（§2.3）
  （pane wait-output の --match / --regex は1行ずつしか照合しないので、Codex が
    折り返した marker を拾えない。公式 CLI reference も agent には agent wait を勧める）
ダイアログ操作のキー送信 -> herdr agent send-keys <agent> enter（0.8.0。pane send-keys でも可）
普通の shell pane に command を打つ -> herdr pane run <pane_id> "<cmd>"
```

JSON とテキストの区別（0.8.0 実測）:

- `agent get` / `agent start` / `agent prompt` / `workspace create` / `workspace get` /
  `pane move` / `pane wait-output` / `workspace list` は
  `{"id":...,"result":{...}}` の JSON エンベロープを返す。pane id は
  `jq -r '.result.agent.pane_id'` のように取り出す。0.8.0 で JSON がデフォルトに
  なり **`--json` フラグは廃止**（worktree 系のみ互換のため受理されるが付けない。
  `workspace list --json` 等は usage エラーになる）。
- **`agent read` と `pane read` は plain text をそのまま出力する**（0.7.5 で
  agent read も plain text 化。旧版の `jq -r '.result.read.text'` は parse error
  になるので使わない）。

`--source` の使い分け: `recent-unwrapped` は履歴バッファで、バッファ末尾に空行が
並びがちなため **`--lines` が小さいと空に見える**（`--lines 200` 以上を推奨。
0.8.0 でも実測で再現）。「いま画面に映っているもの」が欲しいときは
`--source visible` を使う。送信直後は recent バッファへの反映に数秒の遅延が
あり得るので、直後の読み取りで marker が無くても即断しないこと。`recent-unwrapped` が
つなぐのは端末の soft wrap だけで、Codex が自分で入れた改行はつながらない（§9 補足）。Codex 等の全画面 TUI
は代替画面（alternate screen）に描画するが、**0.8.0 は idle になった agent の
代替画面からテキスト履歴を自動収集する**ため、完了後の read で全トランスクリプト
が取れる（実測: goal エコーから最終 marker まで取得できた）。working 中の読み
取りは従来どおり不完全なことがある。成果物をファイル（CODEX_DONE.md 等）を正と
する方針は維持する（公式もフォールバックとして同パターンを推奨）。

その他の実測挙動:

- `herdr pane run` は成功時に**何も出力しない**（exit 0 のみ）。出力が空でも失敗と
  みなさないこと。
- **terminal id（`term_...`）は herdr 再起動で変わる**。スクリプトやログに terminal
  id を保存して使い回さず、ターゲットは agent 名を正とする。

### 2.2 `/goal` には長文を貼り付けない

Codex の `/goal` に巨大な計画全文を貼り付けない。Claude Code は詳細をファイルに書き、Codex には **1行の `/goal`** でそのファイルを読ませる。

良い例:

```text
/goal Read .ai/tasks/<TASK_ID>/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:<TASK_ID>; if blocked print HERDR_TASK_BLOCKED:<TASK_ID>.
```

悪い例:

```text
/goal <PLAN.md の全文を長大に貼り付ける>
```

理由:

- 画面出力だけを source of truth にするとレビュー不能になる。
- ファイル参照にすれば Codex が読み直せる。
- Claude Code が後から `PLAN.md` / `FIX-N.md` / `REVIEW-N.md` を検証できる。

（0.7.5+ の `agent prompt` は bracketed paste を尊重し、複数行テキストも1メッセージ
として送れることを実測済み。旧版にあった「改行が Enter として解釈される」問題は
解消されたが、上記の理由によりファイル契約は維持する。）

`/goal` のサブコマンドは `/goal <objective>`（設定）、`/goal`（状態表示）、`/goal pause`、`/goal resume`、`/goal clear`（codex-cli 0.128+、公式ドキュメント確認済み）。

### 2.3 完了判定は三重化する

`HERDR_TASK_DONE` または Herdr の `done` / `idle` だけで実装完了とみなさない。

Claude Code は次の3つを組み合わせて判断する。

```text
1. Herdr semantic state
   - idle / working / blocked / done / unknown
   - 0.8.0 で公式定義が明文化: idle = 入力可能 かつ その tab が focused UI で
     既読。done = 未読のままバックグラウンド作業が終わった同じ idle 状態。
     CLI read では既読にならない。→ CLI 駆動の本フローでは完了は done になる
     （実測）。人間が Codex の画面を見ていると idle になり得る。
   - 公式 Agents ページ（0.9.3）: Codex は画面の spinner で working を判定するが、
     ターンの終わりは画面から確定できないので「応答後も unknown のまま残ることが
     あり、idle や完了を待つ wait は返らないことがある」。待ちの既定
     （idle|done|blocked）は unknown を含まないので、完了待ちは
     --until idle --until done --until blocked --until unknown と明示する。
     作業中に一瞬 unknown になって早めに返っても、下の「完了の確認」で
     working なら待ち直せばよい（早く起きる損は小さく、起きない損は大きい）。
   - herdr 0.9.4 では Codex もほかのエージェントと同じく、どの規則にも当たらないときは
     idle に倒す（タイトルに spinner がなければ idle。#4507）。unknown に残るのはタイトルを
     出さないときなどに限られるが、`--until unknown` は害がないので付けたままにする。
     逆に、作業の途中で一瞬 idle と判定されて早く返ることはあり得るので、返ったら
     下の「完了の確認」で画面まで見る（2026-10-15 の E2E では早く返らず、done で返った）。
   - `--no-daemon` で起動した Codex（§9）は、herdr の hook（integration v9）が
     ターンの開始（UserPromptSubmit → working）と終了（Stop / Interrupt → idle）を
     直接報告する（0.9.4、#4756）。ただし hook はユーザーが Codex で trust したときだけ動く
     （§9-5）。動いていなければ画面からの判定になる。
   - 完了待ちは `agent prompt --wait`（§10）で行い、返ってきた JSON の
     .result.agent.agent_status で分岐する。待ちの抜け条件は状態だけにし、
     marker の有無で抜けるループを書かない（2026-10-13 macmini で、marker が
     折り返されて見つからず、Codex の完了に約4時間気付かなかった）。

2. 明示 marker（補助）
   - HERDR_TASK_DONE:<TASK_ID>
   - HERDR_TASK_BLOCKED:<TASK_ID>
   - HERDR_TASK_DONE:<TASK_ID>:fix-01
   - Codex は長い行を pane の幅で自分で折り返す。pane が狭いと marker が
     "• HERDR_TASK_DONE:<TASK_ID の前半>" と "  <後半>" の2行に割れる（§9 補足）。
     `recent-unwrapped` はこの改行をつながず、`pane wait-output` の --match /
     --regex は1行ずつしか照合しない（公式 CLI reference）ので、どちらでも
     割れた marker は見つからない。下の「完了の確認」のとおり、agent read の
     出力から空白と改行を除いてから探す。
   - /goal 本文にも marker 文字列が入るので、goal のエコー行
     （"• Goal active Objective: ... print HERDR_TASK_DONE:..."）に注意する。
     空白を除くとエコー行は "printHERDR_TASK_DONE:..." になり、Codex の実際の
     print は "•HERDR_TASK_DONE:..." になる。行頭の "•" 付きで探せば区別できる。

3. ファイルと Git 差分（主）
   - CODEX_DONE.md（blocked なら BLOCKED.md）
   - PROGRESS.md
   - git diff
   - test/lint 結果
```

`HERDR_TASK_DONE` は「Codex の1回の goal が止まった」という意味であり、Claude Code の承認完了ではない。

**完了の確認**（待ちが返った後、毎回行う）:

```bash
# 1. 状態
STATUS="$(herdr agent get "$AGENT" | jq -r '.result.agent.agent_status // empty')"
echo "$STATUS"

# 2. 成果物（主）
ls -l "$TASK_DIR/CODEX_DONE.md" "$TASK_DIR/BLOCKED.md" 2>/dev/null

# 3. marker（補助）。空白・改行を除いてから、行頭の "•" 付きで探す。
#    最後に見つかったものがこのラウンドの marker（修正ラウンドは :fix-NN 付き）かを確かめる。
#    履歴の読み取り（recent-unwrapped で画面より多い行）は idle / done のときしかできず、
#    unknown・blocked・working では agent_not_idle になる（公式 Agent automation）ので visible を読む。
#    LC_ALL=C は BSD tr が不正なバイト列で止まらないようにするため
SRC=recent-unwrapped; case "$STATUS" in idle|done) ;; *) SRC=visible ;; esac
herdr agent read "$AGENT" --source "$SRC" --lines 500 \
  | LC_ALL=C tr -d '[:space:]' \
  | grep -oE "•HERDR_TASK_(DONE|BLOCKED):$TASK_ID(:fix-[0-9]{2})?" | tail -1
```

- marker の正規表現は緩めない。空白を除くと次の行の文字がすぐ後ろに続くので、
  `fix-[0-9]+` のように書くと次の行頭の数字まで取り込む（`fix-[0-9]{2}` にしている。
  FIX 番号は2桁）。goal で独自の suffix（`-part1` 等）を付けた marker を print させた
  場合は、`$TASK_ID` の部分にその suffix まで含める。
- 探せるのは、Codex が marker を単独のメッセージ（行頭が "•"）として出した場合だけ。
  複数行のメッセージの途中に入ると見つからないので、CODEX_GOAL.md / FIX-N.md で
  「最後に marker だけのメッセージを出す」よう指示する（§8・§14.1）。見つからなければ
  §18.3（marker missing）として成果物で判断する。

状態ごとの扱い:

- `working`: 作業中に一瞬 unknown になって早く返っただけ。§10 の `agent wait` で待ち直す。
- `unknown` で成果物も marker も無い: まだ作業中かを短く確かめる
  （`herdr agent wait "$AGENT" --until working --until idle --until done --until blocked --timeout 60000`）。
  working が返れば §10 の `agent wait` で待ち直し、idle / done / blocked が返ればこの確認を
  やり直す。timeout なら §18.4。ここで goal を送り直さない（二重送信になる）。
- `idle` / `done` / `blocked` で成果物も marker も無い: goal が Codex のダイアログに
  飲み込まれた可能性がある（§9-5・§18.2）。visible read で画面を確認する。画面に
  `• Working (…)` が出ていてまだ作業中なら、早く返っただけなので、状態が working に
  戻るのを短く待ってから（`herdr agent wait "$AGENT" --until working --timeout 60000`）
  §10 の `agent wait` で待ち直す。ここでも goal は送り直さない。

送信直後のレース（0.7.5 の「送信後すぐ完了待ちに入ると前ラウンドの done/idle で
即 return する」問題）は、0.8.0 では `agent prompt --wait` が内部で処理する:
working でない状態から送ったプロンプトは **送信後5秒以内に `working` または
`blocked` が観測できなければ `agent_prompt_stalled` エラーが返る**（公式仕様。偽 done で
即返しない。実測: 送信→working 遷移→1分27秒ブロック→done で返却）。0.9.0 で
この判定は厳密化され、無関係な idle/done/session 変化ではゲートを通過しない
（#3506, #3685）。また caller の `--timeout` は送信時間を含み、先に切れれば
`timeout` エラーになる。あわせて 0.8.0 は送信テキストの後 Enter まで短い待ちを
入れるようになり、旧版の「TUI 初期化中のプロンプトが composer に残ったまま無音で
消える」問題も修正された（release notes #1878）。したがって `--until working`
による開始確認は不要。逆に、送信直後の待ちを単独の `agent wait` で始めてはいけない。
`agent wait` は現在の状態が既に一致していると即座に返る（公式 Agent automation）ので、
前ラウンドの done で即 return してしまう。送信と待ちは `agent prompt --wait` の1コマンドで行う。

**`agent_prompt_stalled` / `timeout` はプロンプト未送達の証明ではない**（0.9.0
`--skill` の明記）。返ったら盲目的に再送せず、まず visible read で画面を確認する:
(a) ダイアログ表示中（§9）→ 対処してから再送、(b) goal が composer に残っている
（Enter が効いていない）→ `agent send-keys <agent> enter` のみ、(c) 既に working で
実行中 → 再送せず `agent wait`（§2.1 の --until）で合流。round ごとに marker を変える設計（`:fix-N`）は
引き続き取り違えの保険になる。

---

## 3. ディレクトリ構成

Codex が作業する Git worktree の中に、次の task directory を作る。

```text
.ai/tasks/<TASK_ID>/
  PLAN.md                 # Claude Code が作る詳細実装計画
  CODEX_GOAL.md           # Codex が最初に読む実装契約
  PROGRESS.md             # Codex が checkpoint ごとに更新する進捗ログ
  CODEX_DONE.md           # Codex が完了時に書く完了報告
  BLOCKED.md              # Codex が blocked のときに書く任意ファイル
  REVIEW-01.md            # Claude Code のレビュー
  FIX-01.md               # Claude Code から Codex への修正依頼
  REVIEW-02.md
  FIX-02.md
  REVIEW-FINAL.md         # Claude Code の最終承認または中止理由
  logs/
    agent-start.json
    agent-get.json
    codex-pane-*.txt
    final.diff
    final-status.txt
    test-results.txt
```

重要: main checkout に未コミットで作った task files は、別 worktree には自動では存在しない。Claude Code は worktree を作成した後、Codex が読む task files を **Codex worktree 内**に作成すること。

また、`.ai/` は untracked のまま Codex の `git status` / diff に混ざり、Codex が誤ってコミットに巻き込むリスクがある。worktree 作成直後に `.git/info/exclude` へ `.ai/` を追加して Git から隠すこと（§6 参照）。

---

## 4. 推奨ライフサイクル

```text
0. Claude Code が check-versions.sh で依存バージョンを検証する（§5）
1. Claude Code が TASK_ID を作る
2. Claude Code が git worktree add で Git worktree を作って .ai/ を exclude し、Codex 用 workspace を作って委譲元の直下へ移す（疑似ツリー。応答 JSON の root pane id を控える。§6）
3. Claude Code が Codex worktree 内に PLAN.md / CODEX_GOAL.md を作る
   （brainstorming → writing-plans。§7 参照）
4. Claude Code が Codex 用 workspace の root pane に Codex agent を起動する
   （agent start --kind codex --pane）
5. 起動確認を行う（agent get で生存確認 + visible read でダイアログの有無と
   入力プロンプト表示を確認）
6. Claude Code が Codex TUI に 1行の /goal を agent prompt --wait で送る
   （stalled / timeout エラーなら画面確認→送達済みか判断→対処。§2.3）
7. Codex が実装し、PROGRESS.md を更新する
8. Codex が CODEX_DONE.md を作り、HERDR_TASK_DONE:<TASK_ID> を出す（状態は done になる）
9. Claude Code が pane output / git diff / CODEX_DONE.md / test 結果を保存する
10. Claude Code がレビューし、REVIEW-01.md を書く
11. 問題があれば FIX-01.md を書き、同じ Codex pane に再 /goal する
12. 修正ループを最大3回まで繰り返す
13. 承認できたら REVIEW-FINAL.md に APPROVED を書く
14. ログと差分を保存する
15. Codex pane を閉じる
16. Claude Code が worktree でコミットし、finishing-a-development-branch で
    merge / PR / reject を人間に確認する
17. worktree は merge / PR / reject が終わるまで残す
```

---

## 5. 初期セットアップ確認

**Step 0（必須）**: 委譲を開始する前に、依存バージョンチェッカーを実行する。

```bash
"${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/check-versions.sh
# CLAUDE_PLUGIN_ROOT が未設定の文脈では、この workflow.md と同じディレクトリの
# check-versions.sh を実行する
```

チェッカーは [versions.json](versions.json)（検証済みバージョンの正）と実機の
herdr / codex / superpowers / jq を突き合わせ、ツールごとに OK / WARN / MISSING を
出力する。herdr については `herdr status` で **client と server の整合**も見る
（0.9.0 で protocol 20→22。mise 等で client を入れ替えた直後は既存シェルの PATH に
旧 client が残り、`herdr --version` は旧版・server は新版という状態になる。この
とき agent/workspace 系は全て `protocol_mismatch` の JSON エラーを返す — exit 0
なのでスクリプトは気づけない。実測 2026-09-08。新しいシェルを開くか、mise shims の
herdr を使って揃える）。**exit は常に 0 でブロックはしない** — WARN が出たら各行に書かれた
次アクション（herdr --skill と usage の照合、goals feature の確認など）を実施し、
本書との差分を把握してから進むこと。バージョンを上げて再検証したら
versions.json を更新する。hook 等から低ノイズで呼ぶ場合は `--quiet`（全 OK なら
無出力、WARN / MISSING があるときだけその行と件数を出す）を使う。

herdr が検証済みより新しいときは、versions.json の `on_newer` に書いた確認事項を
`INFO` で出す（件数には数えない。`--quiet` では出さない）。現在の内容は「herdr 本体に
起動元エージェントの下への入れ子表示（#3153 / #4795 / #5210）が入ったか確認する」。
この行が出たら、リリースノートを確かめて入っていればユーザーに伝え、§6 の疑似ツリーから
乗り換えるか相談する。

続けて、必要に応じて次を確認する。

```bash
herdr integration status || true
```

未導入なら、一度だけ以下を案内または実行する（herdr の integration は自動では
入らない。これがないと `agent wait` の状態検知が働かない）。

```bash
herdr integration install codex
herdr integration install claude
```

`/goal` は codex-cli 0.144+ では feature `goals` が stable・既定有効のため、通常は追加設定不要（実測: `codex features list` で stage=stable / effective=true）。`/goal` が Codex の slash command list に出ない場合（古い codex 等）のみ、`codex features enable goals` を実行するか、Codex の `config.toml` に以下を入れる。

```toml
[features]
goals = true
```

注意（実測）: Codex CLI は起動時にアップデート系の割り込みを出すことがある。

- 自動アップデートして「Please restart Codex」で**即終了する**（0.145 実測。
  agent は `agent_not_found` になる → 同じ pane にもう一度 `agent start`）。
- **対話式アップデートダイアログ**を出して止まる（0.145→0.146 で実測:
  「1. Update now / 2. Skip / 3. Skip until next version — Press enter to
  continue」）。このとき status は `idle` のままで `blocked` にならず（0.9.3 + 検出 manifest
  2026.10.11.1 と 0.9.4 では `blocked` と判定され、`agent start` は `agent_not_ready` で返る。§9）、
  **そのまま /goal を送ると Enter が「1. Update now」を選んでしまう**。
  visible read で検出し、`pane send-text <pane_id> "2"` + `agent send-keys
  <agent> enter` で Skip してから送信する。

いずれも `agent start` 直後の §9 起動確認（生存 + visible read）で検出できる。

---

## 6. TASK_ID・worktree・Codex 用ワークスペース（疑似ツリー）の作成

Claude Code は、ユーザーから実装委譲を求められたら、まず task id を作る。

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)-codex-task"
ROOT="$(git rev-parse --show-toplevel)"
WT="$(dirname "$ROOT")/worktrees/$TASK_ID"
BRANCH="ai/$TASK_ID"
```

Codex 用の Git worktree を `git worktree add` で作り、task files を Git から隠す
（Codex の diff/status 汚染と誤コミットを防ぐ）。

```bash
git -C "$ROOT" worktree add -b "$BRANCH" "$WT" HEAD
echo ".ai/" >> "$(git -C "$WT" rev-parse --git-path info/exclude)"
```

**`herdr worktree create` は使わない。** herdr の worktree グループはリポジトリ単位で、
親 workspace は「同じリポジトリの workspace のうちサイドバー順で最初のもの」が
選ばれる（herdr 0.9.3 のソースで確認。0.9.4 は元のチェックアウトの workspace を全部
並べてから子を描くが、リポジトリ単位なのは同じ）。同じリポジトリの workspace が複数あると、
Codex レーンが委譲元とは別の workspace の下に表示される。`--workspace` で呼び元を
指定しても、呼び元が子のようにインデントされるだけで解決しない（2026-10-13 調査。
herdr #4736 / PR #4772 も parent ID は追加しない方針）。

次に、Codex 用のワークスペースを作り、サイドバーで委譲元（Claude Code が居る）
workspace の直下へ移す（**疑似ツリー**）。応答 JSON の root pane id を控え、Codex は
この root pane に直接起動する（§9）。

```bash
# 呼び元 workspace の特定。herdr の外では pane current がエラーにならず
# フォーカス中の pane を返す（0.9.3 実測）ので、HERDR_PANE_ID の有無で判定する。
CALLER_WS=""
if [ -n "${HERDR_PANE_ID:-}" ]; then
  CALLER_WS="$(herdr pane current 2>/dev/null | jq -r '.result.pane.workspace_id // empty' || true)"
fi

# 委譲元が分かるときはラベルの先頭に "└ " を付け、子の行に見せる
if [ -n "$CALLER_WS" ]; then LANE_LABEL="└ $TASK_ID"; else LANE_LABEL="$TASK_ID"; fi
CREATED="$(herdr workspace create --cwd "$WT" --label "$LANE_LABEL" --no-focus)"

# エラー JSON（protocol_mismatch 等は exit 0 で返る）で "null" を拾わないよう // empty を付ける
LANE_WS="$(printf '%s' "$CREATED" | jq -r '.result.workspace.workspace_id // empty')"
PANE_ID="$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id // empty')"
test -n "$PANE_ID" || { printf 'lane create failed: %s\n' "$CREATED" >&2; false; }

# 委譲元の直下へ移す（サイドバーの描画順で、委譲元のかたまりと既存のレーンの後ろ）。
# 並べ替えは CLI に無いので、同梱の place-lane.sh が socket API の workspace.move_block を送る。
# 失敗しても exit 0 で警告を出すだけ（レーンが一番下に残る）。CLAUDE_PLUGIN_ROOT が
# 未設定の文脈では、この workflow.md と同じディレクトリの place-lane.sh を実行する
if [ -n "$CALLER_WS" ]; then
  "${CLAUDE_PLUGIN_ROOT}"/skills/delegating-to-codex/place-lane.sh "$CALLER_WS" "$LANE_WS"
fi
```

以後、Codex に読ませる task files は `$WT/.ai/tasks/$TASK_ID/` に作る。委譲元とレーンの
対応も記録しておく（サイドバーの並び順は後から変わり得るので、並びだけに頼らない）。

```bash
TASK_DIR="$WT/.ai/tasks/$TASK_ID"
mkdir -p "$TASK_DIR/logs"
CALLER_LABEL=""
if [ -n "$CALLER_WS" ]; then
  CALLER_LABEL="$(herdr workspace get "$CALLER_WS" 2>/dev/null | jq -r '.result.workspace.label // empty' || true)"
fi
jq -n --arg task "$TASK_ID" --arg caller "$CALLER_WS" --arg caller_label "$CALLER_LABEL" \
  --arg caller_pane "${HERDR_PANE_ID:-}" --arg lane "$LANE_WS" --arg pane "$PANE_ID" \
  --arg created "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
  '{task_id: $task, caller_workspace: $caller, caller_label: $caller_label, caller_pane: $caller_pane,
    lane_workspace: $lane, pane_id: $pane, created_at: $created}' \
  > "$TASK_DIR/logs/lane.json"
```

- **疑似ツリーにする理由:** どの Claude Code セッションがどの Codex を起動したかを、
  サイドバーで見えるようにするため。Codex の行が委譲元の行の直下に並び、Codex の状態
  （working / done など）もその行に出る。本物の tree（worktree グループ）は上記のとおり
  リポジトリ単位で親が1つなので、Claude ごとに分けられない。2026-10-13 にタブ方式
  （委譲元 workspace の中のタブ）から切り替えた。タブ方式は対応関係が正しいが、
  サイドバーに行が出ず見えなかった。
- **将来:** herdr 本体で「起動元エージェントの下に起動されたエージェントを入れ子で表示」が
  予定されている（issue #3153 でメンテナーが planned と表明。Discussions #4795・#5210）。
  また Discussion #1620（Hierarchical space groups）では、`workspace create` に
  `parent_workspace_id` を渡してリポジトリと無関係に親の下へ並べる API が提案されている。
  どちらかが入ったら乗り換えを検討する（2026-10-14 時点で 0.9.4 にも master にも無い）。`check-versions.sh` が herdr の更新時に versions.json の
  `on_newer` で知らせる（§5）。
- **限界:** 字下げは本物ではない（ラベルの `└` で見せているだけ）ので、折り畳めない。
  委譲元の行を後からドラッグしたり閉じたりしても、レーンの行は付いてこない（そのとき
  レーンは上の行の子に見える）。ユーザーが自分で `└ ` から始まるラベルを付けた
  workspace もレーンとして扱われる。どの Claude が起動したかの正は `logs/lane.json`
  （委譲元の workspace・ラベル・pane と作成時刻）。
- **並べ替え（place-lane.sh）:** `workspace.move_block` は指定した workspace だけを
  `before_workspace_id` の前に移す（公式 Socket API・ソース確認）。ユーザーの他の
  workspace の並びとフォーカスは変わらない（2026-10-13 実測。委譲元が真ん中・末尾の
  どちらでも、2本目は1本目の後ろに並んだ）。サイドバーは worktree グループを最初の
  メンバーの位置にひとかたまりで描くので、移動先はその描画順で決める。委譲元が
  グループの親・子のときは、レーンはグループのかたまりの直後に並ぶ（グループの中には
  入れない）。グループになる条件は herdr の版で違う（0.9.3 まで: 同じリポジトリの
  workspace が2つ以上あり、元のチェックアウトを含む。0.9.4 から: 元のチェックアウトと
  linked worktree の両方を含む。#4772）。place-lane.sh は PATH の herdr（サイドバーを描く
  client）の版で切り替え、版が取れなければ 0.9.4 以降の条件にする。socket は herdr が pane に渡す `HERDR_SOCKET_PATH`。`nc -U` は macOS 標準の
  nc で動く（Linux の netcat-traditional には無いので socat 等に置き換える）。CLI に
  並べ替えのコマンドが入ったら置き換える（Discussions #5141）。テストは
  `tests/test-place-lane.sh`。
- workspace create が失敗した場合（`herdr status` の protocol_mismatch 等）、
  worktree とブランチは既にできている。原因を直して workspace create から再実行する（新しい
  TASK_ID でやり直さない。孤児 worktree が増える）。やり直す場合は先に
  `git -C "$ROOT" worktree remove "$WT" && git -C "$ROOT" branch -D "$BRANCH"` で片付ける。
- root pane の cwd は worktree checkout そのものなので、そのまま Codex の作業ディレクトリになる（0.9.3 実測）。
- `HERDR_PANE_ID` があれば `pane current` は caller context で解決される（pane move 後の
  旧 ID もこの経路なら解決できる）。`pane current` が失敗した場合（stale ID なら
  `pane_not_found`。0.9.3 実測）は `CALLER_WS` が空になり、`└` の付かない単独 workspace が
  一番下にできる。`|| true` は `set -euo pipefail` のスクリプトでもここで止まらないため。
- レーンの workspace は `worktree` が null で、どのグループにも属さない（0.9.3 実測。
  workspace create は worktree の所属情報を付けない — 所属を付けるのは worktree 系の
  API だけ。0.9.3・0.9.4 のソース確認）。
- 作業中のタブを split しないのは、ユーザーの画面を狭め、並列委譲で破綻するため。
- `--no-focus` なので、ユーザーのフォーカスは動かない（0.9.3 実測）。

---

## 7. `PLAN.md` の作成規約

Claude Code は Codex に渡す前に、必ず詳細な `PLAN.md` を作る。

**PLAN.md の作成には Superpowers スキルを使うこと（運用ルール）:**

```text
1. superpowers:brainstorming
   PLAN.md を書き始める前に必ず起動する。
   要件・意図・設計選択肢をユーザーと（または自律的に）探索し、
   Scope / Non-goals / Expected behavior を固める。

2. superpowers:writing-plans
   PLAN.md の執筆自体はこのスキルの規約に従う。
   下のテンプレートは writing-plans の出力を Codex 向けに
   整形するときの最低限の構成である。
```

`PLAN.md` は次の構成にする。

```md
# Implementation Plan: <TASK_ID>

## Objective
何を実装するか。

## Background
なぜ必要か。関連 issue / 仕様 / 現状挙動。

## Scope
今回必ず実装するもの。

## Non-goals
今回やらないもの。Codex が広げてはいけない範囲。

## Files to inspect first
- path/to/file
- path/to/test

## Expected behavior
ユーザー視点・API 視点・エラー時挙動。

## Implementation steps
1. ...
2. ...
3. ...

## Validation commands
- npm test
- npm run lint
- <project-specific command>

## Done criteria
- 仕様を満たす。
- 必須テストが通る。
- CODEX_DONE.md が作られている。
- 関係ないファイルを変更していない。
- HERDR_TASK_DONE:<TASK_ID> を出している。

## Risks / edge cases
- ...

## Notes for Codex
- 不明点は推測で広げず BLOCKED.md に書く。
- secret / credentials / deploy / destructive operation は行わない。
```

---

## 8. `CODEX_GOAL.md` の作成規約

`CODEX_GOAL.md` は、Codex が `/goal` 開始後に最初に読む契約書である。Claude Code は `PLAN.md` より短く、実行規約に寄せて書く。

テンプレート:

```md
# Codex Goal: <TASK_ID>

You are Codex CLI working inside this Git worktree.

## Read first
1. .ai/tasks/<TASK_ID>/PLAN.md
2. AGENTS.md, CLAUDE.md, README, or project-specific contribution docs if present
3. Files listed in PLAN.md

## Objective
Implement exactly what PLAN.md requires.

## Scope control
- Implement only the Required scope in PLAN.md.
- Do not implement optional ideas or future work.
- Do not rewrite unrelated modules.
- Do not modify generated files unless PLAN.md explicitly requires it.
- Do not deploy, publish, rotate credentials, or run destructive commands.

## Progress reporting
- Keep .ai/tasks/<TASK_ID>/PROGRESS.md updated after each checkpoint.
- Record commands run and whether they passed.
- If blocked, write .ai/tasks/<TASK_ID>/BLOCKED.md.

## Validation
Run the commands listed in PLAN.md.
If a command cannot be run, explain why in CODEX_DONE.md.

## Done condition
Before stopping, create .ai/tasks/<TASK_ID>/CODEX_DONE.md with:
- Summary
- Changed files
- Tests run
- Results
- Known risks
- Any remaining follow-ups

When complete, print exactly this as your final message, on its own with nothing else in that message:
HERDR_TASK_DONE:<TASK_ID>

If blocked, print exactly this as your final message, on its own:
HERDR_TASK_BLOCKED:<TASK_ID>
```

---

## 9. Codex agent の起動

Claude Code は、§6 で控えた **Codex 用 workspace の root pane** に Codex を起動する。
0.7.5+ の `agent start` は既存 pane への起動が必須で（`--kind` と `--pane` が必須、
`--cwd` / `--no-focus` / pane 自動生成は廃止）、cwd は pane から引き継がれる。

```bash
AGENT="codex-$TASK_ID"
# agent 名は「小文字始まり・小文字/数字/-/_ のみ・1〜32文字」（invalid_agent_name。
# 0.9.0 実測）。§6 の既定 TASK_ID（YYYYMMDD-HHMMSS-codex-task）なら "codex-" 込みで
# ちょうど 32 文字。TASK_ID に長い suffix を付けた場合は短縮する。
[ "${#AGENT}" -le 32 ] || AGENT="codex-$(printf '%s' "$TASK_ID" | cut -c1-15)"

# --no-daemon: 共有のバックグラウンドサーバー（デーモン）を使わずに動かす。herdr 0.9.4 の
# Codex integration（v9）は、このときだけ hook でターンの開始・終了を報告する（#4756）。
# 共有デーモンだと hook の報告が別の pane に届くことがある（公式 Integrations）。
# 起動中にダイアログ（アップデート・trust）が出ると herdr は blocked と判定し、agent start は
# agent_not_ready（exit 1 の JSON エラー）で返る。起動の失敗ではないので止まらずに
# 下の起動確認へ進む（agent 名はそのまま使える。0.9.4 実測）
herdr agent start "$AGENT" --kind codex --pane "$PANE_ID" -- --no-daemon \
  > "$TASK_DIR/logs/agent-start.json" 2>&1 || true
jq -r '.result.agent.agent_status // .error.code // .' "$TASK_DIR/logs/agent-start.json"
```

応答は `.result.agent` に agent 情報を含む JSON（`pane_id` / `agent_status` /
`interactive_ready` 等）。`agent start` は **Herdr が同一 pane に期待どおりの
agent を検出し対話入力可能と判断してから返る**（公式仕様。既定 30 秒タイムアウト。
実測 ~3 秒）。追加の引数（モデル指定等）は `--no-daemon` の後ろに足す
（例: `-- --no-daemon -m gpt-5.4`）。

hook による状態報告は、ユーザーが Codex で herdr の hooks を trust しているときだけ動く
（していないと下の 5 のレビュー画面が出る）。動いていなくても、0.9.4 は画面（タイトルの
spinner）から working / idle を判定するので、手順は変わらない（2026-10-15 実測: hooks を
trust せずに一巡し、`prompt --wait` は2分40秒後に done で返った。`herdr agent explain` の
rule は `osc_title_idle`）。

**起動確認（必ず行う）。** start が返っても、Codex が**ダイアログを表示したまま
`idle` で止まっている**ことがあるため、visible read で画面を見てから送信する。
0.8.0〜0.9.1 ではどのダイアログも status は `idle` のままで `blocked` にならず、
状態待ちでは検出できなかった。0.9.3（検出 manifest 2026.10.11.1）では trust と
アップデートのダイアログは `blocked` と判定されるようになった（2026-10-13 実測。
`herdr agent explain` で判定ルールが見える）。0.9.4 も同じで、起動中に blocked になると
`agent start` は `agent_not_ready` で返る。hooks のレビュー画面は 0.9.4 でも `done` の
ままで blocked にならない（2026-10-15 実測）。どちらにしても状態だけに頼らず、
visible read で画面を見て判断する。

1. self-update 即終了（§5）→ `agent get` が `agent_not_found` → 再 start。
2. **対話式アップデートダイアログ**（§5）→ そのまま送信すると Enter が
   「Update now」を選んでしまう。`pane send-text "$PANE_ID" "2"` +
   `agent send-keys "$AGENT" enter` で Skip。
3. fresh worktree での **trust 確認ダイアログ**（"Do you trust the contents of
   this directory?"）→ enter で承認（"Yes, continue" が既定選択）。親リポジトリ
   が trust 済みだと出ないこともある（実測）。
   codex-cli 0.156 で trust プロンプトの文言・判定タイミングが変わった（#44732 /
   #44746 / #44755）。2026-09-24 の E2E（permissions: YOLO mode）では trust も
   アップデートダイアログも出ずに「›」が表示された。文言が変わっても「visible read
   で画面を見てから送る」原則は同じ。codex-cli 0.160 で trust されていないリポジトリを
   開いたときは "Trust and continue / Quit" という文言で出て、herdr 0.9.3 の状態は
   `blocked` ではなく `done` だった（2026-10-13 実測）。
4. **共有デーモンの設定不一致ダイアログ**（`--no-daemon` で起動すれば出ない。2026-10-15 実測。
   付けずに起動したときは codex-cli 0.160 で実測: "Background server
   has incompatible feature settings"、選択肢 "1. Run without daemon this time /
   2. Restart with these settings / 3. Cancel"、既定は Cancel）→
   `pane send-text "$PANE_ID" "1"` で「今回はデーモンなしで実行」を選ぶ。2 は共有の
   バックグラウンドサーバーを再起動し、他の Codex セッションの作業を中断し得るので
   選ばない。
5. **hooks のレビュー画面**（codex-cli 0.160 実測: "Hooks … N hooks need review
   before they can run"。0.160 では "Hooks need review / N hooks are new or changed" と
   "1. Review hooks / 2. Trust all and continue / 3. Continue without trusting" の形でも出る。
   対象は herdr の hook（v9 は開始・入力・停止・中断の4つ）と、ユーザーが入れた他のツールの
   hook）→ `agent send-keys "$AGENT" esc` で閉じる（新しい形の画面では "3" を送ってもよい。2026-10-15 実測）。
   trust の判断はユーザーの Codex 設定に保存されるので、Claude Code は `t` や
   "2. Trust all and continue"（trust all）を押さない。
   **この画面は起動確認の後に遅れて出ることがあり、出ている間に送った `/goal` は
   飲み込まれる。そのとき `agent prompt --wait` は `done` で返る**（偽の完了）。
   marker が見つからなければ visible read で画面を確認し、閉じてから送り直す。
   esc で閉じたレーンでは、レビューされていない hooks が動かない。閉じたことと
   その影響（このレーンではユーザーの hooks が動かない）を REVIEW-N.md と人間への
   報告に書く。恒久的に有効にしたい場合は、人間が Codex を直接起動して一度レビューする。

アップデートダイアログは codex-cli 0.160 では `pane send-text "$PANE_ID" "2"` だけで
Skip され、Enter は不要だった（2026-10-13 実測）。送った後は visible read で入力欄
「›」が出ていることを確かめる。

```bash
# 生存確認（self-update 終了なら agent_not_found が返る → 再 start）
herdr agent get "$AGENT" | tee "$TASK_DIR/logs/agent-get.json"

# 画面確認（ダイアログの有無と入力プロンプト「›」の表示を見る）
herdr agent read "$AGENT" --source visible --lines 40

# ダイアログ承認が必要な場合のみ（agent 名ターゲットの send-keys は 0.8.0+）
herdr agent send-keys "$AGENT" enter
```

なお旧版（0.7.5）にあった「TUI 初期化中のプロンプトが無音で消える」罠は 0.8.0 で
修正済み — 送信が届かない状況では `agent prompt` が `agent_prompt_stalled`
エラーで教えてくれる（§2.3）。

補足:

- 0.7.4 まで必要だった「pane move --new-tab --workspace による自 workspace への
  回収」は不要。§6 で委譲元の直下に置いた workspace（1レーン = workspace 1 つ。
  疑似ツリー）がそのまま Codex の置き場所になる。Codex の状態はその行に出て、
  Agents パネルにも Codex agent が個別に表示される。
- ID は `w1`（workspace）/ `w1:t1`（tab）/ `w1:p1`（pane）形式の opaque handle
  （0.8.0 公式）。閉じた tab/pane の ID は再利用されない。**別 workspace へ move
  した pane は新しい workspace 修飾 ID を受け取る** — 旧 ID は移動したプロセスの
  caller context 経由でしか解決されないので、一般のターゲットに使わない。移動後は
  `pane move` の応答 `.result.move_result.pane.pane_id` か agent 名を正とする。
- workspace はその中の最後の pane を閉じると自動で消える（0.9.3 実測）ので、cleanup は
  `herdr pane close` だけでよい（§15）。
- **Codex 用 pane の幅は保証されない。** herdr はクライアントが1つならすべてのタブを
  そのサイズに、複数なら表示中のタブを最後に操作したクライアントのサイズに合わせ、
  クライアントがないと 120×40 を使う（公式 Configuration「Headless terminal size」・
  Concepts「Client and server」）。2026-10-13 の macmini では Codex 用 pane が約50桁の
  まま数時間続いた（旧方式の worktree workspace でも同じことが起きていた）。Codex は
  長い行を pane の幅で自分で折り返すので、marker が2行に割れる（実例:
  `• HERDR_TASK_DONE:20261013-110845-p1c-ai-hand-` と `  part1`）。marker は §2.3 の
  「完了の確認」の方法で探す。

---

## 10. `/goal` の投入

Claude Code は Codex TUI に、1行の `/goal` だけを送る。0.8.0 の主経路は
`herdr agent prompt --wait` — 送信と完了待ちを1コマンドで行う（ターゲットは
agent 名でよい。公式も「For normal agent work, --wait is enough」）。

```bash
GOAL_TEXT="/goal Read .ai/tasks/$TASK_ID/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:$TASK_ID; if blocked print HERDR_TASK_BLOCKED:$TASK_ID."

# Bash の run_in_background で実行し、完了通知で合流する。
# --timeout は付けない（activity 観測後は無期限に待ち、Codex が working 以外に
# なった時点で返る。unknown を含める理由は §2.3）。サーバーのエラーは stderr の JSON。
herdr agent prompt "$AGENT" "$GOAL_TEXT" --wait \
  --until idle --until done --until blocked --until unknown \
  > "$TASK_DIR/logs/prompt-wait-result.json" 2>&1
jq -r '.result.agent.agent_status // .error.code // .' "$TASK_DIR/logs/prompt-wait-result.json"
```

- 返ったら §2.3 の「完了の確認」を行う（実測: 送信 → working 遷移 → 完了で `done`）。
  状態が working のときは、作業中に一瞬 unknown になって早く返っただけなので、
  `herdr agent wait "$AGENT" --until idle --until done --until blocked --until unknown`
  をバックグラウンドで待ち直す。
- **待ちの抜け条件は状態だけにする。** marker や CODEX_DONE.md が現れるまで回るループを
  自作しない。marker は Codex の折り返しで割れることがあり、見つからないとループが
  終わらず完了に気付けない（§2.3。2026-10-13 macmini で約4時間の見落とし）。
- **`agent_prompt_stalled` エラー**（送信後5秒以内に working|blocked なし）が返ったら、
  visible read で画面を確認する — ダイアログ表示中（§9）が典型。未送達とは限らない
  ので、composer に goal が残っていれば Enter だけ、既に working なら再送せず
  上の `agent wait` で合流する（§2.3）。
- `--timeout` を付けた場合（フォアグラウンドで短く様子を見るとき等）、timeout エラーで
  返っても Codex は動き続けている。working なら上の `agent wait` で待ち直す
  （0.9.0: `--timeout` は送信時間込み。送信直後に切れた timeout も未送達の証明ではない）。
- 送信だけ先に済ませて待ちを単独の `agent wait` で始めない（前ラウンドの done で即座に
  返る。§2.3）。Claude 側で並行作業をしたいときも、上のコマンドをバックグラウンドで
  動かせば足りる。

完了後に直近出力を保存する（`agent read` は plain text。jq を通さない）。

```bash
herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  | tee "$TASK_DIR/logs/codex-after-goal.txt"
```

---

## 11. Codex の進捗監視

Claude Code は、Codex の進捗を Herdr の状態・成果物ファイル・marker で確認する（§2.3）。

基本コマンド:

```bash
# Codex の直近出力を見る（plain text。jq 不要）
herdr agent read "$AGENT" --source recent-unwrapped --lines 200

# Herdr の semantic state を待つ（working のときだけ。既に一致していると即座に返る）
# unknown も含める（§2.3）。返ってきた JSON の .result.agent.agent_status で分岐する
herdr agent wait "$AGENT" --until idle --until done --until blocked --until unknown

# 特定状態だけを待つ場合は --until（繰り返し指定可）
herdr agent wait "$AGENT" --until blocked --timeout 1000 || true

# 明示 marker を探す（空白・改行を除いてから行頭の "•" 付きで。idle / done 以外では
# --source visible にする。§2.3 の「完了の確認」の 3 をそのまま使う）
herdr agent read "$AGENT" --source recent-unwrapped --lines 500 \
  | LC_ALL=C tr -d '[:space:]' \
  | grep -oE "•HERDR_TASK_(DONE|BLOCKED):$TASK_ID(:fix-[0-9]{2})?" | tail -1
```

運用ルール:

```text
working 以外 + CODEX_DONE.md があれば（修正ラウンドでは FIX を送った後に更新されていれば）、レビューに進む（marker も見つかれば記録する）。
blocked を検出したら、BLOCKED.md と pane output を読み、必要な入力を与える。
unknown が続く場合は、herdr agent explain を使うか、pane output を保存して人間に状態を報告する。
marker がないが CODEX_DONE.md と diff が妥当なら、レビューに進んでよい。ただし REVIEW.md に marker missing と書く。
marker がエコー行（• Goal active Objective: ...）でしか見つからない場合は、marker 未達として扱う（§2.3 の探し方ならエコー行は拾わない）。
CODEX_DONE.md がない場合は、実装完了とみなさず、FIX-N.md で作成を求める（ただし diff も無いなら先に §18.2 の確認を行う）。
```

---

## 12. Codex 完了後の保存

§2.3 の「完了の確認」で Codex の goal が止まったと分かったら、Claude Code はレビュー前に必ずログと差分を保存する。

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"

herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  > "$TASK_DIR/logs/codex-pane-$STAMP.txt"

git -C "$WT" status --short \
  > "$TASK_DIR/logs/status-$STAMP.txt"

git -C "$WT" diff \
  > "$TASK_DIR/logs/diff-$STAMP.patch"
```

Claude Code は次を読む。

```text
.ai/tasks/<TASK_ID>/PLAN.md
.ai/tasks/<TASK_ID>/CODEX_GOAL.md
.ai/tasks/<TASK_ID>/PROGRESS.md
.ai/tasks/<TASK_ID>/CODEX_DONE.md
git diff
git status --short
テスト結果
```

---

## 13. Claude Code のレビュー規約

Claude Code は、Codex の実装完了後に `REVIEW-N.md` を作る。

レビュー観点:

```text
1. PLAN.md の Scope を満たしているか
2. Non-goals を侵していないか
3. 変更ファイルが妥当か
4. テストが追加/更新されているか
5. 既存テスト・lint が通っているか
6. エラー処理・境界条件が妥当か
7. セキュリティ・secret・destructive operation の問題がないか
8. 不要なリファクタや unrelated change がないか
9. CODEX_DONE.md の内容と実際の diff が一致しているか
```

`REVIEW-N.md` のテンプレート:

```md
# Claude Review <N>: <TASK_ID>

Status: APPROVED | CHANGES_REQUESTED | BLOCKED | ABORTED

## Summary
Claude Code のレビュー要約。

## What matches the plan
- ...

## Problems
- ...

## Required fixes
1. ...
2. ...

## Validation performed by Claude Code
- command: <...>
  result: pass/fail/not-run

## Decision
APPROVED / CHANGES_REQUESTED / BLOCKED / ABORTED
```

Claude Code は、承認できるまでは `APPROVED` を書かない。

### 13.1 レビューの可視化（任意・hunk 併用）

hunk CLI が導入済みの環境（`which hunk` で確認）では、Claude Code はレビュー時に**人間向けの diff ビューを開き、REVIEW-N.md の指摘をインライン注釈**できる。hunk の TUI は人間用であり、Claude 自身の diff 読解は従来どおり `git diff` で行う。なお herdr-plugin-hunk（UI のコマンドパレットから diff を開く herdr プラグイン）はこの手順には不要 — 人間が手動で diff を開くための任意追加であり、その action は CLI から呼べない（実測）。

```bash
# Codex worktree の未コミット差分を人間用に表示。
# agent start は --kind（既知エージェント種別）必須のため、hunk のような
# 任意 TUI は agent start では起動できない。Codex 用 workspace の root pane を
# split して pane run で起動する。
HUNK_PANE="$(herdr pane split "$PANE_ID" --direction right --cwd "$WT" --no-focus \
  | jq -r '.result.pane.pane_id')"
herdr pane run "$HUNK_PANE" "hunk diff"

# Claude は session CLI で構造把握と注釈を行う（TUI は操作しない）
hunk session review --repo "$WT" --json
printf '%s\n' '{"comments":[{"filePath":"src/x.ts","newLine":12,"summary":"REVIEW-01 #1: ..."}]}' \
  | hunk session comment apply --repo "$WT" --stdin
```

指摘の summary には `REVIEW-N.md` の項番を含め、対応関係を保つこと。session CLI の全コマンド（navigate / reload / comment 等）は `hunk skill path` で表示される同梱スキルが正本。**REVIEW-N.md が正本であることは変わらない** — hunk 注釈は人間が diff 上で指摘を追うための補助であり、レビュー記録の代替ではない。レビュー完了後（APPROVED / ABORTED）は hunk pane も `herdr pane close` で片付ける（split で増やした pane を閉じても Codex の root pane には影響しない。逆に hunk pane を閉じ忘れると、Codex pane を閉じても Codex 用 workspace が残る。§15）。

---

## 14. 修正ループ

Claude Code が `CHANGES_REQUESTED` と判断した場合、同じ Codex pane を使い、`FIX-N.md` を作って再度 `/goal` を送る。

### 14.1 `FIX-N.md` テンプレート

```md
# Fix Request <N>: <TASK_ID>

Review result: CHANGES_REQUESTED

## Read first
- .ai/tasks/<TASK_ID>/PLAN.md
- .ai/tasks/<TASK_ID>/REVIEW-<N>.md
- .ai/tasks/<TASK_ID>/CODEX_DONE.md

## Must fix
1. <file path>
   - Problem: ...
   - Expected: ...
   - Test: ...

2. <file path>
   - Problem: ...
   - Expected: ...
   - Test: ...

## Do not
- Do not rewrite unrelated modules.
- Do not broaden scope beyond PLAN.md.
- Do not modify files unrelated to the review findings.

## Validation
- <command>
- <command>

## Done condition
- All Must fix items are addressed.
- CODEX_DONE.md is updated.
- Print exactly HERDR_TASK_DONE:<TASK_ID>:fix-<N> as your final message, on its own with nothing else in that message.
```

### 14.2 修正 goal の投入

方向転換する前に、必要なら既存 goal を clear する。

```bash
herdr agent prompt "$AGENT" "/goal clear"
```

修正 goal を送り、完了まで待つ（§10 と同じ `prompt --wait` 型をバックグラウンドで。
stalled / timeout エラーなら画面確認→送達済みか判断→対処。§2.3）。

```bash
FIX_N="01"   # 2桁（marker の照合が fix-[0-9]{2} のため）
FIX_GOAL="/goal Read .ai/tasks/$TASK_ID/FIX-$FIX_N.md and apply only those fixes. Update CODEX_DONE.md. When complete print HERDR_TASK_DONE:$TASK_ID:fix-$FIX_N."

touch "$TASK_DIR/logs/fix-$FIX_N.sent"   # CODEX_DONE.md が更新されたかの比較用
herdr agent prompt "$AGENT" "$FIX_GOAL" --wait \
  --until idle --until done --until blocked --until unknown \
  > "$TASK_DIR/logs/prompt-wait-fix-$FIX_N.json" 2>&1
jq -r '.result.agent.agent_status // .error.code // .' "$TASK_DIR/logs/prompt-wait-fix-$FIX_N.json"
```

返ったら §2.3 の「完了の確認」を行う。CODEX_DONE.md が FIX を送った後に更新されて
いること（`[ "$TASK_DIR/CODEX_DONE.md" -nt "$TASK_DIR/logs/fix-$FIX_N.sent" ]`）、見つかった
最後の marker が `•HERDR_TASK_DONE:$TASK_ID:fix-$FIX_N` であることを確かめる（前ラウンドの
marker や CODEX_DONE.md を取り違えないため）。

### 14.3 ループ上限

Claude Code は無限に修正ループを回さない。

```text
デフォルト上限: 3ラウンド
```

3ラウンドで収束しない場合:

```text
1. REVIEW-FINAL.md に ABORTED または BLOCKED を書く
2. 未解決点を箇条書きにする
3. 現在の diff / pane log / status を保存する
4. 同じ pane の文脈が汚れている可能性があれば pane を閉じる
5. 必要なら新しい Codex pane を起動し、PLAN.md + 最新 REVIEW/FIX + 現在 diff を読ませて再開する
```

---

## 15. pane を閉じるタイミング

Codex が `HERDR_TASK_DONE` を出した瞬間には pane を閉じない。

pane close の条件:

```text
Claude Code review: APPROVED または ABORTED
Codex status: done または idle
未処理の blocked 質問: なし
CODEX_DONE.md: あり
REVIEW-FINAL.md: あり
final diff / status / pane output: 保存済み
次の FIX-N.md を投げる予定: なし
```

閉じてはいけないタイミング:

```text
Codex が HERDR_TASK_DONE を出した直後
Claude Code のレビュー前
Codex が working
Codex が blocked
FIX-N.md を投げる予定がある
```

pane cleanup:

```bash
herdr agent read "$AGENT" \
  --source recent-unwrapped \
  --lines 500 \
  > "$TASK_DIR/logs/codex-final-pane.txt"

git -C "$WT" status --short \
  > "$TASK_DIR/logs/final-status.txt"

git -C "$WT" diff \
  > "$TASK_DIR/logs/final.diff"

herdr pane close "$PANE_ID"
```

pane close の結果: Codex 用 workspace の最後の pane なので、workspace ごと閉じて
サイドバーの `└` の行も消える（0.9.3 実測）。委譲元 workspace には影響しない。

§13.1 で hunk pane を split した場合は、先にそれも閉じる（残っていると workspace が消えない）。

作業を中止する場合は、いきなり閉じずに可能なら Codex に pause を送る。

```bash
herdr agent prompt "$AGENT" "/goal pause"
```

その後にログ保存、`REVIEW-FINAL.md` 作成、pane close を行う。

---

## 16. 承認後の取り込み（commit → merge / PR）

`REVIEW-FINAL.md` に APPROVED を書いて pane を閉じたら、Claude Code が成果を取り込み可能な状態にする。レビューは未コミット diff に対して行うため、承認後のコミットが必要になる。

```text
1. Claude Code が Codex worktree でコミットする
   - コミットは Claude Code の担当（Codex にはさせない）。
   - PLAN.md の Objective を要約したメッセージに TASK_ID を含める。
   - .ai/ は info/exclude 済みだが、コミット前に git status で混入がないことを確認する。
2. superpowers:finishing-a-development-branch スキルを起動する
   - merge / PR / 保留 / 破棄 の選択肢を人間に提示し、決定に従う。
   - スキルが使えない環境では、同等の選択肢を人間に確認してから実行する。
   - PR を作ると決まったら、gh pr create の前に本文を yomiyasu で推敲する（§16.1。任意）。
3. 決定を実行したら（merge 完了 / reject）、§17 の worktree cleanup に進む。PR を作った場合は、
   PR がマージ（またはクローズ）されるまで worktree を残し（レビュー対応の修正に使う）、その後 §17 に進む
```

```bash
git -C "$WT" status --short    # .ai/ や無関係ファイルが混ざっていないこと
git -C "$WT" add -A
git -C "$WT" commit -m "<type>: <PLAN.md の Objective 要約> ($TASK_ID)"
```

注意:

- §15 の final ログ保存を先に済ませること（`final.diff` は未コミット状態の記録として残す）。
- PR にする場合のブランチは §6 で作った `ai/<TASK_ID>`。push の可否・リモート・レビュー運用はプロジェクト規約に従う。
- 人間が破棄（reject）を選んだ場合、コミット済みのブランチごと §17 の cleanup で worktree を破棄してよい（変更内容は `logs/final.diff` にも保存済み）。人間が事前に破棄を明言している場合は、コミット自体を省略して §17 に進んでよい。

### 16.1 PR の本文の推敲（yomiyasu。任意）

PR を作ると決まったら、`gh pr create` の前に本文を [yomiyasu](https://github.com/nanaism/yomiyasu)（AI が書いた日本語を読みやすく直すスキル）で推敲してから使う。PR の本文は人間が読む文章なので、ここで使う。コミットメッセージ・`PLAN.md`・`CODEX_GOAL.md`・`REVIEW-N.md` には使わない。

```text
1. 本文を .ai/tasks/<TASK_ID>/PR_BODY.md に書く。
2. 次のどちらかに当たれば、この節の 3 を飛ばして 4 に進む。
   - 本文が日本語でない（yomiyasu は日本語専用）
   - スキル一覧に yomiyasu:yomiyasu（プラグインで入れた場合）も yomiyasu（npx skills などで
     入れた場合）も無い（dev-workflow は yomiyasu を必須にしない）
3. 一覧にあるほうの名前で yomiyasu を起動し、「PR_BODY.md を推敲し、最終稿を同じフォルダの
   PR_BODY.final.md に保存して」と頼む（ファイルを渡したときの保存先は yomiyasu が決めないので、
   名前を指定する）。PR_BODY.final.md ができたことを確かめる。
   - yomiyasu が「書き手に確かめたい点」を返したら、本文を書いた Claude Code が PLAN.md・
     REVIEW-*.md・会話から答えて推敲し直す。答えが決まらないものだけを人間に聞く。
   - 推敲の前後の差分は人間に見せない。
4. gh pr create --body-file .ai/tasks/<TASK_ID>/PR_BODY.final.md を実行する（3 を飛ばしたときは PR_BODY.md）。
```

yomiyasu は状態フォルダ `.yomiyasu/` を git リポジトリの最上位に作るが、中に自分で `.gitignore` を置くので、`.ai/` と違って `.git/info/exclude` に足さなくてよい（レビュー対応のコミットの `git add -A` にも混ざらない。yomiyasu 2.1.1 で確認）。

---

## 17. worktree cleanup のタイミング

pane close と worktree remove は別物である。

```text
pane close（§15）:
  Codex のプロセス・画面を閉じる。Claude Code の最終レビュー後に行う。
  Codex 用 workspace も一緒に消える。checkout は残る。

worktree remove:
  Git worktree checkout を削除する。merge / PR / reject が終わった後だけ行う。
  必ず pane close の後に行う（Codex が中で動いたままディレクトリを消さない）。
```

作業ブランチを採用する前に worktree を消さない。

```bash
git -C "$ROOT" worktree remove "$WT"
git -C "$ROOT" branch -d "$BRANCH"   # merge 済みの場合。reject なら -D
```

- PR を作った場合は、PR がマージされるまで worktree もブランチも消さない。マージ後に
  上記（`branch -d`）を行う。PR をマージせずにクローズしたら reject と同じく `-D`
  （PR 作成時に push 済みなので、ローカルを消してもリモートのブランチは残る）。

- `.ai/` は info/exclude で無視されているので、残っていても `worktree remove` は
  `--force` なしで通る（2026-10-13 実測）。ただし checkout ごと消えるので、残したい
  ログは事前に退避しておく。
- Git が未コミットの変更を理由に拒否した場合、`git -C "$ROOT" worktree remove --force "$WT"`
  を使うのは、`logs/final.diff` を保存済みで、かつ人間が破棄を選んだときだけにする。
- pane を閉じずに中止した場合（§14.3 等）も、先に `herdr pane close "$PANE_ID"` してから
  上記を行う。

### 17.1 旧方式（2026-10-13 改訂（skill 1.4.0 / plugin 1.5.0）より前）のレーンの片付け

2026-10-13 改訂（skill 1.4.0 / plugin 1.5.0）より前の本手順は `herdr worktree create` でレーンを作っていた。そのとき作られた
worktree グループの子 workspace（`is_linked_worktree: true`）が残っている場合は、
次のルールで片付ける。

```text
workspace がまだ開いている:
  herdr worktree remove --workspace <id> で checkout と workspace を両方消す
  （pane 内でプロセスが生きていて拒否される場合のみ --force）。
workspace は閉じている:
  git worktree remove + branch -d で消す（herdr worktree remove は workspace_not_found）。
workspace が開いたまま git 側だけ消した:
  参照先のないゾンビ workspace が残る → herdr workspace close <id>。
workspace close --group:
  primary と linked をまとめて閉じるフラグ。workspace_group_close_required の
  エラー回避のために付けてはいけない（ユーザーが明示した場合のみ）。
--trust-repository:
  1リクエスト限りの Git trust。失敗時の再試行フラグではなく、ユーザーが
  リポジトリを確認済みのときだけ使う。
herdr worktree create:
  引数なしでも既定値で worktree を即作成する（0.7.4 実測）。usage 確認目的で叩かない。
```

ゾンビ workspace の検出と一括掃除:

```bash
# linked worktree の workspace だけを対象にする。repo root で開いた通常の
# workspace にも worktree オブジェクトが付く（is_linked_worktree: false）ため、
# `.worktree != null` では通常 workspace まで対象に含めてしまう。
# is_linked_worktree == true で絞ること（true 判定なので jq の // は使わない —
# false // x は x になる）。
herdr workspace list \
  | jq -r '.result.workspaces[] | select(.worktree.is_linked_worktree == true) | [.workspace_id, .worktree.checkout_path] | @tsv' \
  | while IFS=$'\t' read -r ws path; do
      [ -n "$path" ] && [ ! -d "$path" ] && herdr workspace close "$ws"
    done
```

---

## 18. blocked / failed / unknown の扱い

### 18.1 Codex が blocked

Claude Code は pane を閉じない。

```text
1. herdr agent read で出力を読む
2. BLOCKED.md があれば読む
3. 必要な情報を Claude Code が判断できるなら、CLARIFICATION.md または FIX-N.md を作る
4. Codex に再 /goal または必要な回答を送る
5. 人間の判断が必要なら REVIEW-FINAL.md に BLOCKED を書いて報告する
```

codex-cli 0.155+ は、goal の自動継続ターンが3回続けて空（進捗なし）だと goal
自体を blocked にする（#44320）。この場合 BLOCKED.md が無いこともあるので、
agent read で「goal blocked」系の表示を確認し、FIX-N.md で具体的な次の一手を
与えて再 /goal する。

### 18.2 Codex が done / idle だが CODEX_DONE.md がない

実装完了とみなさない。

ただし diff も CODEX_DONE.md も無く marker も無い done は、goal が Codex の
ダイアログ（hooks レビュー画面等）に飲み込まれた可能性が高い（§9-5）。まず visible
read で画面を確認し、ダイアログを閉じてから同じ goal を送り直す。この送り直しは
修正ループのラウンドに数えない。Codex が goal を実行したのに CODEX_DONE.md が無い
場合だけ、次を返す。

```text
Status: CHANGES_REQUESTED
Required fix: CODEX_DONE.md を作り、変更点・テスト・リスクを記録すること。
```

### 18.3 marker がない

`CODEX_DONE.md` と diff が妥当ならレビューに進んでよい。ただし、`REVIEW-N.md` に `Completion marker was missing` と記録する。

### 18.4 Herdr status が unknown

```bash
herdr agent explain "$AGENT" --json || true
# unknown では履歴の読み取りが agent_not_idle になるので visible を読む（公式 Agent automation）
herdr agent read "$AGENT" --source visible
herdr pane get "$PANE_ID"
```

画面出力・diff・task files で判断し、不明なら `BLOCKED` として人間に報告する。

### 18.5 Codex が scope を広げた

Claude Code は `CHANGES_REQUESTED` とし、`FIX-N.md` で unrelated change の revert を要求する。

---

## 19. 安全ルール

Codex には次を許可しない。必要な場合は人間の明示承認を求める。

```text
- production deploy
- publish / release
- secret / credential の表示・変更・送信
- destructive DB operation
- rm -rf や大量削除
- unrelated large refactor
- dependency major upgrade
- security bypass
- network access が必要な操作
```

Codex がこれらを実行しようとして blocked になった場合、Claude Code は原則として拒否し、安全な代替を `FIX-N.md` に書く。

---

## 20. Claude Code 用の実行チェックリスト

ユーザーが「Codex に実装を委譲して」「Herdr 経由で Codex にやらせて」などと言ったら、Claude Code は次を実行する。

```text
[ ] task id を作る
[ ] git worktree add で Git worktree を作り、.git/info/exclude に .ai/ を足す（herdr worktree create は使わない）
[ ] Codex 用 workspace を作り、委譲元の直下へ移す（HERDR_PANE_ID があれば pane current → ラベル "└ <TASK_ID>" で workspace create → place-lane.sh で委譲元の直下へ。なければ単独 workspace。応答 JSON の root pane id を // empty 付きで控え、logs/lane.json に委譲元とレーンを記録する。--json は付けない）
[ ] Codex worktree 内に .ai/tasks/<TASK_ID>/ を作る
[ ] superpowers:brainstorming で要件・設計を固める
[ ] superpowers:writing-plans に従って PLAN.md を書く
[ ] CODEX_GOAL.md を書く
[ ] Codex 用 workspace の root pane に Codex を起動する（agent start --kind codex --pane … -- --no-daemon。
    agent_not_ready は起動ダイアログで止まっているだけなので、そのまま次の起動確認へ）
[ ] 起動確認: agent get で生存確認（self-update 終了なら再 start）
[ ] 起動確認: visible read でダイアログの有無と入力プロンプト「›」を確認する
    （アップデートは "2" で Skip（0.160 は Enter 不要）、trust は enter で承認、
      デーモン設定不一致は "1"、hooks レビュー画面は esc。状態は 0.9.1 以前は idle の
      まま、0.9.3 以降は trust/アップデートが blocked で hooks レビュー画面は done のまま。
      状態だけに頼らない。§9）
[ ] 1行の /goal を agent prompt --wait --until idle --until done --until blocked --until unknown で送る
    （timeout なし・run_in_background。抜け条件は状態だけで、marker を待つループは書かない。
      agent_prompt_stalled / timeout なら visible read で画面確認 → 送達済みか
      判断 → ダイアログ対処・Enter のみ・agent wait 合流のいずれか。§2.3・§10）
[ ] §2.3 の「完了の確認」: 状態（working なら agent wait で待ち直す）・CODEX_DONE.md・
    marker（空白・改行を除いて "•HERDR_TASK_DONE:<id>" を探す。完了は通常 done）
[ ] 完了後に pane output / git diff / status を保存する
[ ] CODEX_DONE.md を読む
[ ] Claude Code がレビューして REVIEW-01.md を書く
[ ] 問題があれば FIX-01.md を書いて同じ pane に再 /goal
[ ] 最大3ラウンドまで繰り返す
[ ] APPROVED なら REVIEW-FINAL.md を書く
[ ] final logs を保存する
[ ] Codex pane を閉じる（hunk pane を split していれば先に閉じる。workspace と `└` の行も消える）
[ ] Claude Code が worktree でコミットする（.ai/ 混入なしを git status で確認）
[ ] finishing-a-development-branch で merge / PR / reject を人間に確認する
[ ] PR にするなら本文を yomiyasu で推敲してから gh pr create（§16.1。日本語で yomiyasu があるときだけ）
[ ] worktree は merge / PR / reject まで残す
[ ] merge / reject 後: git worktree remove + branch -d（reject は -D）で checkout とブランチを消す（必ず pane close の後）
```

---

## 21. 参考 wrapper

必要なら、Claude Code は以下の薄い wrapper を `scripts/ai-codex-herdr.sh` として作って使ってよい。

```bash
#!/usr/bin/env bash
set -euo pipefail

resolve_pane_id() {
  local agent="$1"
  herdr agent get "$agent" | jq -r '.result.agent.pane_id? // empty' | head -n 1
}

read_agent_text() {
  # agent read は plain text（0.7.5+。jq を通さない）
  local agent="$1"
  local lines="$2"
  herdr agent read "$agent" --source recent-unwrapped --lines "$lines"
}

find_marker() {
  # Codex が折り返した marker も拾えるよう、空白・改行を除いてから行頭の "•" 付きで
  # 探し、最後に見つかったものを出す（goal のエコー行は "printHERDR_..." になり拾わない）。
  # 履歴の読み取りは idle / done のときしかできないので、それ以外は visible を読む（§2.3）
  local agent="$1"
  local task_id="$2"
  local status src=recent-unwrapped
  status="$(herdr agent get "$agent" 2>/dev/null | jq -r '.result.agent.agent_status // empty' || true)"
  case "$status" in idle|done) ;; *) src=visible ;; esac
  herdr agent read "$agent" --source "$src" --lines 500 2>/dev/null \
    | LC_ALL=C tr -d '[:space:]' \
    | { grep -oE "•HERDR_TASK_(DONE|BLOCKED):$task_id(:fix-[0-9]{2})?" || true; } \
    | tail -n 1
}

usage() {
  cat >&2 <<'USAGE'
usage:
  ai-codex-herdr start <task_id> <pane_id> <task_dir>
  ai-codex-herdr send-goal <task_id> <task_dir>
  ai-codex-herdr wait <task_id> <task_dir>
  ai-codex-herdr read <task_id>
  ai-codex-herdr close <task_id> <task_dir>
USAGE
}

cmd="${1:-}"
shift || true

case "$cmd" in
  start)
    task_id="${1:?task_id required}"
    pane_id="${2:?pane_id required (§6 の workspace create の .result.root_pane.pane_id)}"
    task_dir="${3:?task_dir required}"
    agent="codex-$task_id"
    mkdir -p "$task_dir/logs"

    # agent start は既存 pane への起動（--kind --pane 必須）。ready 検出まで
    # 待ってから返る（既定 30s）。cwd は pane から引き継がれる。
    # 起動ダイアログで blocked になると agent_not_ready（exit 1）で返るが、起動確認へ進む（§9）
    herdr agent start "$agent" --kind codex --pane "$pane_id" -- --no-daemon \
      > "$task_dir/logs/agent-start.json" 2>&1 || true
    jq -r '.result.agent.agent_status // .error.code // .' "$task_dir/logs/agent-start.json"

    # 起動確認: self-update 即終了なら agent_not_found。ダイアログ
    # （アップデート/trust 等）は状態だけでは判断できないので画面を目視確認する。
    herdr agent get "$agent" | tee "$task_dir/logs/agent-get.json"
    herdr agent read "$agent" --source visible --lines 40
    ;;

  send-goal)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    agent="codex-$task_id"

    goal_text="/goal Read .ai/tasks/$task_id/CODEX_GOAL.md and implement it exactly. When complete print HERDR_TASK_DONE:$task_id; if blocked print HERDR_TASK_BLOCKED:$task_id."

    # 0.8.0 主経路: 送信 + 待ちを1コマンドで。バックグラウンドで実行する前提で
    # timeout は付けず、working 以外（unknown を含む。§2.3）になった時点で返る。
    # 送信後5秒以内に working|blocked が観測できなければ agent_prompt_stalled が
    # 返る（→ visible read で画面確認。未送達とは限らないので §2.3 の判断に従う）。
    herdr agent prompt "$agent" "$goal_text" --wait \
      --until idle --until done --until blocked --until unknown \
      > "$task_dir/logs/prompt-wait-result.json" 2>&1 \
      || echo "warning: prompt failed (stalled?) — check visible screen" >&2
    cat "$task_dir/logs/prompt-wait-result.json"

    read_agent_text "$agent" 500 \
      > "$task_dir/logs/codex-after-goal.txt" || true
    echo "marker: $(find_marker "$agent" "$task_id")"
    ;;

  wait)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    agent="codex-$task_id"

    # 早く返った（作業中に一瞬 unknown になった）ときなどの待ち直し用。
    # agent wait は現在の状態が一致していると即座に返るので、working のときだけ待つ。
    status="$(herdr agent get "$agent" 2>/dev/null | jq -r '.result.agent.agent_status // empty' || true)"
    if [ "$status" = "working" ]; then
      herdr agent wait "$agent" \
        --until idle --until done --until blocked --until unknown || true
      status="$(herdr agent get "$agent" 2>/dev/null | jq -r '.result.agent.agent_status // empty' || true)"
    fi

    echo "status: ${status:-agent_not_found}"
    # unknown で成果物も marker も無いときは、§2.3 のとおり短い agent wait で作業中かを確かめる
    stamp="$(date +%Y%m%d-%H%M%S)"
    read_agent_text "$agent" 500 \
      > "$task_dir/logs/codex-pane-$stamp.txt" || true
    echo "marker: $(find_marker "$agent" "$task_id")"
    ls -l "$task_dir/CODEX_DONE.md" "$task_dir/BLOCKED.md" 2>/dev/null || true
    ;;

  read)
    task_id="${1:?task_id required}"
    agent="codex-$task_id"
    read_agent_text "$agent" 200
    ;;

  close)
    task_id="${1:?task_id required}"
    task_dir="${2:?task_dir required}"
    agent="codex-$task_id"
    pane_id="$(resolve_pane_id "$agent")"
    test -n "$pane_id"

    mkdir -p "$task_dir/logs"
    read_agent_text "$agent" 500 \
      > "$task_dir/logs/codex-final-pane.txt"

    herdr pane close "$pane_id"
    ;;

  *)
    usage
    exit 2
    ;;
esac
```

---

## 22. Claude Code への最終指示

Claude Code は、このワークフローでは次を厳守する。

```text
- Codex にいきなり実装させず、先に PLAN.md を作る。
- PLAN.md の前に superpowers:brainstorming、執筆に superpowers:writing-plans を使う。
- Codex に長文を直接 paste せず、1行の /goal で CODEX_GOAL.md を読ませる。
- Herdr は agent CLI を主軸にし、/goal は agent prompt --wait で送って待つ。
  pane CLI は pane 用意 / send-text / close に使う（marker の検出に wait-output は使わない）。
- socket API は §6 のレーンの並べ替え（place-lane.sh）だけに使う。
- Codex レーンは git worktree add + 委譲元の直下に置く専用 workspace（疑似ツリー。§6）に作り、その root pane に `--no-daemon` で起動する（agent start --kind codex --pane … -- --no-daemon）。herdr worktree create は使わない。
- 起動直後に送信しない。生存確認と visible read（ダイアログ有無）を先に行う。
  ダイアログの状態判定（idle / blocked）は herdr の版と検出 manifest で変わるので、
  状態だけに頼らず画面で判断する（§9）。hooks レビュー画面は遅れて出て goal を
  飲み込み、prompt --wait が done を返すことがある — marker がなければ画面を確認する。
- 完了待ちは agent prompt --wait --until idle --until done --until blocked --until unknown
  を timeout なしでバックグラウンド実行する（herdr 0.9.3 以前の Codex は応答後に unknown のまま残ることがある）。
  抜け条件は状態だけにし、marker を待つループを書かない。返ったら §2.3 の「完了の確認」。
  完了状態は通常 done（CLI 駆動では未読完了が done。0.8.0 公式セマンティクス）。
- agent_prompt_stalled / timeout が返ったら画面確認 → 送達済みか判断 → 対処
  （盲目的な再送はしない。§2.3）。herdr 側の偽 done は 0.8.0 以降ないが、goal が Codex のダイアログ（hooks レビュー画面等）に飲み込まれると done で返る（§9）。
- agent read / pane read は plain text。jq を通さない（agent get 等の JSON とは別）。
  JSON がデフォルトなので --json は付けない。
- marker は agent read の出力から空白・改行を除き、"•HERDR_TASK_DONE:<id>" の形で探す。
  Codex は pane の幅で marker を折り返すことがあり、pane wait-output（1行ずつ照合）や
  行頭アンカーの regex では見つからない。素の substring だと goal エコー行に偽マッチする。
  marker は補助で、主な判断材料は CODEX_DONE.md と diff。
- 「完了の確認」（状態・CODEX_DONE.md・marker）はレビュー開始トリガーであり、pane close トリガーではない。
- pane は Claude Code が APPROVED または ABORTED を書いた後に閉じる。
- 修正が必要なら同じ Codex pane に FIX-N.md を再 /goal する。
- 3ラウンド以上は自動で回し続けない。
- 承認後のコミットは Claude Code が行い、merge / PR / reject は
  finishing-a-development-branch で人間に確認する。勝手に merge しない。
- source of truth は task files と git diff と test 結果であり、画面出力だけではない。
```
