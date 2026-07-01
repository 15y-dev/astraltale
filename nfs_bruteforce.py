#!/usr/bin/env python3
r"""
AstralTale 翻訳オーバーライドファイル総当たり探索スクリプト

out/data/db にある c_*.{ini,bin,txt} ファイルの先頭文字を a~z に変え、
拡張子も ini/txt/bin を試して packageindex に存在するか総当たりチェック。
見つかったファイルはすべて展開・保存する。

使い方:
    python nfs_bruteforce.py --game D:\X-Legend\AstralTale --filelist FileListPC.txt --out D:\work\astraltale\out

    # dry-run（見つかったパスの一覧だけ表示）
    python nfs_bruteforce.py --game D:\X-Legend\AstralTale --filelist FileListPC.txt --out D:\work\astraltale\out --dry-run
"""

import argparse
import string
import sys
import os
from pathlib import Path

from nfs_common import (
    calc_hash, normalize, parse_packageindex,
    load_filelist, extract_chunk, resolve_nfs_path,
)


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale 翻訳オーバーライドファイル総当たり探索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--game", required=True,
                        help="ゲームフォルダ (例: D:/X-Legend/AstralTale)")
    parser.add_argument("--out", required=True,
                        help="出力フォルダ")
    parser.add_argument("--filelist", default=None,
                        help="FileListPC.txt")
    parser.add_argument("--source-dir", default=None,
                        help="元ファイルのあるディレクトリ (デフォルト: --out/data/db)")
    parser.add_argument("--db-path", default="data/db",
                        help="ゲーム内ディレクトリパス (デフォルト: data/db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細ログ")
    args = parser.parse_args()

    game_dir = args.game
    out_dir = Path(args.out)

    # 元ファイルのディレクトリ
    source_dir = Path(args.source_dir) if args.source_dir else out_dir / args.db_path
    if not source_dir.exists():
        print(f"[ERROR] ソースディレクトリが見つかりません: {source_dir}")
        sys.exit(1)

    # c_* ファイル一覧を取得
    base_files = []
    for f in sorted(source_dir.iterdir()):
        if f.is_file() and f.name.startswith("c_"):
            base_files.append(f.name)

    if not base_files:
        print(f"[ERROR] c_* ファイルが見つかりません: {source_dir}")
        sys.exit(1)

    print(f"[INFO] 元ファイル: {len(base_files)} 個 ({source_dir})")

    # packageindex 読み込み
    pi_path = os.path.join(game_dir, "packageindex")
    if not os.path.exists(pi_path):
        print(f"[ERROR] packageindex が見つかりません: {pi_path}")
        sys.exit(1)

    print("[INFO] packageindex 読み込み中...")
    pi_entries, version = parse_packageindex(pi_path)
    print(f"[INFO] {len(pi_entries):,} エントリ (version=0x{version:08X})")

    # filelist 読み込み（FileListPC.txt + GameDataTranslateFileList_*.txt）
    filelist = {}
    filelist_files = []
    if args.filelist:
        fl_path = (args.filelist if os.path.isabs(args.filelist)
                   else os.path.join(game_dir, args.filelist))
        if os.path.exists(fl_path):
            filelist_files.append(fl_path)

    # 翻訳用filelistを自動検索
    import glob
    for pat in ["GameDataTranslateFileList_*.txt"]:
        for f in glob.glob(os.path.join(game_dir, pat)):
            if f not in filelist_files:
                filelist_files.append(f)

    for fl_path in filelist_files:
        fl = load_filelist(fl_path)
        filelist.update(fl)
        print(f"[INFO] filelist: {os.path.basename(fl_path)} → {len(fl):,} エントリ")
    if filelist:
        print(f"[INFO] filelist 合計: {len(filelist):,} エントリ")

    # 元ファイルのハッシュ集合（スキップ用）
    orig_hashes = set()
    for base_name in base_files:
        orig_path = f"{args.db_path}/{base_name}"
        orig_hashes.add(calc_hash(*normalize(orig_path)))

    # 試行する拡張子
    try_extensions = [".ini", ".txt", ".bin"]
    # ロケール接尾辞（翻訳データファイル用）
    try_locales = ["", "_jp", "_en", "_tw", "_kr", "_cn"]

    # 総当たり探索
    total_patterns = len(base_files) * 26 * len(try_extensions) * len(try_locales)
    print(f"\n[INFO] 総当たりチェック: {len(base_files)} ファイル × 26文字 × {len(try_extensions)} 拡張子 × {len(try_locales)} ロケール = {total_patterns:,} パターン")
    print("=" * 70)

    found = {}  # hash → item（重複除去）
    checked = 0

    for base_name in base_files:
        # c_partner.bin → stem="partner", orig_ext=".bin"
        stem = base_name[2:]  # "c_" を除去
        name_without_ext, orig_ext = os.path.splitext(stem)

        for letter in string.ascii_lowercase:
            for locale in try_locales:
                for ext in try_extensions:
                    variant = f"{letter}_{name_without_ext}{locale}{ext}"
                    game_path = f"{args.db_path}/{variant}"

                    fn, pt = normalize(game_path)
                    h = calc_hash(fn, pt)
                    checked += 1

                    if h in pi_entries and h not in orig_hashes and h not in found:
                        entry = pi_entries[h]
                        found[h] = {
                            "game_path": game_path,
                            "hash": h,
                            "entry": entry,
                            "base": base_name,
                        }
                        print(f"  [発見] {game_path:40s}  hash=0x{h:016X}  size={entry['size']:,}")

    print("=" * 70)
    print(f"[INFO] チェック: {checked:,} パターン  → 発見: {len(found)} ファイル")

    if not found:
        print("[INFO] 新しいファイルは見つかりませんでした。")
        return

    if args.dry_run:
        print("\n[DRY] 展開するには --dry-run を外してください")
        return

    # 展開
    nfs_cache = {}
    print(f"\n[INFO] {len(found)} ファイルを展開中...")
    ok = 0
    errors = 0

    for item in found.values():
        game_path = item["game_path"]
        h = item["hash"]
        entry = item["entry"]

        nfs_file = resolve_nfs_path(game_dir, h, entry, filelist, nfs_cache)
        if nfs_file is None:
            print(f"  [SKIP] {game_path} → NFSファイルなし")
            continue

        try:
            data = extract_chunk(nfs_file, entry["offset"], entry["size"], entry["checksum"])
        except ValueError as e:
            print(f"  [ERROR] {game_path}: {e}")
            errors += 1
            continue

        out_path = out_dir / game_path.replace("\\", "/")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as f:
            f.write(data)

        ok += 1
        print(f"  [OK] {game_path} ({len(data):,} bytes)")

    print(f"\n[完了] 展開成功={ok}  エラー={errors}")


if __name__ == "__main__":
    main()
