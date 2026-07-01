#!/usr/bin/env python3
r"""
AstralTale NFS ファイル取得スクリプト

ゲーム内パスを指定して、NFSアーカイブから直接展開・保存する。

使い方:
    # 単一ファイルを取得
    python nfs_get.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out "data/db/C_Item.ini"

    # dry-run（ハッシュ値と存在確認のみ）
    python nfs_get.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out "biology/texture/m001.dds" --dry-run

    # ハッシュ値の計算だけ（--game不要）
    python nfs_get.py --calc "data/db/C_Item.ini"
"""

import argparse
import sys
import os
from pathlib import Path

from nfs_common import (
    calc_hash, normalize, parse_packageindex,
    load_filelist, extract_chunk, resolve_nfs_path,
)


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale NFS ファイル取得ツール — ゲーム内パス指定で展開",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python nfs_get.py --game D:\\X-Legend\\AstralTale --out D:\\work\\out "data/db/C_Item.ini"
  python nfs_get.py --game D:\\X-Legend\\AstralTale --out D:\\work\\out "biology/texture/m001.dds" --dry-run
  python nfs_get.py --calc "data/db/C_Item.ini"
"""
    )
    parser.add_argument("path", nargs="?", default=None,
                        help="ゲーム内パス (例: data/db/C_Item.ini)")
    parser.add_argument("--game", default=None,
                        help="ゲームフォルダ (例: D:/X-Legend/AstralTale)")
    parser.add_argument("--out", default=None,
                        help="出力フォルダ")
    parser.add_argument("--filelist", default=None,
                        help="FileListPC.txt（NFSファイル名解決用）")
    parser.add_argument("--calc", default=None,
                        help="ハッシュ計算のみ（展開しない）")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ（実際には展開しない）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細ログ")
    args = parser.parse_args()

    # --calc モード: ハッシュ計算のみ
    if args.calc:
        fn, pt = normalize(args.calc)
        h = calc_hash(fn, pt)
        print(f"パス:       {args.calc}")
        print(f"正規化:     {pt}/{fn}" if pt else f"正規化:     {fn}")
        print(f"ハッシュ:   0x{h:016X}")
        print(f"ファイル名: {h:016x}.*")
        return

    # パス指定モード
    game_path = args.path
    if not game_path:
        parser.print_help()
        print("\n[ERROR] ゲーム内パスを指定してください")
        sys.exit(1)

    if not args.game:
        print("[ERROR] --game オプションが必要です")
        sys.exit(1)

    if not args.out:
        print("[ERROR] --out オプションが必要です")
        sys.exit(1)

    game_dir = args.game
    out_dir  = Path(args.out)

    # ハッシュ計算
    fn, pt = normalize(game_path)
    h = calc_hash(fn, pt)
    print(f"[INFO] パス:     {game_path}")
    print(f"[INFO] 正規化:   {pt}/{fn}" if pt else f"[INFO] 正規化:   {fn}")
    print(f"[INFO] ハッシュ: 0x{h:016X}")

    # packageindex 読み込み
    pi_path = os.path.join(game_dir, "packageindex")
    if not os.path.exists(pi_path):
        print(f"[ERROR] packageindex が見つかりません: {pi_path}")
        sys.exit(1)

    print("[INFO] packageindex 読み込み中...")
    pi_entries, version = parse_packageindex(pi_path)
    print(f"[INFO] {len(pi_entries):,} エントリ (version=0x{version:08X})")

    # ハッシュ検索
    if h not in pi_entries:
        print(f"[ERROR] 0x{h:016X} が packageindex に見つかりません")
        sys.exit(1)

    entry = pi_entries[h]
    print(f"[INFO] offset={entry['offset']:,}  size={entry['size']:,}  "
          f"checksum=0x{entry['checksum']:08X}  time=0x{entry['time']:08X}")

    # filelist 読み込み
    filelist = {}
    if args.filelist:
        fl_path = args.filelist if os.path.isabs(args.filelist) else \
                  os.path.join(game_dir, args.filelist)
        if os.path.exists(fl_path):
            filelist = load_filelist(fl_path)
            if args.verbose:
                print(f"[INFO] filelist: {len(filelist):,} エントリ")

    # NFSファイル解決
    nfs_file = resolve_nfs_path(game_dir, h, entry, filelist)
    print(f"[INFO] NFSファイル: {nfs_file}")

    if nfs_file is None:
        print(f"[ERROR] NFSファイルが見つかりません")
        sys.exit(1)

    if args.dry_run:
        print(f"[DRY] 展開先: {out_dir / game_path}")
        print("[DRY] 実行するには --dry-run を外してください")
        return

    # 展開
    print("[INFO] 展開中...")
    try:
        data = extract_chunk(nfs_file, entry["offset"], entry["size"], entry["checksum"])
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # 保存
    out_path = out_dir / game_path.replace('\\', '/')
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "wb") as f:
        f.write(data)

    print(f"[完了] {out_path} ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
