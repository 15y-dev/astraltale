#!/usr/bin/env python3
r"""
AstralTale NFS 展開済みファイル リネームスクリプト

ハッシュ関数:
    seed = seed * 0x1000193 ^ byte  (uint64)
    fileHash = hash(filename_lower) + hash(path_lower)
    path: 末尾スラッシュなし・先頭スラッシュなし

使い方:
    # 確認のみ（実際には何もしない）
    python nfs_rename.py --out D:\work\astraltale\out --dry-run

    # 実際にリネーム実行
    python nfs_rename.py --out D:\work\astraltale\out

    # refs.txtを追加パスリストとして使う
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt

    # コピーモード（元ファイルを残す）
    python nfs_rename.py --out D:\work\astraltale\out --copy
"""

import struct
import os
import re
import argparse
import shutil
from pathlib import Path


# ============================================================
# ハッシュ関数
# ============================================================
def hash_char(b: int, seed: int) -> int:
    return (seed * 0x1000193 ^ b) & 0xFFFFFFFFFFFFFFFF

def calc_hash(filename: str, path: str) -> int:
    h = 0
    for b in filename.lower().encode('latin-1'):
        h = hash_char(b, h)
    for b in path.lower().encode('latin-1'):
        h = hash_char(b, h)
    return h

def normalize(raw: str) -> tuple[str, str]:
    s = raw.replace('\\', '/').lower()
    while '//' in s:
        s = s.replace('//', '/')
    while s.startswith('./'):
        s = s[2:]
    s = s.rstrip('/')
    idx = s.rfind('/')
    return (s[idx+1:], s[:idx]) if idx >= 0 else (s, '')


# ============================================================
# ファイル名 → ディレクトリ候補
# ============================================================
def guess_paths(fname: str) -> list[str]:
    """ファイル名からディレクトリ候補を返す（優先順）"""
    fl = fname.lower()
    paths = []

    # *.kfm → biology/
    if fl.endswith('.kfm'):
        paths.append("biology")

    # m*数字.dds, m*数字.DDS → biology/texture/
    if re.match(r'^m\d+', fl) and fl.endswith('.dds'):
        paths.append("biology/texture")

    # S[3桁].nif / S[3桁].big → map/model/s{xxx}/
    m = re.match(r'^(s(\d{1,3}))\.(nif|big)$', fl)
    if m:
        sid = m.group(1)
        paths += [f"map/model/{sid}", "map/model"]

    # s[4桁+].nif → map/model/s{先頭4桁}/
    m = re.match(r'^(s(\d{4,}))\.(nif|big)$', fl)
    if m:
        sid = m.group(1)
        paths += [f"map/model/{sid[:4]}", f"map/model/{sid[:5]}", "map/model"]

    # data/db 系 ini
    DB_FILES = {
        'biologylist.ini', 'weapon.ini', 'color.ini', 'effect.ini',
        'dyneffect.ini', 'motion.ini', 'boundinfo.ini', 'equip.ini',
        'bonescale.ini', 'decorate.ini', 'ridelist.ini',
        'c_weapon.ini', 'c_color.ini',
    }
    if fl in DB_FILES:
        paths.append("data/db")

    return paths


# ============================================================
# ハッシュマップ構築
# ============================================================
def build_hash_map(refs: list[str], extra_paths: list[str] = None) -> dict[int, str]:
    """
    refs: ファイル名リスト（ディレクトリなし）
    extra_paths: フルパス形式の追加パス
    """
    hmap = {}

    # refsからディレクトリを推測して登録
    for fname in refs:
        for path in guess_paths(fname):
            fn, pt = normalize(f"{path}/{fname}")
            h = calc_hash(fn, pt)
            if h not in hmap:
                hmap[h] = f"{path}/{fname}"

    # 追加パス（フルパス形式）
    for raw in (extra_paths or []):
        fn, pt = normalize(raw)
        if fn:
            h = calc_hash(fn, pt)
            if h not in hmap:
                hmap[h] = raw

    return hmap


