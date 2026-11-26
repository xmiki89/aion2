"""Cattura passiva dei pacchetti di Aion 2 (Npcap) e parser del protocollo.

Il client non espone log di combattimento e la memoria è chiusa da NCGuard, quindi
i danni si leggono dal traffico che il server manda in chiaro. Nessuna scrittura
sul processo di gioco: si copiano solo i pacchetti (come fanno i meter esistenti).

    <varint len> <payload>                 frame; len = len(payload) + 4
    <varint len> FF FF <u32 size> <lz4>    bundle compresso di altri frame
    00 ...                                 padding
    17 03 03 <u16 len> ...                 record TLS, da scartare

Record usati:
    04 38 ...   colpi (target, switch, actor, skill u32, tipo, valore)
    05 38 ...   tick DoT / cure (target, effetto, actor, ignoto, skill u32/100, importo)
    45 36 ...   spawn con nome (actor varint, mask u32, mask2, len, nome)

La classe si ricava dal codice skill: le skill da 8 cifre sono
`<prefisso classe><...>`, con 11 Gladiator, 12 Templar, 13 Assassin, 14 Ranger,
15 Sorcerer, 16 Spiritmaster, 17 Cleric, 18 Chanter, 19 Brawler.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import threading
import time
from typing import Any, Callable

PCAP_ERRBUF_SIZE = 256
MAX_STREAM_BUFFER = 4 * 1024 * 1024
MAX_BUNDLE_OUTPUT = 1_000_000
STREAM_IDLE_RESET = 45.0

_CLASS_BY_ROSTER_CLASS = {
    5: "Gladiator",
    6: "Gladiator",
    7: "Gladiator",
    8: "Gladiator",
    9: "Templar",
    10: "Templar",
    11: "Templar",
    12: "Templar",
    13: "Ranger",
    14: "Ranger",
    15: "Ranger",
    16: "Ranger",
    17: "Assassin",
    18: "Assassin",
    19: "Assassin",
    20: "Assassin",
    21: "Spiritmaster",
    22: "Spiritmaster",
    23: "Spiritmaster",
    24: "Spiritmaster",
    25: "Sorcerer",
    26: "Sorcerer",
    27: "Sorcerer",
    28: "Sorcerer",
    29: "Cleric",
    30: "Cleric",
    31: "Cleric",
    32: "Cleric",
    33: "Chanter",
    34: "Chanter",
    35: "Chanter",
    36: "Chanter",
}

CLASS_BY_PREFIX = {
    11: "Gladiator",
    12: "Templar",
    13: "Assassin",
    14: "Ranger",
    15: "Sorcerer",
    16: "Spiritmaster",
    17: "Cleric",
    18: "Chanter",
    19: "Brawler",
}


# ------------------------------------------------------------------ wpcap (ctypes)

class _timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class _pcap_pkthdr(ctypes.Structure):
    _fields_ = [("ts", _timeval), ("caplen", ctypes.c_uint32), ("len", ctypes.c_uint32)]


class _bpf_insn(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class _bpf_program(ctypes.Structure):
    _fields_ = [("bf_len", ctypes.c_uint), ("bf_insns", ctypes.POINTER(_bpf_insn))]


class _pcap_if(ctypes.Structure):
    pass


_pcap_if._fields_ = [
    ("next", ctypes.POINTER(_pcap_if)),
    ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
    ("addresses", ctypes.c_void_p),
    ("flags", ctypes.c_uint),
]


def _load_wpcap():
    try:
        lib = ctypes.CDLL("wpcap.dll")
    except OSError:
        return None
    lib.pcap_findalldevs.argtypes = [ctypes.POINTER(ctypes.POINTER(_pcap_if)), ctypes.c_char_p]
    lib.pcap_findalldevs.restype = ctypes.c_int
    lib.pcap_freealldevs.argtypes = [ctypes.POINTER(_pcap_if)]
    lib.pcap_open_live.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
    lib.pcap_open_live.restype = ctypes.c_void_p
    lib.pcap_compile.argtypes = [ctypes.c_void_p, ctypes.POINTER(_bpf_program), ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32]
    lib.pcap_setfilter.argtypes = [ctypes.c_void_p, ctypes.POINTER(_bpf_program)]
    lib.pcap_freecode.argtypes = [ctypes.POINTER(_bpf_program)]
    lib.pcap_next_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(_pcap_pkthdr)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    lib.pcap_next_ex.restype = ctypes.c_int
    lib.pcap_datalink.argtypes = [ctypes.c_void_p]
    lib.pcap_geterr.argtypes = [ctypes.c_void_p]
    lib.pcap_geterr.restype = ctypes.c_char_p
    lib.pcap_close.argtypes = [ctypes.c_void_p]
    return lib


_WPCAP = _load_wpcap()


def capture_available() -> bool:
    return _WPCAP is not None


def list_devices() -> list[tuple[str, str]]:
    if _WPCAP is None:
        return []
    errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
    devices = ctypes.POINTER(_pcap_if)()
    if _WPCAP.pcap_findalldevs(ctypes.byref(devices), errbuf) != 0:
        return []
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
    _WPCAP.pcap_freealldevs(devices)
    return out


def _local_ip() -> str | None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 9))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def pick_device() -> str | None:
    import socket

    import psutil

    devices = [(name, desc) for name, desc in list_devices() if desc]
    if not devices:
        return None
    ip = _local_ip()
    interface = None
    if ip:
        for name, addresses in psutil.net_if_addrs().items():
            for address in addresses:
                if address.family == socket.AF_INET and address.address == ip:
                    interface = name
                    break
            if interface:
                break
    if interface:
        for name, desc in devices:
            if interface.lower() in desc.lower() or desc.lower() in interface.lower():
                return name
    virtual = ("wan miniport", "wi-fi direct", "tap-windows", "kaspersky", "loopback", "virtual")
    for name, desc in devices:
        if not any(marker in desc.lower() for marker in virtual):
            return name
    return devices[0][0]


def _game_endpoints(pid: int | None) -> list[str]:
    if not pid:
        return []
    import psutil

    hosts: set[str] = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid == pid and conn.raddr and not conn.raddr.ip.startswith("127."):
                hosts.add(conn.raddr.ip)
    except Exception:
        return []
    return sorted(hosts)


def _parse_frame(data: bytes, linktype: int):
    if linktype == 1:
        if len(data) < 14:
            return None
        ethertype = struct.unpack("!H", data[12:14])[0]
        offset = 14
        while ethertype in (0x8100, 0x88A8) and len(data) >= offset + 4:
            ethertype = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
            offset += 4
        if ethertype == 0x0800:
            return _ipv4(data, offset)
        return None
    if linktype in (101, 12):
        return _ipv4(data, 0) if data and data[0] >> 4 == 4 else None
    return None


def _ipv4(data: bytes, offset: int):
    if len(data) < offset + 20:
        return None
    ihl = (data[offset] & 0x0F) * 4
    if data[offset] >> 4 != 4 or ihl < 20 or data[offset + 9] != 6:
        return None
    total = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
    src = ".".join(str(b) for b in data[offset + 12 : offset + 16])
    dst = ".".join(str(b) for b in data[offset + 16 : offset + 20])
    end = min(len(data), offset + total) if total else len(data)
    tcp_at = offset + ihl
    if len(data) < tcp_at + 20:
        return None
    sport, dport = struct.unpack("!HH", data[tcp_at : tcp_at + 4])
    header_len = (data[tcp_at + 12] >> 4) * 4
    if header_len < 20:
        return None
    return src, dst, sport, dport, data[tcp_at + header_len : end]


# ------------------------------------------------------------------ protocollo

def read_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    count = 0
    while True:
        if offset + count >= len(data):
            return None
        byte = data[offset + count]
        count += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, count
        shift += 7
        if shift >= 32:
            return None


def lz4_block(data: bytes, expected: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data) and len(out) < expected:
        token = data[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            while i < len(data):
                extra = data[i]
                i += 1
                literals += extra
                if extra != 255:
                    break
        out += data[i : i + literals]
        i += literals
        if i + 2 > len(data):
            break
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            break
        length = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while i < len(data):
                extra = data[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        start = len(out) - offset
        for k in range(length):
            out.append(out[start + k])
    return bytes(out[:expected])


def class_from_skill(code: int) -> str | None:
    """Classe dal codice skill: 8 cifre, prefisso di classe (11..19)."""
    if not 10_000_000 <= code <= 19_999_999:
        return None
    prefix = code // 1_000_000
    sub = (code // 10_000) % 100
    if sub == 0:
        return None  # skill generiche dei mob
    return CLASS_BY_PREFIX.get(prefix)


class StreamWalker:
    """Trasforma un flusso TCP continuo in payload di frame."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.synced = False
        self.misses = 0

    def _sync(self) -> None:
        """Una cattura live comincia a metà pacchetto: trova dove ripartire."""
        data = bytes(self.buffer)
        best_offset = 0
        best_score = 0
        for start in range(0, min(300, max(0, len(data) - 32))):
            offset = start
            score = 0
            while offset < len(data) and score < 40:
                head = read_varint(data, offset)
                if not head or head[0] < 4 or head[0] > 65535:
                    break
                end = offset + head[1] + head[0] - 4
                if end > len(data):
                    break
                offset = end
                score += 1
            if score > best_score:
                best_score = score
                best_offset = start
        if best_score >= 2:
            del self.buffer[:best_offset]
            self.synced = True

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer += chunk
        if len(self.buffer) > MAX_STREAM_BUFFER:
            del self.buffer[: len(self.buffer) - MAX_STREAM_BUFFER]
        if not self.synced and len(self.buffer) > 64:
            self._sync()
        payloads: list[bytes] = []
        offset = 0
        data = bytes(self.buffer)
        while offset < len(data):
            byte = data[offset]
            if byte == 0x00:
                offset += 1
                continue
            if (
                byte == 0x17
                and offset + 5 <= len(data)
                and data[offset + 1] == 0x03
                and data[offset + 2] <= 0x04
            ):
                size = 5 + struct.unpack(">H", data[offset + 3 : offset + 5])[0]
                if offset + size > len(data):
                    break
                offset += size
                continue
            head = read_varint(data, offset)
            if not head:
                offset += 1
                continue
            length, width = head
            if length < 4 or length > 65535:
                offset += 1
                continue
            end = offset + width + (length - 4)
            if end > len(data):
                break
            payload = data[offset + width : end]
            if payload[:2] == b"\xFF\xFF" and len(payload) >= 6:
                size = struct.unpack("<I", payload[2:6])[0]
                if 0 < size <= MAX_BUNDLE_OUTPUT:
                    inner = lz4_block(payload[6:], size)
                    if inner:
                        payloads.extend(_walk_bytes(inner, 1))
            else:
                payloads.append(payload)
            offset = end
        del self.buffer[:offset]
        if payloads:
            self.misses = 0
        else:
            self.misses += 1
            if self.misses >= 20:
                # niente frame per un pezzo di flusso: riallinea
                self.synced = False
                self.misses = 0
        return payloads


