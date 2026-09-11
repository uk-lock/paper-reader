# 開発環境

Python 3.12のdevcontainer上で開発。Linux向けCPU版PyTorch使用のため、Intel Macでも`marker-pdf`をインストール可能（コンテナ内はGPU不使用）。

## 起動

Docker Desktopを起動し、VS Codeで `preprocess` フォルダを開いてコマンドパレットから `Dev Containers: Reopen in Container` を実行（初回はイメージビルド・パッケージインストールに時間がかかる）。親リポジトリ全体が `/workspaces/paper-reader` にマウントされる。

コンテナの環境:

- Python 3.12
- CPU版PyTorch 2.7.1
- `requirements/requirements.txt` のパッケージ
- JupyterLab 4.6.3
- `paper-reader-env` Jupyterカーネル

VS CodeのNotebookでは、カーネル選択で `paper-reader-env` を選択。

## JupyterLab

コンテナ内ターミナルで、リポジトリルートから実行。

```bash
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser
```

表示されたURLを開く（ポート8888はVS Codeがローカルへ転送）。

## PDF抽出（推奨: `extract_pdf.py`）

marker-pdf（OCR無し・CPU） + PyMuPDF（表の画像化）のハイブリッドで、PDFをMarkdownへ変換。

```bash
python preprocess/src/extract_pdf.py pdf/paper.pdf --output-dir output
```

- devcontainer内で実行（marker-pdf・PyMuPDFの依存関係が必要なため）。Jupyter不要、コマンド一発で変換可能
- OCR無効化により**数十秒**で完了（OCR有効時は数十分〜数時間かかっていた）
- 本文・見出し・引用番号はmarker-pdfの結果をそのまま使用し、表のみPyMuPDFで元PDFから画像切り出しして差し替え
- 数式はLaTeX化されず生テキストのまま残る（意図的な設計。実PDFと見比れて修正する工程は別途Skillで実施）

## marker-pdfのOCR実行（重い・通常は不要）

数式もOCRで丁寧にLaTeX化したい場合のみ使用。CPU版 `llama-server` をコンテナ内でビルドし、OCR・数式認識を実行（LLM補正は無効、OCR自体はローカルのSurya認識モデル/VLMを使用）。

既存環境には **Dev Containers: Rebuild Container** で反映し、Notebookのカーネルを再起動。

```bash
marker_single pdf/paper.pdf --output_dir output --mode fast --ocr_inline_math
```

`fast` モードはPDFのテキストを利用しつつ、数式や問題のある領域のみOCRで補う。全ページ再OCRする場合は `--force_ocr` を追加。CPUのOCR同時リクエスト数は1。

部分変換の例（ページ番号は0始まり）:

```bash
marker_single pdf/paper.pdf --output_dir output/ocr-check --mode fast --ocr_inline_math --page_range "3,5"
```

**論文1本の変換に数十分〜数時間かかることがある**（数式ごとにVLM推論が直列で走るため）。まず部分変換での確認を推奨。モデルは初回実行時にダウンロードされ、`paper-reader-model-cache` Docker volumeへ保存される。

## Colabで気軽に変換する場合

1本だけPDFを変換したい等、devcontainerの起動が手間なときは `preprocess/src/jupyter/colab_convert.ipynb` を使用。

- Google Colabにアップロードして実行。**ランタイムはCPUのままで構わない**（GPU不使用のため、選択してもGPU枠を消費するだけ）
- `llama-server`（CPU版）はソースビルドせず、公式のビルド済みバイナリをノートブック内で自動ダウンロード（GPU向けvllmバックエンドはDocker前提でColabでは動作しないため）
- 入出力はGoogle Drive上のフォルダ（デフォルトは `paper-reader/pdf/`・`paper-reader/output/`）に対して行うため、ローカルのdevcontainer環境とは独立して完結
- OCR・インライン数式認識は有効、LLM補正は無効という方針は `sample.ipynb` と同じ

DBへの保存まで含む本番の前処理パイプラインは、引き続きdevcontainer環境（`sample.ipynb` / `marker_single`）を使用。

## Pythonバージョン

プロジェクトのPythonバージョンは `preprocess/.python-version` に記載。Dockerfileのベースイメージも同じ3.12系を使用。

`preprocess/setup-env.sh` はDockerを使わない環境向けに残置。ただしmacOS IntelはPyTorch 2.7以降が未配布のため、devcontainerを使用のこと。
