#!/usr/bin/env python3
r"""
AstralTale DDS → PNG/JPG 変換スクリプト
Pillow 10.0+ の DDS ネイティブサポートを使用

使い方:
    # 展開済みフォルダのDDSをすべてPNGに変換
    python dds_convert.py --src D:\work\astraltale\out --dst D:\work\astraltale\png

    # リネーム済みフォルダのDDSを変換
    python dds_convert.py --src D:\work\astraltale\out\biology --dst D:\work\astraltale\png --recursive

    # JPG形式で変換（ファイルサイズ小さめ、透過なし）
    python dds_convert.py --src D:\work\astraltale\out --dst D:\work\astraltale\jpg --format jpg

    # 透過ありはPNG、なしはJPGで自動振り分け
    python dds_convert.py --src D:\work\astraltale\out --dst D:\work\astraltale\img --format auto
"""

import argparse
import sys
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("[ERROR] Pillowが必要です: pip install Pillow")
    sys.exit(1)


def has_alpha(img: Image.Image) -> bool:
    """画像に透過チャンネルがあるか確認"""
    if img.mode in ('RGBA', 'LA'):
        # アルファチャンネルが実際に使われているか確認
        if img.mode == 'RGBA':
            r, g, b, a = img.split()
        else:
            g, a = img.split()
        return a.getextrema() != (255, 255)  # 全部不透明でなければ透過あり
    return False


def convert_dds(src: Path, dst: Path, fmt: str = 'png', verbose: bool = False) -> bool:
    """
    DDSファイルをPNG/JPGに変換
    戻り値: 成功=True, 失敗=False
    """
    try:
        img = Image.open(src)

        # RGBまたはRGBAに変換
        if img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
            try:
                img = img.convert('RGBA')
            except Exception:
                img = img.convert('RGB')

        # 出力フォーマット決定
        if fmt == 'auto':
            use_png = has_alpha(img)
            out_ext = '.png' if use_png else '.jpg'
        elif fmt == 'jpg':
            out_ext = '.jpg'
        else:
            out_ext = '.png'

        out_path = dst.with_suffix(out_ext)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_ext == '.jpg':
            # JPG は透過非対応 → RGB に変換
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img, mask=img.split()[1])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(out_path, 'JPEG', quality=90, optimize=True)
        else:
            img.save(out_path, 'PNG', optimize=True)

        if verbose:
            print(f"  ✓ {src.name} → {out_path.name} ({img.size[0]}x{img.size[1]} {img.mode})")
        return True

    except Exception as e:
        if verbose:
            print(f"  ✗ {src.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="DDS → PNG/JPG 変換ツール")
    parser.add_argument("--src",       required=True, help="変換元フォルダ")
    parser.add_argument("--dst",       required=True, help="変換先フォルダ")
    parser.add_argument("--format",    default="png", choices=["png", "jpg", "auto"],
                        help="出力形式 (png/jpg/auto=透過ありPNG・なしJPG)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="サブフォルダも再帰的に処理")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="変換済みファイルをスキップ（デフォルト: ON）")
    parser.add_argument("--verbose",   "-v", action="store_true", help="詳細ログ")
    args = parser.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)

    if not src_dir.exists():
        print(f"[ERROR] 変換元フォルダが見つかりません: {src_dir}")
        sys.exit(1)

    dst_dir.mkdir(parents=True, exist_ok=True)

    # DDS ファイルを収集
    if args.recursive:
        dds_files = list(src_dir.rglob("*.dds")) + list(src_dir.rglob("*.DDS"))
    else:
        dds_files = list(src_dir.glob("*.dds")) + list(src_dir.glob("*.DDS"))

    # BMP/PNG も変換対象に含める
    if args.recursive:
        dds_files += list(src_dir.rglob("*.bmp")) + list(src_dir.rglob("*.BMP"))
    else:
        dds_files += list(src_dir.glob("*.bmp")) + list(src_dir.glob("*.BMP"))

    print(f"[INFO] 対象ファイル: {len(dds_files):,} 件")
    print(f"[INFO] 出力形式: {args.format}")
    print(f"[INFO] 出力先: {dst_dir}")
    print("-" * 60)

    ok    = 0
    skip  = 0
    error = 0

    for src_file in sorted(dds_files):
        # 出力先パスを決定（サブフォルダ構造を維持）
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel.with_suffix('')  # 拡張子なし（convert_ddsで付ける）

        # スキップチェック
        if args.skip_existing:
            for ext in ['.png', '.jpg']:
                if dst_file.with_suffix(ext).exists():
                    skip += 1
                    break
            else:
                # 変換実行
                success = convert_dds(src_file, dst_file, args.format, args.verbose)
                if success:
                    ok += 1
                else:
                    error += 1
        else:
            success = convert_dds(src_file, dst_file, args.format, args.verbose)
            if success:
                ok += 1
            else:
                error += 1

        if not args.verbose and (ok + error) % 500 == 0 and (ok + error) > 0:
            print(f"  [{ok+error:>6}/{len(dds_files)}] 変換中... (成功={ok} エラー={error})")

    print("-" * 60)
    print(f"[完了] 成功={ok:,}  スキップ={skip:,}  エラー={error:,}")
    print(f"[出力] {dst_dir}")


if __name__ == "__main__":
    main()