def _walk_bytes(data: bytes, depth: int) -> list[bytes]:
    payloads: list[bytes] = []
    offset = 0
    while offset < len(data):
        if data[offset] == 0x00:
            offset += 1
            continue
        head = read_varint(data, offset)
        if not head:
            offset += 1
            continue
        length, width = head
        if length < 4 or length > 65535:
            offset += 1
            continue
        end = offset + width + (length - 4)
        if end > len(data):
            break
        payload = data[offset + width : end]
        if payload[:2] == b"\xFF\xFF" and len(payload) >= 6 and depth < 4:
            size = struct.unpack("<I", payload[2:6])[0]
            if 0 < size <= MAX_BUNDLE_OUTPUT:
                inner = lz4_block(payload[6:], size)
                if inner:
                    payloads.extend(_walk_bytes(inner, depth + 1))
        else:
            payloads.append(payload)
        offset = end
    return payloads


class Protocol:
    """Dai payload ai colpi: nomi, classi e danni."""

    def __init__(self) -> None:
        self.names: dict[int, str] = {}
        self.mobs: set[int] = set()
        self.class_votes: dict[int, dict[str, int]] = {}
        self.self_actor: int | None = None
        self.self_class: str | None = None
        self.self_name: str | None = None
        self.self_server: int | None = None

    # ------------------------------------------------------------- nomi
    def display(self, actor: int) -> str:
        return self.names.get(actor) or f"Player {actor}"

    def actor_class(self, actor: int) -> str | None:
        votes = self.class_votes.get(actor)
        if not votes:
            return None
        return max(votes.items(), key=lambda kv: kv[1])[0]

    def _note_name(self, actor: int, name: str) -> None:
        if not name or not 100 <= actor <= 9_999_999:
            return
        clean = "".join(ch for ch in name if ch.isalnum() or ch in "_- ")
        if len(clean) < 2:
            return
        self.names.setdefault(actor, clean.strip())

    def _scan_names(self, payload: bytes) -> None:
        # spawn: <40|41|44|45 36> <actor varint> <mask u32> <mask2> <len> <nome>
        for opcode in (b"\x45\x36", b"\x44\x36", b"\x41\x36", b"\x40\x36"):
            is_mob = opcode in (b"\x41\x36", b"\x40\x36")
            start = payload.find(opcode)
            while start != -1:
                head = read_varint(payload, start + 2)
                if head and 100 <= head[0] <= 9_999_999:
                    actor, width = head
                    if is_mob:
                        self.mobs.add(actor)
                    at = start + 2 + width + 4
                    if at + 1 < len(payload) and payload[at] & 0x01:
                        length = payload[at + 1]
                        raw = payload[at + 2 : at + 2 + length]
                        if 2 <= length <= 36 and _printable(raw):
                            actor_name = raw.decode()
                            self._note_name(actor, actor_name)
                            # il proprio spawn (44/45 36 con marcatore 07) porta
                            # server e classe subito dopo il nome
                            after = at + 2 + length
                            if (
                                not is_mob
                                and payload[at] == 0x07
                                and length >= 3
                                and actor_name.isalnum()
                                and after + 6 <= len(payload)
                            ):
                                server = struct.unpack("<H", payload[after : after + 2])[0]
                                code = struct.unpack("<I", payload[after + 2 : after + 6])[0]
                                if 1000 <= server <= 3000 and 5 <= code <= 36:
                                    self.self_name = actor_name
                                    self.self_server = server
                                    self.self_class = _CLASS_BY_ROSTER_CLASS.get(code)
                                    self.self_actor = actor
                start = payload.find(opcode, start + 1)

        # spawn di mob / evocazioni: segna l'attore come non giocatore
        for opcode in (b"\x40\x36", b"\x41\x36"):
            start = payload.find(opcode)
            while start != -1:
                head = read_varint(payload, start + 2)
                if head and 100 <= head[0] <= 9_999_999:
                    self.mobs.add(head[0])
                start = payload.find(opcode, start + 1)

        # record del proprio personaggio: <len><nome><server u16><classe u32>
        for index in range(len(payload) - 8):
            length = payload[index]
            if not 2 <= length <= 36:
                continue
            raw = payload[index + 1 : index + 1 + length]
            if not _printable(raw):
                continue
            after = index + 1 + length
            if after + 6 > len(payload):
                continue
            server = struct.unpack("<H", payload[after : after + 2])[0]
            code = struct.unpack("<I", payload[after + 2 : after + 6])[0]
            if 1000 <= server <= 3000 and 5 <= code <= 36:
                self.self_name = raw.decode()
                self.self_class = _CLASS_BY_ROSTER_CLASS.get(code)
                self.self_server = server

        # nome preceduto da E2/E0 07 e da un varint con l'actor
        index = 0
        while index + 2 < len(payload):
            if payload[index] in (0xE2, 0xE0) and payload[index + 1] == 0x07:
                length = payload[index + 2]
                raw = payload[index + 3 : index + 3 + length]
                if 2 <= length <= 36 and _printable(raw):
                    actor = _varint_ending_at(payload, index)
                    if actor:
                        self._note_name(actor, raw.decode())
            if index + 2 < len(payload) and payload[index : index + 3] == b"\x0F\x1D\x37":
                head = read_varint(payload, index + 3)
                if head and 100 <= head[0] <= 9_999_999:
                    actor = head[0]
                    scan = index + 3 + head[1]
                    limit = min(len(payload), scan + 500)
                    while scan + 3 < limit:
                        if payload[scan] in (0x06, 0x0E) and payload[scan + 1] == 0 and payload[scan + 2] == 0x36:
                            break
                        if payload[scan] == 0 and payload[scan + 1] == 0:
                            length = payload[scan + 2]
                            raw = payload[scan + 3 : scan + 3 + length]
                            if 2 <= length <= 36 and _printable(raw):
                                self._note_name(actor, raw.decode())
                                break
                        scan += 1
            index += 1

    # ------------------------------------------------------------- parsing
    def consume(self, payload: bytes, now: float) -> list[dict[str, Any]]:
        if len(payload) < 2:
            return []
        self._scan_names(payload)
        if payload[:2] == b"\x04\x38":
            return self._damage(payload, now)
        if payload[:2] == b"\x05\x38":
            return self._dot(payload, now)
        return []

    def _damage(self, payload: bytes, now: float) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        offset = 2
        parsed_any = False
        while offset < len(payload):
            chained = False
            if payload[offset : offset + 2] == b"\x01\x00":
                offset += 2
                chained = True
            if parsed_any and not chained:
                break

            head = read_varint(payload, offset)
            if not head:
                break
            target, width = head
            offset += width
            if target == 0 or target > 2_000_000_000:
                break

            head = read_varint(payload, offset)
            if not head:
                break
            switch, width = head
            offset += width
            low = switch & 0x0F
            no_value = low in (0, 2)
            if not (4 <= low <= 7) and not no_value:
                break

            flag = read_varint(payload, offset)
            if not flag:
                break
            offset += flag[1]

            head = read_varint(payload, offset)
            if not head:
                break
            actor, width = head
            offset += width
            if actor == 0 or actor > 2_000_000_000:
                break

            if offset + 4 > len(payload):
                break
            skill = struct.unpack("<I", payload[offset : offset + 4])[0]
            offset += 4
            if not 1 <= skill <= 299_999_999:
                break
            offset += 1  # uid del colpo
            head = read_varint(payload, offset)
            if not head:
                break
            hit_type, width = head
            offset += width
            if no_value:
                break

            extra = 0
            if low & 0x02:
                if offset + 2 > len(payload):
                    break
                offset += 1
                hp = read_varint(payload, offset)
                if not hp:
                    break
                offset += hp[1]
                offset += 1
                extra = hp[1] - 1

            offset += {5: 12, 6: 10, 7: 14}.get(low, 8) + extra
            if offset >= len(payload):
                break

            head = read_varint(payload, offset)
            if not head:
                break
            first, width = head
            offset += width
            head = read_varint(payload, offset)
            if not head:
                break
            second, width = head
            offset += width
            if first == 0:
                head = read_varint(payload, offset)
                if head:
                    first, second = second, head[0]
                    offset += head[1]

            if not 0 <= second <= 99_999_999:
                break

            cls = class_from_skill(skill)
            if cls:
                votes = self.class_votes.setdefault(actor, {})
                votes[cls] = votes.get(cls, 0) + max(second, 1)

            events.append(
                {
                    "actor": actor,
                    "target": target,
                    "skill": skill,
                    "amount": second,
                    "crit": hit_type == 3,
                    "dot": False,
                    "t": now,
                    "class": cls,
                }
            )
            parsed_any = True
        return events

    def _dot(self, payload: bytes, now: float) -> list[dict[str, Any]]:
        offset = 2
        head = read_varint(payload, offset)
        if not head:
            return []
        target, width = head
        offset += width
        if offset >= len(payload):
            return []
        effect = payload[offset]
        offset += 1
        damage_effect = effect in (0x02, 0x0A, 0x06, 0x0E)
        heal_effect = effect in (0x01, 0x09, 0x0B)
        if not damage_effect and not heal_effect:
            return []
        head = read_varint(payload, offset)
        if not head:
            return []
        actor, width = head
        offset += width
        head = read_varint(payload, offset)
        if not head:
            return []
        offset += head[1]
        if offset + 4 > len(payload):
            return []
        skill = struct.unpack("<I", payload[offset : offset + 4])[0] // 100
        offset += 4
        head = read_varint(payload, offset)
        if not head or not 0 < head[0] <= 99_999_999:
            return []
        amount = head[0]
        if damage_effect and actor == target:
            return []
        cls = class_from_skill(skill)
        if cls:
            votes = self.class_votes.setdefault(actor, {})
            votes[cls] = votes.get(cls, 0) + amount
        return [
            {
                "actor": actor,
                "target": target,
                "skill": skill,
                "amount": amount if damage_effect else 0,
                "heal": amount if heal_effect else 0,
                "crit": False,
                "dot": damage_effect,
                "t": now,
                "class": cls,
            }
        ]


