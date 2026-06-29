#!/usr/bin/env python3
r"""
AstralTale / X-Legend NFS 全ファイル展開スクリプト

使い方:
    # FileListPC.txt で全展開（推奨）
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist FileListPC.txt --out D:\work\astraltale\out

    # GameDataTranslateFileList で翻訳ファイルだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist GameDataTranslateFileList_jp.txt --out D:\work\out

    # filelist なしで packageindex 全エントリを展開（ファイル名はhash値になる）
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out

    # 特定のhashだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\out --hash 0x6C48514446826F5E

チャンクヘッダー構造:
    [0..7]   hash (uint64 LE)
    [8..11]  checksum CRC32 (uint32 LE)
    [12..15] 不明
    [16..17] zlib ヘッダー (78 xx)
    [18..]   zlib データ本体 (raw deflate)
"""

import struct
import zlib
import argparse
import sys
import os
from pathlib import Path


CHUNK_HEADER_SIZE = 16
ZLIB_HEADER_SIZE  = 2


# ============================================================
# packageindex パーサー
# ============================================================
def parse_packageindex(path: str) -> tuple[dict, int]:
    with open(path, "rb") as f:
        data = f.read()

    version = struct.unpack_from("<I", data, 0)[0]
    if version == 0x20190503:
        hash_fmt, hash_size = "<Q", 8
    else:
        hash_fmt, hash_size = "<I", 4

    entry_size = hash_size + 16
    entries = {}
    pos = 4
    while pos + entry_size <= len(data):
        hv       = struct.unpack_from(hash_fmt, data, pos)[0]
        offset   = struct.unpack_from("<I", data, pos + hash_size)[0]
        size_v   = struct.unpack_from("<I", data, pos + hash_size + 4)[0]
        checksum = struct.unpack_from("<I", data, pos + hash_size + 8)[0]
        time_val = struct.unpack_from("<I", data, pos + hash_size + 12)[0]
        xk = hv & 0xFFFFFFFF
        entries[hv] = {
            "offset":   offset ^ xk,
            "size":     size_v ^ xk,
            "checksum": checksum,
            "time":     time_val,
        }
        pos += entry_size

    return entries, version


# ============================================================
# FileListPC.txt / GameDataTranslateFileList パーサー
# ============================================================
def is_hash_col(s: str) -> bool:
    """16文字の16進数文字列かどうか"""
    return len(s) == 16 and all(c in "0123456789abcdefABCDEF" for c in s)

def load_filelist(path: str) -> dict:
    """
    FileListPC.txt または GameDataTranslateFileList_*.txt を読み込む。

    hash行  : hash(16hex), nfs_name, ts, zsize, fsize, crc32, checksum, 00000000
    通常行  : filename,    dir,       nfs_ts, zsize, fsize, crc32, checksum, 00000000

    戻り値: hash(int) -> {"nfs_name": str, "filename": str|None, "directory": str|None}
    """
    result = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    start = 0
    try:
        int(lines[0].strip())
        start = 1
    except (ValueError, IndexError):
        pass

    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue

        col0 = parts[0].strip()

        if is_hash_col(col0):
            # hash行: hash直接指定
            hv       = int(col0, 16)
            nfs_name = parts[1].strip()
            result[hv] = {
                "nfs_name":  nfs_name,
                "filename":  None,
                "directory": None,
            }
        else:
            # 通常行: ファイル名あり（ogg/dll等はpackageindex管理外なのでスキップ）
            # ファイル名をそのままでは照合できないためここでは登録しない
            pass

    return result


