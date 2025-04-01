#!/usr/bin/env python3
"""
plot_data_extended.py

This program reads CSV files (one per beacon) from the Data/ folder.
It loads the beacon mapping from a JSON file (MacsToNames.json),
then for each beacon it creates individual plots:
  - For Humidity:
      • A scatter plot (with connecting line) of all humidity data.
      • A scatter plot (with connecting line) of humidity data for the last 48 hours.
      • A box plot (with dark blue and grey styling) of humidity for the last 48 hours,
        with a median label (no arrow).
  - For Temperature:
      • A scatter plot (with connecting line) of all temperature data.
      • A scatter plot (with connecting line) of temperature data for the last 48 hours.
      • A box plot (with dark blue and grey styling) of temperature for the last 48 hours,
        with a median label (no arrow).
All individual plots are saved into two separate PDFs:
  • "Plots/Humidity.pdf" and "Plots/Temperature.pdf"
Additionally, composite grid pages are generated for each metric – a 3×N grid
(with each column corresponding to a MAC address and rows corresponding to:
  row 0: all data scatter,
  row 1: last 48 hours scatter,
  row 2: box plot)
Finally, a summary CSV ("Plots/summary.csv") is generated.
"""

import os
import json
import math
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.dates as mdates
from datetime import timedelta

# Load mapping from JSON file
MAPPING_FILE = "MacsToNames.json"
try:
    with open(MAPPING_FILE, "r") as f:
        mapping_data = json.load(f)
    MAC_MAPPING = {entry["address"].lower(): entry["name"] for entry in mapping_data}
except Exception as e:
    print(f"Error loading mapping file {MAPPING_FILE}: {e}")
    MAC_MAPPING = {}

DATA_DIR = "Data"
# Ensure output directory exists
OUTPUT_DIR = "Plots"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
OUTPUT_PDF_HUM = os.path.join(OUTPUT_DIR, "Humidity.pdf")
OUTPUT_PDF_TEMP = os.path.join(OUTPUT_DIR, "Temperature.pdf")
SUMMARY_CSV = os.path.join(OUTPUT_DIR, "summary.csv")

# Set global font size to 11
plt.rcParams.update({'font.size': 11})
# Date formatter for the x-axis: day-month hour:minute
date_formatter = mdates.DateFormatter("%d-%m %H:%M")

def plot_scatter(df, y_column, title, color):
    """Generates a scatter plot with a connecting line for the given y_column."""
    plt.figure(figsize=(12, 8))
    plt.scatter(df["timestamp"], df[y_column], c=color, alpha=0.7, edgecolors="w", s=50)
    plt.plot(df["timestamp"], df[y_column], c=color, alpha=0.5)
    plt.title(title)
    plt.xlabel("Timestamp")
    plt.ylabel(y_column.capitalize())
    ax = plt.gca()
    ax.xaxis.set_major_formatter(date_formatter)
    plt.xticks(rotation=45)
    plt.tight_layout()

def plot_box(df, y_column, title, facecolor, median_color):
    """Generates a horizontal box plot for the given y_column with median label (no arrow)."""
    plt.figure(figsize=(12, 8))
    bp = plt.boxplot(df[y_column].dropna(), vert=False, patch_artist=True,
                     boxprops=dict(facecolor=facecolor, color="black"),
                     medianprops=dict(color=median_color, linewidth=2))
    plt.title(title)
    plt.xlabel(y_column.capitalize())
    plt.tight_layout()
    med_val = df[y_column].dropna().median()
    plt.text(med_val, 1.05, f"Median: {med_val:.2f}", horizontalalignment='center', color=median_color)

