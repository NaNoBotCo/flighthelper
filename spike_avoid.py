#!/usr/bin/env python3
"""Airport-avoidance spike: what does it cost to skip one airport?

Somebody in Palm Beach County who doesn't want to fly out of PBI/DJT has two
realistic substitutes: Fort Lauderdale (FLL) and Miami (MIA). This prices the
same trips from all three and shows the honest trade -- fare delta, flying-time
delta, and the extra driving you eat to get it.

Uses the Travelpayouts *Data API* (token-only, no marker/signature). That API
returns origin/destination but NOT connection airports, so this handles
"don't depart from X" only. Filtering itineraries that *connect* through an
airport needs the real-time Search API (marker + signature).

CODE TRANSITION: the FAA identifier became DJT on 2026-07-09, but the IATA code
stays PBI until 2026-08-18. Fare data will emit PBI for a long while yet and
stale caches will emit it indefinitely. So we always query BOTH codes and merge.
Never match on one alone.

Usage:
    TP_TOKEN=xxxxx python3 spike_avoid.py
    python3 spike_avoid.py --month 2026-09
    python3 spike_avoid.py --dest JFK,LHR --links
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
BOOK_HOST = "https://www.aviasales.com"
HERE = os.path.dirname(os.path.abspath(__file__))

# Affiliate attribution. The API's `link` field comes back WITHOUT it, so a
# booking made through the raw link pays nothing. Every outbound link must
# carry this or the whole thing is a free service.
MARKER = "749581"


def book_url(link):
    """Absolute, attributed booking URL from the API's relative `link` field."""
    if not link:
        return None
    sep = "&" if "?" in link else "?"
    return f"{BOOK_HOST}{link}{sep}marker={MARKER}"

# --- the airport under avoidance, and its substitutes -----------------------
# drive_min = one-way driving time from central West Palm Beach, typical
# traffic. Estimates -- swap in real numbers if you ever wire a maps API.
AVOID = {
    "label": "Palm Beach",
    "codes": ["PBI", "DJT"],   # both, deliberately. See CODE TRANSITION above.
    "drive_min": 0,
    "miles": 0,
}
ALTERNATIVES = [
    {"label": "Fort Lauderdale", "codes": ["FLL"], "drive_min": 55, "miles": 50},
    {"label": "Miami",           "codes": ["MIA"], "drive_min": 75, "miles": 70},
]

DESTINATIONS = [
    ("JFK", "New York"),
    ("ATL", "Atlanta"),
    ("ORD", "Chicago"),
    ("BOS", "Boston"),
    ("DFW", "Dallas"),
    ("LAX", "Los Angeles"),
    ("LHR", "London"),
]

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def get_token():
    tok = os.environ.get("TP_TOKEN", "").strip()
    if tok:
        return tok
    path = os.path.join(HERE, ".tp_token")
    if os.path.exists(path):
        with open(path) as f:
            tok = f.read().strip()
        if tok:
            return tok
    print("\n  No saved Travelpayouts token found.")
    print("  Paste it once and it's remembered here for next time.\n")
    try:
        tok = input("  Travelpayouts API token: ").strip()
    except (EOFError, KeyboardInterrupt):
        tok = ""
    if not tok:
        sys.exit("No token. Set TP_TOKEN or put it in flighthelper/.tp_token")
    try:
        with open(path, "w") as f:
            f.write(tok + "\n")
        os.chmod(path, 0o600)  # owner-only; it's a credential
        print(f"  Saved to {path}\n")
    except OSError as e:
        print(f"  (Could not save token: {e})\n")
    return tok


def fmt_minutes(m):
    if not m:
        return "  --  "
    h, mm = divmod(int(m), 60)
    return f"{h}h{mm:02d}" if h else f"{mm}m"


def fmt_stops(n):
    if n is None:
        return "  --   "
    return "nonstop" if n == 0 else f"{n} stop" + ("s" if n > 1 else "")


class TokenRejected(Exception):
    """The API refused our credentials -- stop immediately, don't burn requests."""


