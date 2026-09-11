---
name: 03-02-review-chapter
description: 指定された1章分のMarkdownを元PDFの該当ページと突き合わせ、数式の誤り・欠落を修正する。03-01-fix-heading-structure完了後、対象文書の最上位章の数だけ章を変えて繰り返し実行する。
---

# Skill: 章ごとの数式レビュー

## 目的
`03-01-fix-heading-structure` 完了後、対象文書の最上位章（H2見出し）ごとに `paper-chapter-reviewer` subagentへ数式レビューを委譲する。章を変えて、最上位章の数だけ繰り返し実行する。

## 対象範囲の決め方
- 基本単位: 最上位章（H2見出し）1つを1回のsubagent呼び出し対象とする
- 例外: 1章内の数式数が多く1回で見きれないとsubagentから報告された場合、H3以下の小見出し単位にさらに分割して呼び出す

## 実行方法
Agentツールで `paper-chapter-reviewer` subagentを章ごとに起動する（`subagent_type: "paper-chapter-reviewer"`）。複数章が同じ `<論文名>_review.md` へ書き込むため、必ず `run_in_background: false` で1章ずつ逐次dispatchし、並列には呼び出さない。前の章の完了報告を受け取ってから次の章を起動する。

呼び出し時に渡す情報:
- 対象の `<論文名>_review.md` の絶対パス
- 対象章の開始位置を特定できる見出し（章番号・タイトル）
- 対象章の終了位置（次の見出し。文書末尾が対象章の場合はその旨）
- 元PDFファイルのパスと、対象章に対応するページ範囲

修正対象・修正対象外・自己レビューの基準は `paper-chapter-reviewer` subagent側の定義に従う（本Skillでは規定しない）。

## 完了条件・報告
全最上位章のsubagent呼び出しが完了した時点で完了。各章の完了報告（変更箇所一覧）をまとめて作業ログとして報告する。

## 次のSkill
全章の実行完了後、`03-03-spot-check-review` を1回実行する。
