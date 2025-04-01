#!/usr/bin/env python3
"""
plot_data.py

This program reads CSV files (one per beacon) from the Data/ folder.
It uses a hardcoded mapping from MAC addresses to friendly names and creates for each:
  1. A scatter plot of all humidity data.
  2. A scatter plot of humidity data for the last 48 hours.
  3. A box plot of the last 48 hours of humidity data.
All plots are compiled into a single PDF file ("all_plots.pdf").
"""

import os
import json
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import timedelta

# Load mapping from JSON file.
MAPPING_FILE = "MacsToNames.json"
try:
    with open(MAPPING_FILE, "r") as f:
        mapping_data = json.load(f)
    # Create a dictionary mapping MAC (lowercase) to friendly name.
    MAC_MAPPING = {entry["address"].lower(): entry["name"] for entry in mapping_data}
except Exception as e:
    print(f"Error loading mapping file {MAPPING_FILE}: {e}")
    MAC_MAPPING = {}


# Directory where CSV files are stored (e.g., "Data/Daddy Bear.csv", etc.)
DATA_DIR = "Data"

# Output PDF file for plots
OUTPUT_PDF = "Plots/all_plots.pdf"

# Create a PDFPages object so we can save multiple plots into one PDF
with PdfPages(OUTPUT_PDF) as pdf:
    # Process each MAC/friendly name from the mapping
    for mac, name in MAC_MAPPING.items():
        csv_file = os.path.join(DATA_DIR, f"{name}.csv")
        if not os.path.isfile(csv_file):
            print(f"CSV file for {name} not found at {csv_file}. Skipping.")
            continue

        # Read CSV into a DataFrame; parse 'timestamp' column as datetime
        try:
            df = pd.read_csv(csv_file, parse_dates=["timestamp"])
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")
            continue

        if df.empty:
            print(f"No data in {csv_file}. Skipping.")
            continue

        # Sort the DataFrame by timestamp for consistency
        df.sort_values("timestamp", inplace=True)

        # -------------------------
        # 1. Scatter plot for all humidity data
        plt.figure(figsize=(12, 8))
        plt.scatter(df["timestamp"], df["relhum"], c="blue", alpha=0.6, edgecolors="w", s=50)
        plt.title(f"{name} - Humidity (All Data)")
        plt.xlabel("Timestamp")
        plt.ylabel("Relative Humidity (%)")
        plt.xticks(rotation=45)
        plt.tight_layout()
        pdf.savefig()  # Save current figure to PDF
        plt.close()

        # -------------------------
        # 2. Scatter plot for the last 48 hours
        # Use the maximum timestamp in the file as reference
        max_time = df["timestamp"].max()
        cutoff = max_time - timedelta(hours=48)
        df_recent = df[df["timestamp"] >= cutoff]

        plt.figure(figsize=(12, 8))
        plt.scatter(df_recent["timestamp"], df_recent["relhum"], c="green", alpha=0.6, edgecolors="w", s=50)
        plt.title(f"{name} - Humidity (Last 48 Hours)")
        plt.xlabel("Timestamp")
        plt.ylabel("Relative Humidity (%)")
        plt.xticks(rotation=45)
        plt.tight_layout()
        pdf.savefig()
        plt.close()

        # -------------------------
        # 3. Box plot for humidity values in the last 48 hours
        plt.figure(figsize=(12, 8))
        plt.boxplot(df_recent["relhum"].dropna(), vert=False, patch_artist=True,
                    boxprops=dict(facecolor="cyan", color="blue"),
                    medianprops=dict(color="red"))
        plt.title(f"{name} - Humidity Box Plot (Last 48 Hours)")
        plt.xlabel("Relative Humidity (%)")
        plt.tight_layout()
        pdf.savefig()
        plt.close()

print(f"All plots saved to {OUTPUT_PDF}")
