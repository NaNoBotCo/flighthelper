#!/usr/bin/env python3
"""DEAD -- DO NOT RUN. Kept only for the control-route pattern below.

Amadeus decommissioned its Self-Service portal on 2026-07-17: new registrations
closed AND existing keys deactivated. developers.amadeus.com is Enterprise-only
now (sales contact, contracts). There is no key this script can ever accept.
Removed from the launcher 2026-07-22.

The idea worth salvaging: price a KNOWN-GOOD control route first, so you can
tell "this airport is thin" from "this data source is thin." That mistake is
what made the PBI baseline untrustworthy in the first place. Reuse the pattern
against whatever source comes next.

--- original docstring below ---

Amadeus coverage spike: can PBI be measured honestly?

WHY THIS EXISTS
The Travelpayouts Data API can't answer the airport-avoidance question. Its
cached fares mirror what other Aviasales users happened to search, so a thinly-
searched airport is thinly covered -- across 7 routes we measured PBI 8 results,
FLL 34, MIA 57. The airport we're measuring is the one with the worst data, and
a missing baseline silently reads as "that airport is bad." The tool would argue
for avoidance out of nothing but absent data.

The Travelpayouts Search API would fix that, but it requires 50,000+ MAU and
they don't make exceptions. So: Amadeus for search structure, Travelpayouts
(marker 749581) purely for the booking handoff and commission.

THE ONE QUESTION THIS ANSWERS
Is Amadeus's PBI coverage dense enough to trust as a baseline?

THE TRAP THIS AVOIDS
Amadeus's TEST environment serves a limited cached dataset -- thin results there
may be an artifact of the sandbox, not a fact about the airport. Concluding
"PBI is sparse" from sandbox gaps would repeat the exact error we just caught
Travelpayouts making. So every run prices a CONTROL route that the test
environment is known to cover well. Read the control first:

    control healthy + PBI thin  -> PBI really is thin. Real finding.
    control thin                -> the sandbox is thin. Finding is WORTHLESS.
                                   Re-run against production before believing it.

SETUP
Free key: https://developers.amadeus.com -> register -> Self-Service app.
You get an API Key + API Secret. First run asks for both once and remembers them.

Usage:
    python3 spike_amadeus.py
    python3 spike_amadeus.py --date 2026-10-08
    python3 spike_amadeus.py --prod          # production host, real data, costs money
    python3 spike_amadeus.py --structure     # dump one full itinerary
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(HERE, ".amadeus_creds")

TEST_HOST = "https://test.api.amadeus.com"
PROD_HOST = "https://api.amadeus.com"

# Same airports and destinations as the Travelpayouts spike, so the coverage
# numbers are directly comparable against TP's PBI 8 / FLL 34 / MIA 57.
ORIGINS = [
    ("PBI", "Palm Beach"),
    ("FLL", "Fort Lauderdale"),
    ("MIA", "Miami"),
]
DESTINATIONS = ["JFK", "ATL", "ORD", "BOS", "DFW", "LAX", "LHR"]

# Route the Amadeus sandbox is known to cover densely. If THIS comes back thin,
# the sandbox is the problem and every other number below is meaningless.
CONTROL_ROUTE = ("MAD", "BCN", "Madrid -> Barcelona (sandbox control)")

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def get_creds():
    """Env vars win, then the saved file, then prompt -- but only for what's missing.
    Half-saved credentials are normal here: the key was filed ahead of the secret."""
    saved = {}
    if os.path.exists(CREDS_FILE):
        try:
            with open(CREDS_FILE) as f:
                saved = json.load(f) or {}
        except (OSError, ValueError):
            saved = {}

    key = os.environ.get("AMADEUS_CLIENT_ID", "").strip() or saved.get("key", "").strip()
    sec = os.environ.get("AMADEUS_CLIENT_SECRET", "").strip() or saved.get("secret", "").strip()
    if key and sec:
        return key, sec

    print("\n  Amadeus credentials incomplete.")
    print("  Free key: https://developers.amadeus.com -> Self-Service app.\n")
    try:
        if not key:
            key = input("  Amadeus API Key:    ").strip()
        else:
            print(f"  Amadeus API Key:    {key[:6]}...{key[-4:]}  (already saved)")
        if not sec:
            sec = input("  Amadeus API Secret: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nCancelled.")
    if not key or not sec:
        sys.exit("Need both key and secret.")

    try:
        with open(CREDS_FILE, "w") as f:
            json.dump({"key": key, "secret": sec}, f)
        os.chmod(CREDS_FILE, 0o600)  # owner-only; these are credentials
        print(f"\n  Saved to {CREDS_FILE}\n")
    except OSError as e:
        print(f"\n  (Could not save: {e})\n")
    return key, sec


def get_access_token(host, key, secret):
    """OAuth2 client_credentials. Token lasts ~30 min; a spike finishes well inside that."""
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": key,
        "client_secret": secret,
    }).encode()
    req = urllib.request.Request(
        f"{host}/v1/security/oauth2/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 401:
            sys.exit(f"\n  Amadeus rejected these credentials (401).\n  Delete "
                     f"{CREDS_FILE} and re-run to re-enter them.\n  {detail}\n")
        sys.exit(f"\n  Auth failed HTTP {e.code}: {detail}\n")
    except urllib.error.URLError as e:
        sys.exit(f"\n  Could not reach {host}\n  {e.reason}\n\n"
                 f"  Check your internet connection. If the hostname won't resolve,\n"
                 f"  you may be behind a VPN, proxy, or DNS filter blocking Amadeus.\n")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"\n  Unexpected auth failure: {e}\n")


def search(host, token, origin, dest, when, adults=1, max_results=50):
    """One flight-offers search. Returns (offers, error_string)."""
    q = urllib.parse.urlencode({
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": when,
        "adults": adults,
        "currencyCode": "USD",
        "max": max_results,
    })
    req = urllib.request.Request(
        f"{host}/v2/shopping/flight-offers?{q}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r).get("data", []) or [], None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            errs = json.loads(raw).get("errors", [])
            msg = errs[0].get("detail") or errs[0].get("title") if errs else raw[:120]
        except Exception:  # noqa: BLE001
            msg = raw[:120]
        return [], f"HTTP {e.code}: {msg}"
    except Exception as e:  # noqa: BLE001
        return [], str(e)


def cheapest(offers):
    if not offers:
        return None
    return min(offers, key=lambda o: float(o["price"]["grandTotal"]))


def legs(offer):
    """Every flight leg across all itineraries -> [(from, to, carrier+number), ...]."""
    out = []
    for itin in offer.get("itineraries", []):
        for seg in itin.get("segments", []):
            out.append((
                seg["departure"]["iataCode"],
                seg["arrival"]["iataCode"],
                f'{seg.get("carrierCode", "")}{seg.get("number", "")}',
            ))
    return out


def connection_airports(offer):
    """Intermediate airports only -- the thing Travelpayouts' Data API cannot tell us."""
    ls = legs(offer)
    return [arr for (_, arr, _) in ls[:-1]] if len(ls) > 1 else []


