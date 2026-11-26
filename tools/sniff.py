"""Cattura passiva dello stream di Aion 2 (Npcap via ctypes).

Nessuna scrittura sul processo di gioco, nessuna iniezione: si copiano solo i
pacchetti che il server manda al client, come fanno i meter esistenti.

Uso:
    python tools/sniff.py --list                  # interfacce disponibili
    python tools/sniff.py --seconds 20            # cattura sulle connessioni di AION2.exe
    python tools/sniff.py --seconds 20 --all      # tutto il TCP della macchina

Produce in --out (default sniff_out):
    capture.pcap        cattura grezza, apribile con Wireshark
    flow_<n>_<from>.bin primi MB di payload di ogni flusso
"""

from __future__ import annotations

import argparse
import ctypes
import pathlib
import struct
import sys
import time

wpcap = ctypes.CDLL("wpcap.dll")

PCAP_ERRBUF_SIZE = 256
MAX_BUFFER = 4 * 1024 * 1024


class timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class pcap_pkthdr(ctypes.Structure):
    _fields_ = [("ts", timeval), ("caplen", ctypes.c_uint32), ("len", ctypes.c_uint32)]


class bpf_insn(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class bpf_program(ctypes.Structure):
    _fields_ = [("bf_len", ctypes.c_uint), ("bf_insns", ctypes.POINTER(bpf_insn))]


class pcap_if(ctypes.Structure):
    pass


pcap_if._fields_ = [
    ("next", ctypes.POINTER(pcap_if)),
    ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
    ("addresses", ctypes.c_void_p),
    ("flags", ctypes.c_uint),
]

wpcap.pcap_findalldevs.argtypes = [ctypes.POINTER(ctypes.POINTER(pcap_if)), ctypes.c_char_p]
wpcap.pcap_findalldevs.restype = ctypes.c_int
wpcap.pcap_freealldevs.argtypes = [ctypes.POINTER(pcap_if)]
wpcap.pcap_open_live.argtypes = [
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_char_p,
]
wpcap.pcap_open_live.restype = ctypes.c_void_p
wpcap.pcap_compile.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(bpf_program),
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_uint32,
]
wpcap.pcap_setfilter.argtypes = [ctypes.c_void_p, ctypes.POINTER(bpf_program)]
wpcap.pcap_freecode.argtypes = [ctypes.POINTER(bpf_program)]
wpcap.pcap_next_ex.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.POINTER(pcap_pkthdr)),
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
]
wpcap.pcap_next_ex.restype = ctypes.c_int
wpcap.pcap_datalink.argtypes = [ctypes.c_void_p]
wpcap.pcap_geterr.argtypes = [ctypes.c_void_p]
wpcap.pcap_geterr.restype = ctypes.c_char_p
wpcap.pcap_close.argtypes = [ctypes.c_void_p]


def list_devices() -> list[tuple[str, str]]:
    errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
    devices = ctypes.POINTER(pcap_if)()
    if wpcap.pcap_findalldevs(ctypes.byref(devices), errbuf) != 0:
        raise OSError(errbuf.value.decode(errors="replace"))
    out: list[tuple[str, str]] = []
    node = devices
    while node:
        entry = node.contents
        out.append(
            (
                entry.name.decode(errors="replace") if entry.name else "",
                entry.description.decode(errors="replace") if entry.description else "",
            )
        )
        node = entry.next
    wpcap.pcap_freealldevs(devices)
    return out


def local_ip_for_remote() -> str | None:
    """IP locale usato per uscire verso Internet (nessun pacchetto inviato)."""
    import socket as _socket

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 9))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def pick_device() -> str:
    import socket as _socket

    import psutil

    devices = [(name, desc) for name, desc in list_devices() if desc]
    if not devices:
        raise OSError("nessuna interfaccia di cattura disponibile")

    ip = local_ip_for_remote()
    interface = None
    if ip:
        for name, addresses in psutil.net_if_addrs().items():
            for address in addresses:
                if address.family == _socket.AF_INET and address.address == ip:
                    interface = name
                    break
            if interface:
                break
    if interface:
        for name, desc in devices:
            if interface.lower() in desc.lower() or desc.lower() in interface.lower():
                print(f"Interfaccia attiva: {interface} ({ip})")
                return name

    virtual = ("wan miniport", "wi-fi direct", "tap-windows", "kaspersky", "loopback", "virtual")
    for name, desc in devices:
        if not any(marker in desc.lower() for marker in virtual):
            return name
    return devices[0][0]


def game_pid() -> int | None:
    import psutil

    best: tuple[int, int] | None = None
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        name = (proc.info.get("name") or "").lower()
        if name != "aion2.exe":
            continue
        rss = int(getattr(proc.info.get("memory_info"), "rss", 0) or 0)
        if best is None or rss > best[1]:
            best = (int(proc.info["pid"]), rss)
    return best[0] if best else None


