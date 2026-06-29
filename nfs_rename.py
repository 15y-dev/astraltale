#!/usr/bin/env python3
r"""
AstralTale NFS 展開済みファイル リネームスクリプト

ハッシュ関数:
    calc_hash(filename, path) = hash(filename_bytes) + hash(path_bytes)
    各文字: seed = seed * 0x1000193 ^ byte
    正規化: 大文字→小文字, \→/, 先頭の./除去, 末尾スラッシュなし

使い方:
    # game.binから既知パスを使ってリネーム
    python nfs_rename.py --out D:\work\astraltale\out --dry-run

    # 実際にリネーム実行
    python nfs_rename.py --out D:\work\astraltale\out

    # カスタムパスリストを追加
    python nfs_rename.py --out D:\work\astraltale\out --paths my_paths.txt
"""

import struct
import os
import argparse
from pathlib import Path


# ============================================================
# ハッシュ関数
# ============================================================
def hash_char(b: int, seed: int) -> int:
    return (seed * 0x1000193 ^ b) & 0xFFFFFFFFFFFFFFFF

def calc_hash(filename: str, path: str) -> int:
    h = 0
    for b in filename.encode('latin-1'):
        h = hash_char(b, h)
    for b in path.encode('latin-1'):
        h = hash_char(b, h)
    return h

def normalize(raw: str) -> tuple[str, str]:
    """生パス → (filename, path) に正規化"""
    s = raw.replace('\\', '/').lower()
    while '//' in s:
        s = s.replace('//', '/')
    while s.startswith('./'):
        s = s[2:]
    s = s.rstrip('/')
    idx = s.rfind('/')
    if idx >= 0:
        return s[idx+1:], s[:idx]
    return s, ''


# ============================================================
# 既知パスリスト（game.binから抽出 + 推測）
# ============================================================
KNOWN_PATHS = [
    # data/db 系
    "data/db/BiologyList.ini",
    "data/db/Weapon.ini",
    "data/db/color.ini",
    "data/db/effect.ini",
    "data/db/dynEffect.ini",
    "data/db/Motion.ini",
    "data/db/BoundInfo.ini",
    "data/db/Equip.ini",
    "data/db/BoneScale.ini",
    "data/db/Decorate.ini",
    "data/db/RideList.ini",
    "data/db/C_Weapon.ini",

    # map/model 系
    "map/model/S099/S099_camera_out.nif",
    *[f"map/model/S{i:03d}/S{i:03d}.nif" for i in range(1, 600)],
    *[f"map/model/S{i:03d}/S{i:03d}.big" for i in range(1, 600)],
    *[f"map/model/S{i:03d}/S{i:03d}_camera_out.nif" for i in range(1, 600)],

    # map/model/object, sky 系
    "map/model/object",
    "map/model/sky",

    # biology 系（モンスターモデル）
    *[f"biology/m{i:03d}/m{i:03d}.kfm" for i in range(1, 500)],
    *[f"biology/m{i:03d}/m{i:03d}{j:02d}.dds" for i in range(1, 500) for j in range(1, 10)],
    *[f"biology/m{i:03d}/m{i:03d}.nif" for i in range(1, 500)],

    # sound 系
    *[f"sound/S{i}.smp" for i in range(1, 9000)],
    *[f"smp/S{i}.smp" for i in range(1, 9000)],

    # UI 系
    *[f"ui/itemicon/{i:04d}.dds" for i in range(1, 10000)],
    *[f"ui/skillicon/{i:04d}.dds" for i in range(1, 5000)],
    *[f"ui/uiicon/{i:04d}.dds" for i in range(1, 5000)],

    # ride 系
    *[f"ride/r{i:03d}/r{i:03d}.kfm" for i in range(1, 200)],
    *[f"ride/r{i:03d}/r{i:03d}.nif" for i in range(1, 200)],

    # partner 系
    *[f"partner/p{i:03d}/p{i:03d}.kfm" for i in range(1, 200)],
    *[f"partner/p{i:03d}/p{i:03d}.nif" for i in range(1, 200)],

    # scene 系
    *[f"scene/S{i:03d}.ini" for i in range(1, 600)],

    # その他
    "movies/logo.ogv",
    "idc.ini",
    "client.ini",
    "locate.ini",
    "locate_1.ini",
    "banner.ini",
]