# ============================================================
# デフォルト既知パス（game.binから抽出）
# ============================================================
DEFAULT_KNOWN = [
    # data/db 系
    "data/db/BiologyList.ini",
    "data/db/Weapon.ini",
    "data/db/color.ini",
    "data/db/Color.ini",
    "data/db/effect.ini",
    "data/db/dynEffect.ini",
    "data/db/Motion.ini",
    "data/db/BoundInfo.ini",
    "data/db/Equip.ini",
    "data/db/BoneScale.ini",
    "data/db/Decorate.ini",
    "data/db/RideList.ini",
    # map model
    *[f"map/model/S{i:03d}/S{i:03d}.nif" for i in range(1, 600)],
    *[f"map/model/S{i:03d}/S{i:03d}.big" for i in range(1, 600)],
    # biology kfm
    *[f"biology/m{i:03d}.kfm" for i in range(1, 1000)],
    # biology texture dds
    *[f"biology/texture/m{i:03d}{j:02d}.dds" for i in range(1, 500) for j in range(1, 20)],
    *[f"biology/texture/m{i:03d}{j:02d}a.dds" for i in range(1, 500) for j in range(1, 10)],
]


# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="AstralTale 展開済みファイル リネームツール")
    parser.add_argument("--out",     required=True, help="展開済みフォルダ")
    parser.add_argument("--refs",    default=None,  help="iniから抽出したrefs.txt（ファイル名のみ）")
    parser.add_argument("--paths",   default=None,  help="フルパス形式の追加パスリスト")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ（実際には何もしない）")
    parser.add_argument("--copy",    action="store_true", help="リネームではなくコピー")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[ERROR] フォルダが見つかりません: {out_dir}")
        return

    # refs.txt 読み込み
    refs = []
    if args.refs:
        with open(args.refs, 'r', encoding='utf-8-sig') as f:
            refs = [l.strip() for l in f if l.strip()]
        print(f"[INFO] refs.txt: {len(refs):,} 件")

    # 追加パスリスト読み込み
    extra_paths = list(DEFAULT_KNOWN)
    if args.paths:
        with open(args.paths, 'r', encoding='utf-8') as f:
            extra_paths += [l.strip() for l in f if l.strip()]
        print(f"[INFO] 追加パス: {len(extra_paths):,} 件")

    # ハッシュマップ構築
    print("[INFO] ハッシュマップ構築中...")
    hmap = build_hash_map(refs, extra_paths)
    print(f"[INFO] {len(hmap):,} パターン生成")

    # 展開済みファイルを取得
    exts = ['*.dds','*.nif','*.ini','*.txt','*.bin','*.kf','*.kfm',
            '*.smp','*.pmap','*.png','*.bmp','*.jpg','*.xml']
    files = []
    for ext in exts:
        files += list(out_dir.glob(ext))

    print(f"[INFO] 対象ファイル: {len(files):,} 件")
    print("-" * 60)

    renamed = 0
    skipped = 0

    for f in sorted(files):
        # ファイル名がhash値かチェック
        stem = f.stem
        try:
            h = int(stem, 16)
        except ValueError:
            if args.verbose:
                print(f"  [SKIP] {f.name} (既にリネーム済み)")
            skipped += 1
            continue

        if h not in hmap:
            if args.verbose:
                print(f"  [UNKN] {f.name}")
            skipped += 1
            continue

        # 新しいパスを決定
        known_raw = hmap[h]
        fn, pt = normalize(known_raw)

        # 拡張子は元ファイルのものを維持
        orig_ext = f.suffix.lower()
        known_base = fn.rsplit('.', 1)[0] if '.' in fn else fn
        final_name = known_base + orig_ext

        new_dir  = out_dir / pt.replace('/', os.sep) if pt else out_dir
        new_path = new_dir / final_name

        if args.dry_run:
            print(f"  [DRY] {f.name} → {pt + '/' if pt else ''}{final_name}")
            renamed += 1
            continue

        new_dir.mkdir(parents=True, exist_ok=True)

        if new_path.exists():
            if args.verbose:
                print(f"  [SKIP] {final_name} (既に存在)")
            skipped += 1
            continue

        if args.copy:
            shutil.copy2(f, new_path)
        else:
            f.rename(new_path)

        renamed += 1
        if args.verbose or renamed % 200 == 0:
            print(f"  [{renamed:>5}] {f.name} → {pt + '/' if pt else ''}{final_name}")

    print("-" * 60)
    action = "DRY RUN" if args.dry_run else ("コピー" if args.copy else "リネーム")
    print(f"[完了] {action}: {renamed:,} 件  スキップ: {skipped:,} 件")


if __name__ == "__main__":
    main()
