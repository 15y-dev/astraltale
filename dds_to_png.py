#!/usr/bin/env python3
r"""
AstralTale 縦長DDS → PNG 一括変換スクリプト

対応フォーマット:
    - B8G8R8A8 (BGRA 32bit) ← ゲームの主要フォーマット
    - R8G8B8A8 (RGBA 32bit)
    - B8G8R8   (BGR 24bit)
    - DXT1/DXT3/DXT5 (BC1/BC2/BC3) ← 要 pip install pillow-dds

使い方:
    # 縦長のみ変換（デフォルト）
    python dds_to_png.py --src D:\work\astraltale\out --dst D:\work\astraltale\png_out

    # 全ddsを変換
    python dds_to_png.py --src D:\work\astraltale\out --dst D:\work\astraltale\png_out --all

    # 最小サイズ指定（小さいアイコンを除外）
    python dds_to_png.py --src D:\work\astraltale\out --dst D:\work\astraltale\png_out --min-height 200
r"""

import struct
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("[ERROR] Pillow と NumPy が必要です: pip install pillow numpy")
    sys.exit(1)


def linear_to_srgb(img: Image.Image) -> Image.Image:
    """リニア色空間(γ=1.0)からsRGB(γ≈2.2)へ変換"""
    has_alpha = img.mode == 'RGBA'
    if has_alpha:
        r, g, b, a = img.split()
        rgb = Image.merge('RGB', (r, g, b))
    else:
        rgb = img if img.mode == 'RGB' else img.convert('RGB')
        a = None

    arr = np.array(rgb, dtype=np.float32) / 255.0
    # sRGB公式ガンマカーブ
    arr = np.where(
        arr <= 0.0031308,
        arr * 12.92,
        1.055 * np.power(np.maximum(arr, 0.0), 1.0 / 2.4) - 0.055
    )
    result = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), 'RGB')

    if has_alpha:
        r2, g2, b2 = result.split()
        return Image.merge('RGBA', (r2, g2, b2, a))
    return result


def read_dds_header(data: bytes) -> dict | None:
    """DDSヘッダーを解析して情報を返す"""
    if len(data) < 128 or data[:4] != b'DDS ':
        return None

    height   = struct.unpack_from('<I', data, 12)[0]
    width    = struct.unpack_from('<I', data, 16)[0]
    pf_flags = struct.unpack_from('<I', data, 80)[0]
    pf_four  = data[84:88]
    rgb_bits = struct.unpack_from('<I', data, 88)[0]
    r_mask   = struct.unpack_from('<I', data, 92)[0]
    g_mask   = struct.unpack_from('<I', data, 96)[0]
    b_mask   = struct.unpack_from('<I', data, 100)[0]
    a_mask   = struct.unpack_from('<I', data, 104)[0]

    return {
        'width':    width,
        'height':   height,
        'pf_flags': pf_flags,
        'fourcc':   pf_four,
        'rgb_bits': rgb_bits,
        'r_mask':   r_mask,
        'g_mask':   g_mask,
        'b_mask':   b_mask,
        'a_mask':   a_mask,
    }


