#!/usr/bin/env python3
r"""
AstralTale / X-Legend NFS 全ファイル展開スクリプト

使い方:
    # FileListPC.txt で全展開（推奨）
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist FileListPC.txt --out D:\work\astraltale\out

    # GameDataTranslateFileList で翻訳ファイルだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist GameDataTranslateFileList_jp.txt --out D:\work\astraltale\out

    # filelist なしで packageindex 全エントリを展開（ファイル名はhash値になる）
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out

    # 特定のhashだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out --hash 0x6C48514446826F5E --verbose
"""

import argparse
import sys
import os
from pathlib import Path

from nfs_common import (
    parse_packageindex, load_filelist, extract_chunk,
    guess_extension, resolve_nfs_path,
)


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale NFS ファイル全展開ツール"
    )
    parser.add_argument("--game",     required=True,
                        help="ゲームフォルダ (例: D:/X-Legend/AstralTale)")
    parser.add_argument("--out",      required=True,
                        help="出力フォルダ")
    parser.add_argument("--filelist", default=None,
                        help="FileListPC.txt または GameDataTranslateFileList_*.txt")
    parser.add_argument("--hash",     default=None,
                        help="特定のhashだけ展開 (例: 0x6C48514446826F5E)")
    parser.add_argument("--verbose",  "-v", action="store_true",
                        help="詳細ログ")
    args = parser.parse_args()

    game_dir = args.game
    out_dir  = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # packageindex 読み込み
    pi_path = os.path.join(game_dir, "packageindex")
    if not os.path.exists(pi_path):
        print(f"[ERROR] packageindex が見つかりません: {pi_path}")
        sys.exit(1)

    print("[INFO] packageindex 読み込み中...")
    pi_entries, version = parse_packageindex(pi_path)
    print(f"[INFO] {len(pi_entries):,} エントリ (version=0x{version:08X})")

    # 特定hash指定
    if args.hash:
        target = int(args.hash, 16)
        if target not in pi_entries:
            print(f"[ERROR] 0x{target:016X} が packageindex に見つかりません")
            sys.exit(1)
        pi_entries = {target: pi_entries[target]}

    # filelist 読み込み
    filelist = {}
    if args.filelist:
        fl_path = args.filelist if os.path.isabs(args.filelist) else \
                  os.path.join(game_dir, args.filelist)
        if not os.path.exists(fl_path):
            print(f"[ERROR] filelist が見つかりません: {fl_path}")
            sys.exit(1)
        print(f"[INFO] filelist 読み込み中: {fl_path}")
        filelist = load_filelist(fl_path)
        print(f"[INFO] {len(filelist):,} エントリ (hash行のみ)")

    nfs_cache = {}
    ok    = 0
    skip  = 0
    error = 0
    total = len(pi_entries)

    print(f"\n[INFO] 展開開始: {total:,} エントリ")
    print("-" * 60)

    for hv, entry in pi_entries.items():
        nfs_file = resolve_nfs_path(game_dir, hv, entry, filelist, nfs_cache)
        if nfs_file is None:
            if args.verbose:
                print(f"  [SKIP] 0x{hv:016X} → NFSファイル存在しない")
            skip += 1
            continue

        # 展開
        try:
            data = extract_chunk(nfs_file, entry["offset"], entry["size"], entry["checksum"])
        except ValueError as e:
            if args.verbose:
                print(f"  [ERROR] 0x{hv:016X}: {e}")
            error += 1
            continue

        # 出力パス決定
        ext      = guess_extension(data)
        out_path = out_dir / f"{hv:016x}{ext}"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as f:
            f.write(data)

        ok += 1
        if args.verbose or ok % 1000 == 0:
            print(f"  [{ok:>6}/{total}] {out_path.name} ({len(data):,} bytes)")

    print("-" * 60)
    print(f"[完了] 成功={ok:,}  スキップ={skip:,}  エラー={error:,}")
    print(f"[出力] {out_dir}")


if __name__ == "__main__":
    main()
