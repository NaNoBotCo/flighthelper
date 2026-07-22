#!/usr/bin/env python3
"""Data spike: pull cached cheapest fares for the friend's real routes.

This uses the Travelpayouts *Data API* (token-only, no signature). It is fast
and cheap but only returns coarse fields: price, stop count, duration, selling
gate, airline, and a deep link. It does NOT return per-segment baggage, terminal,
or a self-transfer/recheck flag -- that needs the real-time Search API (marker + signature).

Usage:  TP_TOKEN=xxxxx python3 spike_prices.py
"""
import json
import os
import sys
import urllib.request

TOKEN = os.environ.get("TP_TOKEN", "").strip()
ROUTES = [
    ("ABJ", "FCO", "Abidjan -> Rome"),
    ("FCO", "BOM", "Rome -> Mumbai"),
    ("FCO", "CNX", "Rome -> Chiang Mai"),
    ("ABJ", "EBB", "Abidjan -> Entebbe (Uganda)"),
]
BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def fetch(origin, dest):
    q = (
        f"{BASE}?origin={origin}&destination={dest}"
        f"&currency=usd&limit=5&sorting=price&token={TOKEN}"
    )
    with urllib.request.urlopen(q, timeout=30) as r:
        return json.load(r)


def main():
    if not TOKEN:
        sys.exit("Set TP_TOKEN env var with your Travelpayouts API token.")
    for origin, dest, label in ROUTES:
        print(f"\n=== {label}  ({origin} -> {dest}) ===")
        try:
            data = fetch(origin, dest).get("data", [])
        except Exception as e:  # noqa: BLE001
            print(f"  error: {e}")
            continue
        if not data:
            print("  (no cached results)")
            continue
        for x in data:
            print(
                f"  ${x['price']:>5}  {x['transfers']} stop(s)  "
                f"{x['duration']} min  via {x['gate']}  air:{x['airline']}  "
                f"dep {x['departure_at'][:10]}"
            )


if __name__ == "__main__":
    main()
