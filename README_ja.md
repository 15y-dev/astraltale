# AstralTale Toolkit

**AstralTale**（X-Legend Entertainment）のゲームデータを解析・抽出するための Python ツールキットです。

> 📖 [English README](README.md)

## 概要

AstralTale はゲームアセット（テクスチャ、モデル、設定ファイル、翻訳データ等）を独自の NFS アーカイブ形式で格納しています。ファイルは FNV ライクなハッシュ値で管理され、zlib で圧縮されています。本ツールキットでは以下の操作が可能です：

- `packageindex` バイナリインデックスの解析
- NFS アーカイブからのファイル展開
- ハッシュ名から元のファイルパスへの復元
- DDS テクスチャの PNG/JPG 変換
- 翻訳オーバーライドファイルの総当たり探索
- プロセスメモリからの RC4 鍵ダンプ
- ネットワーク通信の監視

## スクリプト一覧

| スクリプト | 説明 |
|---|---|
| `nfs_common.py` | 共通ライブラリ — ハッシュ計算、packageindex 解析、チャンク展開、拡張子推定 |
| `nfs_extract.py` | NFS アーカイブから全ファイルを一括展開 |
| `nfs_get.py` | ゲーム内パスを指定して単一ファイルを取得 |
| `nfs_bruteforce.py` | 翻訳オーバーライドファイル（`t_*_jp.ini` 等）の総当たり探索 |
| `nfs_rename.py` | ハッシュ名の展開済みファイルを元のパスにリネーム |
| `packageindex_parser.py` | `packageindex` の解析・CSV エクスポート |
| `dds_convert.py` | Pillow を使った DDS → PNG/JPG 変換 |
| `dds_to_png.py` | 縦長（ポートレート）DDS の PNG 変換（自動コントラスト補正付き） |
| `memory_dump.py` | プロセスメモリをスキャンして RC4 S-Box・暗号鍵を探索 |
| `network_monitor.py` | 対象プロセスのネットワークパケットをリアルタイム監視（psutil + scapy） |

## 必要環境

- **Python 3.10+**
- **Pillow** (`pip install Pillow`) — DDS/画像変換用
- **psutil** (`pip install psutil`) — ネットワーク監視用
- **scapy** (`pip install scapy`) — ネットワーク監視用
- 管理者権限 — `memory_dump.py` の実行に必要

## 使い方

### 1. NFS から全ファイル展開

```bash
python nfs_extract.py --game "D:\X-Legend\AstralTale" --filelist FileListPC.txt --out .\out
```

### 2. ゲーム内パス指定で単一ファイル取得

```bash
python nfs_get.py --game "D:\X-Legend\AstralTale" --out .\out "data/db/C_Item.ini"
```

### 3. 展開済みファイルのリネーム

```bash
# 確認のみ（ドライラン）
python nfs_rename.py --out .\out --refs refs.txt --dry-run

# コピーモード（元ファイルを残す・推奨）
python nfs_rename.py --out .\out --refs refs.txt --copy
```

### 4. 翻訳ファイルの総当たり探索

```bash
python nfs_bruteforce.py --game "D:\X-Legend\AstralTale" --filelist FileListPC.txt --out .\out
```

### 5. DDS テクスチャを PNG に変換

```bash
# 全 DDS ファイルを変換
python dds_convert.py --src .\out --dst .\png --format png

# 縦長画像のみ（ポートレート向け）
python dds_to_png.py --src .\out --dst .\png_out
```

### 6. packageindex の解析

```bash
python packageindex_parser.py packageindex
python packageindex_parser.py packageindex --output result.csv
python packageindex_parser.py packageindex --lookup 0x55217DEBFC107937
```

### 7. ハッシュ値の計算（ゲームフォルダ不要）

```bash
python nfs_get.py --calc "data/db/C_Item.ini"
```

## ディレクトリ構成

```
astraltale/
├── nfs_common.py           # 共通ライブラリ
├── nfs_extract.py          # 一括展開ツール
├── nfs_get.py              # 単一ファイル展開ツール
├── nfs_bruteforce.py       # 翻訳ファイル探索ツール
├── nfs_rename.py           # ファイルリネームツール
├── packageindex_parser.py  # インデックス解析ツール
├── dds_convert.py          # DDS → PNG/JPG 変換ツール
├── dds_to_png.py           # ポートレート DDS → PNG 変換ツール
├── memory_dump.py          # RC4 鍵メモリスキャナ
├── network_monitor.py      # ネットワークパケット監視
├── known_paths.txt         # 既知のゲーム内パス一覧（biology, texture 等）
├── refs.txt                # INI ファイルから抽出したファイル参照リスト
├── packageindex.csv        # エクスポート済み packageindex データ
├── jp_out/                 # 展開された日本語翻訳ファイル
├── png_out/                # 変換済み PNG 画像
├── portrait_dds/           # ポートレート DDS テクスチャ
└── gamebin/                # ゲームバイナリ解析データ
```

## ハッシュアルゴリズム

ゲームは FNV-1 ライクな 64 ビットハッシュでファイルパスをアーカイブエントリにマッピングしています：

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

ファイル名を先にハッシュし、その後ディレクトリパスをハッシュします。両方とも小文字に変換されます。

## ライセンス

本プロジェクトは教育・研究目的です。
