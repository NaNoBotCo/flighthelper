#!/usr/bin/env python3
"""Probe: does this account actually have real-time Flight Search API access?

The Data API (spike_avoid.py) can't answer the airport-avoidance question --
its cached fares are far too sparse for a thinly-searched airport like PBI, and
sparse-baseline bias makes the tool argue for avoidance out of missing data.
Live search is the fix. This checks whether we're allowed to call it.

Three outcomes we're distinguishing:
  1. search_id returned      -> access GRANTED, build on this.
  2. signature/auth error    -> our signature math is wrong (fixable here).
  3. 403 / not-allowed       -> access must be APPLIED for. Different problem.

Signature = md5(token : marker : <all param values, keys sorted alphabetically>)
Nested objects sort their own keys; arrays keep order. The marker appears twice
on purpose -- once as prefix, once in its alphabetical slot.

Usage:  python3 probe_search_api.py
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "749581"
SEARCH_URL = "https://api.travelpayouts.com/v1/flight_search"
RESULTS_URL = "https://api.travelpayouts.com/v1/flight_search_results?uuid="


def get_token():
    tok = os.environ.get("TP_TOKEN", "").strip()
    if tok:
        return tok
    path = os.path.join(HERE, ".tp_token")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    sys.exit("No token found (TP_TOKEN or flighthelper/.tp_token)")


def sig_values(obj):
    """Flatten to signature-ordered values: dicts sort keys, lists keep order."""
    if isinstance(obj, dict):
        out = []
        for k in sorted(obj):
            out.extend(sig_values(obj[k]))
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(sig_values(item))
        return out
    return [str(obj)]


def build_request(token, origin, dest, date_str):
    params = {
        "marker": MARKER,
        "host": "flighthelper.local",
        "user_ip": "127.0.0.1",
        "locale": "en",
        "trip_class": "Y",
        "passengers": {"adults": 1, "children": 0, "infants": 0},
        "segments": [{"origin": origin, "destination": dest, "date": date_str}],
    }
    values = sig_values(params)
    base = f"{token}:{MARKER}:" + ":".join(values)
    signature = hashlib.md5(base.encode()).hexdigest()
    # Show the base string with the token masked, so a signature mismatch is debuggable.
    print(f"  signature base: <TOKEN>:{MARKER}:" + ":".join(values))
    print(f"  signature:      {signature}")
    return {**params, "signature": signature}


def post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.status, json.load(r)


def main():
    token = get_token()
    origin, dest, date_str = "PBI", "JFK", "2026-09-15"

    print()
    print("=" * 72)
    print("  FLIGHT SEARCH API ACCESS PROBE")
    print(f"  marker {MARKER}   {origin} -> {dest}   {date_str}")
    print("=" * 72)
    print()

    body = build_request(token, origin, dest, date_str)
    print()

    try:
        status, data = post(SEARCH_URL, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        print(f"  RESULT: HTTP {e.code}")
        print(f"  {detail}")
        print()
        if e.code == 403:
            print("  -> Looks like ACCESS NOT GRANTED. This needs an application,")
            print("     not a code fix.")
        elif e.code in (400, 401):
            print("  -> Auth/signature rejected. Compare the base string above")
            print("     against the docs' ordering rules.")
        print()
        return
    except Exception as e:  # noqa: BLE001
        print(f"  RESULT: request failed -- {e}")
        print()
        return

    print(f"  RESULT: HTTP {status}")
    search_id = data.get("search_id") if isinstance(data, dict) else None
    if not search_id:
        print(f"  No search_id. Raw response:\n  {json.dumps(data)[:600]}")
        print()
        return

    print(f"  search_id: {search_id}")
    print("  -> ACCESS GRANTED. Polling for results...")
    print()

    for attempt in range(1, 9):
        time.sleep(3)
        try:
            with urllib.request.urlopen(RESULTS_URL + search_id, timeout=45) as r:
                chunks = json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"  poll {attempt}: failed -- {e}")
            continue

        proposals = []
        for chunk in chunks if isinstance(chunks, list) else [chunks]:
            proposals.extend(chunk.get("proposals") or [])
        print(f"  poll {attempt}: {len(proposals)} proposals")

        if proposals:
            p = proposals[0]
            print()
            print("  --- first proposal, structure check ---")
            print(f"  top-level keys: {sorted(p.keys())}")
            for seg_i, seg in enumerate(p.get("segment") or []):
                for f in seg.get("flight") or []:
                    print(f"    seg{seg_i}: {f.get('departure')} -> {f.get('arrival')}  "
                          f"{f.get('operating_carrier')}{f.get('number')}  "
                          f"delay={f.get('delay')}")
            print()
            print("  KEY QUESTION -- can we see connection airports? "
                  f"{'YES' if (p.get('segment') or [{}])[0].get('flight') else 'NO'}")
            print()
            out = os.path.join(HERE, "search_api_sample.json")
            with open(out, "w") as f:
                json.dump(proposals[:3], f, indent=2)
            print(f"  Saved 3 sample proposals -> {out}")
            print()
            return

    print("  Polling finished with no proposals (search may have found nothing).")
    print()


if __name__ == "__main__":
    main()
