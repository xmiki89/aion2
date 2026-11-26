"""Parser dei record di danno di Aion 2 da una cattura passiva.

Formato del flusso (server -> client), ricavato dai byte delle nostre catture:

    <varint len> <payload>                 un frame; len = len(payload) + 4
    <varint len> FF FF <u32 size> <lz4>    un bundle compresso di altri frame
    00 ...                                 padding da saltare
    17 03 03 <u16 len> ...                 record TLS di un'altra connessione

Un frame di danno ha il payload che comincia con `04 38`. Dentro, una sequenza
di colpi:

    [01 00]                      marker di colpo concatenato
    <varint target> <varint switch> <varint flag>
    <varint actor> <u32 skill> <byte uid> <varint hit type>
    <12|10|14|8 byte>            campi del colpo (dipende da switch & 0x0F)
    [flags <varint hp> <angle>]  plotter, solo se switch & 0x02
    <varint scalar> <varint danno>

Uso:
    python tools/damage_parse.py sniff_combat          # analizza la cartella
    python tools/damage_parse.py sniff_combat --top 10
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import struct
import sys

MAX_BUNDLE_OUTPUT = 1_000_000


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


def tls_record_size(data: bytes) -> int | None:
    if len(data) < 5 or data[0] != 0x17 or data[1] != 0x03 or data[2] > 0x04:
        return None
    return 5 + struct.unpack(">H", data[3:5])[0]


def walk_frames(data: bytes, depth: int = 0):
    """Restituisce i payload dei frame trovati nel flusso."""
    offset = 0
    while offset < len(data):
        if data[offset] == 0x00:
            offset += 1
            continue
        record = tls_record_size(data[offset:])
        if record:
            if offset + record > len(data):
                break
            offset += record
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
                    yield from walk_frames(inner, depth + 1)
        else:
            yield payload
        offset = end


def parse_damage_payload(payload: bytes, stamp: float) -> list[dict]:
    """Estrae i colpi da un payload che comincia con 04 38."""
    hits: list[dict] = []
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

        if not read_varint(payload, offset):
            break
        offset += read_varint(payload, offset)[1]

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

        temp = {5: 12, 6: 10, 7: 14}.get(low, 8)
        extra = 0
        if low & 0x02:
            if offset + 2 > len(payload):
                break
            offset += 1  # flags del plotter
            hp = read_varint(payload, offset)
            if not hp:
                break
            offset += hp[1]
            offset += 1  # byte dell'angolo
            extra = hp[1] - 1

        offset += temp + extra
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

        if second < 0 or second > 99_999_999:
            break

        hits.append(
            {
                "t": stamp,
                "actor": actor,
                "target": target,
                "skill": skill,
                "damage": second,
                "scalar": first,
                "crit": hit_type == 3,
                "switch": switch,
            }
        )
        parsed_any = True
    return hits


def scan_from(data: bytes, start: int) -> tuple[int, int, list[dict]]:
    """Cammina il flusso da `start`; ritorna (frame, frame di danno, colpi)."""
    frames = 0
    damage_frames = 0
    hits: list[dict] = []
    for payload in walk_frames(data[start:]):
        frames += 1
        if payload[:2] == b"\x04\x38":
            damage_frames += 1
            hits.extend(parse_damage_payload(payload, 0.0))
    return frames, damage_frames, hits


def analyse(path: pathlib.Path) -> list[dict]:
    """Analizza i flussi server->client, riallineandosi se il flusso parte a metà
    pacchetto (una cattura comincia sempre dove capita)."""
    hits: list[dict] = []
    for flow in sorted(path.glob("flow_*servertoclient.bin")):
        data = flow.read_bytes()
        frames, damage_frames, flow_hits = scan_from(data, 0)
        start_used = 0
        if frames < 20 and len(data) > 64:
            best = (frames, damage_frames, flow_hits)
            for start in range(1, min(512, len(data) - 16)):
                candidate = scan_from(data, start)
                if candidate[0] > best[0]:
                    best = candidate
                    start_used = start
            frames, damage_frames, flow_hits = best
        if start_used:
            print(f"{flow.name}: riallineato a +{start_used} byte")
        print(
            f"{flow.name}: {len(data):,} B -> {frames} frame, {damage_frames} di danno, "
            f"{len(flow_hits)} colpi"
        )
        hits.extend(flow_hits)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", default="sniff_combat")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()

    hits = analyse(pathlib.Path(args.folder))
    if not hits:
        print("\nNessun colpo: la cattura non contiene record di danno parsabili.")
        return 0

    by_actor: dict[int, dict] = collections.defaultdict(lambda: {"dmg": 0, "hits": 0, "crits": 0, "skills": collections.Counter()})
    for hit in hits:
        entry = by_actor[hit["actor"]]
        entry["dmg"] += hit["damage"]
        entry["hits"] += 1
        entry["crits"] += 1 if hit["crit"] else 0
        entry["skills"][hit["skill"]] += hit["damage"]

    total = sum(h["damage"] for h in hits)
    print(f"\nColpi: {len(hits):,} | danno totale: {total:,} | attori: {len(by_actor)}")
    print("\nTop attori per danno:")
    for actor, entry in sorted(by_actor.items(), key=lambda kv: -kv[1]["dmg"])[: args.top]:
        top_skill = entry["skills"].most_common(1)[0] if entry["skills"] else (0, 0)
        print(
            f"  actor {actor:>10}: {entry['dmg']:>9,} dmg in {entry['hits']:>4} colpi"
            f" ({entry['crits']} crit) | skill {top_skill[0]}: {top_skill[1]:,}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
