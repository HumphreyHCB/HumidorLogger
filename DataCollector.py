#!/usr/bin/env python3
# see https://github.com/jdstmporter/ThermoBeacon2
"""
DataCollector.py

This program collects readings from ThermoBeacon devices.
With the new "autocsv" command, it automatically scans for 30 seconds every 21 minutes,
computes a median reading from the scan window for each beacon (based on a mapping file),
and appends the data as a new row into a CSV file stored in the Data/ folder.
"""

import sys, re, json, asyncio, csv, os, datetime, time
from argparse import ArgumentParser, Namespace
import bleak
import paho.mqtt.client as mqtt
from bleak import BleakClient, BleakScanner
from tb_protocol import *
import pandas as pd

# BLE characteristic UUIDs
TX_CHAR_UUID = '0000fff5-0000-1000-8000-00805F9B34FB'
RX_CHAR_UUID = '0000fff3-0000-1000-8000-00805F9B34FB'

def mac_addr(x):
    x = x.lower()
    if not re.match(r"^(?:[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", x):
        raise ValueError()
    return x

# Set up command-line parsing.
parser = ArgumentParser()
subparsers = parser.add_subparsers(help='action', dest='command', required=True)

# (Existing commands)
sub = subparsers.add_parser('scan', help="Scan for ThermoBeacon devices")
sub.add_argument('-mac', type=mac_addr, required=False)
sub.add_argument('-t', type=int, default=20, metavar='<Scan duration, seconds>', required=False)

sub = subparsers.add_parser('identify', help="Identify a device")
sub.add_argument('-mac', type=mac_addr, required=True)

sub = subparsers.add_parser('dump', help="Dump logged data")
sub.add_argument('-mac', type=mac_addr, required=True)

sub = subparsers.add_parser('query', help="Query device for details")
sub.add_argument('-mac', type=mac_addr, required=True)
sub.add_argument('-t', type=int, default=3, metavar='<Query duration, seconds>', required=False)

sub = subparsers.add_parser('mqtt', help="Send data via mqtt")
sub.add_argument('-mac', type=mac_addr, required=True)
sub.add_argument('-t', type=int, default=3, metavar='<Query duration, seconds>', required=False)
sub.add_argument('-broker', required=True)
sub.add_argument('-port', type=int, required=True)
sub.add_argument('-topic', required=True)

# New subcommand: autocsv
sub = subparsers.add_parser('autocsv', help="Automatically scan for 25 seconds every 25 minutes and update CSV files for all beacons")
sub.add_argument('-m', '--mapping', type=str, default="MacsToNames.json", help="Path to the MacsToNames.json mapping file")
sub.add_argument('--scan-duration', type=int, default=30, help="Scan duration in seconds (default: 30)")
sub.add_argument('--cycle-interval', type=int, default=1260, help="Cycle interval in seconds (default: 1260 = 21 minutes)")

args = parser.parse_args()

# --- New code for automatic scanning and CSV update ---

async def perform_scan(scan_duration, monitored_macs):
    """
    Performs a BLE scan for the given duration and collects advertisement data
    from ThermoBeacon devices whose MAC addresses are in monitored_macs.
    Returns a dictionary mapping MAC -> list of reading dictionaries.
    """
    results = {}  # Key: mac, Value: list of readings

    def detection_callback(device, advertisement_data):
        if advertisement_data.local_name != 'ThermoBeacon':
            return
        mac = device.address.lower()
        if mac not in monitored_macs:
            return
        # Process manufacturer data messages.
        for key, bvalue in advertisement_data.manufacturer_data.items():
            if len(bvalue) == 18:  # Matches TBAdvData format
                try:
                    data = TBAdvData(key, bvalue)
                except Exception:
                    continue
                reading = {
                    "temp": data.tmp,
                    "relhum": data.hum,
                    "button": 1 if data.btn else 0,  # store as 1/0 for later median/majority
                    "battery": data.btr,
                    "uptime": data.upt
                }
                results.setdefault(mac, []).append(reading)

    scanner = BleakScanner(detection_callback)
    await scanner.start()
    await asyncio.sleep(scan_duration)
    await scanner.stop()
    return results

def median(lst):
    """Return the median of a list of numbers."""
    n = len(lst)
    if n == 0:
        return None
    sorted_lst = sorted(lst)
    mid = n // 2
    if n % 2 == 1:
        return sorted_lst[mid]
    else:
        return (sorted_lst[mid - 1] + sorted_lst[mid]) / 2

def majority_button(lst):
    """For a list of 0/1 values, return True if the majority are 1, else False."""
    if not lst:
        return None
    return sum(lst) >= (len(lst) / 2)

