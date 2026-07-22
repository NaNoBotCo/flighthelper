#!/usr/bin/env python3
"""How often -- and by how much -- is skipping PBI/DJT actually CHEAPER?

Three routes suggested the substitutes always win. That's a direction, not a
finding. This widens the sample to settle it, because it decides the product's
headline: "skip it for about the same money" is a very different claim from
"skip it AND save."

No departure_at filter here: month-filtering collapsed PBI's coverage (JFK went
3 results -> 0), and PBI coverage is the binding constraint on sample size.

Usage:  python3 measure_savings.py
        python3 measure_savings.py --one-way
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVOID_CODES = ["PBI", "DJT"]
SUBSTITUTES = {"FLL": "Fort Lauderdale", "MIA": "Miami"}

# Destinations PBI plausibly serves -- domestic majors plus the Caribbean/UK
# routes a South Florida airport would realistically carry.
DESTINATIONS = [
    "JFK", "LGA", "EWR", "BOS", "DCA", "IAD", "BWI", "PHL", "CLT", "ATL",
    "ORD", "MDW", "DTW", "MSP", "DEN", "DFW", "IAH", "LAX", "SFO", "SEA",
    "LAS", "PHX", "NAS", "LHR",
]

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def token():
    t = os.environ.get("TP_TOKEN", "").strip()
    if t:
        return t
    p = os.path.join(HERE, ".tp_token")
    if os.path.exists(p):
        with open(p) as f:
            return f.read().strip()
    sys.exit("No token (TP_TOKEN or flighthelper/.tp_token)")


def cheapest(tok, origin, dest, one_way):
    q = urllib.parse.urlencode({
        "origin": origin, "destination": dest, "currency": "usd",
        "limit": 30, "sorting": "price",
        "one_way": "true" if one_way else "false", "token": tok,
    })
    try:
        with urllib.request.urlopen(f"{BASE}?{q}", timeout=30) as r:
            data = json.load(r).get("data") or []
    except Exception:  # noqa: BLE001
        return None
    return min((d["price"] for d in data), default=None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one-way", action="store_true")
    args = ap.parse_args()
    tok = token()
    trip = "one way" if args.one_way else "round trip"

    print(f"\n{'=' * 74}")
    print(f"  {BOLD}IS SKIPPING PBI/DJT CHEAPER?{RESET}   {trip}, {len(DESTINATIONS)} destinations")
    print(f"{'=' * 74}\n")
    print(f"  {'DEST':<6}{'PBI/DJT':>10}{'FLL':>9}{'MIA':>9}{'BEST ALT':>10}{'YOU SAVE':>11}")
    print("  " + "-" * 70)

    rows, savings, cheaper, dearer, spreads = [], [], 0, 0, []

    for dest in DESTINATIONS:
        avoid = None
        for code in AVOID_CODES:
            p = cheapest(tok, code, dest, args.one_way)
            if p is not None:
                avoid = p if avoid is None else min(avoid, p)
            time.sleep(0.3)

        subs = {}
        for code in SUBSTITUTES:
            p = cheapest(tok, code, dest, args.one_way)
            if p is not None:
                subs[code] = p
            time.sleep(0.3)

        if len(subs) == 2:
            spreads.append(abs(subs["FLL"] - subs["MIA"]))

        best = min(subs.values()) if subs else None
        if avoid is not None and best is not None:
            delta = avoid - best          # positive => substitute is cheaper
            savings.append(delta)
            if delta > 0:
                cheaper += 1
            elif delta < 0:
                dearer += 1
            verdict = f"${delta:+d}"
        else:
            verdict = "--"

        rows.append(dest)
        print(f"  {dest:<6}"
              f"{('$%d' % avoid) if avoid is not None else '--':>10}"
              f"{('$%d' % subs['FLL']) if 'FLL' in subs else '--':>9}"
              f"{('$%d' % subs['MIA']) if 'MIA' in subs else '--':>9}"
              f"{('$%d' % best) if best is not None else '--':>10}"
              f"{verdict:>11}")

    print("  " + "-" * 70)
    n = len(savings)
    print(f"\n  {BOLD}VERDICT{RESET}")
    if not n:
        print("  No route had both a PBI fare and a substitute fare. Nothing to conclude.")
    else:
        print(f"  Comparable routes (PBI had a fare): {BOLD}{n}{RESET} of {len(DESTINATIONS)}")
        print(f"  Substitute CHEAPER: {BOLD}{cheaper}{RESET}   "
              f"more expensive: {dearer}   tie: {n - cheaper - dearer}")
        print(f"  Median saving: {BOLD}${statistics.median(savings):.0f}{RESET}   "
              f"mean: ${statistics.mean(savings):.0f}   "
              f"range: ${min(savings)} to ${max(savings)}")
        pct = 100.0 * cheaper / n
        print()
        if pct >= 80:
            print(f"  {BOLD}-> Skipping PBI/DJT is cheaper {pct:.0f}% of the time.{RESET}")
            print(f"     Lead with the savings. The principle and the price agree.")
        elif pct >= 55:
            print(f"  {BOLD}-> Usually cheaper ({pct:.0f}%), but not reliably.{RESET}")
            print(f"     Say 'often cheaper', show the number, never promise it.")
        else:
            print(f"  {BOLD}-> NOT reliably cheaper ({pct:.0f}%).{RESET}")
            print(f"     Do not sell this on savings. Sell it on choice.")

    if spreads:
        print(f"\n  {BOLD}FLL vs MIA{RESET} -- the choice between substitutes")
        print(f"  Median spread: {BOLD}${statistics.median(spreads):.0f}{RESET}   "
              f"max: ${max(spreads)}   (n={len(spreads)})")
        print(f"  {DIM}Compare against the PBI saving above: whichever is bigger")
        print(f"  is the decision your tool should actually be helping with.{RESET}")
    print(f"\n{'=' * 74}\n")


if __name__ == "__main__":
    main()
