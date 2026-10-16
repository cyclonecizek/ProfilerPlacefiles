#!/usr/bin/env python3
"""
NASA KSC Spaceport Weather Archive 915 MHz Doppler Radar Wind Profiler
-> GRLevelX placefile.

Archive CSV columns used:
    Date, Time, SiteName, Height, Speed, Direction

The five profilers report horizontal wind profiles nominally every 15 minutes.
Height is supplied by the archive in km and is displayed here in feet.
Speed is converted from m/s to knots.

The KSC search token structure below was verified against the supplied search:
  2026-08-16 18:45Z -> 2026-08-16 19:45Z
  BaIQStkBaIQTtkAAAABaAAa6bCa7bBbD
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

USER_AGENT = "KSC-915MHz-Profiler-GRLevelX/1.0"
BASE60 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz01234567"
TOKEN_PREFIX = "Ba"
TOKEN_BETWEEN = "Ba"
TOKEN_AFTER_END = "AAAABaAAa6bCa7bBbD"
YEAR_BASE = 1990

LOOKBACK_MINUTES = int(os.getenv("LOOKBACK_MINUTES", "120"))
STALE_MINUTES = int(os.getenv("STALE_MINUTES", "180"))
MPS_TO_KT = 1.9438444924406
KM_TO_FT = 3280.8398950131


@dataclass
class Row:
    dt: datetime
    site: str
    height_km: float
    speed_mps: float | None
    direction_deg: float | None


def fnum(value):
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def enc60(n: int) -> str:
    if not 0 <= n < len(BASE60):
        raise ValueError(f"KSC token value out of range: {n}")
    return BASE60[n]


def encode_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    year_code = dt.year - YEAR_BASE
    if not 0 <= year_code < len(BASE60):
        raise ValueError(f"Year {dt.year} is outside the verified KSC token range")
    return (
        enc60(dt.month)
        + enc60(dt.day)
        + enc60(dt.hour)
        + enc60(dt.minute)
        + enc60(year_code)
    )


def build_token(start: datetime, end: datetime) -> str:
    if end <= start:
        raise ValueError("end must be later than start")
    # Token layout was directly verified for 2026 from a controlled KSC search.
    if start.year != 2026 or end.year != 2026:
        raise ValueError("Automatic 915 MHz profiler token generation is currently verified only for 2026")
    return TOKEN_PREFIX + encode_dt(start) + TOKEN_BETWEEN + encode_dt(end) + TOKEN_AFTER_END


def build_export_url(start: datetime, end: datetime) -> str:
    return "https://kscweather.ksc.nasa.gov/wxarchive/WindProfiler915/Export/" + build_token(start, end)


def fetch_export() -> str:
    override = os.getenv("KSC_PROFILER_RESULT_URL", "").strip()
    if override:
        url = override
    else:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(minutes=LOOKBACK_MINUTES)
        url = build_export_url(start, end)

    print("KSC 915 MHz export URL:", url)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,text/plain,application/octet-stream,*/*",
    }
    retry_delays = [0, 10, 20, 40, 60]
    last_error = None

    for attempt, delay in enumerate(retry_delays, start=1):
        if delay:
            print(f"Retrying KSC profiler request in {delay} seconds...")
            time.sleep(delay)

        try:
            try:
                r = requests.get(url, timeout=60, headers=headers)
            except requests.exceptions.SSLError:
                if urlparse(url).hostname != "kscweather.ksc.nasa.gov":
                    raise
                print(
                    "WARNING: KSC TLS certificate chain could not be validated; "
                    "retrying this exact NASA host with certificate verification disabled."
                )
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.get(url, timeout=60, headers=headers, verify=False)

            r.raise_for_status()
            if attempt > 1:
                print(f"KSC profiler request succeeded on attempt {attempt}.")
            return r.text

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
        ) as exc:
            last_error = exc
            print(
                f"KSC profiler attempt {attempt}/{len(retry_delays)} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            if isinstance(exc, requests.exceptions.HTTPError):
                response = getattr(exc, "response", None)
                status = response.status_code if response is not None else None
                if status is not None and 400 <= status < 500 and status != 429:
                    raise

    raise RuntimeError(
        "KSC 915 MHz profiler request failed after all retries. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    )


API_BASE = os.getenv("PROFILER_API_BASE_URL", "https://codiapi-915drwp.rad.spaceforce.mil").rstrip("/")


def api_get(path, params):
    for attempt in range(3):
        try:
            response = requests.get(API_BASE + path, params=params, timeout=30,
                                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Profiler API returned no readings or an invalid response")
            return data
        except requests.exceptions.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or (status is not None and status < 500 and status != 429):
                raise
            time.sleep(2 ** attempt)


def parse_api(data):
    if not isinstance(data, list):
        raise ValueError("Profiler API response must be a JSON array")
    rows = []
    for item in data:
        dt = datetime.fromisoformat(item["consensus_datetime"].replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        height = fnum(item.get("altitude_km"))
        site = str(item["drwp_identifier"]).strip().upper()
        if height is None or not 0 <= height < 9999 or not site.startswith("RWP"):
            continue
        speed = fnum(item.get("wind_speed_mps"))
        direction = fnum(item.get("wind_direction_deg"))
        if speed is not None and (speed < 0 or speed >= 9999):
            speed = None
        if direction is not None and not 0 <= direction <= 360:
            direction = None
        rows.append(Row(dt, site, height, speed, direction))
    if not rows:
        raise ValueError("No valid profiler API rows parsed")
    return rows


def fetch_api_profiles(sites, now):
    def fetch_site(site):
        # /latest limits rows, so limit=60 can mix two profile times.
        # Discover the newest time, then retrieve every gate at that exact time.
        latest = parse_api(api_get("/915drwp/latest", {"drwp_identifier": site, "limit": 1}))
        dt = max(r.dt for r in latest)
        age = (now - dt).total_seconds() / 60
        if age > STALE_MINUTES or age < -15:
            raise ValueError(f"{site}: API profile {dt.isoformat()} is not current (age {age:.0f} min)")
        rows = parse_api(api_get("/915drwp/range", {
            "drwp_identifier": site, "date": dt.strftime("%Y-%m-%dT%H:%M:%S")}))
        if any(r.site != site or r.dt != dt for r in rows):
            raise ValueError(f"{site}: API returned a different station or profile time")
        if not any(r.speed_mps is not None and r.direction_deg is not None for r in rows):
            raise ValueError(f"{site}: API profile has no valid winds")
        return rows
    with ThreadPoolExecutor(max_workers=min(5, len(sites))) as pool:
        return [row for profile in pool.map(fetch_site, sites) for row in profile]


def fetch_rows(sites, now):
    try:
        return fetch_api_profiles(sites, now), "Live 915 MHz DRWP API", None
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
        reason = str(exc)
        print(f"Profiler API unavailable or not current: {reason}; using KSC archive fallback.")
        return parse_csv(fetch_export()), "NASA KSC Spaceport Weather Archive (fallback)", reason


def parse_dt(date_s: str, time_s: str) -> datetime | None:
    text = f"{date_s.strip()} {time_s.strip()}"
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%m/%d/%y %H:%M:%S", "%m/%d/%y %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse_csv(text: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    required = {"Date","Time","SiteName","Height","Speed","Direction"}
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise ValueError("Profiler CSV missing columns: " + ", ".join(sorted(missing)))

    out = []
    for r in reader:
        dt = parse_dt(str(r["Date"]), str(r["Time"]))
        height = fnum(r["Height"])
        if dt is None or height is None:
            continue
        site = str(r["SiteName"]).strip().upper()
        if not site.startswith("RWP"):
            continue
        out.append(Row(
            dt=dt,
            site=site,
            height_km=height,
            speed_mps=fnum(r["Speed"]),
            direction_deg=fnum(r["Direction"]),
        ))

    if not out:
        raise ValueError("No valid KSC 915 MHz profiler rows were parsed")
    return out


def load_sites(path: Path):
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["SiteName"].strip().upper()] = {
                "name": r["Name"].strip(),
                "lat": float(r["Latitude"]),
                "lon": float(r["Longitude"]),
                "elev_m": float(r["SiteElevationMeters"]),
            }
    return out


def latest_profiles(rows: list[Row]):
    by_site_time = {}
    for r in rows:
        by_site_time.setdefault((r.site, r.dt), []).append(r)

    profiles = {}
    for (site, dt), profile_rows in by_site_time.items():
        valid = sum(
            1 for r in profile_rows
            if r.speed_mps is not None and r.direction_deg is not None
        )
        old = profiles.get(site)
        if old is None or dt > old["dt"]:
            profiles[site] = {"dt": dt, "rows": profile_rows, "valid": valid}
    return profiles


def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", "")
            .replace("\n", "\\n")
    )


def default_icon_url():
    explicit = os.getenv("PROFILER_ICON_URL", "").strip()
    if explicit:
        return explicit
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"http://{owner}.github.io/{name}/profiler_915_icon.png"
    return "http://cyclonecizek.github.io/ProfilerPlacefiles/profiler_915_icon.png"


ICON_URL = default_icon_url()


def build_hover(site: str, meta: dict, profile: dict, now: datetime, source="Live 915 MHz DRWP API") -> str:
    dt = profile["dt"]
    age = max(0, int((now - dt).total_seconds() / 60))
    rows = sorted(profile["rows"], key=lambda r: r.height_km)
    valid_rows = [
        r for r in rows
        if r.speed_mps is not None and r.direction_deg is not None
    ]
    valid_rows.sort(key=lambda r: r.height_km, reverse=True)

    lines = [
        f"KSC 915 MHz Wind Profiler {site}",
        meta["name"],
        f"Observation: {dt:%Y-%m-%d %H:%MZ}",
        f"Age: {age} min",
        f"Site elevation: {meta['elev_m'] * 3.280839895:.0f} ft MSL",
        f"Valid levels: {len(valid_rows)} / {len(rows)}",
        "",
        "HEIGHT       WIND",  # top of atmosphere first; lowest level appears at bottom
    ]

    for r in valid_rows:
        height_ft = int(round(r.height_km * KM_TO_FT))
        speed_kt = int(round(r.speed_mps * MPS_TO_KT))
        direction = int(round(r.direction_deg)) % 360
        if direction == 0:
            direction = 360
        lines.append(f"{height_ft:>6,d} ft    {direction:03d} deg @ {speed_kt:02d} kt")

    lines += [
        "",
        "Heights converted from source km to ft.",
        "Speeds converted from m/s to kt.",
        f"Source: {source}",
    ]
    return "\n".join(lines)


def build_placefile(rows: list[Row], sites: dict, now: datetime, source="Live 915 MHz DRWP API"):
    profiles = latest_profiles(rows)
    lines = [
        "; KSC 915 MHz Doppler Radar Wind Profilers",
        "RefreshSeconds: 60",
        "Threshold: 300",
        f'IconFile: 1, 32, 32, 16, 16, "{ICON_URL}"',
        'Font: 1, 11, 1, "Arial"',
        "; Hover each profiler marker for the latest vertical wind profile.",
        "; Height displayed in feet; speed displayed in knots.",
        f"; Source: {source}",
    ]
    diag = []

    for site in sorted(sites):
        profile = profiles.get(site)
        if not profile:
            continue
        age = max(0, int((now - profile["dt"]).total_seconds() / 60))
        if age > STALE_MINUTES:
            print(f"{site}: latest profile is stale ({age} min); omitted.")
            continue

        meta = sites[site]
        hover = esc(build_hover(site, meta, profile, now, source))

        lines.append(f"Object: {meta['lat']:.8f}, {meta['lon']:.8f}")
        lines.append(f'Icon: 0, 0, 0, 1, 1, "{hover}"')
        lines.append("Color: 255 255 255")
        lines.append(f'Text: 22, 0, 1, "{site}", "{hover}"')
        lines.append("End:")

        diag.append({
            "site": site,
            "name": meta["name"],
            "observation_utc": profile["dt"].isoformat(),
            "age_minutes": age,
            "rows_in_profile": len(profile["rows"]),
            "valid_wind_levels": profile["valid"],
        })

    return "\n".join(lines) + "\n", diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="local API JSON or legacy KSC profiler CSV")
    ap.add_argument("--sites", default="docs/ksc_915mhz_profiler_sites.csv")
    ap.add_argument("--output", default="docs/ksc_915mhz_profilers.txt")
    ap.add_argument("--json-output", default="docs/ksc_915mhz_profilers.json")
    ap.add_argument("--print-url", action="store_true")
    ap.add_argument("--start", help="UTC YYYY-MM-DDTHH:MM")
    ap.add_argument("--end", help="UTC YYYY-MM-DDTHH:MM")
    args = ap.parse_args()

    if args.print_url:
        if args.start and args.end:
            start = datetime.strptime(args.start, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            end = datetime.strptime(args.end, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        else:
            end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            start = end - timedelta(minutes=LOOKBACK_MINUTES)
        print(build_export_url(start, end))
        return

    sites = load_sites(Path(args.sites))
    now = datetime.now(timezone.utc)
    fallback_reason = None
    if args.input:
        text = Path(args.input).read_text(encoding="utf-8-sig")
        rows = parse_api(json.loads(text)) if text.lstrip().startswith("[") else parse_csv(text)
        source = "Local profiler input"
    else:
        rows, source, fallback_reason = fetch_rows(sites, now)
    placefile, diag = build_placefile(rows, sites, now, source)
    if not diag:
        raise ValueError("No current profiler markers; refusing to replace published output")

    Path(args.output).write_text(placefile, encoding="utf-8")
    Path(args.json_output).write_text(json.dumps({
        "generated_utc": now.isoformat(),
        "rows_parsed": len(rows),
        "source": source,
        "api_fallback_reason": fallback_reason,
        "profiles": diag,
    }, indent=2), encoding="utf-8")

    print(f"Parsed {len(rows)} profiler rows.")
    print(f"Generated {len(diag)} profiler markers.")
    print("Wrote:", args.output, args.json_output)


if __name__ == "__main__":
    main()
