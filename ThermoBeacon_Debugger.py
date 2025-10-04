#!/usr/bin/env python3
"""
ThermoBeacon_Debugger.py — one-file, no-args, just-run helper

What it does (single run):
  • Loads MacsToNames.json (same shape you already use: [{"address": "aa:bb:...", "name": "Kitchen"}, ...])
  • Scans BLE advertisements for ThermoBeacon beacons for SCAN_SECONDS (default 60s)
  • Decodes readings from manufacturer data (temp, humidity, battery, uptime, button)
  • For each mapped device: computes medians during the scan window, prints a summary table,
    and appends a new row to Data/<Name>.csv in the columns you already use
      [timestamp, mac, temp, relhum, button, battery, uptime]
  • Also lists any ThermoBeacon devices seen that are NOT in your mapping (to help fix mappings)

Usage:
  • Ensure your Bluetooth adapter is on.
  • Put this file next to MacsToNames.json, then run:  python3 ThermoBeacon_Debugger.py
  • On Linux, if you get a permissions error, either run with sudo OR grant capabilities:
        sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))

Notes:
  • No command-line options. Edit the CONFIG section below if you want to tweak timings.
  • This script is advertisement-based (no GATT connection). That’s the most reliable for these beacons.
  • If a device is quiet for the entire window, you’ll see “NOT SEEN” and no CSV row will be added for it.
"""

from __future__ import annotations
import asyncio
import csv
import datetime as dt
import json
import subprocess
import time
import os
import sys
import textwrap
import traceback
from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Tuple

# --- Try bleak import early with a helpful message ---
try:
    from bleak import BleakScanner
    from bleak.exc import BleakDBusError
except Exception as e:
    print("\nERROR: The 'bleak' package is required. Install it with:\n  pip install bleak\n")
    raise

# =====================
# CONFIG (edit if needed)
# =====================
SCAN_SECONDS = 60  # how long to scan in one shot
MAPPING_FILE = "MacsToNames.json"
DATA_DIR = "Data"
DEBUG_PRINT_FIRST_N = 20  # print the first N advertisements (for debugging)

# =====================
# Helpers: MAC + pretty print
# =====================

def norm_mac(s: str) -> str:
    """Normalize MAC string to lowercase with colons."""
    s = s.strip().lower()
    # Accept forms with or without separators; reinsert colons if missing
    hex_chars = [c for c in s if c in "0123456789abcdef"]
    if len(hex_chars) == 12:
        return ":".join(["".join(hex_chars[i:i+2]) for i in range(0, 12, 2)])
    # else assume it's already colon/hyphen separated
    s = s.replace("-", ":")
    return s


def ensure_data_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


# =====================
# Decoders (from your tb_protocol.py, kept consistent)
# =====================

def tb_decode_temperature(b: bytes) -> float:
    result = int.from_bytes(b, byteorder='little') / 16.0
    if result > 4000:
        result -= 4096
    return result


def tb_decode_humidity(b: bytes) -> float:
    result = int.from_bytes(b, byteorder='little') / 16.0
    if result > 4000:
        result -= 4096
    return result

# MAC helpers for embedded addresses in manufacturer data
def mac_bytes_to_str_le(b: bytes) -> str:
    """MAC string as-is from payload (little-endian order as broadcast in TB frames)."""
    return ":".join(f"{x:02x}" for x in b)

def mac_bytes_to_str_be(b: bytes) -> str:
    """MAC string reversed to conventional big-endian display order."""
    return ":".join(f"{x:02x}" for x in b[::-1])


MSG_ADVERTISE_DATA = 1
MSG_ADVERTISE_MINMAX = 2


class TBAdvertisingMessage:
    def __init__(self, msg_type, id, bvalue: bytes):
        self.id = id
        self.msg_type = msg_type
        # Button bit as per your working code
        self.btn = False if bvalue[1] == 0 else True
        # Device MAC encoded little-endian; not used for addressing here because we prefer OS address
        self.mac = int.from_bytes(bvalue[2:8], byteorder='little')


