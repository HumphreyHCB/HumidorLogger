#!/usr/bin/env python3
"""
plot_data_extended.py

1) Summary CSV is generated first
2) 'seaborn-v0_8' style for a nicer look
3) Box plots (last 48 hrs) with median label offset
4) Scatter plots have a minimum figure size but remain dynamic
5) For humidity plots: dotted lines at y=60 and y=70,
   always at least y=[55..80], expanding further if needed.
6) Composite plots appear FIRST in each PDF, then individual plots.
"""

import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
from datetime import timedelta

# -----------------------------
# 1) GLOBAL SETTINGS & SETUP
# -----------------------------
plt.style.use('seaborn-v0_8')
plt.rcParams.update({'font.size': 11})

date_formatter = mdates.DateFormatter("%d-%m %H:%M")

MAPPING_FILE = "MacsToNames.json"
DATA_DIR = "Data"
OUTPUT_DIR = "Plots"
OUTPUT_PDF_HUM = os.path.join(OUTPUT_DIR, "Humidity.pdf")
OUTPUT_PDF_TEMP = os.path.join(OUTPUT_DIR, "Temperature.pdf")
SUMMARY_CSV = os.path.join(OUTPUT_DIR, "summary.csv")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Load MAC->Name mapping
try:
    with open(MAPPING_FILE, "r") as f:
        mapping_data = json.load(f)
    MAC_MAPPING = {entry["address"].lower(): entry["name"] for entry in mapping_data}
except Exception as e:
    print(f"Error loading mapping file {MAPPING_FILE}: {e}")
    MAC_MAPPING = {}

def get_axis_label(y_column: str) -> str:
    if y_column == "relhum":
        return "Humidity"
    elif y_column == "temp":
        return "Temperature"
    else:
        return y_column


# -------------------------------------------------------------
# 2) HELPER FUNCTIONS FOR PLOTTING
# -------------------------------------------------------------
def add_humidity_lines_and_limits(ax):
    ax.axhline(60, color='gray', linestyle='--', alpha=0.8)
    ax.axhline(70, color='gray', linestyle='--', alpha=0.8)
    current_min, current_max = ax.get_ylim()
    base_min, base_max = 55, 80
    new_min = min(current_min, base_min)
    new_max = max(current_max, base_max)
    ax.set_ylim(new_min, new_max)

def plot_scatter(df, y_column, title, color):
    plt.figure(figsize=(10, 6))
    plt.scatter(df["timestamp"], df[y_column], c=color, alpha=0.7, edgecolors="w", s=50)
    plt.plot(df["timestamp"], df[y_column], c=color, alpha=0.5)
    plt.title(title)
    plt.xlabel("Timestamp")
    plt.ylabel(get_axis_label(y_column))
    ax = plt.gca()
    ax.xaxis.set_major_formatter(date_formatter)
    plt.xticks(rotation=45)
    if y_column == "relhum":
        add_humidity_lines_and_limits(ax)
    plt.tight_layout()

def plot_box(df, y_column, title, facecolor, median_color):
    plt.figure(figsize=(10, 6))
    plt.boxplot(df[y_column].dropna(), vert=False, patch_artist=True,
                boxprops=dict(facecolor=facecolor, color="black"),
                medianprops=dict(color=median_color, linewidth=2))
    plt.title(title)
    plt.xlabel(get_axis_label(y_column))
    ax = plt.gca()
    if not df[y_column].dropna().empty:
        med_val = df[y_column].median()
        ax.text(med_val, 1.12, f"Median: {med_val:.2f}",
                horizontalalignment='center', color=median_color)
    plt.tight_layout()

def create_composite_by_mac(devices_data, y_column, composite_title, color_all, color_recent):
    N = len(devices_data)
    if N == 0:
        return None

    fig, axes = plt.subplots(3, N, figsize=(4 * N, 12), squeeze=False)
    fig.suptitle(composite_title, fontsize=16)

    for j, (name, df) in enumerate(devices_data):
        df.sort_values("timestamp", inplace=True)
        max_time = df["timestamp"].max()
        cutoff = max_time - timedelta(hours=48)
        df_recent = df[df["timestamp"] >= cutoff]

        # Row 0: ALL data scatter
        ax = axes[0][j]
        ax.scatter(df["timestamp"], df[y_column], c=color_all, alpha=0.7, edgecolors="w", s=40)
        ax.plot(df["timestamp"], df[y_column], c=color_all, alpha=0.5)
        ax.set_title(name)
        ax.set_xlabel("Timestamp")
        ax.set_ylabel(get_axis_label(y_column))
        ax.xaxis.set_major_formatter(date_formatter)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
        if y_column == "relhum":
            add_humidity_lines_and_limits(ax)

        # Row 1: LAST 48 hours scatter
        ax = axes[1][j]
        ax.scatter(df_recent["timestamp"], df_recent[y_column], c=color_recent, alpha=0.7, edgecolors="w", s=40)
        ax.plot(df_recent["timestamp"], df_recent[y_column], c=color_recent, alpha=0.5)
        ax.set_title(name)
        ax.set_xlabel("Timestamp")
        ax.set_ylabel(get_axis_label(y_column))
        ax.xaxis.set_major_formatter(date_formatter)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
        if y_column == "relhum":
            add_humidity_lines_and_limits(ax)

        # Row 2: BOX plot of last 48 hours
        ax = axes[2][j]
        ax.boxplot(df_recent[y_column].dropna(), vert=False, patch_artist=True,
                   boxprops=dict(facecolor="darkblue", color="black"),
                   medianprops=dict(color="grey", linewidth=2))
        ax.set_xlabel(get_axis_label(y_column))
        if not df_recent[y_column].dropna().empty:
            med_val = df_recent[y_column].median()
            ax.text(med_val, 1.12, f"Median: {med_val:.2f}",
                    horizontalalignment='center', color="grey")
        if y_column == "relhum":
            add_humidity_lines_and_limits(ax)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