def fetch(token, origin, dest, month, one_way=False):
    """One cached-fare query. Returns [] on any failure (logged to stderr).

    month=None means "any date". That matters: filtering by month collapses the
    avoided airport's coverage (PBI->JFK went 3 results -> 0, and PBI dropped
    from 11 comparable routes to 3). Because fares may then be for different
    dates, every row prints its own departure date -- an unlabelled comparison
    across dates would be dishonest."""
    params = {
        "origin": origin,
        "destination": dest,
        "currency": "usd",
        "limit": 30,
        "sorting": "price",
        "one_way": "true" if one_way else "false",
        "token": token,
    }
    if month:
        params["departure_at"] = month
    q = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{BASE}?{q}", timeout=30) as r:
            return json.load(r).get("data", []) or []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TokenRejected(str(e.code)) from e
        print(f"    ! {origin}->{dest}: HTTP {e.code}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"    ! {origin}->{dest}: {e}", file=sys.stderr)
    return []


def cheapest_from(token, airport, dest, month, one_way):
    """Cheapest offer across ALL of an airport's codes (PBI + DJT merged)."""
    pool = []
    for code in airport["codes"]:
        pool.extend(fetch(token, code, dest, month, one_way))
        time.sleep(0.35)  # be polite to the cached-fare endpoint
    if not pool:
        return None
    return min(pool, key=lambda x: x.get("price") or 10**9)


def outbound_minutes(offer):
    return offer.get("duration_to") or offer.get("duration")


def dep_date(offer):
    """'Aug 15' from the offer's departure timestamp, or blank."""
    raw = (offer or {}).get("departure_at") or ""
    if len(raw) < 10:
        return ""
    y, m, d = raw[:4], raw[5:7], raw[8:10]
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    try:
        return f"{months[int(m) - 1]} {int(d)}"
    except (ValueError, IndexError):
        return y


def report_row(airport, offer, one_way):
    codes = "/".join(airport["codes"])
    if not offer:
        return f"  {airport['label']:<17} {codes:<8} {DIM}no cached fares{RESET}"
    drive = airport["drive_min"] * (1 if one_way else 2)
    drive_txt = "no drive" if not drive else (
        f"+{fmt_minutes(drive)} drive" + ("" if one_way else " r/t")
    )
    return (
        f"  {airport['label']:<17} {codes:<8} "
        f"${offer['price']:<6} {fmt_stops(offer.get('transfers')):<8} "
        f"{fmt_minutes(outbound_minutes(offer)):<7} "
        f"{DIM}dep {dep_date(offer):<7} {drive_txt}{RESET}"
    )


def verdict(avoid_offer, alt_results, one_way):
    """alt_results: list of (airport, offer). Returns list of printable lines."""
    live = [(a, o) for a, o in alt_results if o]
    if not live:
        if not avoid_offer:
            return [f"  {DIM}No cached fares on this route from any of the three.{RESET}"]
        return [f"  {BOLD}No substitute found{RESET} -- only PBI/DJT had fares."]

    best_air, best = min(live, key=lambda p: p[1]["price"])
    drive = best_air["drive_min"] * (1 if one_way else 2)
    where = f"{best_air['label']} ({best_air['codes'][0]}), ${best['price']}"

    if not avoid_offer:
        return [
            f"  {BOLD}-> Fly from {where}{RESET}",
            f"     {DIM}No PBI/DJT fare cached on this route, so no comparison.{RESET}",
        ]

    # Positive saving = the substitute is cheaper. Measured across 24 routes,
    # it was cheaper on 11 of 11 comparable ones -- so lead with the number.
    saving = avoid_offer["price"] - best["price"]
    d_fly = (outbound_minutes(best) or 0) - (outbound_minutes(avoid_offer) or 0)

    if saving > 0:
        lines = [f"  {BOLD}-> SKIP DJT AND SAVE ${saving}{RESET}   fly from {where}"]
        lines.append(f"     DJT/PBI would cost ${avoid_offer['price']}. "
                     f"That's {BOLD}${saving} back in your pocket{RESET}.")
    elif saving < 0:
        lines = [f"  {BOLD}-> Skipping DJT costs you ${-saving} here{RESET}   "
                 f"cheapest alternative is {where}"]
        lines.append(f"     DJT/PBI is ${avoid_offer['price']} -- the one route "
                     f"where staying local is cheaper.")
    else:
        lines = [f"  {BOLD}-> Same price either way (${best['price']}){RESET}   "
                 f"alternative is {where}"]

    cost = []
    if d_fly > 0:
        cost.append(f"{fmt_minutes(d_fly)} more flying")
    elif d_fly < 0:
        cost.append(f"{fmt_minutes(-d_fly)} LESS flying")
    if drive:
        cost.append(f"{fmt_minutes(drive)} driving"
                    + ("" if one_way else " round trip"))
    if cost:
        lines.append(f"     Costs you: {', '.join(cost)}.")
    if saving > 0 and drive:
        lines.append(f"     {DIM}${saving / (drive / 60):.0f} saved per hour "
                     f"behind the wheel.{RESET}")
    return lines


def main():
    ap = argparse.ArgumentParser(description="Price the cost of avoiding one airport.")
    ap.add_argument("--month", help="YYYY-MM to search (default: any date -- "
                                    "filtering by month guts the PBI baseline)")
    ap.add_argument("--dest", help="comma-separated IATA codes (default: built-in list)")
    ap.add_argument("--one-way", action="store_true", help="one-way instead of round trip")
    ap.add_argument("--links", action="store_true", help="print booking deep links")
    args = ap.parse_args()

    month = args.month  # None = any date; see fetch() for why that's the default

    dests = DESTINATIONS
    if args.dest:
        wanted = [c.strip().upper() for c in args.dest.split(",") if c.strip()]
        known = dict(DESTINATIONS)
        dests = [(c, known.get(c, c)) for c in wanted]

    token = get_token()
    trip = "one way" if args.one_way else "round trip"
    airports = [AVOID] + ALTERNATIVES

    print()
    print("=" * 72)
    print(f"  {BOLD}SKIP DJT -- WHAT YOU SAVE{RESET}   {trip}, {month or 'any date'}")
    print(f"  {DIM}Substitutes: " +
          ", ".join(f"{a['label']} ({a['codes'][0]}, ~{a['miles']}mi)"
                    for a in ALTERNATIVES) + f"{RESET}")
    print("=" * 72)

    for code, city in dests:
        print(f"\n  {BOLD}{city.upper()}  ({code}){RESET}")
        print("  " + "-" * 68)
        offers = []
        for airport in airports:
            try:
                o = cheapest_from(token, airport, code, month, args.one_way)
            except TokenRejected as e:
                print()
                print(f"  {BOLD}TOKEN REJECTED (HTTP {e}){RESET}")
                print("  The Travelpayouts API refused this token. Check it in your")
                print("  affiliate account, then re-run. Nothing else was queried.")
                print()
                sys.exit(1)
            offers.append((airport, o))
            print(report_row(airport, o, args.one_way))
        print()
        for line in verdict(offers[0][1], offers[1:], args.one_way):
            print(line)
        if args.links:
            for airport, o in offers:
                url = book_url(o.get("link")) if o else None
                if url:
                    print(f"     {DIM}{airport['codes'][0]}: {url}{RESET}")

    print()
    print("=" * 72)
    print(f"  {DIM}Cached fares, not live availability. Drive times are estimates.")
    print(f"  Connection-airport avoidance needs the real-time Search API.{RESET}")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
