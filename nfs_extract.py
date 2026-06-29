#!/usr/bin/env python3
r"""
AstralTale / X-Legend NFS 全ファイル展開スクリプト

使い方:
    # FileListPC.txt を使って全展開（ファイル名あり）
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist FileListPC.txt --out D:\work\astraltale\out

    # packageindex だけで全展開（ファイル名はhash値になる）
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out

    # 特定のhashだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --out D:\work\astraltale\out --hash 0x6C48514446826F5E

    # GameDataTranslateFileList を使って翻訳ファイルだけ展開
    python nfs_extract.py --game D:\X-Legend\AstralTale --filelist GameDataTranslateFileList_jp.txt --out D:\work\astraltale\out
"""

import struct
import zlib
import argparse
import sys
import os
from pathlib import Path


# ========================
# チャンクヘッダー構造
# [0..7]   hash (uint64 LE)
# [8..11]  checksum CRC32 (uint32 LE)
# [12..15] 不明 (展開後サイズ？)
# [16..17] zlib ヘッダー (78 xx)
# [18..]   zlib データ本体
# ========================
CHUNK_HEADER_SIZE = 16
ZLIB_HEADER_SIZE  = 2  # 78 xx


def parse_packageindex(path: str) -> dict:
    """packageindex を読み込んで hash → entry の辞書を返す"""
    entries = {}
    with open(path, "rb") as f:
        data = f.read()

    version = struct.unpack_from("<I", data, 0)[0]
    if version == 0x20190503:
        hash_fmt, hash_size = "<Q", 8
    else:
        hash_fmt, hash_size = "<I", 4

    entry_size = hash_size + 16
    pos = 4
    while pos + entry_size <= len(data):
        hv       = struct.unpack_from(hash_fmt, data, pos)[0]
        offset   = struct.unpack_from("<I", data, pos + hash_size)[0]
        size     = struct.unpack_from("<I", data, pos + hash_size + 4)[0]
        checksum = struct.unpack_from("<I", data, pos + hash_size + 8)[0]
        time_val = struct.unpack_from("<I", data, pos + hash_size + 12)[0]
        xk = hv & 0xFFFFFFFF
        entries[hv] = {
            "offset":   offset ^ xk,
            "size":     size   ^ xk,
            "checksum": checksum,
            "time":     time_val,
        }
        pos += entry_size

    return entries, version


def nfs_path(game_dir: str, nfs_name: str) -> str:
    """nfs_name(uint32の16進文字列) → NFSファイルのフルパス"""
    folder = nfs_name[0]  # 先頭1文字がフォルダ名
    return os.path.join(game_dir, "nfs", folder, nfs_name)


def extract_chunk(nfs_file: str, offset: int, size: int, expected_checksum: int) -> bytes:
    """NFSファイルからチャンクを取り出してzlib展開する"""
    with open(nfs_file, "rb") as f:
        f.seek(offset)
        chunk = f.read(size)

    if len(chunk) < CHUNK_HEADER_SIZE + ZLIB_HEADER_SIZE:
        raise ValueError(f"チャンクが短すぎる: {len(chunk)} バイト")

    # ヘッダー検証: chunk[8..11] が checksum と一致するか
    actual_csum = struct.unpack_from("<I", chunk, 8)[0]
    if actual_csum != expected_checksum:
        raise ValueError(
            f"checksum不一致: 期待=0x{expected_checksum:08X}, 実際=0x{actual_csum:08X}"
        )

    # zlib展開: 先頭16バイトのヘッダー + 2バイトのzlibヘッダーをスキップ
    compressed = chunk[CHUNK_HEADER_SIZE + ZLIB_HEADER_SIZE:]
    try:
        return zlib.decompress(compressed, wbits=-15)  # raw deflate
    except zlib.error as e:
        raise ValueError(f"zlib展開失敗: {e}")


def guess_extension(data: bytes) -> str:
    """先頭バイトからファイル拡張子を推定"""
    if data[:4] == b"DDS ":
        return ".dds"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return ".mp3"
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:3] in (b"\xef\xbb\xbf", ) or (data[:1] in (b"[", b"#", b"V") and b"\r\n" in data[:64]):
        return ".ini"
    if data[:8] == b"Gamebryo":
        return ".nif"
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] == b"PK\x03\x04":
        return ".zip"
    # テキストっぽいか判定
    try:
        sample = data[:256].decode("utf-8")
        if "|" in sample or "=" in sample:
            return ".ini"
        return ".txt"
    except UnicodeDecodeError:
        pass
    return ".bin"


