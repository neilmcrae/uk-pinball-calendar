#!/usr/bin/env python3
"""
fetch_ifpa_uk_tournaments.py
-----------------------------------
Pulls UK tournaments from the IFPA API and writes them into TWO pages
(between the IFPA_DATA_START / IFPA_DATA_END markers in each), so opening
either always shows current data with no separate JSON fetch/CORS headache:

    tournaments.html      — every future UK tournament
    pinball-republic.html — just the ones at Pinball Republic

Both files must already exist alongside this script — it only edits their
embedded data block, it doesn't create the page layout.

Usage:
    export IFPA_API_KEY="your_key_here"
    python3 fetch_ifpa_uk_tournaments.py

Optional flags:
    --months-ahead 24        how far forward to pull (default 24 / 2 years)
    --months-back 0          how far back to include recently-finished events (default 0 = future only)
    --html tournaments.html  path to the "all tournaments" HTML file to update
    --pr-html pinball-republic.html  path to the "Pinball Republic only" HTML file to update
    --json tournaments.json  also write a standalone JSON dump (handy for the
                              Google Apps Script pipeline / spreadsheet cross-check)

NOTE ON PINBALL REPUBLIC DETECTION:
This flags a tournament as Pinball Republic by searching whatever venue/
address text the calendar/search response already includes for the string
"pinball republic" (case-insensitive). It only uses data from that single
bulk call — no extra per-tournament lookups — so if IFPA's summary response
for a given event genuinely doesn't include a venue name or address at all,
it won't be caught. Run with IFPA_DEBUG=1 to see a sample raw record and
confirm what venue/address fields (if any) are actually coming back.

NOTE ON THE IFPA API:
The publicly documented pattern is:
    GET https://api.ifpapinball.com/v1/<endpoint>?api_key=YOUR_KEY&...
but IFPA has iterated the backend more than once (community clients report
both `/v1/...` and unversioned `/...` paths still working, and some now take
the key as an `X-Api-Key` header instead of a query param). Since you've
already got a working Apps Script pulling roster data for the 154-tournament
UK set, the safest move is:

  1. Try running this as-is first.
  2. If you get a 401/404, open your working Apps Script and copy the exact
     base URL + auth style it uses into IFPA_BASE / AUTH_MODE below — the
     rest of this script (filtering, pagination, dedupe, HTML injection)
     will work unchanged.

This script is deliberately defensive: it tries a couple of known endpoint
shapes for the calendar/tournament search before giving up, and prints
exactly what it tried so you can see where to point it.
"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
import urllib.request
import urllib.parse
import urllib.error

IFPA_BASE = "https://api.ifpapinball.com"
AUTH_MODE = "query"  # "query" -> ?api_key=... , "header" -> X-Api-Key header

# Pinball Republic detection: just look for this text (case-insensitive)
# anywhere in the tournament's venue/address fields from the summary data
# the calendar/search endpoint already gives us. No extra API calls.
PINBALL_REPUBLIC_TEXT = "pinball republic"


def _flatten_strings(obj, _depth=0):
    """Yield every string value found anywhere inside a nested dict/list,
    however IFPA happens to have structured the record (a plain field, or
    nested under venue/location/etc). Depth-capped to stay fast/safe."""
    if _depth > 5:
        return
    if isinstance(obj, str):
        if obj:
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten_strings(v, _depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _flatten_strings(v, _depth + 1)


def http_get_json(url, api_key, headers=None):
    req_headers = dict(headers or {})
    if AUTH_MODE == "header":
        req_headers["X-Api-Key"] = api_key
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_url(path, api_key, params):
    params = dict(params or {})
    if AUTH_MODE == "query":
        params["api_key"] = api_key
    qs = urllib.parse.urlencode(params)
    return f"{IFPA_BASE}{path}?{qs}"


def try_fetch_calendar(api_key, start_date, end_date):
    """
    Try a few plausible endpoint shapes for a GB tournament/calendar search.
    Returns (list_of_raw_tournaments, endpoint_used) or raises the last error.
    """
    attempts = [
        ("/v1/calendar/search", {
            "country_code": "GB",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }),
        ("/v1/tournament/search", {
            "country": "GB",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }),
        ("/tournament/search", {
            "country": "GB",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }),
        ("/v1/calendar", {
            "country_code": "GB",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }),
    ]

    last_err = None
    for path, params in attempts:
        url = build_url(path, api_key, params)
        print(f"  trying: {path} ...", end=" ")
        try:
            data = http_get_json(url, api_key)
            items = data.get("tournaments") or data.get("calendar") or data.get("results") or data
            if isinstance(items, list):
                print(f"OK ({len(items)} results)")
                return items, path
            print("unexpected shape, skipping")
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}")
            last_err = e
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}")
            last_err = e

    raise RuntimeError(
        "Couldn't find a working calendar endpoint automatically. "
        f"Last error: {last_err}\n"
        "Open your working Apps Script / a browser DevTools network tab on "
        "ifpapinball.com and copy the exact request URL it uses, then set "
        "IFPA_BASE / edit try_fetch_calendar() to match it."
    )


def normalise(item):
    """Map whatever field names IFPA returns into our simple schema."""
    def pick(*keys, default=""):
        for k in keys:
            v = item.get(k)
            if isinstance(v, str) and v:
                return v
        return default

    venue = pick("venue_name", "location_name", "venue", default="")
    city = pick("city", "location_city", default="")
    name = pick("tournament_name", "name", default="Untitled tournament")
    start = pick(
        "start_date", "event_start_date", "date", "tournament_start_date",
        "date_start", "begin_date",
        default="",
    )
    end = pick(
        "end_date", "event_end_date", "tournament_end_date",
        "date_end", "finish_date", "last_date",
        default="",
    )
    if not end:
        end = start  # genuinely single-day event, or API just didn't send one
    ttype = pick("tournament_type", "type", default="Tournament")
    # Two distinct links, kept separate:
    #  - ifpa_url:  the tournament's own page on ifpapinball.com (we can
    #    always build this ourselves from the tournament id)
    #  - info_url:  the organiser's own submitted website/info link, shown
    #    on the IFPA page as a separate "more information" link. Field
    #    naming for this isn't consistent across endpoints, so try the
    #    likely candidates.
    info_url = pick(
        "website", "tournament_website", "event_website",
        "external_url", "external_website", "web_url", "site_url",
        "registration_url", "reg_url", "organizer_url", "info_url",
        default="",
    )
    tid = str(pick("tournament_id", "id", default=name))
    ifpa_url = f"https://www.ifpapinball.com/tournaments/view.php?t={tid}" if tid else ""
    country = pick("country_code", "country", default="")

    # Recursively pull every string value out of the raw record, however
    # deeply IFPA has nested it (venue-as-object, location-as-object, etc.)
    # — rather than betting on one specific field name/path, search
    # *everything* the API sent back for this event for the plain text
    # "pinball republic". No extra API calls, no postcode logic — just a
    # substring search over whatever this one summary record contains.
    all_strings = list(_flatten_strings(item))
    full_blob = " ".join(all_strings)
    is_pr = PINBALL_REPUBLIC_TEXT in full_blob.lower()

    # Best-effort address/postcode for display, and to help debug PR
    # detection — also searched recursively rather than one fixed field.
    postcode_field = pick(
        "postal_code", "postcode", "zip", "zip_code",
        "venue_postcode", "venue_zip", "location_postcode", "location_zip",
        default="",
    )
    if not postcode_field:
        pc_match = re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", full_blob.upper())
        postcode_field = pc_match.group(0) if pc_match else ""

    address_field = pick(
        "address", "venue_address", "location_address", "full_address",
        default="",
    )
    if not address_field:
        # fall back to the longest string in the record that contains the
        # postcode we found, if any — usually the full street address
        candidates = [s for s in all_strings if postcode_field and postcode_field in s.upper()]
        address_field = max(candidates, key=len) if candidates else ""

    # If we never got a venue name from the flat fields, see if one is
    # nested (e.g. venue: {name: "Pinball Republic", ...}).
    if not venue:
        for key in ("venue", "location"):
            nested = item.get(key)
            if isinstance(nested, dict):
                nested_name = nested.get("name")
                if isinstance(nested_name, str) and nested_name:
                    venue = nested_name
                    break

    return {
        "id": tid,
        "name": name,
        "venue": venue,
        "address": address_field,
        "city": city,
        "country": country,
        "postcode": postcode_field,
        "start_date": str(start)[:10],
        "end_date": str(end)[:10] if end else str(start)[:10],
        "type": ttype,
        "pinball_republic": is_pr,
        "ifpa_url": ifpa_url,
        "info_url": info_url,
    }


def dedupe(rows):
    seen = {}
    for r in rows:
        seen[r["id"]] = r  # last write wins
    return sorted(seen.values(), key=lambda r: r["start_date"])


UK_COUNTRY_CODES = {"GB", "UK"}


def keep_future_uk_only(rows, today_iso):
    """Belt-and-braces filter: only UK events, only still-running-or-ahead.
    Applied even though the API call already asks for country=GB and a
    forward date range, in case the API ignores either param."""
    out = []
    for r in rows:
        if r["end_date"] and r["end_date"] < today_iso:
            continue  # already finished
        if r["country"] and r["country"].upper() not in UK_COUNTRY_CODES:
            continue  # not a UK event
        out.append(r)
    return out


def inject_into_html(html_path, payload):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    block = (
        '<!-- IFPA_DATA_START -->\n'
        '<script id="tournament-data" type="application/json">\n'
        + json.dumps(payload, indent=2)
        + '\n</script>\n'
        '<!-- IFPA_DATA_END -->'
    )

    pattern = re.compile(
        r"<!-- IFPA_DATA_START -->.*?<!-- IFPA_DATA_END -->", re.DOTALL
    )
    if not pattern.search(html):
        raise RuntimeError(
            f"Couldn't find IFPA_DATA_START/END markers in {html_path}. "
            "Don't edit those marker comments in index.html."
        )
    # Use a function (not a raw string) as the replacement so re.sub doesn't
    # try to interpret \u... sequences inside the JSON payload as regex
    # backreferences/escapes.
    new_html = pattern.sub(lambda m: block, html)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months-ahead", type=int, default=24)
    ap.add_argument("--months-back", type=int, default=0)
    ap.add_argument("--html", default="tournaments.html",
                     help="the 'all UK tournaments' page")
    ap.add_argument("--pr-html", default="pinball-republic.html",
                     help="the 'Pinball Republic only' page")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    api_key = os.environ.get("IFPA_API_KEY")
    if not api_key:
        print("Set IFPA_API_KEY in your environment first:\n"
              '  export IFPA_API_KEY="your_key_here"', file=sys.stderr)
        sys.exit(1)

    today = date.today()
    start_date = today - timedelta(days=30 * args.months_back)
    end_date = today + timedelta(days=30 * args.months_ahead)

    print(f"Fetching UK tournaments {start_date} -> {end_date} ...")
    raw_items, endpoint = try_fetch_calendar(api_key, start_date, end_date)
    print(f"Using endpoint: {endpoint}")

    if raw_items and os.environ.get("IFPA_DEBUG"):
        print("\n--- sample raw item from calendar/search (IFPA_DEBUG=1) ---")
        print(json.dumps(raw_items[0], indent=2)[:2000])
        print("--- end sample ---\n")

    rows = dedupe(normalise(item) for item in raw_items)
    pr_count = sum(1 for r in rows if r["pinball_republic"])
    info_count = sum(1 for r in rows if r["info_url"])
    multiday_count = sum(1 for r in rows if r["start_date"] != r["end_date"])
    print(f"Flagged {pr_count} Pinball Republic tournaments.")
    if pr_count:
        for r in rows:
            if r["pinball_republic"]:
                print(f"  - {r['name']!r} @ venue={r['venue']!r} address={r['address']!r}")
    print(f"Found an organiser info link for {info_count}/{len(rows)} tournaments (IFPA entry link is always built).")
    print(f"{multiday_count}/{len(rows)} tournaments have a different start and end date.")
    if raw_items and (info_count < len(rows) or multiday_count == 0 or pr_count == 0):
        print("  Run with IFPA_DEBUG=1 to see the raw field names IFPA is sending,")
        print("  then adjust the `pick(...)` calls for `info_url` / `start` / `end` in this script.")
    rows = keep_future_uk_only(rows, today.isoformat())
    print(f"Normalised to {len(rows)} future UK tournaments.")

    payload_all = {
        "generated_at": today.isoformat(),
        "source_endpoint": endpoint,
        "tournaments": rows,
    }
    payload_pr = {
        "generated_at": today.isoformat(),
        "source_endpoint": endpoint,
        "tournaments": [r for r in rows if r["pinball_republic"]],
    }

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload_all, f, indent=2)
        print(f"Wrote {args.json}")

    inject_into_html(args.html, payload_all)
    print(f"Updated {args.html} ({len(payload_all['tournaments'])} tournaments) — open it in a browser to check.")

    if os.path.exists(args.pr_html):
        inject_into_html(args.pr_html, payload_pr)
        print(f"Updated {args.pr_html} ({len(payload_pr['tournaments'])} tournaments) — open it in a browser to check.")
    else:
        print(f"Skipped {args.pr_html} — file not found. Make sure it's in the same "
              "folder as this script (download it alongside tournaments.html).")


if __name__ == "__main__":
    main()
