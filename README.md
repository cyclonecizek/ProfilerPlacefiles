# KSC 915 MHz Profiler Placefiles

GRLevelX markers with vertical wind profiles for the five configured profilers.

## Live API and archive fallback

The preferred source is `https://codiapi-915drwp.rad.spaceforce.mil`.
For each configured station, `/915drwp/latest?drwp_identifier=...&limit=1`
discovers the latest consensus time, and `/915drwp/range?date=...&drwp_identifier=...`
retrieves the complete profile at that time. This avoids mixing stations or
truncating a profile with a fixed row limit. Missing `9999` wind values and
invalid directions are omitted from the displayed wind table. Calm winds remain valid.

On October 16, 2026, all five API stations returned August 5, 2026 as their
latest profile time, while the archive had October 16 profiles. The API is
therefore checked for freshness before use. If any configured station is
unavailable, older than `STALE_MINUTES`, more than 15 minutes in the future,
or has no valid winds, the entire network is fetched from the existing archive
path. The API will be used automatically once all configured stations are current.
Diagnostic JSON records the actual source and API fallback reason. Source labels
in the placefile and hover text reflect the source actually used.

The existing archive token generation and optional `KSC_PROFILER_RESULT_URL`
secret remain for fallback. The archive token is verified only for 2026.
API requests validate TLS; the pre-existing archive-only TLS workaround remains.
If both sources fail, or no current markers can be generated, outputs are not published.

## Presentation

Existing markers, profile tables, and placefile URL are retained:

https://cyclonecizek.github.io/ProfilerPlacefiles/ksc_915mhz_profilers.txt

Speeds are converted from m/s to knots, and altitude gates from km to feet.
The configured CSV coordinates and station elevations are retained. The API
raw-file longitude uses a positive west value; it is not applied as a signed
longitude. Profile time is `consensus_datetime` interpreted as UTC, rather than
request time. Current profiles are selected separately for each station.

## Running

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
python src/ksc_915mhz_profiler_placefile.py
```

`--input` accepts API JSON or legacy archive CSV. `--print-url` still shows
the archive fallback URL. `PROFILER_API_BASE_URL` overrides the API host.
`LOOKBACK_MINUTES` defaults to 120 for archive fallback; `STALE_MINUTES`
defaults to 180 for both sources. `PROFILER_ICON_URL` overrides the marker URL.

GitHub requests updates every five minutes; source profiles have a nominal
15-minute cadence. Source/workflow changes on main also trigger an update.
GR refreshes the published placefile every 60 seconds. Pages deploys after a
successful updater run.
