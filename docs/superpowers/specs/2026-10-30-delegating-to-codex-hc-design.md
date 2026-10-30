# delegating-to-codex を herdr-core (hc) で動かす 設計

2026-10-30

## 目的

delegating-to-codex は、Claude が計画を書き、herdr TUI の pane で動かした Codex に 1 行の `/goal` で
実装させ、レビューと修正のループを回す手順書 (`workflow.md`) と補助スクリプトでできている。

2026-10 に herdr から herdr-core (`hc`) と、その上で動くデスクトップアプリ Herdr が出た。ユーザーは
Herdr を本格的に使うことにしたので、委譲も hc の上で動くようにする。

hc には、今の手順書が herdr TUI の上で無理に作っていたものが最初から入っている。

| 今の手順書の工夫 (herdr TUI) | hc で置き換わるもの |
|---|---|
| 委譲元の下にレーンを見せる疑似ツリー (`└` ラベル + `place-lane.sh` の `workspace.move_block`) | Claude の中から `hc run` すると Codex は Claude の子になり、Herdr のエージェント一覧で Claude の下に出る |
| `agent prompt --wait` の stalled 判定・`--until unknown` の付け足し | Codex 自身が OSC 7501 で working / done / blocked を報告し、`hc wait` がそれを待つ |
| 折り返しに強い marker 検索 | 完了は状態と `CODEX_DONE.md` で判定できる |
| terminal id が再起動で変わる問題 | 名前 (`--name`) で指せる |

## 完了した状態

1. Herdr アプリのターミナルの中で動く Claude が delegating-to-codex を使うと、Codex が hc のターミナルで
   動き、Herdr のエージェント一覧でその Claude の子として見える。
2. herdr-core の外 (cmux や herdr TUI の中) の Claude が使っても動く。Herdr アプリが動いていれば、
   Codex は Herdr にタスク用の space として見える。
3. 契約ファイル (`.ai/tasks/<TASK_ID>/` の `PLAN.md`・`CODEX_GOAL.md`・`CODEX_DONE.md`・`REVIEW-N.md`・
   `FIX-N.md`・`REVIEW-FINAL.md`・`logs/`)、レビューと修正のループ (最大 3 ラウンド)、承認後の取り込み
   (Claude のコミット → finishing-a-development-branch → PR 本文の yomiyasu) は今と同じ。
4. `check-versions.sh` が hc を確かめる (版・core が動いているか)。
5. 実際に 1 件委譲して、起動 → `/goal` → 完了 → 修正ラウンド 1 回 → 片付けまでが通っている (E2E)。
   herdr-core の中の Claude からと、外の Claude からの両方で確認している。
6. SKILL.md・workflow.md・versions.json・README・hooks の文言・テストが hc に合っている。プラグインの版は
   2.0.0 (herdr TUI での委譲をやめる破壊的変更のため)。

## 非目標

- **herdr TUI での委譲は残さない。** 両方を手順書に持つと、1500 行の手順書の分岐が倍になる。hc は
  herdr-core が入っていればどこからでも使える (Claude がどのターミナルにいても動く) ので、TUI 版は要らない。
  TUI 版は git の履歴 (plugin 1.8.0) に残る。
- hc の templates (`~/.config/herdr-core/templates/`) は使わない。プラグインの外のマシン別ファイルに
  依存させない。
- 別マシンでの委譲 (`hc run --on`)。Claude と Codex は同じマシンで動かす (macmini の Claude なら
  macmini の core で動くので、特別な扱いは要らない)。
- Codex から Claude への `hc send` での報告。下の「決めたこと」参照。

## 前提 (2026-10-30 に実測・ドキュメントで確認)

- hc 0.1.14 / Herdr 0.1.8 / codex-cli 0.164.0 / Claude Code 2.1.314。
- Codex 0.164 は OSC 7501 を出す (バイナリに `]7501;state=` がある)。hc は状態を OSC 7501 からだけ取り、
  画面からは推測しない。
- hc の主なコマンド (詳しくは `hc --skill` と `hc <command> --help`):
  - `hc run --bg --name <n> --cwd <dir> [--outlive-parent] [--no-notify] [--label k=v] <argv...>`。
    hc のターミナルの中から起動すると、起動元が親になる (`--parent` / `--no-parent` で変えられる)。
    親が終わると子も終わる (`--outlive-parent` を除く)。名前は 1〜32 文字の `a-z 0-9 - _`。
  - `hc wait <t> [--timeout S]`: 作業中でなくなる (または終了する) まで待つ。既定 180 秒で
    `reason: timeout` として戻る (失敗ではない。待ち直す)。sleep で回すのは禁止 (hc の規約)。
  - `hc send <t> <text> [--wait] [--if idle]`: 貼り付けて Enter。相手が blocked なら `--force` なしでは拒否。
  - `hc keys <t> enter|esc|...`・`hc read <t> --lines N`・`hc get <t>`・`hc interrupt <t>`・`hc kill <t>`・`hc rm <t>`。
  - エラーは stderr の `{error: {kind, message, hint}}`。exit code: 3 not_found・9 blocked・
    10 status_mismatch・11 finished など。