def game_hosts(pid: int | None) -> list[str]:
    if not pid:
        return []
    import psutil

    hosts: set[str] = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid != pid or not conn.raddr:
                continue
            hosts.add(conn.raddr.ip)
    except Exception:
        return []
    return sorted(hosts)


def open_capture(device: str, bpf: str) -> tuple[int, str]:
    errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
    handle = wpcap.pcap_open_live(device.encode(), 262144, 1, 200, errbuf)
    if not handle:
        raise OSError(f"pcap_open_live: {errbuf.value.decode(errors='replace')}")
    program = bpf_program()
    if wpcap.pcap_compile(handle, ctypes.byref(program), bpf.encode(), 1, 0xFFFFFFFF) != 0:
        message = wpcap.pcap_geterr(handle)
        wpcap.pcap_close(handle)
        raise OSError(f"filtro BPF '{bpf}' non valido: {message.decode(errors='replace')}")
    if wpcap.pcap_setfilter(handle, ctypes.byref(program)) != 0:
        message = wpcap.pcap_geterr(handle)
        wpcap.pcap_close(handle)
        raise OSError(f"pcap_setfilter: {message.decode(errors='replace')}")
    wpcap.pcap_freecode(ctypes.byref(program))
    linktype = int(wpcap.pcap_datalink(handle))
    return int(handle), f"linktype {linktype}"


def parse_frame(data: bytes, linktype: int):
    """Ritorna (proto, src, dst, sport, dport, payload) oppure None."""
    if linktype == 1:  # Ethernet
        if len(data) < 14:
            return None
        ethertype = struct.unpack("!H", data[12:14])[0]
        offset = 14
        while ethertype in (0x8100, 0x88A8) and len(data) >= offset + 4:
            ethertype = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
            offset += 4
        if ethertype == 0x0800:
            return _ipv4(data, offset)
        if ethertype == 0x86DD:
            return _ipv6(data, offset)
        return None
    if linktype in (101, 12):  # raw IP
        if not data:
            return None
        version = data[0] >> 4
        return _ipv4(data, 0) if version == 4 else _ipv6(data, 0)
    if linktype == 113:  # Linux cooked
        if len(data) < 16:
            return None
        ethertype = struct.unpack("!H", data[14:16])[0]
        return _ipv4(data, 16) if ethertype == 0x0800 else None
    if linktype == 0:  # BSD loopback
        if len(data) < 4:
            return None
        return _ipv4(data, 4) if data[4] >> 4 == 4 else None
    return None


def _ipv4(data: bytes, offset: int):
    if len(data) < offset + 20:
        return None
    ihl = (data[offset] & 0x0F) * 4
    if data[offset] >> 4 != 4 or ihl < 20:
        return None
    proto = data[offset + 9]
    total = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
    src = ".".join(str(b) for b in data[offset + 12 : offset + 16])
    dst = ".".join(str(b) for b in data[offset + 16 : offset + 20])
    end = min(len(data), offset + total) if total else len(data)
    if proto != 6:
        return None
    return _tcp(data, offset + ihl, end, src, dst)


def _ipv6(data: bytes, offset: int):
    if len(data) < offset + 40:
        return None
    if data[offset] >> 4 != 6:
        return None
    next_header = data[offset + 6]
    payload_len = struct.unpack("!H", data[offset + 4 : offset + 6])[0]
    src = ":".join(f"{struct.unpack('!H', data[offset + 8 + i * 2 : offset + 10 + i * 2])[0]:x}" for i in range(8))
    dst = ":".join(f"{struct.unpack('!H', data[offset + 24 + i * 2 : offset + 26 + i * 2])[0]:x}" for i in range(8))
    if next_header != 6:
        return None
    return _tcp(data, offset + 40, min(len(data), offset + 40 + payload_len), src, dst)


def _tcp(data: bytes, offset: int, end: int, src: str, dst: str):
    if len(data) < offset + 20:
        return None
    sport, dport = struct.unpack("!HH", data[offset : offset + 4])
    header_len = (data[offset + 12] >> 4) * 4
    if header_len < 20:
        return None
    payload = data[offset + header_len : end]
    return ("tcp", src, dst, sport, dport, payload)


def ascii_preview(blob: bytes, limit: int = 400) -> str:
    chunk = blob[:limit]
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    return text


def hexdump(blob: bytes, limit: int = 256) -> str:
    lines = []
    for start in range(0, min(len(blob), limit), 16):
        piece = blob[start : start + 16]
        hexes = " ".join(f"{b:02x}" for b in piece)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in piece)
        lines.append(f"    {start:04x}  {hexes:<47}  {text}")
    return "\n".join(lines)


def write_pcap_header(out, linktype: int) -> None:
    out.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, linktype))


