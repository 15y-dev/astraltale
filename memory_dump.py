"""
AstralTale RC4鍵メモリダンプスクリプト

game.bin のプロセスメモリをスキャンして RC4 S-Box (KSA後) を探し、
RC4鍵を特定する。psutil/scapy 不要、ctypes のみ使用。

RC4 ステート構造 (0x108 = 264 bytes, LibTomCrypt 1.18.2):
  +0x00: int32 i  (KSA後は 0)
  +0x04: int32 j  (KSA後は 0)
  +0x08: uint8 S[256]  (0..255 の permutation)

使い方:
    python memory_dump.py <PID>
    python memory_dump.py <PID> --verbose
    python memory_dump.py --wait game.bin
"""

import sys
import ctypes
import ctypes.wintypes as wt
import struct
import argparse
import time

# ─────────────────────────────────────────────
# Windows API 定数
# ─────────────────────────────────────────────

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

# ─────────────────────────────────────────────
# Windows API 関数
# ─────────────────────────────────────────────

kernel32 = ctypes.windll.kernel32

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


def open_process(pid: int):
    """プロセスをオープン (読み取り用)"""
    access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        if err == 5:  # ERROR_ACCESS_DENIED
            print(f"[ERROR] PID {pid} へのアクセスが拒否されました。")
            print("        管理者権限でコマンドプロンプトを起動してください。")
        else:
            print(f"[ERROR] OpenProcess 失敗: エラーコード {err}")
        sys.exit(1)
    return handle


def read_memory(handle, address: int, size: int) -> bytes | None:
    """プロセスメモリを読み取る"""
    buf = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buf,
        size,
        ctypes.byref(bytes_read),
    )
    if ok and bytes_read.value == size:
        return buf.raw
    return None


def iter_regions(handle):
    """コミット済みの読み取り可能メモリリージョンを列挙"""
    mbi = MEMORY_BASIC_INFORMATION()
    mbi_size = ctypes.sizeof(mbi)
    addr = 0
    max_addr = (1 << 47) - 1  # ユーザー空間上限 (x64)

    while addr < max_addr:
        ret = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size
        )
        if ret == 0:
            break

        base = mbi.BaseAddress or 0  # c_void_p は値0のとき None を返す
        region_size = mbi.RegionSize or 0

        if (mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and not (mbi.Protect & PAGE_NOACCESS)
                and mbi.Protect != 0
                and region_size > 0):
            yield base, region_size

        next_addr = base + region_size
        if next_addr <= addr:
            break
        addr = next_addr


# ─────────────────────────────────────────────
# RC4 S-Box 検出
# ─────────────────────────────────────────────

def is_rc4_sbox(data: bytes, offset: int) -> bool:
    """256バイトが 0..255 の permutation (各値が1回ずつ出現) かチェック"""
    if offset + 256 > len(data):
        return False
    sbox = data[offset:offset + 256]
    return len(set(sbox)) == 256


def rc4_ksa(key: bytes) -> list[int]:
    """RC4 KSA を Python で再現して S-Box を返す"""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    return S


def recover_key_from_sbox(sbox: bytes, key_len: int = 5) -> bytes | None:
    """
    S-Box からブルートフォースで鍵を復元する。
    5バイト鍵 = 2^40 = 約1兆通り → ブルートフォースは非現実的。
    代わりに、ソケットオブジェクト内の隣接メモリから鍵を探す。
    """
    # ブルートフォースは非現実的なので None を返す
    return None


