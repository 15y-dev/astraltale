"""
指定したPIDのプロセスのネットワークをリアルタイムで監視・キャプチャするスクリプト

- psutil : PIDからローカルポートの一覧を取得し、対象プロセスの接続を特定
- scapy  : 実際のパケットをキャプチャし、IPアドレス・ポート・ペイロードを表示

使い方:
    sudo python network_monitor.py <PID>
    sudo python network_monitor.py <PID> --iface eth0   # NICを指定
    sudo python network_monitor.py <PID> --payload       # ペイロードも表示
例:
    sudo python network_monitor.py 1234
    sudo python network_monitor.py 1234 --iface en0 --payload
"""

import sys
import argparse
import threading
import psutil
from datetime import datetime
from scapy.all import sniff, IP, IPv6, TCP, UDP, Raw


# ─────────────────────────────────────────────
# psutil: 対象PIDのポート一覧を動的に取得
# ─────────────────────────────────────────────

def get_process(pid: int) -> psutil.Process:
    try:
        return psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(f"[ERROR] PID {pid} のプロセスが見つかりません。")
        sys.exit(1)
    except psutil.AccessDenied:
        print(f"[ERROR] PID {pid} へのアクセスが拒否されました。sudo で実行してください。")
        sys.exit(1)


def get_local_ports(proc: psutil.Process) -> set[int]:
    """プロセスが使っているローカルポート番号のセットを返す"""
    ports = set()
    try:
        for conn in proc.net_connections(kind="all"):
            if conn.laddr:
                ports.add(conn.laddr.port)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return ports


# ─────────────────────────────────────────────
# ログ出力ヘルパー
# ─────────────────────────────────────────────

RESET  = "\033[0m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RED    = "\033[31m"
GRAY   = "\033[90m"

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexdump(data: bytes, indent: str = "        ") -> str:
    """バイト列を16進数で整形表示する"""
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hex_left = " ".join(f"{b:02x}" for b in chunk[:8])
        hex_right = " ".join(f"{b:02x}" for b in chunk[8:])
        hex_part = f"{hex_left}  {hex_right}".rstrip()
        lines.append(f"{indent}{GRAY}{offset:04x}: {hex_part}{RESET}")
    return "\n".join(lines)


def log_packet(direction: str, proto: str, src: str, dst: str,
               size: int, flags: str = "", payload: bytes = b"", show_payload: bool = False):
    color = GREEN if direction == "OUT" else YELLOW
    flag_str = f" [{flags}]" if flags else ""
    payload_str = ""
    if show_payload and payload:
        payload_str = "\n" + hexdump(payload[:256])

    print(
        f"{GRAY}[{ts()}]{RESET} "
        f"{color}{direction:<3}{RESET} "
        f"{CYAN}{proto:<4}{RESET} "
        f"{src:<40} -> {dst:<40} "
        f"{size:>6} bytes{flag_str}"
        f"{payload_str}"
    )


# ─────────────────────────────────────────────
# scapy: パケットコールバック
# ─────────────────────────────────────────────

def make_callback(proc: psutil.Process, show_payload: bool):
    """パケットコールバックをクロージャで生成"""

    # ポートキャッシュ（1秒ごとに更新するため別スレッドで管理）
    port_cache: dict = {"ports": set(), "lock": threading.Lock()}

    def refresh_ports():
        import time
        while True:
            new_ports = get_local_ports(proc)
            with port_cache["lock"]:
                port_cache["ports"] = new_ports
            time.sleep(1.0)

    t = threading.Thread(target=refresh_ports, daemon=True)
    t.start()
    # 初回即時取得
    with port_cache["lock"]:
        port_cache["ports"] = get_local_ports(proc)

    def callback(pkt):
        # IP層がなければスキップ
        ip_layer = None
        if IP in pkt:
            ip_layer = pkt[IP]
        elif IPv6 in pkt:
            ip_layer = pkt[IPv6]
        if ip_layer is None:
            return

        src_ip = ip_layer.src
        dst_ip = ip_layer.dst

        # TCP / UDP 判定
        if TCP in pkt:
            proto = "TCP"
            l4 = pkt[TCP]
            src_port = l4.sport
            dst_port = l4.dport
            # TCPフラグ文字列化
            flag_map = {"F": "FIN", "S": "SYN", "R": "RST",
                        "P": "PSH", "A": "ACK", "U": "URG"}
            flags = "+".join(v for k, v in flag_map.items() if k in str(l4.flags))
        elif UDP in pkt:
            proto = "UDP"
            l4 = pkt[UDP]
            src_port = l4.sport
            dst_port = l4.dport
            flags = ""
        else:
            return  # ICMP等は対象外

        src_full = f"{src_ip}:{src_port}"
        dst_full = f"{dst_ip}:{dst_port}"
        size = len(pkt)
        payload = bytes(pkt[Raw].load) if Raw in pkt else b""

        with port_cache["lock"]:
            ports = port_cache["ports"]

        # 対象PIDのポートが送信元 → OUT、宛先 → IN
        if src_port in ports:
            log_packet("OUT", proto, src_full, dst_full, size, flags, payload, show_payload)
        elif dst_port in ports:
            log_packet("IN ", proto, src_full, dst_full, size, flags, payload, show_payload)
        # どちらでもなければ無視

    return callback


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PID指定ネットワークキャプチャ (psutil + scapy)")
    parser.add_argument("pid", type=int, help="監視対象のプロセスID")
    parser.add_argument("--iface", default=None, help="キャプチャするNIC (例: eth0, en0)")
    parser.add_argument("--payload", action="store_true", help="ペイロードを16進数/テキストで表示")
    args = parser.parse_args()

    proc = get_process(args.pid)
    proc_name = proc.name()

    print(f"{'='*80}")
    print(f"  PID   : {args.pid} ({proc_name})")
    print(f"  NIC   : {args.iface or 'すべて'}")
    print(f"  ペイロード表示: {'ON' if args.payload else 'OFF'}")
    print(f"  終了  : Ctrl+C")
    print(f"{'='*80}")
    print(f"{'時刻':<14} {'方向':<4} {'プロト':<5} {'送信元':<40}   {'宛先':<40} {'サイズ'}")
    print(f"{'-'*120}")

    callback = make_callback(proc, args.payload)

    try:
        sniff(
            iface=args.iface,
            filter="tcp or udp",   # BPFフィルタでカーネル側に絞らせる
            prn=callback,
            store=False,           # メモリに溜めない
        )
    except KeyboardInterrupt:
        print(f"\n{'='*80}")
        print("  キャプチャを終了しました。")
        print(f"{'='*80}")
    except PermissionError:
        print("[ERROR] 権限が不足しています。sudo で実行してください。")
        sys.exit(1)


def _enable_ansi_on_windows():
    """Windows コンソールで ANSI エスケープシーケンスを有効化"""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


if __name__ == "__main__":
    _enable_ansi_on_windows()
    main()