# -------------------------------------------------------------
# 3) MAIN LOGIC
#    - Read all CSVs
#    - Generate summary
#    - Then produce composite plots FIRST,
#      then individual plots for each device.
# -------------------------------------------------------------
def main():
    # 1) Collect data
    all_data = []
    for mac, name in MAC_MAPPING.items():
        csv_file = os.path.join(DATA_DIR, f"{name}.csv")
        if not os.path.isfile(csv_file):
            print(f"CSV file for {name} not found at {csv_file}. Skipping.")
            continue
        try:
            df = pd.read_csv(csv_file, parse_dates=["timestamp"])
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")
            continue
        if df.empty:
            print(f"No data in {csv_file}. Skipping.")
            continue

        df.sort_values("timestamp", inplace=True)
        all_data.append((mac, name, df))

    # 2) Generate summary CSV
    summary_rows = []
    for mac, name, df in all_data:
        hum_median = df["relhum"].median()
        hum_min = df["relhum"].min()
        hum_max = df["relhum"].max()
        temp_median = df["temp"].median()
        temp_min = df["temp"].min()
        temp_max = df["temp"].max()

        summary_rows.append({
            "mac": mac,
            "name": name,
            "humidity_median": hum_median,
            "humidity_min": hum_min,
            "humidity_max": hum_max,
            "temperature_median": temp_median,
            "temperature_min": temp_min,
            "temperature_max": temp_max
        })

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(SUMMARY_CSV, index=False)
        print(f"Summary CSV saved to {SUMMARY_CSV}")

    # 3) Prepare composite lists (for the entire dataset)
    #    (We'll do them all at once before we do individual plots.)
    composite_humidity = []
    composite_temperature = []
    for mac, name, df in all_data:
        composite_humidity.append((name, df))
        composite_temperature.append((name, df))

    # 4) Create PDFs & Write Composite PLOTS FIRST
    with PdfPages(OUTPUT_PDF_HUM) as pdf_hum, PdfPages(OUTPUT_PDF_TEMP) as pdf_temp:

        # --- A) Composite Humidity (first in Humidity.pdf) ---
        if composite_humidity:
            fig_hum_comp = create_composite_by_mac(
                composite_humidity,
                "relhum",
                "Composite Plots by MAC for Humidity",
                "blue",
                "green"
            )
            if fig_hum_comp:
                pdf_hum.savefig(fig_hum_comp)
                plt.close(fig_hum_comp)

        # --- B) Composite Temperature (first in Temperature.pdf) ---
        if composite_temperature:
            fig_temp_comp = create_composite_by_mac(
                composite_temperature,
                "temp",
                "Composite Plots by MAC for Temperature",
                "red",
                "orange"
            )
            if fig_temp_comp:
                pdf_temp.savefig(fig_temp_comp)
                plt.close(fig_temp_comp)

        # --- C) Then do Individual Plots for each device ---
        for mac, name, df in all_data:
            print(f"Generating individual plots for {name}...")

            max_time = df["timestamp"].max()
            cutoff = max_time - timedelta(hours=48)
            df_recent = df[df["timestamp"] >= cutoff]

            # HUMIDITY PDF
            plot_scatter(df, "relhum", f"{name} - Humidity (All Data)", "blue")
            pdf_hum.savefig()
            plt.close()

            plot_scatter(df_recent, "relhum", f"{name} - Humidity (Last 48 Hours)", "green")
            pdf_hum.savefig()
            plt.close()

            plot_box(df_recent, "relhum", f"{name} - Humidity Box Plot (Last 48 Hours)", "darkblue", "grey")
            pdf_hum.savefig()
            plt.close()

            # TEMPERATURE PDF
            plot_scatter(df, "temp", f"{name} - Temperature (All Data)", "red")
            pdf_temp.savefig()
            plt.close()

            plot_scatter(df_recent, "temp", f"{name} - Temperature (Last 48 Hours)", "orange")
            pdf_temp.savefig()
            plt.close()

            plot_box(df_recent, "temp", f"{name} - Temperature Box Plot (Last 48 Hours)", "darkblue", "grey")
            pdf_temp.savefig()
            plt.close()

            print(f"Individual plots for {name} generated.")

    print(f"Humidity plots saved to {OUTPUT_PDF_HUM}")
    print(f"Temperature plots saved to {OUTPUT_PDF_TEMP}")


if __name__ == "__main__":
    main()