- hc の規約: **Codex は `--no-daemon` で起動しなければならない** (そうしないとコマンドが hc の外で動く)。
- 2026-10-30 の別セッションでの試し (airoa、`hc-visible/RESULT.md`):
  - Claude (hc の中) から `hc run --bg` で起動した Codex は Claude の子になった (`parent: t8`)。
  - 起動直後にフォルダの trust 確認が出て、`hc keys <t> enter` で進んだ。
  - Codex からの `hc send <親>` は、Claude の次の入力として割り込む形で届いた。
- Herdr アプリでは、hc で起動したターミナルは `herdr.space=<id>` (と任意で `herdr.tab=<id>`) のラベルが
  あるときだけ画面に出る。ラベルの無いもののうち、エージェントの子 (sub-agent) は親のタブに属し、
  エージェント一覧に出る (ピークで見られる・タブとして残せる)。それ以外は見えない。
- `herdr-app do space.new --name <n> --folder <dir>` で space を作れる (作った ID が返る)。
  `herdr-app ls`・`herdr-app status` で今の画面を確かめられる。

## 設計

### 1. 全体の流れ (今と同じ部分と変わる部分)

0. `check-versions.sh` (hc に合わせて書き直す)
1. `git worktree add` + `.git/info/exclude` に `.ai/` (今と同じ)
2. brainstorming → writing-plans で `PLAN.md`、`CODEX_GOAL.md` (今と同じ)
3. **Codex を hc で起動** → 起動の確認 (ダイアログの処理) → `/goal` を送る → `hc wait` で待つ
4. レビュー → `REVIEW-N.md` (今と同じ)
5. 直すところがあれば `FIX-N.md` → **同じ Codex に `hc send` で `/goal`** → 待つ (最大 3 ラウンド)
6. 承認 → `REVIEW-FINAL.md` → ログの保存 → **`hc kill` + `hc rm`** (作った space があれば閉じる) →
   Claude がコミット → finishing-a-development-branch (今と同じ)
7. merge / reject の後に `git worktree remove` (今と同じ。必ず 6 の片付けの後)

### 2. Codex の起動と見せ方

Claude がどこで動いているかで分ける。

- **herdr-core の中 (`HC_TERMINAL_ID` がある)**: `hc run --bg --name <codex名> --cwd <worktree>
  --outlive-parent --no-notify codex --no-daemon`。Codex は Claude の子になり、Herdr のエージェント一覧で
  その Claude の下に出る。ラベルは付けない。
- **herdr-core の外**: Herdr アプリが動いていれば、`herdr-app do space.new` でタスク用の space
  (名前は TASK_ID が分かるもの、フォルダは worktree) を作り、`--label herdr.space=<id>` を付けて起動する。
  アプリが動いていなければラベル無しで起動し、`hc attach <codex名>` で見られることをユーザーに伝える。
- どちらでも、委譲元 (Claude の `HC_TERMINAL_ID` があればそれ)・Codex の名前・作った space の ID を
  `logs/lane.json` に残す (片付けと「どの Claude が起動したか」の確認に使う)。

`/goal` は起動の引数に含めず、起動して準備ができてから `hc send` で送る。`/goal` が Codex の入力欄で
slash command として解釈されることを確実にするため (起動引数の prompt が slash command として扱われるかは
確かめていない)。

### 3. 起動の確認とダイアログ

起動直後に出うるもの (codex-cli 0.160〜0.164 の実績) を、`hc get` の状態と `hc read` の画面で判断する:

- フォルダの trust 確認 → `hc keys <codex名> enter`
- 対話式のアップデート確認 → Skip を選ぶ (今の手順書では "2" → Enter。`hc keys` で同じ操作をする)
- hooks のレビュー画面 → `hc keys <codex名> esc` (trust all の `t` は押さない)
- 共有デーモンの設定不一致 → `--no-daemon` で起動していれば出ない

入力欄 (`›`) が出て、状態が idle (または報告なし) になったら `/goal` を送る。`hc send` が blocked で
拒否されたら、`--force` は使わず画面を読んで上のダイアログを処理する。

### 4. 待ち方と完了の判定

- Claude は Bash の `run_in_background` で、`hc wait <codex名>` を `reason: timeout` の間だけ繰り返すループを
  回し、作業中でなくなったら抜ける。sleep で回さない。
- 抜けたら `hc get` の状態で分ける: `done` / `idle` → `CODEX_DONE.md` を確かめる。`blocked` → 画面を読み、
  ダイアログか人の判断が要る質問かを見る (人の判断が要るならユーザーに聞く)。`error` → 画面を読む。
  ターミナルが終わっていたら (`finished`) → 画面とログを確かめ、必要なら起動し直す。
- **完了は状態と `CODEX_DONE.md` で判定する。** marker (`•HERDR_TASK_DONE:<id>`) はやめる。
  どのラウンドの完了かは `CODEX_DONE.md` に書かせる (ラウンド名の行など。形は実装に任せる)。