def load_filelist(filelist_path: str) -> dict:
    """
    FileListPC.txt または GameDataTranslateFileList_*.txt を読み込む。
    戻り値: nfs_name → [(filename, directory), ...] または
            hash → (filename, directory) の辞書
    """
    result = {}
    with open(filelist_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    # 1行目がエントリ数なら読み飛ばす
    start = 0
    try:
        int(lines[0].strip())
        start = 1
    except ValueError:
        pass

    for line in lines[start:]:
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue

        # GameDataTranslateFileList 形式: hash, nfs_name, ...
        # FileListPC.txt 形式: filename, dir, nfs_name, ...
        first = parts[0].strip()
        if len(first) == 16 and all(c in "0123456789abcdefABCDEF" for c in first):
            # GameDataTranslateFileList 形式
            fhash    = int(first, 16)
            nfs_name = parts[1].strip()
            result[fhash] = {"nfs_name": nfs_name, "filename": None, "directory": None}
        else:
            # FileListPC.txt 形式
            filename  = parts[0].strip()
            directory = parts[1].strip().lstrip("/").replace("/", os.sep)
            nfs_name  = parts[2].strip()
            if nfs_name not in result:
                result[nfs_name] = []
            result[nfs_name].append({"filename": filename, "directory": directory})

    return result


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale NFS ファイル全展開ツール"
    )
    parser.add_argument("--game",     required=True,  help="ゲームフォルダ (例: D:/X-Legend/AstralTale)")
    parser.add_argument("--out",      required=True,  help="出力フォルダ")
    parser.add_argument("--filelist", default=None,   help="FileListPC.txt または GameDataTranslateFileList_*.txt")
    parser.add_argument("--hash",     default=None,   help="特定のhashだけ展開 (例: 0x6C48514446826F5E)")
    parser.add_argument("--no-verify", action="store_true", help="CRC32検証をスキップ")
    parser.add_argument("--verbose",  "-v", action="store_true", help="詳細ログ")
    args = parser.parse_args()

    game_dir   = args.game
    out_dir    = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # packageindex 読み込み
    pi_path = os.path.join(game_dir, "packageindex")
    if not os.path.exists(pi_path):
        print(f"[ERROR] packageindex が見つかりません: {pi_path}")
        sys.exit(1)

    print(f"[INFO] packageindex 読み込み中...")
    entries, version = parse_packageindex(pi_path)
    print(f"[INFO] {len(entries):,} エントリ読み込み完了 (version=0x{version:08X})")

    # 特定hashのみの場合
    if args.hash:
        target = int(args.hash, 16)
        if target not in entries:
            print(f"[ERROR] hash 0x{target:016X} が見つかりません")
            sys.exit(1)
        entries = {target: entries[target]}
        print(f"[INFO] 指定hash: 0x{target:016X}")

    # filelistの読み込み
    filelist = None
    filelist_type = None
    if args.filelist:
        fl_path = args.filelist if os.path.isabs(args.filelist) else os.path.join(game_dir, args.filelist)
        if not os.path.exists(fl_path):
            print(f"[ERROR] filelist が見つかりません: {fl_path}")
            sys.exit(1)
        print(f"[INFO] filelist 読み込み中: {fl_path}")
        filelist = load_filelist(fl_path)
        # typeを判定
        sample_key = next(iter(filelist))
        filelist_type = "translate" if isinstance(sample_key, int) else "filelist"
        print(f"[INFO] filelist タイプ: {filelist_type}, {len(filelist):,} エントリ")

    # NFSファイルのキャッシュ（同じファイルを何度も開かないように）
    nfs_cache = {}

    ok = 0
    skip = 0
    error = 0
    total = len(entries)

    print(f"\n[INFO] 展開開始: {total:,} エントリ")
    print("-" * 60)

    for i, (hv, entry) in enumerate(entries.items()):
        offset   = entry["offset"]
        size     = entry["size"]
        checksum = entry["checksum"]

        # NFSファイル名の特定
        nfs_name = None
        out_filename = None
        out_subdir = ""

        if filelist_type == "translate" and hv in filelist:
            nfs_name = filelist[hv]["nfs_name"]
        elif filelist_type == "filelist":
            # FileListPC.txtはnfs_nameがキー → hashからは引けない
            # nfs_nameをpackageindexのtimeから推定（近似）
            pass

        # nfs_nameが不明な場合はhashから探す（総当たり不要）
        # → NFSフォルダ内をtime値から探す
        if nfs_name is None:
            time_val = entry["time"]
            nfs_name_candidate = f"{time_val:08x}"
            folder = nfs_name_candidate[0]
            candidate_path = os.path.join(game_dir, "nfs", folder, nfs_name_candidate)
            if os.path.exists(candidate_path):
                nfs_name = nfs_name_candidate

        if nfs_name is None:
            if args.verbose:
                print(f"  [SKIP] 0x{hv:016X} → NFSファイル特定不可")
            skip += 1
            continue

        nfs_file = os.path.join(game_dir, "nfs", nfs_name[0], nfs_name)
        if not os.path.exists(nfs_file):
            if args.verbose:
                print(f"  [SKIP] 0x{hv:016X} → {nfs_file} 存在しない")
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

        # 出力パスの決定
        if filelist_type == "translate" and hv in filelist:
            fname = filelist[hv].get("filename")
            fdir  = filelist[hv].get("directory") or ""
            if fname:
                out_path = out_dir / fdir / fname
            else:
                ext = guess_extension(data)
                out_path = out_dir / f"{hv:016x}{ext}"
        else:
            ext = guess_extension(data)
            out_path = out_dir / f"{hv:016x}{ext}"

        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as f:
            f.write(data)

        ok += 1
        if args.verbose or ok % 500 == 0:
            print(f"  [{ok:>6}/{total}] {out_path.name} ({len(data):,} bytes)")

    print("-" * 60)
    print(f"[完了] 成功={ok:,}  スキップ={skip:,}  エラー={error:,}")
    print(f"[出力] {out_dir}")


if __name__ == "__main__":
    main()