class TBAdvData(TBAdvertisingMessage):
    def __init__(self, id, bvalue: bytes):
        super().__init__(MSG_ADVERTISE_DATA, id, bvalue)
        self.btr = int.from_bytes(bvalue[8:10], byteorder='little')
        self.btr = self.btr * 100 / 3400.0
        self.tmp = tb_decode_temperature(bvalue[10:12])
        self.hum = tb_decode_humidity(bvalue[12:14])
        self.upt = int.from_bytes(bvalue[14:18], byteorder='little')


class TBAdvMinMax(TBAdvertisingMessage):
    def __init__(self, id, bvalue: bytes):
        super().__init__(MSG_ADVERTISE_MINMAX, id, bvalue)
        self.max = tb_decode_temperature(bvalue[8:10])
        self.max_t = int.from_bytes(bvalue[10:14], byteorder='little')
        self.min = tb_decode_temperature(bvalue[14:16])
        self.min_t = int.from_bytes(bvalue[16:20], byteorder='little')


# =====================
# Data structures
# =====================

@dataclass
class Reading:
    ts: dt.datetime
    temp: float
    relhum: float
    battery: float
    uptime: int
    button: int  # 1/0


# =====================
# Mapping loader
# =====================

def load_mapping(path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (mac->name, name->mac) from mapping file. Ignores entries without address/name."""
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: Could not read mapping file '{path}': {e}\n\n"
              f"Create it like: [{{\"address\": \"aa:bb:cc:dd:ee:ff\", \"name\": \"Kitchen\"}}, ...]")
        sys.exit(1)

    mac2name: Dict[str, str] = {}
    name2mac: Dict[str, str] = {}
    for entry in data:
        mac = norm_mac(str(entry.get("address", "")).strip())
        name = str(entry.get("name", "")).strip()
        if mac and name:
            mac2name[mac] = name
            name2mac[name] = mac
    if not mac2name:
        print("ERROR: Mapping file contains no usable entries.")
        sys.exit(1)
    return mac2name, name2mac


# =====================
# Scanning logic
# =====================

def _btctl_show() -> str:
    try:
        out = subprocess.run(["bluetoothctl", "show"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
        return out.stdout
    except Exception:
        return ""


def _btctl_scan_off():
    try:
        # Turn off any external discovery session that might block ours
        subprocess.run(["bluetoothctl", "--timeout", "1", "scan", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except Exception:
        pass


async def scan_window(seconds: int, mac2name: Dict[str, str]) -> Tuple[Dict[str, List[Reading]], Dict[str, List[Reading]]]:
    """
    Scan for `seconds` and collect advertisement readings.
    Returns (seen_for_mapped, seen_unmapped) as MAC->list[Reading].
    Keys in `seen_for_mapped` are the EXACT MAC strings from your mapping (either OS MAC, embedded-LE, or embedded-BE).
    Unmapped keys are the OS MACs.
    """
    seen: Dict[str, List[Reading]] = {}
    seen_unmapped: Dict[str, List[Reading]] = {}

    interested = set(mac2name.keys())
    debug_count = 0

    def cb(device, advertisement_data):
        nonlocal debug_count
        try:
            mac_os = norm_mac(device.address)
            t_now = dt.datetime.now()

            # Debug sniff: print the first few adverts we see
            if debug_count < DEBUG_PRINT_FIRST_N:
                md = advertisement_data.manufacturer_data or {}
                lens = [len(v) for v in md.values()]
                print(f"DBG adv #{debug_count+1}: os_mac={mac_os} name={advertisement_data.local_name} md_lens={lens}")
                debug_count += 1

            # If there's no manufacturer data, nothing to decode
            if not advertisement_data.manufacturer_data:
                return

            for key, bvalue in advertisement_data.manufacturer_data.items():
                blen = len(bvalue)
                if blen == 18:
                    # Primary TB data frame
                    try:
                        d = TBAdvData(key, bvalue)
                    except Exception:
                        continue

                    # Derive embedded MAC strings from payload bytes [2:8]
                    raw_mac = bytes(bvalue[2:8])
                    embedded_le = norm_mac(mac_bytes_to_str_le(raw_mac))
                    embedded_be = norm_mac(mac_bytes_to_str_be(raw_mac))

                    # Choose the mapping key to attribute this reading to
                    if mac_os in interested:
                        map_key = mac_os
                    elif embedded_le in interested:
                        map_key = embedded_le
                    elif embedded_be in interested:
                        map_key = embedded_be
                    else:
                        map_key = None

                    r = Reading(ts=t_now, temp=d.tmp, relhum=d.hum, battery=float(d.btr), uptime=int(d.upt), button=1 if d.btn else 0)

                    if map_key is None:
                        seen_unmapped.setdefault(mac_os, []).append(r)
                    else:
                        seen.setdefault(map_key, []).append(r)

                elif blen == 22:
                    # Min/Max TB frame — useful for debugging but we don't record as a point
                    try:
                        _ = TBAdvMinMax(key, bvalue)
                    except Exception:
                        continue
                    continue
                else:
                    # Unknown frame length — ignore
                    continue
        except Exception:
            traceback.print_exc()

    # Try to ensure no other discovery session is active (helps avoid BlueZ InProgress quirks)
    show = _btctl_show()
    if "Discovering: yes" in show:
        print("Note: External discovery was active. Requesting 'scan off' via bluetoothctl…")
        _btctl_scan_off()
        time.sleep(0.5)

    # Build scanner with best-effort active mode
    try:
        scanner = BleakScanner(cb, scanning_mode="active")
    except TypeError:
        scanner = BleakScanner(cb)

    # Ask BlueZ to send duplicates and only LE traffic (best-effort; ignore if unsupported)
    try:
        if hasattr(scanner, "set_scanning_filter"):
            try:
                scanner.set_scanning_filter(duplicate=True)
            except Exception:
                scanner.set_scanning_filter(**{"DuplicateData": True, "Transport": "le"})
    except Exception:
        pass
    try:
        # BlueZ can raise org.bluez.Error.InProgress if discovery already started elsewhere.
        try:
            await scanner.start()
        except BleakDBusError as e:
            if "InProgress" in str(e):
                pass
            else:
                raise
        await asyncio.sleep(seconds)
    finally:
        # On stop, BlueZ may again report InProgress while transitioning. Ignore safely.
        try:
            await scanner.stop()
        except BleakDBusError as e:
            if "InProgress" in str(e):
                pass
            else:
                raise

    return seen, seen_unmapped


# =====================
# CSV writing + summary
# =====================

def write_csv_row(csv_path: str, mac: str, rlist: List[Reading]) -> Tuple[dict, bool]:
    """Write a median row to csv_path. Returns (row_dict, wrote_bool)."""
    if not rlist:
        return {}, False
    temps = [r.temp for r in rlist]
    hums = [r.relhum for r in rlist]
    bats = [r.battery for r in rlist]
    upts = [r.uptime for r in rlist]
    btns = [r.button for r in rlist]

    row = {
        "timestamp": dt.datetime.now().isoformat(timespec='seconds'),
        "mac": mac,
        "temp": float(median(temps)),
        "relhum": float(median(hums)),
        "button": 1 if sum(btns) >= (len(btns) / 2) else 0,
        "battery": float(median(bats)),
        "uptime": int(median(upts)),
    }

    write_header = not os.path.isfile(csv_path)
    with open(csv_path, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "mac", "temp", "relhum", "button", "battery", "uptime"])
        if write_header:
            w.writeheader()
        w.writerow(row)
    return row, True


def print_table(mapped_rows: List[Tuple[str, str, List[Reading]]], unmapped_rows: List[Tuple[str, List[Reading]]]):
    def fmt(v, width):
        return str(v).ljust(width)

    print("\n=== ThermoBeacon Debug Summary ===")
    if mapped_rows:
        print("\n-- Mapped devices --")
        header = f"{fmt('Name', 18)}  {fmt('MAC', 17)}  {fmt('#Seen', 5)}  {fmt('Temp(°C)', 9)}  {fmt('Hum(%)', 7)}  {fmt('Batt(%)', 8)}  {fmt('Uptime(s)', 10)}"
        print(header)
        print("-" * len(header))
        for name, mac, rlist in mapped_rows:
            if rlist:
                temps = [r.temp for r in rlist]
                hums = [r.relhum for r in rlist]
                bats = [r.battery for r in rlist]
                upts = [r.uptime for r in rlist]
                print(f"{fmt(name,18)}  {fmt(mac,17)}  {fmt(len(rlist),5)}  {fmt(f'{median(temps):.2f}',9)}  {fmt(f'{median(hums):.1f}',7)}  {fmt(f'{median(bats):.0f}',8)}  {fmt(int(median(upts)),10)}")
            else:
                print(f"{fmt(name,18)}  {fmt(mac,17)}  {fmt('0',5)}  {'NOT SEEN in window':<40}")
    else:
        print("(No mapped devices loaded)")

    if unmapped_rows:
        print("\n-- Unmapped ThermoBeacon devices seen (not in your MacsToNames.json) --")
        header = f"{fmt('MAC', 17)}  {fmt('#Seen', 5)}  {fmt('Temp(°C)', 9)}  {fmt('Hum(%)', 7)}  {fmt('Batt(%)', 8)}  {fmt('Uptime(s)', 10)}"
        print(header)
        print("-" * len(header))
        for mac, rlist in unmapped_rows:
            temps = [r.temp for r in rlist]
            hums = [r.relhum for r in rlist]
            bats = [r.battery for r in rlist]
            upts = [r.uptime for r in rlist]
            print(f"{fmt(mac,17)}  {fmt(len(rlist),5)}  {fmt(f'{median(temps):.2f}',9)}  {fmt(f'{median(hums):.1f}',7)}  {fmt(f'{median(bats):.0f}',8)}  {fmt(int(median(upts)),10)}")


# =====================
# Main
# =====================

def main():
    print("ThermoBeacon Debugger — single scan run")
    # Helpful version prints
    try:
        import bleak
        print(f"bleak version: {getattr(bleak, '__version__', 'unknown')}")
    except Exception:
        pass
    try:
        out = _btctl_show()
        if out:
            for line in out.splitlines():
                if line.strip().startswith("Controller ") or line.strip().startswith("Discovering:") or line.strip().startswith("Powered:"):
                    print(line)
    except Exception:
        pass
    print(f"Mapping file: {MAPPING_FILE}")
    mac2name, name2mac = load_mapping(MAPPING_FILE)
    ensure_data_dir(DATA_DIR)

    interested_macs = sorted(mac2name.keys())
    print(f"Loaded {len(interested_macs)} mapped devices.")
    for m in interested_macs:
        print(f"  - {mac2name[m]} -> {m}")

    print(f"\nScanning for {SCAN_SECONDS} seconds… (Ctrl+C to abort)\n")

    try:
        seen, seen_unmapped = asyncio.run(scan_window(SCAN_SECONDS, mac2name))
    except PermissionError as e:
        print("\nPermissionError starting BLE scan. On Linux, try either:\n  • sudo python3 ThermoBeacon_Debugger.py\n  • or grant capabilities: sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))\n")
        raise

    # Build rows for table
    mapped_rows: List[Tuple[str, str, List[Reading]]] = []
    for mac in interested_macs:
        rlist = seen.get(mac, [])
        mapped_rows.append((mac2name[mac], mac, rlist))

    unmapped_rows: List[Tuple[str, List[Reading]]] = sorted(seen_unmapped.items(), key=lambda x: x[0])

    # Print summary table
    print_table(mapped_rows, unmapped_rows)

    # Write CSV rows for mapped devices that we actually saw
    any_written = False
    for name, mac, rlist in mapped_rows:
        if not rlist:
            continue
        csv_path = os.path.join(DATA_DIR, f"{name}.csv")
        row, wrote = write_csv_row(csv_path, mac, rlist)
        if wrote:
            any_written = True
            print(f"Wrote CSV -> {csv_path} : {row}")

    if not any_written:
        print("\nNo mapped devices produced readings in this window; no CSV rows were added.")
        print("Hints: ensure sensors are advertising, you are within range, and your adapter is enabled.")

    print("\nDone.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
    except Exception:
        print("\nUnexpected error:\n" + traceback.format_exc())
        sys.exit(1)