- `/goal` が複数のターンにまたがって途中で一度 done になる場合もあるので、`CODEX_DONE.md` が無いのに
  done なら、すぐ送り直さず画面を読む (今の手順書の §18.2 の考え方を引き継ぐ)。

### 5. 修正ラウンド・片付け

- 修正は同じ Codex に `hc send <codex名> "/goal Read .ai/tasks/<id>/FIX-N.md ..."`。
- 承認後: `hc kill <codex名>` → `hc rm <codex名>`。space を作っていたら閉じる (閉じ方は実装で
  `herdr-app commands` から確かめる)。worktree の削除は今まで通りその後。
- 旧方式 (herdr TUI) のレーンが残っている場合の片付けは、短い節として残す (今の §17.1 と同じ扱い)。

### 6. 消すもの・書き直すもの

- 消す: `place-lane.sh` とそのテスト、疑似ツリーの説明、marker の検索、`agent prompt` の stalled の扱い、
  `--until unknown`、protocol_mismatch の注意など herdr TUI 固有の記述。
- `check-versions.sh` / `versions.json`: herdr を hc に置き換える (`hc --version` の版を same-minor で照合、
  core が動いているか)。herdr-app は任意 (無ければ INFO。見せ方が変わるだけ)。codex の検証済みを 0.164.0 に。
  herdr の `on_newer` (入れ子表示待ち) は役目を終えたので消す。
- SKILL.md: Quick Reference と Common Mistakes を hc の操作と罠に書き直す。
- workflow.md: §2.1・§2.3・§6・§9〜§11・§13.1・§15・§17・§18・§21 を中心に hc に書き直す。契約ファイルの
  テンプレート (§7・§8・§13・§14) は、marker の行を消す以外は変えない。
- hooks の文言: `session-rules.sh` の「(herdr / /goal)」、`prompt-rules-reminder.sh` の「pane run で 1行
  /goal、idle+marker 待ち」を hc に合わせる。反応する語に `hc` を足すかは実装に任せる。
- README・plugin.json の説明・プラグインと skill の版 (2.0.0)。

## 決めたこと (Claude の判断。ユーザーは質問を省いて任せた)

- **herdr TUI 版は残さず hc 版に置き換える。** 上の非目標を参照。
- **`--outlive-parent` を付ける。** Claude のセッションを閉じたり再開したりしても、作業中の Codex が
  巻き添えで終わらないようにする (今の herdr TUI のレーンも Claude とは独立に生きている)。
- **`--no-notify` を付け、Codex に `hc send` で報告させない。** どちらも Claude の端末に文字を打ち込む。
  Claude が作業中なら次のユーザー入力として割り込み、ユーザーがその Claude の入力欄に打っている途中なら
  そこに混ざる。待ちは `hc wait` で足りるので、報告はファイル (`CODEX_DONE.md`) に一本化する。
- **marker をやめる。** OSC 7501 の状態と `CODEX_DONE.md` で足りる。折り返しに弱い仕組みを残す理由が無い。
- **herdr-core の外の Claude からは、Herdr アプリが動いていれば space を作って見せる。** ラベルが無いと
  Herdr に出ないため。

## 実装に任せること

- `--outlive-parent` を付けても、Herdr のエージェント一覧で委譲元の下に表示されるか。表示されないなら
  ユーザーに見える方を優先して、`--outlive-parent` を外すか (外すときは Claude を閉じると Codex も終わる
  ことを手順書に書く)、Claude の space / tab のラベルを付けるかを決め、理由を手順書に残す。
- `herdr-app do space.new` で作った space に、Codex 以外の既定のタブ (シェル) ができるかと、その扱い。
- アップデート確認の Skip を `hc keys` でどう押すか (`hc keys <t> 2 enter` で足りるか)。
- `hc wait` を回すループの形 (JSON の `reason`・`status` の見方)。
- `CODEX_DONE.md` でのラウンドの見分け方。
- テスト: `test-check-versions.sh` を hc に合わせる。`test-place-lane.sh` は消す。`test-section-refs.sh`
  (節番号の参照の検査) が通るように節を振り直す。

## 検証

- `plugins/dev-workflow/tests/` のテストがすべて通る (CI の `test.yml` と同じもの)。
- E2E (Claude が実際に委譲する。小さなおもちゃの repo で):
  - herdr-core の中の Claude から: 起動 → ダイアログ処理 → `/goal` → 完了 → `REVIEW-1.md` で 1 つ直させる →
    `FIX-1.md` で `/goal` → 完了 → 承認 → 片付け。Herdr のエージェント一覧で Codex が Claude の下に
    見えることを `herdr-app ls` と `herdr-app shot` で確かめる。
  - herdr-core の外 (cmux + herdr TUI) の Claude から: 同じ流れで、Codex がタスク用の space に見え、
    片付けで space が消えること。
- 結果を versions.json の `verified_at` と note に残す。