def capture(seconds: int, device: str | None, bpf_override: str | None, out_dir: pathlib.Path) -> int:
    pid = game_pid()
    hosts = game_hosts(pid)
    if pid:
        print(f"AION2.exe PID {pid}")
    else:
        print("AION2.exe non in esecuzione: catturo tutto il TCP (utile solo come prova).")
    if hosts:
        print(f"Server remoti del gioco: {', '.join(hosts)}")
        bpf = "tcp and (" + " or ".join(f"host {h}" for h in hosts) + ")"
    else:
        bpf = "tcp"
    if bpf_override:
        bpf = bpf_override
    device = device or pick_device()
    print(f"Interfaccia: {device}")
    print(f"Filtro: {bpf}")

    handle, info = open_capture(device, bpf)
    print(f"Cattura avviata ({info}), {seconds}s. Combatti un po' adesso.")

    out_dir.mkdir(parents=True, exist_ok=True)
    pcap_path = out_dir / "capture.pcap"
    segments_path = out_dir / "segments.jsonl"
    flows: dict[tuple, dict] = {}
    packets = 0
    payload_bytes = 0
    started = time.time()
    header_pointer = ctypes.POINTER(pcap_pkthdr)()
    data_pointer = ctypes.POINTER(ctypes.c_ubyte)()
    segments = segments_path.open("w", encoding="utf-8")
    segment_count = 0
    server_set = set(hosts)

    with pcap_path.open("wb") as pcap:
        write_pcap_header(pcap, 1)
        while time.time() - started < seconds:
            status = wpcap.pcap_next_ex(
                ctypes.c_void_p(handle), ctypes.byref(header_pointer), ctypes.byref(data_pointer)
            )
            if status == 0:
                continue
            if status < 0:
                break
            header = header_pointer.contents
            raw = ctypes.string_at(data_pointer, header.caplen)
            packets += 1
            pcap.write(
                struct.pack(
                    "<IIII",
                    header.ts.tv_sec & 0xFFFFFFFF,
                    header.ts.tv_usec & 0xFFFFFFFF,
                    header.caplen,
                    header.len,
                )
            )
            pcap.write(raw)
            parsed = parse_frame(raw, 1)
            if not parsed:
                continue
            _proto, src, dst, sport, dport, payload = parsed
            if not payload:
                continue
            key = (src, sport, dst, dport)
            entry = flows.get(key)
            if entry is None:
                entry = {"packets": 0, "bytes": 0, "buffer": bytearray(), "first": started}
                flows[key] = entry
            entry["packets"] += 1
            entry["bytes"] += len(payload)
            payload_bytes += len(payload)
            if len(entry["buffer"]) < MAX_BUFFER:
                entry["buffer"] += payload
            if segment_count < 50000:
                stamp = header.ts.tv_sec + header.ts.tv_usec / 1_000_000
                direction = "s2c" if src in server_set else "c2s"
                segments.write(
                    '{"t": %.3f, "dir": "%s", "src": "%s:%d", "dst": "%s:%d", "n": %d, "hex": "%s"}\n'
                    % (stamp, direction, src, sport, dst, dport, len(payload), payload[:4096].hex())
                )
                segment_count += 1
    wpcap.pcap_close(ctypes.c_void_p(handle))
    segments.close()

    elapsed = max(time.time() - started, 0.001)
    print(f"\nPacchetti: {packets} | payload TCP: {payload_bytes:,} B | flussi: {len(flows)}")
    print(f"Salvato: {pcap_path} ({pcap_path.stat().st_size:,} B)" if pcap_path.exists() else "nessun pcap")
    print(f"Segmenti: {segment_count} -> {segments_path}")

    ordered = sorted(flows.items(), key=lambda kv: kv[1]["bytes"], reverse=True)
    for index, (key, entry) in enumerate(ordered[:12]):
        src, sport, dst, dport = key
        direction = "server->client" if src in server_set else "client->server"
        print(
            f"\n[{index}] {src}:{sport} -> {dst}:{dport}  {direction}  "
            f"{entry['packets']} pkt, {entry['bytes']:,} B "
            f"({entry['bytes'] / elapsed:,.0f} B/s)"
        )
        blob = bytes(entry["buffer"])
        path = out_dir / f"flow_{index}_{direction.replace('->', 'to')}.bin"
        path.write_bytes(blob)
        print(f"    salvato {path.name} ({len(blob):,} B)")
        printable = sum(1 for b in blob[:4096] if 32 <= b < 127)
        print(f"    stampabile: {printable * 100 // max(len(blob[:4096]), 1)}% dei primi 4 KB")
        print(hexdump(blob))
        preview = ascii_preview(blob, 300)
        if preview.strip("."):
            print(f"    testo: {preview}")
    if not flows:
        print("\nNessun payload TCP catturato: la cattura richiede privilegi di amministratore.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="elenca le interfacce")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--device", default=None)
    parser.add_argument("--filter", default=None, help="filtro BPF manuale")
    parser.add_argument("--out", default="sniff_out")
    args = parser.parse_args()

    if args.list:
        for name, desc in list_devices():
            print(f"{name}\n   {desc}")
        return 0

    try:
        return capture(args.seconds, args.device, args.filter, pathlib.Path(args.out))
    except OSError as exc:
        print(f"ERRORE: {exc}")
        print("Se parla di permessi, la cattura va lanciata come amministratore.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
