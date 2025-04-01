#!/usr/bin/env python3
"""
plot_data_extended.py

This program reads CSV files (one per beacon) from the Data/ folder.
It loads the beacon mapping from a JSON file (MacsToNames.json),
then for each beacon it creates:
  - For Humidity:
      • A scatter plot of all humidity data.
      • A scatter plot of humidity data for the last 48 hours.
      • A box plot (with dark blue and grey styling) of humidity for the last 48 hours,
        with an annotation of the median value.
  - For Temperature:
      • A scatter plot of all temperature data.
      • A scatter plot of temperature data for the last 48 hours.
      • A box plot (with dark blue and grey styling) of temperature for the last 48 hours,
        with an annotation of the median value.
All individual plots are saved into two separate PDFs:
  • "Plots/Humidity.pdf" and "Plots/Temperature.pdf"
Additionally, composite grid pages (one for each metric) are generated showing the “all data”
scatter plots for all beacons, and a summary CSV ("Plots/summary.csv") is generated.
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
# Create a date formatter for the x-axis: day-month hour:minute
date_formatter = mdates.DateFormatter("%d-%m %H:%M")

def plot_scatter(df, y_column, title, color):
    """Generates a scatter plot for the given y-column."""
    plt.figure(figsize=(12, 8))
    plt.scatter(df["timestamp"], df[y_column], c=color, alpha=0.7, edgecolors="w", s=50)
    plt.title(title)
    plt.xlabel("Timestamp")
    plt.ylabel(y_column.capitalize())
    ax = plt.gca()
    ax.xaxis.set_major_formatter(date_formatter)
    plt.xticks(rotation=45)
    plt.tight_layout()

def plot_box(df, y_column, title, facecolor, median_color):
    """Generates a horizontal box plot for the given y-column with median annotation."""
    plt.figure(figsize=(12, 8))
    bp = plt.boxplot(df[y_column].dropna(), vert=False, patch_artist=True,
                     boxprops=dict(facecolor=facecolor, color="black"),
                     medianprops=dict(color=median_color, linewidth=2))
    plt.title(title)
    plt.xlabel(y_column.capitalize())
    plt.tight_layout()
    med_val = df[y_column].dropna().median()
    plt.annotate(f"Median: {med_val:.2f}", xy=(med_val, 1), xytext=(med_val, 1.1),
                 arrowprops=dict(facecolor=median_color, shrink=0.05),
                 horizontalalignment='center')

def create_composite(scatter_data, y_column, composite_title, point_color):
    """
    Creates a composite grid figure of scatter plots (all data) for a given y_column.
    scatter_data is a list of tuples: (friendly_name, dataframe).
    Returns the figure.
    """
    n = len(scatter_data)
    if n == 0:
        return None
    ncols = 2
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows), squeeze=False)
    fig.suptitle(composite_title, fontsize=14)
    for idx, (name, df) in enumerate(scatter_data):
        row = idx // ncols
        col = idx % ncols
        ax = axes[row][col]
        ax.scatter(df["timestamp"], df[y_column], c=point_color, alpha=0.7, edgecolors="w", s=40)
        ax.set_title(name)
        ax.set_xlabel("Timestamp")
        ax.set_ylabel(y_column.capitalize())
        ax.xaxis.set_major_formatter(date_formatter)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
    for idx in range(n, nrows * ncols):
        row = idx // ncols
        col = idx % ncols
        axes[row][col].axis("off")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig

def main():
    summary_rows = []
    composite_humidity = []   # list of tuples: (name, df)
    composite_temperature = []  # list of tuples: (name, df)

    with PdfPages(OUTPUT_PDF_HUM) as pdf_hum, PdfPages(OUTPUT_PDF_TEMP) as pdf_temp:
        # Process each device based on mapping
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

            # -------------------------
            # Humidity plots (added to Humidity.pdf)
            plot_scatter(df, "relhum", f"{name} - Humidity (All Data)", "blue")
            pdf_hum.savefig(); plt.close()
            plot_scatter(df_recent, "relhum", f"{name} - Humidity (Last 48 Hours)", "green")
            pdf_hum.savefig(); plt.close()
            plot_box(df_recent, "relhum", f"{name} - Humidity Box Plot (Last 48 Hours)",
                     facecolor="darkblue", median_color="grey")
            pdf_hum.savefig(); plt.close()

            # -------------------------
            # Temperature plots (added to Temperature.pdf)
            plot_scatter(df, "temp", f"{name} - Temperature (All Data)", "red")
            pdf_temp.savefig(); plt.close()
            plot_scatter(df_recent, "temp", f"{name} - Temperature (Last 48 Hours)", "orange")
            pdf_temp.savefig(); plt.close()
            plot_box(df_recent, "temp", f"{name} - Temperature Box Plot (Last 48 Hours)",
                     facecolor="darkblue", median_color="grey")
            pdf_temp.savefig(); plt.close()

            # Append full-data for composite figures
            composite_humidity.append((name, df))
            composite_temperature.append((name, df))

            # Compute summary statistics for all data (for both metrics)
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
            print(f"Plots and summary for {name} generated.")

        # Create composite grid plots and add them to the respective PDFs.
        if composite_humidity:
            fig_hum = create_composite(composite_humidity, "relhum", 
                                       "Composite Scatter Plots for Humidity (All Data)", "blue")
            if fig_hum:
                pdf_hum.savefig(fig_hum)
                plt.close(fig_hum)
        if composite_temperature:
            fig_temp = create_composite(composite_temperature, "temp", 
                                        "Composite Scatter Plots for Temperature (All Data)", "red")
            if fig_temp:
                pdf_temp.savefig(fig_temp)
                plt.close(fig_temp)

    # Write the summary CSV
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(SUMMARY_CSV, index=False)
        print(f"Summary CSV saved to {SUMMARY_CSV}")
    print(f"Humidity plots saved to {OUTPUT_PDF_HUM}")
    print(f"Temperature plots saved to {OUTPUT_PDF_TEMP}")

if __name__ == "__main__":
    main()
