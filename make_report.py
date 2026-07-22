#!/usr/bin/env python3
"""Generate a shareable HTML flight report for Roberta.

Queries live cached fares (Travelpayouts Data API), scores each route for
comfort, flags likely self-transfer (recheck-bags) itineraries, and writes a
single self-contained roberta_flights.html you can message or AirDrop.

The token is used only while generating -- it is NOT written into the HTML,
so the file is safe to forward to anyone.

Usage:  TP_TOKEN=xxxxx python3 make_report.py
"""
import datetime as dt
import html
import json
import os
import sys
import urllib.request

TOKEN = os.environ.get("TP_TOKEN", "").strip()
BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
OUT = "roberta_flights.html"

ROUTES = [
    ("ABJ", "FCO", "Abidjan", "Rome"),
    ("FCO", "BOM", "Rome", "Mumbai"),
    ("FCO", "CNX", "Rome", "Chiang Mai"),
    ("ABJ", "EBB", "Abidjan", "Entebbe (Uganda)"),
]

# Low-cost carriers that don't fly long-haul on one ticket -> self-transfer smell.
LCC = {"W4", "FR", "U2", "AK", "FD", "QZ", "DY", "VY", "PC", "G9", "6E", "TR"}
VIRTUAL_GATES = {"Kiwi.com", "Kupi.com"}


def fetch(origin, dest):
    q = (f"{BASE}?origin={origin}&destination={dest}"
         f"&currency=usd&limit=10&sorting=price&token={TOKEN}")
    with urllib.request.urlopen(q, timeout=30) as r:
        return json.load(r).get("data", [])


def hm(mins):
    return f"{mins // 60}h {mins % 60:02d}m"


def self_transfer_suspect(opt):
    return (opt.get("gate") in VIRTUAL_GATES
            or (opt["airline"] in LCC and opt["transfers"] >= 2))


def comfort(opt):
    """Return (label, css_class, notes[])."""
    notes = []
    score = 100
    stops = opt["transfers"]
    dur = opt["duration"]
    score -= stops * 14
    if dur > 1500:
        score -= 25
    elif dur > 900:
        score -= 12
    if self_transfer_suspect(opt):
        score -= 30
        notes.append(
            "Looks like separate tickets stitched together. You may have to "
            "collect and re-check your bags between flights \u2014 leave lots of "
            "extra time, and your luggage is not protected if a flight is late."
        )
    if stops >= 3:
        notes.append("Three stops is a long, tiring day of airports.")
    if dur >= 1800:
        notes.append("Over 30 hours door to door.")
    if score >= 78:
        return "Comfortable", "good", notes
    if score >= 55:
        return "Manageable", "ok", notes
    return "Tough trip", "bad", notes


def book_url(opt):
    link = opt.get("link", "")
    if link.startswith("/"):
        return "https://www.aviasales.com" + link
    return "https://www.aviasales.com/search/" + opt["origin"] + opt["destination"] + "1"


def pick(opts):
    """Cheapest, and comfiest (fewest stops then shortest) if different."""
    cheapest = min(opts, key=lambda o: o["price"])
    comfiest = min(opts, key=lambda o: (o["transfers"], o["duration"]))
    out = [("Cheapest", cheapest)]
    if comfiest is not cheapest and (comfiest["transfers"] < cheapest["transfers"]
                                     or comfiest["duration"] < cheapest["duration"]):
        out.append(("Comfiest", comfiest))
    return out