def fmt_iso_duration(d):
    """PT5H35M -> 5h35."""
    if not d or not d.startswith("PT"):
        return "  --  "
    h = m = 0
    num = ""
    for ch in d[2:]:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            h, num = int(num or 0), ""
        elif ch == "M":
            m, num = int(num or 0), ""
    return f"{h}h{m:02d}" if h else f"{m}m"


def main():
    ap = argparse.ArgumentParser(description="Measure Amadeus coverage for the avoidance baseline.")
    ap.add_argument("--date", help="YYYY-MM-DD departure (default: 8 weeks out)")
    ap.add_argument("--prod", action="store_true", help="production host (real data, billable)")
    ap.add_argument("--structure", action="store_true", help="dump one full itinerary")
    args = ap.parse_args()

    when = args.date or (date.today() + timedelta(weeks=8)).isoformat()
    host = PROD_HOST if args.prod else TEST_HOST
    env = "PRODUCTION" if args.prod else "test sandbox"

    key, secret = get_creds()
    token = get_access_token(host, key, secret)

    print()
    print("=" * 74)
    print(f"  {BOLD}AMADEUS COVERAGE SPIKE{RESET}   {env}   departing {when}")
    print(f"  {DIM}Question: is PBI dense enough to trust as an avoidance baseline?{RESET}")
    print("=" * 74)

    # --- control first. Everything below is void if this is thin. ---------
    c_from, c_to, c_label = CONTROL_ROUTE
    c_offers, c_err = search(host, token, c_from, c_to, when)
    print(f"\n  {BOLD}CONTROL{RESET}  {c_label}")
    if c_err:
        print(f"    {BOLD}FAILED: {c_err}{RESET}")
        print(f"    Cannot judge sandbox health. Fix this before trusting anything below.\n")
    else:
        print(f"    {len(c_offers)} offers")
        if len(c_offers) < 5:
            print(f"    {BOLD}!! SANDBOX LOOKS THIN.{RESET} Numbers below are probably artifacts,")
            print(f"       not facts about these airports. Re-run with --prod before believing them.")
        else:
            print(f"    {DIM}Sandbox healthy -- thin results below are real findings.{RESET}")
    time.sleep(0.5)

    # --- coverage matrix -------------------------------------------------
    print(f"\n  {BOLD}COVERAGE{RESET}  (offers returned per route)")
    print("  " + "-" * 70)
    header = f"  {'':<18}" + "".join(f"{d:>7}" for d in DESTINATIONS) + f"{'TOTAL':>9}"
    print(BOLD + header + RESET)

    totals, best_by_origin = {}, {}
    for code, label in ORIGINS:
        counts, row_best = [], {}
        for dest in DESTINATIONS:
            offers, err = search(host, token, code, dest, when)
            counts.append(-1 if err else len(offers))
            if offers:
                row_best[dest] = cheapest(offers)
            if err:
                print(f"\n    {DIM}! {code}->{dest}: {err}{RESET}", file=sys.stderr)
            time.sleep(0.45)  # sandbox is rate-limited
        good = [c for c in counts if c >= 0]
        totals[code] = sum(good)
        best_by_origin[code] = row_best
        cells = "".join(("{:>7}".format("err" if c < 0 else c)) for c in counts)
        print(f"  {label:<18}{cells}{totals[code]:>9}")

    print("  " + "-" * 70)
    print(f"  {DIM}Travelpayouts Data API, same routes, for comparison: "
          f"PBI 8, FLL 34, MIA 57{RESET}")

    # --- the verdict on the baseline -------------------------------------
    print(f"\n  {BOLD}BASELINE VERDICT{RESET}")
    pbi = totals.get("PBI", 0)
    alts = max(totals.get("FLL", 0), totals.get("MIA", 0))
    if pbi == 0:
        print(f"  {BOLD}PBI returned nothing.{RESET} Baseline unusable -- same failure as TP.")
    elif alts and pbi < alts * 0.4:
        print(f"  PBI ({pbi}) is far behind the substitutes ({alts}).")
        print(f"  {BOLD}Still a biased baseline.{RESET} Do not ship a comparison on this.")
    else:
        print(f"  PBI ({pbi}) is comparable to the substitutes ({alts}).")
        print(f"  {BOLD}Baseline is trustworthy -- the comparison can be built honestly.{RESET}")

    # --- structural proof: connection airports are visible ---------------
    print(f"\n  {BOLD}STRUCTURE CHECK{RESET}  (can we see connection airports?)")
    sample = None
    for code, _ in ORIGINS:
        for dest, offer in best_by_origin.get(code, {}).items():
            if len(legs(offer)) > 1:
                sample = (code, dest, offer)
                break
        if sample:
            break

    if not sample:
        print(f"  {DIM}No multi-leg itinerary in this sample -- nothing to prove structure on.{RESET}")
    else:
        code, dest, offer = sample
        print(f"  {code} -> {dest}, ${offer['price']['grandTotal']}")
        for frm, to, flt in legs(offer):
            print(f"    {frm} -> {to}   {flt}")
        vias = connection_airports(offer)
        print(f"  connects via: {', '.join(vias) if vias else '(nonstop)'}")
        print(f"  {BOLD}-> Connection filtering is buildable.{RESET} "
              f"{DIM}Travelpayouts' Data API gives only a stop COUNT.{RESET}")
        if args.structure:
            print("\n" + json.dumps(offer, indent=2)[:4000])

    # --- fare comparison, only if the baseline earned it ------------------
    if pbi > 0:
        print(f"\n  {BOLD}CHEAPEST FARE BY ORIGIN{RESET}")
        print("  " + "-" * 70)
        for dest in DESTINATIONS:
            row = []
            for code, _ in ORIGINS:
                o = best_by_origin.get(code, {}).get(dest)
                row.append(f"{code} ${float(o['price']['grandTotal']):>7.0f} "
                           f"{fmt_iso_duration((o.get('itineraries') or [{}])[0].get('duration')):<6}"
                           if o else f"{code} {'--':>9}       ")
            print(f"  {dest:<5} " + "  ".join(row))

    print()
    print("=" * 74)
    print(f"  {DIM}Monetization unchanged: search here, hand off to Travelpayouts")
    print(f"  booking links with marker 749581 to earn commission.{RESET}")
    print("=" * 74)
    print()


if __name__ == "__main__":
    main()
