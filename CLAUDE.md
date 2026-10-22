# agent-product

建築・不動産の実務向けエージェント機能を置くリポジトリ。

- 現地写真（＋住所）から図面・解体概算・造成計画図・土地概況を一式で出す: `.claude/skills/site-photo-report/`（手順は SKILL.md）
  - 依存: Python 3.10+、reportlab、openpyxl、numpy、Pillow、ezdxf（`pip install reportlab openpyxl numpy pillow ezdxf`）、日本語フォント（IPAゴシック等）、PDF確認用に poppler（pdftoppm）
  - 案件ごとの作業フォルダ `jobs/` は顧客の写真・住所を含むため git 管理しない（.gitignore 済み）