def _printable(raw: bytes) -> bool:
    return bool(raw) and all(32 <= byte < 127 for byte in raw)


def _varint_ending_at(data: bytes, end: int) -> int | None:
    for start in range(max(0, end - 5), end):
        head = read_varint(data, start)
        if head and start + head[1] == end and 100 <= head[0] <= 9_999_999:
            return head[0]
    return None


# ------------------------------------------------------------------ feed live

class CaptureFeed:
    """Cattura in background e consegna eventi pronti per il meter."""

    def __init__(self, pid_provider: Callable[[], int | None] | None = None) -> None:
        self.pid_provider = pid_provider
        self.protocol = Protocol()
        self.events: list[dict[str, Any]] = []
        self.packets = 0
        self.hits = 0
        self.error = ""
        self.paused = False
        self._self_damage = 0
        self._damage_by_actor: dict[int, int] = {}
        self._pending: dict[int, list[dict[str, Any]]] = {}
        self._pending_since: dict[int, float] = {}
        self._self_label: str | None = None
        self._rename: tuple[str, str] | None = None
        self._labels: dict[int, str] = {}
        self._renames: list[tuple[str, str]] = []
        self.known_name: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._walker: dict[tuple, StreamWalker] = {}
        self._last_seen: dict[tuple, float] = {}
        self._last_device = ""
        self.self_hint: str | None = None

    # ------------------------------------------------------------------ stato
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return True
        if not capture_available():
            self.error = "Npcap non installato (serve per leggere i pacchetti)"
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aion2-capture", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def poll(self) -> list[dict[str, Any]]:
        self._flush_pending()
        self._track_self_label()
        with self._lock:
            events = self.events
            self.events = []
        return events

    def take_renames(self) -> list[tuple[str, str]]:
        renames = self._renames
        self._renames = []
        if self._rename is not None:
            renames.append(self._rename)
            self._rename = None
        return renames

    def candidates(self) -> list[str]:
        """Righe che possono essere il giocatore (chi fa danni da giocatore)."""
        rows: list[str] = []
        for actor in sorted(self._damage_by_actor, key=lambda a: -self._damage_by_actor[a]):
            if actor in self.protocol.mobs or not self.protocol.actor_class(actor):
                continue
            rows.append(self.protocol.names.get(actor) or f"Player {actor}")
        return rows

    def set_self_label(self, label: str) -> None:
        """Dice al meter qual e' la riga del giocatore (nome o 'Player <id>')."""
        if not label:
            return
        if label.startswith("Player "):
            try:
                actor = int(label.split(" ", 1)[1])
            except ValueError:
                actor = 0
            if actor:
                self.protocol.self_actor = actor
                self.self_hint = None
                old = self._labels.get(actor) or label
                if old != "Tu":
                    self._renames.append((old, "Tu"))
                self._labels[actor] = "Tu"
                self.protocol.self_name = self.protocol.names.get(actor)
                return
        self.set_self_hint(label)
        for actor, name in self.protocol.names.items():
            if name.lower() == label.lower():
                self.protocol.self_actor = actor
                break

    def _track_self_label(self) -> None:
        """Se il nome del personaggio arriva dopo i primi colpi, rinomina la riga."""
        if self.protocol.self_actor is None:
            return
        label = self.protocol.names.get(self.protocol.self_actor) or "Tu"
        if self._self_label is None:
            self._self_label = label
        elif label != self._self_label:
            self._rename = (self._self_label, label)
            self._self_label = label

    def _flush_pending(self) -> None:
        """Colpi in attesa del nome: appena lo spawn arriva, entrano con il nome."""
        now = time.monotonic()
        with self._lock:
            for actor, items in list(self._pending.items()):
                name = self.protocol.names.get(actor)
                if name:
                    for event in items:
                        event["src"] = name
                        event["class"] = self.protocol.actor_class(actor)
                        self.events.append(event)
                    self._pending.pop(actor, None)
                    self._pending_since.pop(actor, None)
                elif now - self._pending_since.get(actor, now) > 45:
                    # mai nominato: non e' un giocatore, non mostrarlo
                    self._pending.pop(actor, None)
                    self._pending_since.pop(actor, None)

    def set_self_hint(self, name: str | None) -> None:
        self.self_hint = name
        if name:
            self.set_known_name(name)

    def set_known_name(self, name: str | None) -> None:
        """Nome del personaggio scelto dal giocatore (o letto da session.json)."""
        if not name:
            return
        self.known_name = name
        if not self.protocol.self_name:
            self.protocol.self_name = name

    # ------------------------------------------------------------------ cattura
    def _game_pid(self) -> int | None:
        if self.pid_provider is not None:
            try:
                return self.pid_provider()
            except Exception:
                return None
        try:
            import psutil
        except Exception:
            return None
        best: tuple[int, int] | None = None
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            name = (proc.info.get("name") or "").lower()
            if name != "aion2.exe":
                continue
            rss = int(getattr(proc.info.get("memory_info"), "rss", 0) or 0)
            if best is None or rss > best[1]:
                best = (int(proc.info["pid"]), rss)
        return best[0] if best else None

    def _run(self) -> None:
        while not self._stop.is_set():
            pid = self._game_pid()
            if not pid:
                self.error = "Aion 2 non in esecuzione"
                self._stop.wait(2.0)
                continue
            hosts = _game_endpoints(pid)
            if not hosts:
                self.error = "Attendo la connessione al server di Aion 2"
                self._stop.wait(2.0)
                continue
            device = pick_device()
            if not device:
                self.error = "Nessuna interfaccia di rete per la cattura"
                self._stop.wait(5.0)
                continue
            self._last_device = device
            bpf = "tcp and (" + " or ".join(f"host {host}" for host in hosts) + ")"
            try:
                self._capture_loop(device, bpf, hosts)
            except Exception as exc:  # pragma: no cover - diagnostica
                self.error = f"Cattura interrotta: {exc}"
                self._stop.wait(3.0)

    def _capture_loop(self, device: str, bpf: str, hosts: list[str]) -> None:
        errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = _WPCAP.pcap_open_live(device.encode(), 262144, 1, 200, errbuf)
        if not handle:
            self.error = "Cattura negata: Npcap richiede i privilegi di amministratore"
            self._stop.wait(10.0)
            return
        program = _bpf_program()
        if _WPCAP.pcap_compile(handle, ctypes.byref(program), bpf.encode(), 1, 0xFFFFFFFF) != 0:
            message = _WPCAP.pcap_geterr(handle)
            _WPCAP.pcap_close(handle)
            self.error = f"Filtro non valido: {message.decode(errors='replace')}"
            return
        _WPCAP.pcap_setfilter(handle, ctypes.byref(program))
        _WPCAP.pcap_freecode(ctypes.byref(program))
        self.error = ""
        server = set(hosts)
        header = ctypes.POINTER(_pcap_pkthdr)()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        last_check = time.monotonic()
        try:
            while not self._stop.is_set():
                status = _WPCAP.pcap_next_ex(ctypes.c_void_p(handle), ctypes.byref(header), ctypes.byref(data))
                if status == 0:
                    continue
                if status < 0:
                    break
                raw = ctypes.string_at(data, header.contents.caplen)
                self.packets += 1
                parsed = _parse_frame(raw, 1)
                if not parsed:
                    continue
                src, dst, sport, dport, payload = parsed
                if not payload:
                    continue
                key = (src, sport, dst, dport)
                walker = self._walker.get(key)
                if walker is None:
                    walker = StreamWalker()
                    self._walker[key] = walker
                self._last_seen[key] = time.monotonic()
                for frame in walker.feed(payload):
                    now = time.monotonic()
                    for hit in self.protocol.consume(frame, now):
                        event = self._to_event(hit, src in server)
                        if event is not None:
                            with self._lock:
                                self.events.append(event)
                if time.monotonic() - last_check > 5:
                    last_check = time.monotonic()
                    for key, stamp in list(self._last_seen.items()):
                        if time.monotonic() - stamp > STREAM_IDLE_RESET:
                            self._walker.pop(key, None)
                            self._last_seen.pop(key, None)
        finally:
            _WPCAP.pcap_close(ctypes.c_void_p(handle))

    # ------------------------------------------------------------------ eventi
    def _to_event(self, hit: dict[str, Any], from_server: bool) -> dict[str, Any] | None:
        actor = int(hit["actor"])
        target = int(hit["target"])
        skill = int(hit["skill"])
        amount = int(hit["amount"])
        heal = int(hit.get("heal") or 0)
        label = f"Skill {skill}"

        if heal:
            return {
                "type": "heal",
                "src": self.protocol.display(actor),
                "class": self.protocol.actor_class(actor),
                "skill": label,
                "amount": heal,
                "t": hit["t"],
            }
        if amount <= 0:
            return None
        self_actor = self._self_actor()
        name = self.protocol.names.get(actor)
        if actor == self_actor:
            kind = "damage"
            source = name or self.known_name or "Tu"
            self._self_damage += amount
        elif target == self_actor:
            kind = "taken"
            mob = actor in self.protocol.mobs or 1_000_000 <= skill <= 9_999_999
            source = name or ("Mob" if mob else f"Player {actor}")
        else:
            # un mob che colpisce altri non entra nel meter
            if 1_000_000 <= skill <= 9_999_999 or actor in self.protocol.mobs:
                return None
            if not name:
                # un mob non ha nome e non entra; un giocatore senza spawn si'
                if not self.protocol.actor_class(actor):
                    return None
                source = f"Player {actor}"
            else:
                source = name
            kind = "damage"
        self._damage_by_actor[actor] = self._damage_by_actor.get(actor, 0) + (
            amount if kind == "damage" else 0
        )
        previous = self._labels.get(actor)
        if previous is not None and previous != source:
            with self._lock:
                self._renames.append((previous, source))
        self._labels[actor] = source
        self.hits += 1
        return {
            "type": kind,
            "src": source,
            "class": self.protocol.actor_class(actor),
            "skill": label,
            "amount": amount,
            "crit": bool(hit.get("crit")),
            "multi": bool(hit.get("dot")),
            "t": hit["t"],
            "self": actor == self_actor,
        }

    def _self_actor(self) -> int | None:
        if self.protocol.self_actor is not None:
            return self.protocol.self_actor
        if self.known_name and self.protocol.self_actor is None:
            # un solo giocatore senza nome e in combattimento: sei tu
            unnamed = [
                actor
                for actor in self._damage_by_actor
                if actor not in self.protocol.mobs
                and self.protocol.actor_class(actor)
                and not self.protocol.names.get(actor)
            ]
            if len(unnamed) == 1:
                self.protocol.self_actor = unnamed[0]
                self._labels[unnamed[0]] = self.known_name
                return unnamed[0]
        for name in (self.protocol.self_name, self.self_hint):
            if not name:
                continue
            for actor, actor_name in self.protocol.names.items():
                if actor_name.lower() == name.lower():
                    self.protocol.self_actor = actor
                    return actor
        hint = self.self_hint
        if hint:
            for actor, name in self.protocol.names.items():
                if name.lower() == hint.lower():
                    self.protocol.self_actor = actor
                    return actor
        return None

    # ------------------------------------------------------------------ classe
    def detected_class(self) -> str | None:
        actor = self.protocol.self_actor
        if actor is not None:
            found = self.protocol.actor_class(actor)
            if found:
                return found
        return self.protocol.self_class

    def detected_name(self) -> str | None:
        actor = self.protocol.self_actor
        if actor is not None and self.protocol.names.get(actor):
            return self.protocol.names[actor]
        return self.known_name or self.protocol.self_name
