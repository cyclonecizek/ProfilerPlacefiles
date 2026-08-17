# KSC 915 MHz Wind Profiler GRLevelX Placefile

Live GRLevelX placefile for the five NASA KSC / Cape Canaveral 915 MHz Doppler Radar Wind Profilers.

## What it displays

One marker is plotted at each profiler location:

- RWP0001 — South Cape
- RWP0002 — False Cape
- RWP0003 — Merritt Island
- RWP0004 — Mosquito Lagoon
- RWP0005 — Ti-Co / Space Coast Regional Airport

Hover a marker to see the newest vertical wind profile. Archive heights are converted from km to feet and wind speed is converted from m/s to knots. Missing wind levels are omitted.

## Files

- `src/ksc_915mhz_profiler_placefile.py` — KSC downloader/parser/placefile generator
- `docs/ksc_915mhz_profiler_sites.csv` — profiler coordinates
- `docs/profiler_915_icon.png` — GR marker icon
- `docs/ksc_915mhz_profilers.txt` — generated live placefile
- `docs/ksc_915mhz_profilers.json` — generation diagnostics
- `.github/workflows/update-profiler.yml` — scheduled updater
- `.github/workflows/pages.yml` — GitHub Pages deployment

## Setup

1. Create a public GitHub repository, for example `KSC_915MHz_Profiler_Placefile`.
2. Upload this package preserving the folder structure.
3. In **Settings → Actions → General**, enable GitHub Actions and permit workflow write access if required.
4. In **Settings → Pages**, set **Source** to **GitHub Actions**.
5. Run **Update KSC 915 MHz Profiler Placefile** manually once.
6. After the Pages deployment succeeds, use:

   `https://YOUR-USER.github.io/YOUR-REPO/ksc_915mhz_profilers.txt`

   in the GR Placefile Manager.

The profiler updater polls every five minutes. KSC states the 915 MHz profiler network generates horizontal/vertical profile estimates every 15 minutes, so repeated runs normally publish only when a new profile appears.

## Optional override

Normally the script automatically generates the rolling KSC export URL. For troubleshooting, repository secret `KSC_PROFILER_RESULT_URL` can override the generated URL.

## Data caution

The KSC archive states that its stored data are provided as-is and are not quality controlled. The placefile is for visualization and should not be treated as an official launch-weather decision product.