def create_composite_by_mac(devices_data, y_column, composite_title, color_all, color_recent):
    """
    Creates a composite grid figure for a given y_column.
    The grid has 3 rows and N columns (N = number of devices):
      Row 0: Scatter plot (all data with connecting line)
      Row 1: Scatter plot (last 48 hours with connecting line)
      Row 2: Box plot (last 48 hours with median label)
    """
    N = len(devices_data)
    if N == 0:
        return None
    nrows = 3
    ncols = N
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 12), squeeze=False)
    fig.suptitle(composite_title, fontsize=16)
    for j, (name, df) in enumerate(devices_data):
        df.sort_values("timestamp", inplace=True)
        max_time = df["timestamp"].max()
        cutoff = max_time - timedelta(hours=48)
        df_recent = df[df["timestamp"] >= cutoff]
        
        # Row 0: Scatter plot (all data) with connecting line
        ax = axes[0][j]
        ax.scatter(df["timestamp"], df[y_column], c=color_all, alpha=0.7, edgecolors="w", s=40)
        ax.plot(df["timestamp"], df[y_column], c=color_all, alpha=0.5)
        ax.set_title(name)
        ax.set_xlabel("Timestamp")
        ax.set_ylabel(y_column.capitalize())
        ax.xaxis.set_major_formatter(date_formatter)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
        
        # Row 1: Scatter plot (last 48 hours) with connecting line
        ax = axes[1][j]
        ax.scatter(df_recent["timestamp"], df_recent[y_column], c=color_recent, alpha=0.7, edgecolors="w", s=40)
        ax.plot(df_recent["timestamp"], df_recent[y_column], c=color_recent, alpha=0.5)
        ax.set_title(name)
        ax.set_xlabel("Timestamp")
        ax.set_ylabel(y_column.capitalize())
        ax.xaxis.set_major_formatter(date_formatter)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
        
        # Row 2: Box plot (last 48 hours) with median label (no arrow)
        ax = axes[2][j]
        bp = ax.boxplot(df_recent[y_column].dropna(), vert=False, patch_artist=True,
                        boxprops=dict(facecolor="darkblue", color="black"),
                        medianprops=dict(color="grey", linewidth=2))
        ax.set_xlabel(y_column.capitalize())
        med_val = df_recent[y_column].dropna().median()
        ax.text(med_val, 1.05, f"Median: {med_val:.2f}", horizontalalignment='center', color="grey")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig

def main():
    summary_rows = []
    composite_humidity = []   # list of tuples: (name, df)
    composite_temperature = []  # list of tuples: (name, df)

    with PdfPages(OUTPUT_PDF_HUM) as pdf_hum, PdfPages(OUTPUT_PDF_TEMP) as pdf_temp:
        # Process each device from mapping
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
            max_time = df["timestamp"].max()
            cutoff = max_time - timedelta(hours=48)
            df_recent = df[df["timestamp"] >= cutoff]

            # Individual Humidity plots (added to Humidity.pdf)
            plot_scatter(df, "relhum", f"{name} - Humidity (All Data)", "blue")
            pdf_hum.savefig(); plt.close()
            plot_scatter(df_recent, "relhum", f"{name} - Humidity (Last 48 Hours)", "green")
            pdf_hum.savefig(); plt.close()
            plot_box(df_recent, "relhum", f"{name} - Humidity Box Plot (Last 48 Hours)", "darkblue", "grey")
            pdf_hum.savefig(); plt.close()

            # Individual Temperature plots (added to Temperature.pdf)
            plot_scatter(df, "temp", f"{name} - Temperature (All Data)", "red")
            pdf_temp.savefig(); plt.close()
            plot_scatter(df_recent, "temp", f"{name} - Temperature (Last 48 Hours)", "orange")
            pdf_temp.savefig(); plt.close()
            plot_box(df_recent, "temp", f"{name} - Temperature Box Plot (Last 48 Hours)", "darkblue", "grey")
            pdf_temp.savefig(); plt.close()

            composite_humidity.append((name, df))
            composite_temperature.append((name, df))

            # Compute summary statistics (all data)
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
            print(f"Individual plots and summary for {name} generated.")

        # Create composite grids (3 rows x N columns) and add them to the PDFs.
        if composite_humidity:
            fig_hum_comp = create_composite_by_mac(composite_humidity, "relhum",
                                                   "Composite Plots by MAC for Humidity", "blue", "green")
            if fig_hum_comp:
                pdf_hum.savefig(fig_hum_comp)
                plt.close(fig_hum_comp)
        if composite_temperature:
            fig_temp_comp = create_composite_by_mac(composite_temperature, "temp",
                                                    "Composite Plots by MAC for Temperature", "red", "orange")
            if fig_temp_comp:
                pdf_temp.savefig(fig_temp_comp)
                plt.close(fig_temp_comp)

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(SUMMARY_CSV, index=False)
        print(f"Summary CSV saved to {SUMMARY_CSV}")
    print(f"Humidity plots saved to {OUTPUT_PDF_HUM}")
    print(f"Temperature plots saved to {OUTPUT_PDF_TEMP}")

if __name__ == "__main__":
    main()
