#!/usr/bin/env python3
"""現地写真レポート 一式出力。

使い方:
  # 1) 住所から公開データ（座標・標高・航空写真・ハザード等）を取って site.json に書き足す
  python run.py fetch site.json
  # 2) 図面・見積・資料一式（PDF / Excel / DXF）を出す
  python run.py build site.json --out 出力フォルダ
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sitekit import report  # noqa: E402
from sitekit.common import load_json, save_json  # noqa: E402


def cmd_build(args):
    spec = load_json(args.spec)
    base = os.path.dirname(os.path.abspath(args.spec))
    out = args.out or os.path.join(base, "output")
    summary = report.build(spec, out, base)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_fetch(args):
    from sitekit import terrain

    spec = load_json(args.spec)
    base = os.path.dirname(os.path.abspath(args.spec))
    info = terrain.fetch(spec, base, half_size_m=args.half, step_m=args.step)
    save_json(spec, args.spec)
    print(json.dumps(info, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("spec")
    b.add_argument("--out")
    b.set_defaults(func=cmd_build)
    f = sub.add_parser("fetch")
    f.add_argument("spec")
    f.add_argument("--half", type=float, default=30.0, help="標高を取る範囲（敷地中心から±m）")
    f.add_argument("--step", type=float, default=1.0, help="標高の取得間隔 m")
    f.set_defaults(func=cmd_fetch)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
