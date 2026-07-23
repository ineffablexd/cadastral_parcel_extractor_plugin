# 🚀 Cadastral Parcel Extractor

<p align="center">
  <a href="https://github.com/ineffablexd/demo-qgis-plugin"><img src="https://img.shields.io/badge/version-1.0.0-blue.svg" alt="Version"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0--or--later-green.svg" alt="License"/></a>
  <a href="https://qgis.org"><img src="https://img.shields.io/badge/QGIS-3.0+-orange.svg" alt="QGIS Compatibility"/></a>
  <img src="https://img.shields.io/badge/Suite-Ineffable_Tools-purple.svg" alt="Suite Branding"/>
</p>

---

## 📖 Description

**Cadastral Parcel Extractor** is a high-precision QGIS plugin developed for transmission line corridor analysis, safety buffer calculation, and land acquisition workflows. It dynamically calculates corridor buffer zones based on grid voltage presets, reprojects layers to UTM coordinate systems, extracts touching land parcels, and exports formatted KMZ files with floating centroid parcel labels and CSV land scheduling reports.

---

## 🖼️ Visual Workflow

<p align="center">
  <img src="assets/before_running.png" width="48%" alt="Before Running Tool"/>
  <img src="assets/after_running.png" width="48%" alt="After Running Tool"/>
</p>
<p align="center">
  <i>Fig 1: Automated extraction of affected cadastral parcels and progressive streaming overlay.</i>
</p>

---

## ✨ Key Features

- ⚡ **Multi-Corridor Batch Queue:** Process multiple transmission line corridors simultaneously with progressive line-by-line streaming.
- 🌍 **Automatic UTM Detection:** Computes the optimal UTM zone projection automatically for precise metric buffer calculations.
- ⚡ **Voltage Corridor Presets:** Includes standard presets for 132kV, 220kV, 400kV, 765kV, and 1200kV power transmission lines with automatic layer name detection.
- 🌐 **Google Earth KMZ Export:** Exports outline-only KMZ files featuring floating centroid parcel labels (`PIN`) that open natively in Google Earth Pro.
- 📊 **Land Scheduling CSV Export:** Generates clean attribute CSV reports for clipped cadastral parcels.
- 🛠️ **Seamless Integration:** Fully integrated into the **Ineffable Tools** suite with a dedicated menu and toolbar action.

---

## 🛠️ Installation

### Via QGIS Plugin Manager

1. Open **QGIS**.
2. Navigate to `Plugins` > `Manage and Install Plugins...`.
3. Search for **Cadastral Parcel Extractor**.
4. Click **Install Plugin**. (Note: Ensure the Ineffable repository is added to your plugin providers).

### Manual Installation (GitHub)

1. Clone the repository or download the ZIP from GitHub.
2. Extract the plugin folder into your QGIS plugins directory:
    - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
    - **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
    - **MacOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS and enable the plugin from the Plugin Manager.

---

## 🚀 How to Use

1. **Launch Plugin:** Locate the **Ineffable Tools** menu in the top menu bar or click the plugin icon on the toolbar.
2. **Select Cadastral Layer & Label Field:** Choose your target cadastral polygon layer and select the label attribute field (e.g. `PIN`).
3. **Queue Transmission Lines:** Add transmission line vector layers to the table queue; voltage presets and buffer widths will auto-fill based on layer names.
4. **Process & Extract:** Click **Process & Extract Parcels** to run the analysis. Outputs are streamed progressively into QGIS and exported to disk.
5. **View Results:** Open exported `.kmz` files in Google Earth Pro to inspect floating centroid labels and open `.csv` files for land scheduling.

---

## 👤 Author & License

- **Author:** Vicky Sharma
- **Email:** [vsharma@powergrid.in](mailto:vsharma@powergrid.in)
- **GitHub:** [@ineffablexd](https://github.com/ineffablexd)
- **License:** Distributed under the **GPL-2.0-or-later** license. See [LICENSE](LICENSE) for more details.

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/ineffablexd">Ineffable</a>
</p>
