#!/usr/bin/env python3
"""
AstralTale / X-Legend NFS packageindex parser
Based on LegendToolX/NFS-EXTRACTOR/NfsExtractor/NFS/LibNFS.cs

Usage:
    python packageindex_parser.py packageindex
    python packageindex_parser.py packageindex --output result.csv
    python packageindex_parser.py packageindex --lookup <hash_hex>
"""

import struct
import datetime
import argparse
import csv
import sys


SUPPORTED_VERSIONS = {
    0x20151018: "v2015 (uint32 hash)",
    0x20190503: "v2019 (uint64 hash)",
}


def parse_packageindex(filepath: str, xor: bool = True) -> list[dict]:
    """
    Parse an NFS packageindex file and return a list of chunk entries.

    Args:
        filepath: Path to the packageindex file
        xor: If True, XOR-decode Offset and Size using the lower 32 bits of Hash

    Returns:
        List of dicts with keys: hash, offset, size, checksum, timestamp, date
    """
    entries = []

    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 4:
        raise ValueError("File too small to be a valid packageindex")

    # Read version (first 4 bytes, little-endian uint32)
    version = struct.unpack_from("<I", data, 0)[0]

    if version not in SUPPORTED_VERSIONS:
        print(f"[WARNING] Unknown version: 0x{version:08X} — attempting to parse anyway")
    else:
        print(f"[INFO] Version: 0x{version:08X} ({SUPPORTED_VERSIONS[version]})")

    # Entry layout:
    #   v2015: uint32 hash + uint32 offset + uint32 size + uint32 checksum + uint32 time = 20 bytes
    #   v2019: uint64 hash + uint32 offset + uint32 size + uint32 checksum + uint32 time = 24 bytes
    if version == 0x20190503:
        hash_fmt = "<Q"   # uint64
        hash_size = 8
    else:
        hash_fmt = "<I"   # uint32 (also used for unknown versions as fallback)
        hash_size = 4

    entry_size = hash_size + 4 + 4 + 4 + 4  # hash + offset + size + checksum + time
    pos = 4  # skip version field

    while pos + entry_size <= len(data):
        hash_val = struct.unpack_from(hash_fmt, data, pos)[0]
        offset   = struct.unpack_from("<I", data, pos + hash_size)[0]
        size     = struct.unpack_from("<I", data, pos + hash_size + 4)[0]
        checksum = struct.unpack_from("<I", data, pos + hash_size + 8)[0]
        timestamp = struct.unpack_from("<I", data, pos + hash_size + 12)[0]

        if xor:
            xor_key = hash_val & 0xFFFFFFFF
            offset  = offset ^ xor_key
            size    = size   ^ xor_key

        try:
            date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            date_str = "invalid"

        entries.append({
            "hash":      hash_val,
            "offset":    offset,
            "size":      size,
            "checksum":  checksum,
            "timestamp": timestamp,
            "date":      date_str,
        })

        pos += entry_size

    return entries, version


def format_hash(version: int, hash_val: int) -> str:
    if version == 0x20190503:
        return f"0x{hash_val:016X}"
    return f"0x{hash_val:08X}"


def print_summary(entries: list[dict], version: int, top_n: int = 20):
    print(f"\n{'='*60}")
    print(f"Total entries : {len(entries):,}")

    sizes = [e["size"] for e in entries]
    print(f"Size  min     : {min(sizes):,} bytes")
    print(f"Size  max     : {max(sizes):,} bytes")
    print(f"Size  avg     : {sum(sizes)//len(sizes):,} bytes")
    print(f"{'='*60}")

    print(f"\nFirst {top_n} entries:")
    print(f"{'#':>5}  {'Hash':>18}  {'Offset':>12}  {'Size':>10}  {'Checksum':>10}  {'Date'}")
    for i, e in enumerate(entries[:top_n]):
        print(
            f"{i:>5}  {format_hash(version, e['hash'])}  "
            f"{e['offset']:>12,}  {e['size']:>10,}  "
            f"0x{e['checksum']:08X}  {e['date']}"
        )

    print(f"\nTop 10 largest files:")
    print(f"{'Hash':>18}  {'Offset':>12}  {'Size':>10}  {'Date'}")
    for e in sorted(entries, key=lambda x: x["size"], reverse=True)[:10]:
        print(
            f"{format_hash(version, e['hash'])}  "
            f"{e['offset']:>12,}  {e['size']:>10,}  {e['date']}"
        )


def export_csv(entries: list[dict], version: int, output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["hash", "offset", "size", "checksum", "timestamp", "date"])
        for e in entries:
            writer.writerow([
                format_hash(version, e["hash"]),
                e["offset"],
                e["size"],
                f"0x{e['checksum']:08X}",
                e["timestamp"],
                e["date"],
            ])
    print(f"\n[INFO] Exported {len(entries):,} entries to: {output_path}")


def lookup_hash(entries: list[dict], version: int, target_hex: str):
    try:
        target = int(target_hex, 16)
    except ValueError:
        print(f"[ERROR] Invalid hex value: {target_hex}")
        return

    results = [e for e in entries if e["hash"] == target]
    if not results:
        print(f"[NOT FOUND] Hash {format_hash(version, target)} not in index")
        return

    for e in results:
        print(f"\nHash     : {format_hash(version, e['hash'])}")
        print(f"Offset   : {e['offset']:,}  (0x{e['offset']:X})")
        print(f"Size     : {e['size']:,}  (0x{e['size']:X})")
        print(f"Checksum : 0x{e['checksum']:08X}")
        print(f"Date     : {e['date']}")


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale / X-Legend NFS packageindex parser"
    )
    parser.add_argument("file", help="Path to packageindex file")
    parser.add_argument(
        "--output", "-o",
        help="Export all entries to a CSV file"
    )
    parser.add_argument(
        "--lookup", "-l",
        help="Look up a specific hash (hex, e.g. 0x55217DEBFC107937)"
    )
    parser.add_argument(
        "--no-xor",
        action="store_true",
        help="Disable XOR decoding of Offset/Size (raw values)"
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=20,
        help="Number of entries to show in summary (default: 20)"
    )
    args = parser.parse_args()

    try:
        entries, version = parse_packageindex(args.file, xor=not args.no_xor)
    except FileNotFoundError:
        print(f"[ERROR] File not found: {args.file}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    if args.lookup:
        lookup_hash(entries, version, args.lookup)
    elif args.output:
        export_csv(entries, version, args.output)
        print_summary(entries, version, top_n=args.top)
    else:
        print_summary(entries, version, top_n=args.top)


if __name__ == "__main__":
    main()
