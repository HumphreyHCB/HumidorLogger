# Humidor Logger

Humidor Logger is a simple repository that collects humidity and temperature data from multiple sensors, then automatically generates and publishes plots **every hour** using GitHub Actions.

## Overview

- **Automatic Updates**: A scheduled workflow runs hourly, pulling the latest sensor data (stored as CSV files) and generating new plots.
- **Plotted Metrics**: Each release contains updated humidity and temperature PDF files, as well as a summary CSV.
- **Easy Access to Plots**: You can always download the freshest PDF plots and CSV summary from our [latest release](https://github.com/HumphreyHCB/HumidorLogger/releases/latest).

## How It Works

1. **Data Collection**  
   The script collects humidity and temperature readings from various beacons/devices.  
2. **Data Storage**  
   CSV files (one per device) are stored in the `Data/` folder, with timestamps for each reading.  
3. **Plot Generation**  
   Every hour (or on manual push), a GitHub Actions workflow runs `plot_data_extended.py`:
   - Generates individual and composite PDF plots (Humidity & Temperature).
   - Produces a `summary.csv` with min, max, and median statistics.
4. **Release Publishing**  
   The workflow creates a new [GitHub Release](https://github.com/HumphreyHCB/HumidorLogger/releases/latest) containing:
   - `Humidity.pdf`
   - `Temperature.pdf`
   - `summary.csv`

## Repository Contents

- **Data/**  
  Contains CSV files with raw sensor readings.
- **Plots/**  
  Locally generated PDFs and summary CSV (these are also uploaded as release assets).
- **MacsToNames.json**  
  Maps beacon MAC addresses to friendly device names.
- **plot_data_extended.py**  
  Main Python script for processing CSV data and creating plots.

## Getting the Latest Plots

Simply visit our [Latest Release](https://github.com/HumphreyHCB/HumidorLogger/releases/latest) page to download the updated humidity and temperature PDF files.

## License

This project is [MIT Licensed](LICENSE) – feel free to use and adapt it!

---

Feel free to customize or expand sections (such as adding instructions to run the script locally, describing your hardware setup, or outlining contributing guidelines).