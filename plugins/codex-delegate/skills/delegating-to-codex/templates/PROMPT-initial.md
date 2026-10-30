# 実装依頼: {task_id} / round {round}

`{task_dir_rel}/PLAN.md` を全て読み、計画の範囲だけをテスト先行で実装する。
不明点で作業できない場合は status を blocked とし、summary に必要な判断を書く。
任意の追加・範囲外のリファクタはしない。

禁止: deploy、publish、秘密情報の取得・変更、ネットワーク、破壊的操作、コミット、subagent。
自分が起動したバックグラウンド処理・ターミナルを全て停止してから報告する。
最終回答は done.schema.json に従う JSON オブジェクトだけにする。
必須項目: status (done または blocked)、summary、changed_files (文字列配列)、tests、risks。
summary / tests / risks は短い日本語。実行した検証と結果を tests に記録する。