def find_rc4_states(handle, verbose: bool = False) -> list[dict]:
    """
    プロセスメモリ全体をスキャンして RC4 ステート構造を探す。
    
    LibTomCrypt RC4 ステート:
      +0x00: i (int32) = 0 (KSA直後)
      +0x04: j (int32) = 0 (KSA直後)
      +0x08: S[256] (permutation of 0..255)
    
    注意: PRGA が1回でも実行されると i != 0 になるため、
    通信開始後は i, j > 0 の可能性がある。
    """
    results = []
    total_scanned = 0
    regions_scanned = 0

    print("[*] メモリスキャン開始...")

    for base, size in iter_regions(handle):
        regions_scanned += 1
        
        # 巨大リージョンは分割して読む (最大16MB単位)
        chunk_size = min(size, 16 * 1024 * 1024)
        
        for chunk_offset in range(0, size, chunk_size):
            read_size = min(chunk_size, size - chunk_offset)
            data = read_memory(handle, base + chunk_offset, read_size)
            if data is None:
                continue
            
            total_scanned += len(data)
            
            # RC4 ステート構造を探す (8バイトヘッダ + 256バイト S-Box)
            # i, j は 0..255 の範囲であること
            for off in range(0, len(data) - 264):
                # i, j を読む (int32 LE)
                i_val = struct.unpack_from("<I", data, off)[0]
                j_val = struct.unpack_from("<I", data, off + 4)[0]
                
                # i, j は 0..255 の範囲
                if i_val > 255 or j_val > 255:
                    continue
                
                # S-Box チェック
                sbox_start = off + 8
                if is_rc4_sbox(data, sbox_start):
                    addr = base + chunk_offset + off
                    sbox = data[sbox_start:sbox_start + 256]
                    
                    # 周辺メモリも記録 (鍵がオブジェクト内にある可能性)
                    context_start = max(0, off - 32)
                    context_end = min(len(data), sbox_start + 256 + 32)
                    context = data[context_start:context_end]
                    
                    result = {
                        "address": addr,
                        "i": i_val,
                        "j": j_val,
                        "sbox": sbox,
                        "context_addr": base + chunk_offset + context_start,
                        "context": context,
                    }
                    results.append(result)
                    
                    if verbose:
                        print(f"  [+] RC4 S-Box 発見: 0x{addr:016X}  i={i_val} j={j_val}")

        if verbose and regions_scanned % 100 == 0:
            mb = total_scanned / (1024 * 1024)
            print(f"  ... {regions_scanned} リージョン, {mb:.1f} MB スキャン済")

    mb = total_scanned / (1024 * 1024)
    print(f"[*] スキャン完了: {regions_scanned} リージョン, {mb:.1f} MB")
    
    return results


# ─────────────────────────────────────────────
# 鍵候補の抽出
# ─────────────────────────────────────────────

def find_key_near_sbox(handle, sbox_addr: int) -> bytes | None:
    """
    ソケットオブジェクトのレイアウト:
      +0x78: 5バイト RC4 鍵
      +0x80: 送信用 RC4 ステートへのポインタ
      +0x88: 受信用 RC4 ステートへのポインタ
    
    S-Box のアドレスから逆算して、ポインタテーブルを探す。
    """
    # S-Box ステートの先頭 (i,j の位置) = sbox_addr - 8
    state_addr = sbox_addr - 8
    
    # このポインタを含むメモリを検索
    # ソケットオブジェクトの +0x80 or +0x88 にこのポインタがある
    # → ソケットオブジェクトの先頭 + 0x78 に鍵がある
    
    # まず state_addr をリトルエンディアンのバイト列に変換
    state_ptr_bytes = struct.pack("<Q", state_addr)
    
    # state_addr の周辺を広く読んで、ポインタを探す
    # (ヒープ上のオブジェクトなので、同じヒープリージョン内にある可能性)
    search_range = 1024 * 1024  # 1MB
    search_start = max(0, state_addr - search_range)
    
    data = read_memory(handle, search_start, search_range * 2)
    if data is None:
        return None
    
    # state_ptr_bytes を検索
    pos = 0
    while True:
        idx = data.find(state_ptr_bytes, pos)
        if idx == -1:
            break
        
        ptr_addr = search_start + idx
        
        # +0x80 にこのポインタがあると仮定 → オブジェクト先頭 = ptr_addr - 0x80
        obj_base_80 = ptr_addr - 0x80
        key_addr_80 = obj_base_80 + 0x78
        
        # +0x88 にこのポインタがあると仮定 → オブジェクト先頭 = ptr_addr - 0x88  
        obj_base_88 = ptr_addr - 0x88
        key_addr_88 = obj_base_88 + 0x78
        
        # 両方の候補を読んでみる
        for label, key_addr in [("送信用(+0x80)", key_addr_80), ("受信用(+0x88)", key_addr_88)]:
            key_data = read_memory(handle, key_addr, 5)
            if key_data is not None:
                # 鍵として妥当かチェック (全ゼロや全FFでないこと)
                if key_data != b'\x00' * 5 and key_data != b'\xff' * 5:
                    # KSA で検証
                    expected_sbox = rc4_ksa(key_data)
                    # しかし PRGA で S-Box が変化しているので、KSA 直後とは一致しない
                    # → 鍵候補として報告するだけ
                    return key_data
        
        pos = idx + 1
    
    return None


# ─────────────────────────────────────────────
# 表示
# ─────────────────────────────────────────────