def dds_to_image(data: bytes, hdr: dict) -> tuple[Image.Image, bool] | None:
    """DDSデータをPIL Imageに変換。戻り値: (Image, is_linear) または None
    is_linear=True: リニア色空間(γ=1.0)、sRGBガンマ補正が必要
    is_linear=False: sRGB色空間、そのまま使用可能
    """
    w, h = hdr['width'], hdr['height']
    pf_flags = hdr['pf_flags']
    fourcc   = hdr['fourcc']
    rgb_bits = hdr['rgb_bits']
    r_mask   = hdr['r_mask']
    g_mask   = hdr['g_mask']
    b_mask   = hdr['b_mask']
    a_mask   = hdr['a_mask']

    pixel_data = data[128:]

    # FourCC形式（圧縮）
    if pf_flags & 0x4:
        fc = fourcc.rstrip(b'\x00').decode('ascii', errors='replace')

        # DX10拡張ヘッダー
        if fc == 'DX10':
            dxgi = struct.unpack_from('<I', data, 128)[0]
            pixel_data = data[148:]
            # BC7_UNORM(98), BC7_UNORM_SRGB(99)
            if dxgi in (98, 99):
                try:
                    from PIL import ImageFile
                    # BC7はPillowが対応していないのでスキップ
                    return None
                except:
                    return None
            # R8G8B8A8_UNORM(28)=リニア, R8G8B8A8_UNORM_SRGB(29)=sRGB
            if dxgi in (28, 29):
                expected = w * h * 4
                if len(pixel_data) < expected:
                    return None
                img = Image.frombytes('RGBA', (w, h), pixel_data[:expected], 'raw', 'RGBA')
                return (img, dxgi == 28)  # 28=リニア, 29=sRGB
            # B8G8R8A8_UNORM(87)=リニア, B8G8R8A8_UNORM_SRGB(91)=sRGB
            if dxgi in (87, 91):
                expected = w * h * 4
                if len(pixel_data) < expected:
                    return None
                img = Image.frombytes('RGBA', (w, h), pixel_data[:expected], 'raw', 'BGRA')
                return (img, dxgi == 87)  # 87=リニア, 91=sRGB
            return None

        # DXT1 (BC1) - 旧DDSフォーマット、sRGB前提
        if fc == 'DXT1':
            try:
                from PIL import DdsImagePlugin
                import io
                return (Image.open(io.BytesIO(data)), False)
            except:
                return None

        # DXT3/DXT5 (BC2/BC3) - 旧DDSフォーマット、sRGB前提
        if fc in ('DXT3', 'DXT5'):
            try:
                import io
                return (Image.open(io.BytesIO(data)), False)
            except:
                return None

        return None

    # RGB/RGBA形式（非圧縮） - 旧DDSフォーマット、色空間情報なし→sRGB前提
    if pf_flags & 0x40 or pf_flags & 0x41:
        expected = w * h * (rgb_bits // 8)
        if len(pixel_data) < expected:
            return None
        raw = pixel_data[:expected]

        if rgb_bits == 32:
            # マスクから BGRA か RGBA か判定
            if r_mask == 0x00ff0000:  # BGRA
                return (Image.frombytes('RGBA', (w, h), raw, 'raw', 'BGRA'), False)
            elif r_mask == 0x000000ff:  # RGBA
                return (Image.frombytes('RGBA', (w, h), raw, 'raw', 'RGBA'), False)
            else:
                # フォールバック: BGRA として試す
                return (Image.frombytes('RGBA', (w, h), raw, 'raw', 'BGRA'), False)

        elif rgb_bits == 24:
            if r_mask == 0xff0000:  # BGR
                return (Image.frombytes('RGB', (w, h), raw, 'raw', 'BGR'), False)
            else:  # RGB
                return (Image.frombytes('RGB', (w, h), raw, 'raw', 'RGB'), False)

        elif rgb_bits == 16:
            # RGB565 など
            return None

    return None


def main():
    parser = argparse.ArgumentParser(description="DDS → PNG 一括変換")
    parser.add_argument("--src",        required=True, help="変換元フォルダ")
    parser.add_argument("--dst",        required=True, help="出力先フォルダ")
    parser.add_argument("--all",        action="store_true", help="全ddsを変換（デフォルト:縦長のみ）")
    parser.add_argument("--min-height", type=int, default=100, help="最小高さ（px）デフォルト100")
    parser.add_argument("--min-width",  type=int, default=0,   help="最小幅（px）デフォルト0")
    parser.add_argument("--verbose",    "-v", action="store_true")
    args = parser.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    dst_dir.mkdir(parents=True, exist_ok=True)

    dds_files = list(src_dir.glob("*.dds"))
    print(f"[INFO] DDS ファイル: {len(dds_files):,} 件")
    print(f"[INFO] 縦長のみ: {not args.all}")
    print(f"[INFO] 最小サイズ: {args.min_width}x{args.min_height}")
    print("-" * 60)

    ok = skip = error = linear_count = 0

    for f in sorted(dds_files):
        data = f.read_bytes()
        hdr  = read_dds_header(data)

        if hdr is None:
            if args.verbose: print(f"  [SKIP] {f.name} (DDSヘッダー不正)")
            skip += 1
            continue

        w, h = hdr['width'], hdr['height']

        # サイズフィルター
        if h < args.min_height or w < args.min_width:
            skip += 1
            continue

        # 縦長フィルター
        if not args.all and h <= w:
            skip += 1
            continue

        # 変換
        result = dds_to_image(data, hdr)
        if result is None:
            if args.verbose: print(f"  [ERR ] {f.name} ({w}x{h}) 未対応フォーマット")
            error += 1
            continue

        img, is_linear = result

        # リニア色空間→sRGBガンマ補正（くすみの根本原因を解消）
        if is_linear:
            img = linear_to_srgb(img)
            linear_count += 1
            if args.verbose:
                print(f"  [γ補正] {f.name} リニア→sRGB変換適用")

        # autocontrast補正（ヒストグラム引き伸ばし、GIMPの自動レベル相当）
        from PIL import ImageOps
        if img.mode == 'RGBA':
            r, g, b, a = img.split()
            rgb = Image.merge('RGB', (r, g, b))
            rgb = ImageOps.autocontrast(rgb, cutoff=0.5)
            r2, g2, b2 = rgb.split()
            img = Image.merge('RGBA', (r2, g2, b2, a))
        else:
            img = ImageOps.autocontrast(img, cutoff=0.5)

        out_path = dst_dir / (f.stem + ".png")
        img.save(out_path, "PNG")
        ok += 1

        if args.verbose or ok % 100 == 0:
            gamma_tag = " [γ]" if is_linear else ""
            print(f"  [{ok:>5}] {f.name} ({w}x{h}) → {out_path.name}{gamma_tag}")

    print("-" * 60)
    print(f"[完了] 変換: {ok:,} 件  スキップ: {skip:,} 件  エラー: {error:,} 件")
    print(f"[γ補正] リニア→sRGB変換: {linear_count:,} 件")
    print(f"[出力] {dst_dir}")


if __name__ == "__main__":
    main()