# ============================================================
# NFS チャンク展開
# ============================================================
def extract_chunk(nfs_file: str, offset: int, size: int, expected_checksum: int) -> bytes:
    with open(nfs_file, "rb") as f:
        f.seek(offset)
        chunk = f.read(size)

    if len(chunk) < CHUNK_HEADER_SIZE + ZLIB_HEADER_SIZE:
        raise ValueError(f"チャンクが短すぎる: {len(chunk)} bytes")

    actual_csum = struct.unpack_from("<I", chunk, 8)[0]
    if actual_csum != expected_checksum:
        raise ValueError(
            f"checksum不一致: 期待=0x{expected_checksum:08X} 実際=0x{actual_csum:08X}"
        )

    compressed = chunk[CHUNK_HEADER_SIZE + ZLIB_HEADER_SIZE:]
    try:
        return zlib.decompress(compressed, wbits=-15)
    except zlib.error as e:
        raise ValueError(f"zlib展開失敗: {e}")


# ============================================================
# 拡張子推定
# ============================================================
def guess_extension(data: bytes) -> str:
    if data[:4]  == b"DDS ":       return ".dds"
    if data[:3]  == b"NIF":        return ".nif"
    if data[:4]  == b"OggS":       return ".ogg"
    if data[:3]  in (b"ID3",):     return ".mp3"
    if data[:4]  == b"RIFF":       return ".wav"
    if data[:4]  == b"\x89PNG":    return ".png"
    if data[:2]  == b"\xff\xd8":   return ".jpg"
    if data[:2]  == b"BM":         return ".bmp"
    if data[:4]  == b"PK\x03\x04": return ".zip"
    if data[:4]  == b"<xml":       return ".xml"
    if data[:3]  == b"\xef\xbb\xbf":  # UTF-8 BOM
        return ".ini"
    try:
        sample = data[:512].decode("utf-8")
        if "|" in sample or "=" in sample or "[" in sample:
            return ".ini"
        return ".txt"
    except UnicodeDecodeError:
        pass
    return ".bin"


# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="AstralTale NFS ファイル全展開ツール"
    )
    parser.add_argument("--game",      required=True,
                        help="ゲームフォルダ (例: D:/X-Legend/AstralTale)")
    parser.add_argument("--out",       required=True,
                        help="出力フォルダ")
    parser.add_argument("--filelist",  default=None,
                        help="FileListPC.txt または GameDataTranslateFileList_*.txt")
    parser.add_argument("--hash",      default=None,
                        help="特定のhashだけ展開 (例: 0x6C48514446826F5E)")
    parser.add_argument("--verbose",   "-v", action="store_true",
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

    # NFSファイル存在チェック用キャッシュ
    nfs_exist_cache = {}

    def nfs_file_path(nfs_name: str) -> str | None:
        if nfs_name in nfs_exist_cache:
            return nfs_exist_cache[nfs_name]
        p = os.path.join(game_dir, "nfs", nfs_name[0], nfs_name)
        result = p if os.path.exists(p) else None
        nfs_exist_cache[nfs_name] = result
        return result

    ok    = 0
    skip  = 0
    error = 0
    total = len(pi_entries)

    print(f"\n[INFO] 展開開始: {total:,} エントリ")
    print("-" * 60)

    for hv, entry in pi_entries.items():
        offset   = entry["offset"]
        size     = entry["size"]
        checksum = entry["checksum"]
        time_val = entry["time"]

        # NFSファイル名の決定
        # 1. filelist にhashがあればそちらのnfs_nameを使う
        # 2. なければ packageindex の time 値をそのままファイル名として探す
        nfs_name = None
        if hv in filelist:
            nfs_name = filelist[hv]["nfs_name"]
        else:
            candidate = f"{time_val:08x}"
            nfs_name = candidate  # 存在しなければ後でスキップ

        nfs_file = nfs_file_path(nfs_name)
        if nfs_file is None:
            if args.verbose:
                print(f"  [SKIP] 0x{hv:016X} → nfs/{nfs_name[0]}/{nfs_name} 存在しない")
            skip += 1
            continue

        # 展開
        try:
            data = extract_chunk(nfs_file, offset, size, checksum)
        except ValueError as e:
            if args.verbose:
                print(f"  [ERROR] 0x{hv:016X}: {e}")
            error += 1
            continue

        # 出力パス決定
        ext = guess_extension(data)
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
