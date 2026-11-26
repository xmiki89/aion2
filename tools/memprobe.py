"""Sonda read-only della memoria di Aion 2.

Scopo: capire se il client (protetto da NCGuard) consente la lettura della
memoria e se le stringhe che ci interessano (classi, etichette UI) sono
rintracciabili. Nessuna scrittura, nessun bypass dell'anti-cheat.

Uso:
    python tools/memprobe.py                 # solo accesso + elenco moduli
    python tools/memprobe.py --find Sorcerer --find Assassin
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import re
import sys
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
CHUNK = 16 * 1024 * 1024
OVERLAP = 64


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
    ]


def find_process() -> int | None:
    import psutil

    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "").lower()
        if name.startswith("aion2") and name.endswith(".exe") and "meter" not in name:
            return proc.info["pid"]
    return None


def process_name(pid: int) -> str:
    import psutil

    try:
        return psutil.Process(pid).name()
    except Exception:
        return "?"


def open_process(pid: int) -> int:
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        hint = {
            5: "accesso negato (anti-cheat o permessi)",
            87: "PID inesistente",
        }.get(err, "errore Windows")
        raise OSError(err, f"OpenProcess fallito: {hint} (WinError {err})")
    return handle


def modules(pid: int) -> list[tuple[str, int, int]]:
    import psutil

    found = []
    try:
        for entry in psutil.Process(pid).memory_maps(grouped=True):
            path = entry.path or ""
            if not path or "\\" not in path:
                continue
            base = int(getattr(entry, "addr", 0)) if hasattr(entry, "addr") else 0
            size = int(entry.rss or 0)
            found.append((path.rsplit("\\", 1)[-1], base, size))
    except Exception as exc:  # pragma: no cover - diagnostica
        print("  (elenco moduli non disponibile:", exc, ")")
    return found


def regions(handle: int):
    address = 0
    mbi = MEMORY_BASIC_INFORMATION64()
    size = ctypes.sizeof(mbi)
    while True:
        written = kernel32.VirtualQueryEx(
            wt.HANDLE(handle), ctypes.c_void_p(address), ctypes.byref(mbi), size
        )
        if not written:
            break
        end = address + mbi.RegionSize
        if (
            mbi.State == MEM_COMMIT
            and mbi.Protect not in (PAGE_NOACCESS, 0)
            and not (mbi.Protect & PAGE_GUARD)
        ):
            yield address, mbi.RegionSize
        if end <= address:
            break
        address = end


def scan(handle: int, targets: list[str], budget: int) -> dict[str, list[int]]:
    needles: dict[bytes, str] = {}
    for target in targets:
        needles[target.encode("utf-16-le")] = f"{target} (utf16)"
        needles[target.encode("ascii")] = f"{target} (ascii)"
    hits: dict[str, list[int]] = {label: [] for label in needles.values()}
    buffer = ctypes.create_string_buffer(CHUNK)
    read = ctypes.c_size_t(0)
    scanned = 0
    started = time.time()
    for base, size in regions(handle):
        if scanned >= budget or time.time() - started > 120:
            break
        offset = 0
        while offset < size:
            length = min(CHUNK, size - offset)
            if not kernel32.ReadProcessMemory(
                wt.HANDLE(handle),
                ctypes.c_void_p(base + offset),
                buffer,
                ctypes.c_size_t(length),
                ctypes.byref(read),
            ):
                offset += length
                continue
            data = buffer.raw[: read.value]
            scanned += len(data)
            for needle, label in needles.items():
                position = data.find(needle)
                while position != -1 and len(hits[label]) < 8:
                    hits[label].append(base + offset + position)
                    position = data.find(needle, position + 1)
            offset += max(length - OVERLAP, 1)
            if scanned >= budget:
                break
    return {label: addrs for label, addrs in hits.items() if addrs}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--find", action="append", default=[])
    parser.add_argument("--budget", type=int, default=2 * 1024**3)
    parser.add_argument("--pid", type=int, default=0, help="processo da sondare (default: AION2.exe)")
    args = parser.parse_args()

    pid = args.pid or find_process()
    if not pid:
        print("Aion 2 non è in esecuzione: avvia il gioco e riprova.")
        return 2
    print(f"{process_name(pid)} PID {pid}")

    try:
        handle = open_process(pid)
    except OSError as exc:
        print(f"ESITO: accesso NEGATO -> {exc}")
        print("L'anti-cheat impedisce la lettura: questa strada non è percorribile senza aggirarlo.")
        return 1

    print("ESITO: OpenProcess con PROCESS_VM_READ riuscito.")
    mods = [m for m in modules(pid) if re.search(r"\.(exe|dll)$", m[0], re.I)]
    print(f"Moduli leggibili: {len(mods)} (primi 8)")
    for name, base, size in mods[:8]:
        print(f"  {name:<34} base=0x{base:012x} rss={size:,}")

    if args.find:
        print(f"\nScansione di {args.budget // (1024**2)} MB per: {', '.join(args.find)}")
        found = scan(handle, args.find, args.budget)
        if not found:
            print("  nessuna occorrenza trovata.")
        for label, addrs in found.items():
            print(f"  {label}: {', '.join(f'0x{a:012x}' for a in addrs[:5])}")

    kernel32.CloseHandle(wt.HANDLE(handle))
    return 0


if __name__ == "__main__":
    sys.exit(main())
