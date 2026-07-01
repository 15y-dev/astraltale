# AstralTale Toolkit

A collection of Python tools for analyzing and extracting game data from **AstralTale** (X-Legend Entertainment's NFS archive format).

> 📖 [日本語版 README はこちら](README_ja.md)

## Overview

AstralTale stores game assets (textures, models, configs, translations, etc.) in a proprietary NFS archive system. Files are referenced by FNV-like hash values and compressed with zlib. This toolkit provides scripts to:

- Parse the `packageindex` binary index
- Extract files from NFS archives
- Resolve hash-based filenames back to original paths
- Convert DDS textures to PNG/JPG
- Brute-force discover translation override files
- Dump RC4 keys from process memory
- Monitor network traffic

## Scripts

| Script | Description |
|---|---|
| `nfs_common.py` | Shared library — hash calculation, packageindex parsing, chunk decompression, file type detection |
| `nfs_extract.py` | Bulk extraction of all files from NFS archives |
| `nfs_get.py` | Extract a single file by its in-game path |
| `nfs_bruteforce.py` | Brute-force search for translation override files (e.g. `t_*_jp.ini`) |
| `nfs_rename.py` | Rename hash-named extracted files back to their original paths |
| `packageindex_parser.py` | Parse and inspect the `packageindex` file, export to CSV |
| `dds_convert.py` | Convert DDS textures to PNG/JPG using Pillow |
| `dds_to_png.py` | Convert tall/portrait DDS images to PNG with auto-contrast |
| `memory_dump.py` | Scan process memory for RC4 S-Box states and recover encryption keys |
| `network_monitor.py` | Real-time network packet capture for a target process (psutil + scapy) |

## Requirements

- **Python 3.10+**
- **Pillow** (`pip install Pillow`) — for DDS/image conversion
- **psutil** (`pip install psutil`) — for network monitor
- **scapy** (`pip install scapy`) — for network monitor
- Administrator privileges — for `memory_dump.py`

## Quick Start

### 1. Extract all files from NFS

```bash
python nfs_extract.py --game "D:\X-Legend\AstralTale" --filelist FileListPC.txt --out .\out
```

### 2. Extract a single file by game path

```bash
python nfs_get.py --game "D:\X-Legend\AstralTale" --out .\out "data/db/C_Item.ini"
```

### 3. Rename extracted files to original paths

```bash
# Dry run (preview only)
python nfs_rename.py --out .\out --refs refs.txt --dry-run

# Copy mode (keeps originals)
python nfs_rename.py --out .\out --refs refs.txt --copy
```

### 4. Brute-force translation files

```bash
python nfs_bruteforce.py --game "D:\X-Legend\AstralTale" --filelist FileListPC.txt --out .\out
```

### 5. Convert DDS textures to PNG

```bash
# All DDS files
python dds_convert.py --src .\out --dst .\png --format png

# Portrait images only (tall DDS)
python dds_to_png.py --src .\out --dst .\png_out
```

### 6. Inspect packageindex

```bash
python packageindex_parser.py packageindex
python packageindex_parser.py packageindex --output result.csv
python packageindex_parser.py packageindex --lookup 0x55217DEBFC107937
```

### 7. Calculate a hash (no game folder needed)

```bash
python nfs_get.py --calc "data/db/C_Item.ini"
```

## Directory Structure

```
astraltale/
├── nfs_common.py           # Shared library
├── nfs_extract.py          # Bulk extractor
├── nfs_get.py              # Single file extractor
├── nfs_bruteforce.py       # Translation file finder
├── nfs_rename.py           # File renamer
├── packageindex_parser.py  # Index parser
├── dds_convert.py          # DDS → PNG/JPG converter
├── dds_to_png.py           # Portrait DDS → PNG converter
├── memory_dump.py          # RC4 key memory scanner
├── network_monitor.py      # Network packet monitor
├── known_paths.txt         # Known game file paths (biology, textures)
├── refs.txt                # File references extracted from INI files
├── packageindex.csv        # Exported packageindex data
├── jp_out/                 # Extracted Japanese translation files
├── png_out/                # Converted PNG images
├── portrait_dds/           # Portrait DDS textures
└── gamebin/                # Game binary analysis
```

## Hash Algorithm

The game uses an FNV-1-like hash (64-bit) to map file paths to archive entries:

```python
def hash_char(b: int, seed: int) -> int:
    return (seed * 0x1000193 ^ b) & 0xFFFFFFFFFFFFFFFF

def calc_hash(filename: str, path: str) -> int:
    h = 0
    for b in filename.lower().encode("latin-1"):
        h = hash_char(b, h)
    for b in path.lower().encode("latin-1"):
        h = hash_char(b, h)
    return h
```

The filename is hashed first, then the directory path — both lowercased.

## License

This project is for educational and research purposes.
