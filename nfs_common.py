#!/usr/bin/env python3
"""
AstralTale NFS 共通ライブラリ

ハッシュ計算、packageindex パース、FileList パース、NFS チャンク展開、
拡張子推定など、各スクリプトで共通の機能を集約。
"""

import struct
import zlib
import os


# ============================================================
# 定数
# ============================================================
CHUNK_HEADER_SIZE = 16
ZLIB_HEADER_SIZE = 2


# ============================================================
# ハッシュ関数（Ghidra FUN_140d023a0/FUN_140d023c0 解析結果）
# ============================================================
def hash_char(b: int, seed: int) -> int:
    """seed * 0x1000193 XOR byte (uint64)"""
    return (seed * 0x1000193 ^ b) & 0xFFFFFFFFFFFFFFFF


def calc_hash(filename: str, path: str) -> int:
    """
    filename: ファイル名のみ（小文字）
    path:     ディレクトリ（小文字、末尾/先頭スラッシュなし）
    """
    h = 0
    for b in filename.lower().encode("latin-1"):
        h = hash_char(b, h)
    for b in path.lower().encode("latin-1"):
        h = hash_char(b, h)
    return h


def normalize(raw: str) -> tuple[str, str]:
    """生パス → (filename, path) に正規化"""
    s = raw.replace("\\", "/").lower()
    while "//" in s:
        s = s.replace("//", "/")
    while s.startswith("./"):
        s = s[2:]
    s = s.rstrip("/")
    idx = s.rfind("/")
    return (s[idx + 1 :], s[:idx]) if idx >= 0 else (s, "")


def path_to_hash(game_path: str) -> int:
    """ゲーム内パスからハッシュ値を計算"""
    fn, pt = normalize(game_path)
    return calc_hash(fn, pt)


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
        hv = struct.unpack_from(hash_fmt, data, pos)[0]
        offset = struct.unpack_from("<I", data, pos + hash_size)[0]
        size_v = struct.unpack_from("<I", data, pos + hash_size + 4)[0]
        checksum = struct.unpack_from("<I", data, pos + hash_size + 8)[0]
        time_val = struct.unpack_from("<I", data, pos + hash_size + 12)[0]
        xk = hv & 0xFFFFFFFF
        entries[hv] = {
            "offset": offset ^ xk,
            "size": size_v ^ xk,
            "checksum": checksum,
            "time": time_val,
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
              ↑ ogg/dll等 packageindex 管理外のためスキップ

    戻り値: hash(int) -> {"nfs_name": str}
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
        if len(parts) < 2:
            continue

        col0 = parts[0].strip()
        if is_hash_col(col0):
            hv = int(col0, 16)
            nfs_name = parts[1].strip()
            result[hv] = {"nfs_name": nfs_name}

    return result


# ============================================================
# NFS チャンク展開
# ============================================================
def extract_chunk(nfs_file: str, offset: int, size: int, expected_checksum: int) -> bytes:
    """
    NFSファイルからチャンクを読み込み展開する。
    sizeは展開後サイズの場合も圧縮チャンクサイズの場合もあるため、
    余裕を持って読み込み decompressobj で安全に展開する。
    """
    # sizeが展開後サイズの場合、圧縮データはそれより大きくなり得る
    # 余裕を持ってバッファを確保（最低256バイト + ヘッダー分）
    read_size = max(size * 2, 256) + CHUNK_HEADER_SIZE

    with open(nfs_file, "rb") as f:
        f.seek(offset)
        chunk = f.read(read_size)

    if len(chunk) < CHUNK_HEADER_SIZE:
        raise ValueError(f"チャンクが短すぎる: {len(chunk)} bytes")

    actual_csum = struct.unpack_from("<I", chunk, 8)[0]
    if actual_csum != expected_checksum:
        raise ValueError(
            f"checksum不一致: 期待=0x{expected_checksum:08X} 実際=0x{actual_csum:08X}"
        )

    payload = chunk[CHUNK_HEADER_SIZE:]

    # zlib形式で展開（decompressobjで余分なデータがあっても安全）
    if len(payload) >= 2 and payload[0] == 0x78:
        try:
            obj = zlib.decompressobj()
            return obj.decompress(payload)
        except zlib.error:
            pass
        # raw deflate（zlibヘッダー2バイトをスキップ）
        try:
            obj = zlib.decompressobj(wbits=-15)
            return obj.decompress(payload[ZLIB_HEADER_SIZE:])
        except zlib.error:
            pass

    # 非圧縮データ（zlibヘッダーなし or 展開失敗）→ size分だけ返す
    return payload[:size]


# ============================================================
# 拡張子推定
# ============================================================
def guess_extension(data: bytes) -> str:
    # Gamebryo系 (NifTools)
    if data[:8] == b"Gamebryo":
        if data[:13] == b";Gamebryo KFM":
            return ".kfm"
        if data[:12] == b";Gamebryo KF":
            return ".kf"
        return ".nif"

    # 画像
    if data[:4] == b"DDS ":
        return ".dds"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:2] == b"BM":
        return ".bmp"

    # 音声
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:3] in (b"ID3", b"\xff\xfb", b"\xff\xfe"):
        return ".mp3"

    # アーカイブ
    if data[:4] == b"PK\x03\x04":
        return ".zip"

    # ゲーム固有
    if data[:4] == b"SMP2":
        return ".smp"
    if data[:11] == b"PathMapVer0":
        return ".pmap"
    if data[:4] == b"KMF!":
        return ".kmf"
    if data[:4] == b"LAY\x00":
        return ".layout"

    # XML / HTML
    if data[:5] == b"<?xml":
        return ".xml"
    if data[:9] == b"<!DOCTYPE":
        return ".html"

    # テキスト系
    if data[:3] == b"\xef\xbb\xbf":  # UTF-8 BOM
        try:
            sample = data[3:512].decode("utf-8")
            if sample.startswith("[") or "|" in sample or "=" in sample:
                return ".ini"
            return ".txt"
        except UnicodeDecodeError:
            pass
        return ".txt"

    try:
        sample = data[:512].decode("utf-8")
        if sample.startswith("[") or ("|" in sample and "\n" in sample[:64]):
            return ".ini"
        if all(0x20 <= ord(c) < 0x7F or c in "\r\n\t" for c in sample[:64]):
            return ".txt"
    except UnicodeDecodeError:
        pass

    return ".bin"


# ============================================================
# ヘルパー: NFSファイルパス解決
# ============================================================
def resolve_nfs_path(
    game_dir: str, hv: int, entry: dict, filelist: dict, cache: dict = None
) -> str | None:
    """
    ハッシュ値 + packageindex エントリ + filelist から NFSファイルのパスを返す。
    見つからなければ None。cache を渡すと NFS ファイル存在チェックをキャッシュする。
    """
    if hv in filelist:
        nfs_name = filelist[hv]["nfs_name"]
    else:
        nfs_name = f"{entry['time']:08x}"

    if cache is not None:
        if nfs_name in cache:
            return cache[nfs_name]

    p = os.path.join(game_dir, "nfs", nfs_name[0], nfs_name)
    result = p if os.path.exists(p) else None

    if cache is not None:
        cache[nfs_name] = result

    return result
