# CSVスキーマ

`04-01-split-sentences`〜`06-01-load-to-db`の間、`output/<論文名>/`配下のCSVが前処理パイプラインの
中心的な中間データ形式。列定義・付随するフラグCSVの仕様は複数のSkillに分散しているため、
本ドキュメントに一元化する。パイプライン全体における位置づけは[01_workflow.md](01_workflow.md)、
最終的な保存先のDBスキーマは[03_db.md](03_db.md)を参照。

## `<論文名>.csv`（メインのCSV）

[04-01-split-sentences](../.claude/skills/04-01-split-sentences/SKILL.md)（`postprocess/src/split_sentences.py`）が生成し、
`04-02-review-split`・`05-01-translate`・`05-02-review-translation`が値を埋めながら`06-01-load-to-db`まで引き継がれる、1論文＝1ファイルのCSV。

| 列 | 型 | 説明 |
| --- | --- | --- |
| `paper_id` | text | 論文の識別子。1つのCSVには単一の`paper_id`のみ |
| `sentence_id` | text | 文の識別子。`{paper_id}-{order:05d}`形式（例: `paper-00042`） |
| `page_number` | int (空欄可) | 元PDF上のページ番号。現状`split_sentences.py`が未対応のため常に空欄 |
| `order` | int | 論文内での出現順（1始まりの連番）。DB上は予約語回避のため`sentence_order`列に対応 |
| `type` | text | `heading` / `body` / `caption` / `footnote` / `reference` のいずれか（下表参照） |
| `heading_level` | int (空欄可) | `type=heading`のときの見出しレベル（H1なら1、H2なら2、…）。それ以外は空欄 |
| `original_text` | text | 原文（英語） |
| `translated_text` | text (空欄可) | 翻訳文（日本語）。`05-01-translate`〜`05-02-review-translation`で埋める。`type=reference`は翻訳対象外のため常に空欄 |

### `type`列の値

| 値 | 意味 | 翻訳対象 |
| --- | --- | --- |
| `heading` | 見出し | ○ |
| `body` | 本文 | ○ |
| `caption` | 図表キャプション | ○ |
| `footnote` | 脚注 | ○ |
| `reference` | 参考文献リストの1件 | ×（`translated_text`は空欄のまま） |

### 書き込みルール

- **`04-01-split-sentences`完了以降、`original_text`・`order`・`sentence_id`・`type`・`heading_level`列は変更しない。**
  変更対象は`04-02-review-split`での分割誤り修正、および`translated_text`列のみ
- `translated_text`列への書き戻しは、CSVを直接編集せず必ず`postprocess/src/apply_translations.py`経由で行う
  （カンマ・引用符のエスケープを壊さないため）。入力は`{"sentence_id": "translated_text", ...}`形式のJSON
- `06-01-load-to-db`（`load_to_db.py`）は上記の列構成・`type`値・翻訳要否を保存前に検証する
  （不正があれば保存せずエラー終了。詳細は[03_db.md](03_db.md#dbへの格納処理load_to_dbpy)）

## `<論文名>_flags.csv`（分割レビュー用の自動検出候補）

`split_sentences.py`が`<論文名>.csv`と同時に出力する。`04-02-review-split`が消費し、パイプライン上のファイルとしては残らない。

列: `order, type, reason, detail`

| `reason` | 検出内容 |
| --- | --- |
| `order_not_sequential` | `order`列が1始まりの連番になっていない（分類ロジック自体のバグの兆候。発生したら`split_sentences.py`側の問題として報告する） |
| `unbalanced_math_delimiter` | `$`の数が奇数（`$$`はペアとして除外済み）。数式の途中で分割された疑い |
| `too_short` | `original_text`が20文字未満。文分割の誤爆やページ跨ぎ分断の疑い |
| `no_terminal_punctuation` | 文末が句読点等（`. ! ? : ; ) " ' ” ’ $`）で終わっていない。ページ跨ぎ分断の典型パターン |

既知のfalse positive（対応不要、確認だけして次へ進んでよい）:

- 著者名・所属一覧の行（例: `Jane Doe∗ Example University jdoe@example.com`）: 元々句読点で終わらない正常な行
- ディスプレイ数式ブロック（`$$...$$`）: 数式として完結しているのに句読点が無いだけ
- `**ラベル**`のような孤立した太字ラベル（例: `**Input-Input Layer5**`）: 図の見出しラベルとして正常
- キャプション中の短い断片（pysbdが丸括弧書きや「数字+ピリオド+大文字語」を誤って文境界と認識するクセ。`(right)`等）: 軽微なため許容する既知の限界

## `<論文名>_translation_flags.csv`（翻訳レビュー用の自動検出候補）

`postprocess/src/check_translation.py`が`05-01-translate`完了後のCSVに対して出力する。`05-02-review-translation`が消費する。

列: `order, sentence_id, type, reason, detail`

| `reason` | 検出内容 |
| --- | --- |
| `missing_translation` | 翻訳対象（`type`が`heading`/`body`/`caption`/`footnote`）なのに`translated_text`が空欄 |
| `no_japanese_detected` | `translated_text`に日本語文字が1つも無い（訳し忘れ・原文コピーの疑い） |
| `math_mismatch` | 原文の数式（`$...$`/`$$...$$`）の集合が訳文と一致しない（数式が変更・欠落した疑い） |
| `citation_number_missing` | 原文の引用番号（例: `[13]`）が訳文に見当たらない |
| `reference_should_not_be_translated` | `type=reference`なのに`translated_text`が設定されている（対象外行への誤翻訳） |

## 関連ドキュメント

- [01_workflow.md](01_workflow.md): これらのCSVが生成・更新される前処理パイプライン全体の流れ
- [03_db.md](03_db.md): `06-01-load-to-db`によるDBへの保存先スキーマ
- [postprocess/README.md](../postprocess/README.md): 各Programの実行コマンド詳細