def build_hash_map(extra_paths: list[str] = None) -> dict[int, str]:
    """既知パスからhash→パスのマップを構築"""
    hmap = {}
    paths = KNOWN_PATHS + (extra_paths or [])
    
    for raw in paths:
        fname, path = normalize(raw)
        if not fname:
            continue
        h = calc_hash(fname, path)
        if h not in hmap:
            hmap[h] = raw
    
    return hmap


def main():
    parser = argparse.ArgumentParser(description="AstralTale 展開済みファイル リネームツール")
    parser.add_argument("--out",      required=True, help="展開済みフォルダ (例: D:\\work\\astraltale\\out)")
    parser.add_argument("--paths",    default=None,  help="追加パスリストファイル（1行1パス）")
    parser.add_argument("--dry-run",  action="store_true", help="実際にリネームせず確認のみ")
    parser.add_argument("--copy",     action="store_true", help="リネームではなくコピー（元ファイルを残す）")
    parser.add_argument("--verbose",  "-v", action="store_true", help="詳細ログ")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[ERROR] フォルダが見つかりません: {out_dir}")
        return

    # 追加パスリスト読み込み
    extra_paths = []
    if args.paths:
        with open(args.paths, 'r', encoding='utf-8') as f:
            extra_paths = [l.strip() for l in f if l.strip()]
        print(f"[INFO] 追加パス: {len(extra_paths)} 件")

    # hashマップ構築
    print("[INFO] ハッシュマップ構築中...")
    hmap = build_hash_map(extra_paths)
    print(f"[INFO] {len(hmap):,} パターン生成")

    # 展開済みファイルを走査
    files = list(out_dir.glob("*.dds")) + list(out_dir.glob("*.nif")) + \
            list(out_dir.glob("*.ini")) + list(out_dir.glob("*.txt")) + \
            list(out_dir.glob("*.bin")) + list(out_dir.glob("*.kf"))  + \
            list(out_dir.glob("*.kfm")) + list(out_dir.glob("*.smp")) + \
            list(out_dir.glob("*.pmap")) + list(out_dir.glob("*.png")) + \
            list(out_dir.glob("*.bmp"))

    print(f"[INFO] 対象ファイル: {len(files):,} 件")
    print("-" * 60)

    renamed = 0
    skipped = 0

    for f in files:
        # ファイル名からhashを取得
        stem = f.stem  # 拡張子なし
        try:
            h = int(stem, 16)
        except ValueError:
            # 既にリネーム済み
            if args.verbose:
                print(f"  [SKIP] {f.name} (既にリネーム済み？)")
            skipped += 1
            continue

        if h not in hmap:
            if args.verbose:
                print(f"  [UNKN] {f.name}")
            skipped += 1
            continue

        # 新しいファイルパスを決定
        known_path = hmap[h]
        fname, path = normalize(known_path)
        
        # 出力先: out_dir / path / filename（拡張子は元のまま）
        new_dir  = out_dir / path.replace('/', os.sep) if path else out_dir
        new_name = fname.replace(fname.split('.')[-1], '') .rstrip('.') + f.suffix.lower()
        # 拡張子をそのまま使う（.ini, .dds など）
        orig_ext = f.suffix.lower()
        known_ext = '.' + fname.split('.')[-1] if '.' in fname else ''
        final_name = fname if known_ext and known_ext == orig_ext else (fname.rsplit('.', 1)[0] + orig_ext if '.' in fname else fname + orig_ext)
        
        new_path = new_dir / final_name

        if args.dry_run:
            print(f"  [DRY] {f.name} → {path}/{final_name}")
            renamed += 1
            continue

        # 実際に移動/コピー
        new_dir.mkdir(parents=True, exist_ok=True)
        
        if new_path.exists():
            if args.verbose:
                print(f"  [SKIP] {final_name} (既に存在)")
            skipped += 1
            continue

        if args.copy:
            import shutil
            shutil.copy2(f, new_path)
        else:
            f.rename(new_path)

        renamed += 1
        if args.verbose or renamed % 100 == 0:
            print(f"  [{renamed:>5}] {f.name} → {path}/{final_name}")

    print("-" * 60)
    action = "DRY RUN" if args.dry_run else ("コピー" if args.copy else "リネーム")
    print(f"[完了] {action}: {renamed:,} 件  スキップ: {skipped:,} 件")


if __name__ == "__main__":
    main()