async def autocsv_loop(mapping_file, scan_duration, cycle_interval):
    """
    Main loop for the autocsv command.
    Every cycle, scan for scan_duration seconds, process collected readings from each monitored beacon,
    compute the median (or majority for button), and append a new row to the corresponding CSV file.
    """
    # Load mapping file.
    try:
        with open(mapping_file, 'r') as f:
            mappings = json.load(f)
    except Exception as e:
        print(f"Error reading mapping file {mapping_file}: {e}")
        return

    # Build mapping: mac (lowercase) -> friendly name, and a set of monitored MACs.
    mac_to_name = {}
    monitored_macs = set()
    for entry in mappings:
        mac = entry.get("address", "").lower()
        if mac:
            monitored_macs.add(mac)
            mac_to_name[mac] = entry.get("name", mac)

    # Ensure the Data folder exists.
    data_folder = "Data"
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)

    print("Starting automatic CSV updates. Press Ctrl+C to stop.")
    while True:
        cycle_start = time.time()
        print(f"\nStarting scan cycle at {datetime.datetime.now().isoformat()}")
        scan_results = await perform_scan(scan_duration, monitored_macs)
        now = datetime.datetime.now().isoformat()

        # Process readings for each monitored beacon.
        for mac in monitored_macs:
            if mac in scan_results and len(scan_results[mac]) > 0:
                readings = scan_results[mac]
                median_temp = median([r["temp"] for r in readings])
                median_relhum = median([r["relhum"] for r in readings])
                median_battery = median([r["battery"] for r in readings])
                median_uptime = median([r["uptime"] for r in readings])
                median_button = majority_button([r["button"] for r in readings])
                row = {
                    "timestamp": now,
                    "mac": mac,
                    "temp": median_temp,
                    "relhum": median_relhum,
                    "button": median_button,
                    "battery": median_battery,
                    "uptime": median_uptime
                }
                friendly_name = mac_to_name.get(mac, mac)
                csv_filename = os.path.join(data_folder, f"{friendly_name}.csv")
                write_header = not os.path.isfile(csv_filename)
                try:
                    with open(csv_filename, 'a', newline='') as csvfile:
                        writer = csv.DictWriter(
                            csvfile,
                            fieldnames=["timestamp", "mac", "temp", "relhum", "button", "battery", "uptime"]
                        )
                        if write_header:
                            writer.writeheader()
                        writer.writerow(row)

                    prune_csv_to_last_months(csv_filename, months=6)
                    print(f"Updated CSV for {friendly_name} with new row at {now}")
                except Exception as e:
                    print(f"Error writing to {csv_filename}: {e}")
            else:
                print(f"No readings found for {mac} in this cycle.")

        cycle_end = time.time()
        elapsed = cycle_end - cycle_start
        sleep_time = cycle_interval - elapsed
        if sleep_time > 0:
            print(f"Cycle complete. Sleeping for {sleep_time:.0f} seconds until next scan.")
            await asyncio.sleep(sleep_time)
        else:
            print("Cycle took longer than the interval; starting next cycle immediately.")

# --- Placeholder implementations for existing commands ---
async def scan():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    await asyncio.sleep(20)
    await scanner.stop()

def detection_callback(device, advertisement_data):
    name = advertisement_data.local_name
    if name is None or name != 'ThermoBeacon':
        return
    for key, bvalue in advertisement_data.manufacturer_data.items():
        if len(bvalue) == 18:
            data = TBAdvData(key, bvalue)
            print(f"[{device.address}] Temp: {data.tmp}°C, Hum: {data.hum}%, Battery: {data.btr}%, Uptime: {data.upt}")
        else:
            data = TBAdvMinMax(key, bvalue)
            print(f"[{device.address}] Max: {data.max}°C, Min: {data.min}°C")

def identify(address):
    print(f"Identify {address}")

def dump(address):
    print(f"Dump {address}")

def query(address, duration):
    # In your actual code, this function returns a dict with keys: mac, temp, relhum, button, battery, uptime
    # Here we return a dummy value.
    return {"mac": address, "temp": 22.0, "relhum": 40.0, "button": False, "battery": 90.0, "uptime": 10000}

def send_mqtt(address, duration, broker, port, topic):
    print(f"MQTT {address}")

def prune_csv_to_last_months(csv_filename, months=6):
    """Keep only rows from the last `months` months."""
    try:
        if not os.path.isfile(csv_filename):
            return

        df = pd.read_csv(csv_filename, parse_dates=["timestamp"])
        if df.empty:
            return

        cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
        df = df[df["timestamp"] >= cutoff]

        df.to_csv(csv_filename, index=False)
    except Exception as e:
        print(f"Error pruning {csv_filename}: {e}")

# --- Main function ---

def main():
    cmd = args.command
    if cmd == 'scan':
        loop = asyncio.get_event_loop()
        loop.run_until_complete(scan())
    elif cmd == 'identify':
        identify(args.mac)
    elif cmd == 'dump':
        dump(args.mac)
    elif cmd == 'query':
        result = query(args.mac, args.t)
        print(result)
    elif cmd == 'mqtt':
        send_mqtt(args.mac, args.t, args.broker, args.port, args.topic)
    elif cmd == 'autocsv':
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(autocsv_loop(args.mapping, args.scan_duration, args.cycle_interval))
        except KeyboardInterrupt:
            print("Autocsv loop terminated by user.")
    else:
        print("Command not implemented.")

if __name__ == '__main__':
    main()
