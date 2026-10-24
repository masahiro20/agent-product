# agent-product

建築・不動産の実務向けエージェント機能を置くリポジトリ。

- 現地写真（＋住所）から図面・解体概算・造成計画図・土地概況を一式で出す: `.claude/skills/site-photo-report/`（手順は SKILL.md）
  - 依存: Python 3.10+、reportlab、openpyxl、numpy、Pillow、ezdxf（`pip install reportlab openpyxl numpy pillow ezdxf`）、日本語フォント（IPAゴシック等）、PDF確認用に poppler（pdftoppm）
  - 案件ごとの作業フォルダ `jobs/` は顧客の写真・住所を含むため git 管理しない（.gitignore 済み）
- 社内向け Web ツール（上のスキルを画面から使う）: `app.py`（FastAPI）＋ `webapp/`（写真の読み取り・変換）＋ `public/`（画面。ホームランディックHPのトーンに合わせる）
  - Vercel にデプロイ（`vercel.json`）。環境変数: `ANTHROPIC_API_KEY`（必須）、`ACCESS_PASSWORD`（社内共有キー、未設定なら認証なし）、`SITE_MODEL`（既定 claude-opus-5-5）、`SITE_EFFORT`（既定 medium）
  - ローカル: `pip install -r requirements.txt uvicorn && uvicorn app:app --port 8765`。APIキー無しで画面を確認するときは `SITE_MOCK_READING=<読み取り結果JSON>` を付ける
  - エンジンは `.claude/skills/site-photo-report/scripts` をそのまま import する（`webapp/engine.py`）。PDF の日本語フォントは `fonts/ipag.ttf`（IPAフォントライセンス）