def card_html(o_code, d_code, o_name, d_name, opts):
    if not opts:
        return (f'<section class="route"><h2>{html.escape(o_name)} '
                f'&rarr; {html.escape(d_name)}</h2>'
                f'<p class="none">No fares found right now.</p></section>')
    rows = []
    for tag, o in pick(opts):
        label, cls, notes = comfort(o)
        note_html = "".join(
            f'<p class="note">{html.escape(n)}</p>' for n in notes)
        rows.append(f"""
        <div class="opt">
          <div class="opt-head">
            <span class="tag {('cheap' if tag=='Cheapest' else 'comfy')}">{tag}</span>
            <span class="price">${o['price']}</span>
          </div>
          <div class="facts">
            <span>{o['transfers']} stop{'s' if o['transfers']!=1 else ''}</span>
            <span>{hm(o['duration'])} total</span>
            <span>dep {html.escape(str(o['departure_at'])[:10])}</span>
          </div>
          <div class="comfort {cls}">{label}</div>
          {note_html}
          <a class="book" href="{html.escape(book_url(o))}" target="_blank"
             rel="noopener">See live prices &amp; book &rarr;</a>
        </div>""")
    return (f'<section class="route"><h2>{html.escape(o_name)} '
            f'&rarr; {html.escape(d_name)} '
            f'<small>{o_code}&ndash;{d_code}</small></h2>'
            + "".join(rows) + "</section>")


def build(sections):
    today = dt.date.today().strftime("%d %B %Y")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flights for Roberta</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: #f4f6fb; color: #14203a;
    font-size: 19px; line-height: 1.5;
  }}
  .wrap {{ max-width: 640px; margin: 0 auto; padding: 22px 18px 60px; }}
  header h1 {{ font-size: 30px; margin: 8px 0 4px; }}
  header p {{ margin: 0 0 4px; color: #56607a; }}
  .route {{ background: #fff; border-radius: 16px; padding: 18px 18px 8px;
    margin: 20px 0; box-shadow: 0 2px 10px rgba(20,32,58,.06); }}
  .route h2 {{ font-size: 23px; margin: 0 0 6px; }}
  .route h2 small {{ font-size: 15px; color: #8b93a7; font-weight: 500; }}
  .opt {{ border-top: 1px solid #eef0f6; padding: 14px 0; }}
  .opt:first-of-type {{ border-top: none; }}
  .opt-head {{ display: flex; align-items: center; justify-content: space-between; }}
  .tag {{ font-size: 13px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; padding: 3px 9px; border-radius: 999px; }}
  .tag.cheap {{ background: #e6f4ea; color: #1f7a3f; }}
  .tag.comfy {{ background: #e7eefc; color: #2456c7; }}
  .price {{ font-size: 27px; font-weight: 800; }}
  .facts {{ display: flex; flex-wrap: wrap; gap: 14px; color: #56607a;
    font-size: 16px; margin: 8px 0; }}
  .comfort {{ display: inline-block; font-weight: 700; padding: 4px 12px;
    border-radius: 999px; font-size: 16px; }}
  .comfort.good {{ background: #e6f4ea; color: #1f7a3f; }}
  .comfort.ok {{ background: #fdf3e0; color: #9a6b13; }}
  .comfort.bad {{ background: #fce8e6; color: #b3261e; }}
  .note {{ background: #fff7f6; border-left: 4px solid #e2645a;
    padding: 10px 12px; border-radius: 8px; margin: 10px 0 0;
    font-size: 16px; color: #7a2c25; }}
  .book {{ display: inline-block; margin-top: 12px; font-weight: 700;
    color: #2456c7; text-decoration: none; }}
  .book:hover {{ text-decoration: underline; }}
  footer {{ color: #8b93a7; font-size: 14px; margin-top: 30px; text-align: center; }}
  .none {{ color: #8b93a7; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>Flights for Roberta \u2708\ufe0f</h1>
    <p>Comfort-first picks on your usual routes.</p>
    <p><strong>Prices as of {today}</strong> \u2014 they move around, so treat these
    as a snapshot. Tap a route to see live fares.</p>
  </header>
  {''.join(sections)}
  <footer>A preview of the flight helper we're building for you.<br>
  Comfort scores flag long layovers, too many stops, and "self-transfer"
  trips where you'd have to re-check your bags.</footer>
</div></body></html>"""


def main():
    if not TOKEN:
        sys.exit("Set TP_TOKEN env var with your Travelpayouts API token.")
    sections = []
    for o_code, d_code, o_name, d_name in ROUTES:
        try:
            opts = fetch(o_code, d_code)
        except Exception as e:  # noqa: BLE001
            print(f"  {o_code}->{d_code} error: {e}", file=sys.stderr)
            opts = []
        sections.append(card_html(o_code, d_code, o_name, d_name, opts))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(sections))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