RESET  = "\033[0m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RED    = "\033[31m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"


def hexdump(data: bytes, start_addr: int = 0, indent: str = "  ") -> str:
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hex_left = " ".join(f"{b:02x}" for b in chunk[:8])
        hex_right = " ".join(f"{b:02x}" for b in chunk[8:])
        ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        addr = start_addr + offset
        lines.append(f"{indent}{GRAY}{addr:016x}:{RESET} {hex_left}  {hex_right}  {GRAY}|{ascii_repr}|{RESET}")
    return "\n".join(lines)


def print_results(results: list[dict], handle):
    if not results:
        print(f"\n{RED}[!] RC4 S-Box が見つかりませんでした。{RESET}")
        print("    考えられる原因:")
        print("    - ゲームがまだサーバーに接続していない")
        print("    - メモリ保護によりスキャンがブロックされた")
        print("    - RC4 ステートが想定と異なるレイアウト")
        return

    print(f"\n{GREEN}{'='*70}{RESET}")
    print(f"{GREEN}{BOLD}  RC4 S-Box を {len(results)} 個発見！{RESET}")
    print(f"{GREEN}{'='*70}{RESET}")

    for i, r in enumerate(results):
        addr = r["address"]
        print(f"\n{CYAN}── S-Box #{i+1} ──────────────────────────────────{RESET}")
        print(f"  アドレス : {YELLOW}0x{addr:016X}{RESET}")
        print(f"  i = {r['i']}, j = {r['j']}")
        
        # S-Box の先頭32バイトを表示
        print(f"  S-Box (先頭32バイト):")
        sbox = r["sbox"]
        hex_str = " ".join(f"{b:02x}" for b in sbox[:32])
        print(f"    {hex_str}")
        
        # S-Box が初期状態 (KSA未実行) かチェック
        if list(sbox) == list(range(256)):
            print(f"  {GRAY}※ 初期状態 (0,1,2,...,255) — KSA 未実行{RESET}")
            continue
        
        # ポインタ逆引きで鍵を探す
        print(f"  鍵候補を検索中...")
        key = find_key_near_sbox(handle, addr + 8)  # +8 は S-Box 先頭
        if key:
            hex_key = " ".join(f"{b:02x}" for b in key)
            print(f"  {GREEN}{BOLD}鍵候補: {hex_key}{RESET}")
            
            # KSA を実行して検証
            expected = rc4_ksa(key)
            if r["i"] == 0 and r["j"] == 0 and list(sbox) == expected:
                print(f"  {GREEN}✅ KSA 検証 OK — この鍵は正しい！{RESET}")
            else:
                print(f"  {YELLOW}⚠ KSA 検証不一致（PRGA 実行後のため S-Box が変化している可能性）{RESET}")
        else:
            print(f"  {GRAY}鍵候補が見つかりませんでした{RESET}")
        
        # 周辺メモリ表示
        print(f"  周辺メモリ:")
        print(hexdump(r["context"][:64], r["context_addr"]))


# ─────────────────────────────────────────────
# プロセス名からPIDを検索
# ─────────────────────────────────────────────

def find_pid_by_name(name: str) -> int | None:
    """タスクリストからプロセス名でPIDを検索"""
    import subprocess
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True, errors="replace"
        )
        for line in output.strip().split("\n"):
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                proc_name = parts[0].strip('"')
                pid_str = parts[1].strip('"')
                if proc_name.lower() == name.lower():
                    return int(pid_str)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def _enable_ansi_on_windows():
    """Windows コンソールで ANSI エスケープシーケンスを有効化"""
    if sys.platform == "win32":
        kernel32_local = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32_local.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong()
        kernel32_local.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32_local.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def main():
    parser = argparse.ArgumentParser(
        description="AstralTale RC4鍵メモリダンプ (ctypes のみ, 管理者権限必要)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("pid", type=int, nargs="?", help="対象プロセスの PID")
    group.add_argument("--wait", metavar="NAME", help="プロセス名を指定して起動を待つ (例: game.bin)")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ表示")
    args = parser.parse_args()

    _enable_ansi_on_windows()

    # PID 取得
    if args.wait:
        print(f"[*] プロセス '{args.wait}' の起動を待機中... (Ctrl+C で中止)")
        pid = None
        while pid is None:
            pid = find_pid_by_name(args.wait)
            if pid is None:
                time.sleep(1.0)
        print(f"[*] プロセス発見: PID {pid}")
    else:
        pid = args.pid

    # プロセスオープン
    print(f"[*] PID {pid} をオープン中...")
    handle = open_process(pid)
    print(f"[*] OpenProcess 成功")

    try:
        # RC4 S-Box 検索
        results = find_rc4_states(handle, verbose=args.verbose)
        
        # 結果表示
        print_results(results, handle)
        
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
