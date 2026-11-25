#!/usr/bin/env python3
"""
Huppa API Explore

Brede verkenning van wat de (uitgebreide) Huppa-app aan data aanbiedt:
1. Haalt de Huppa web-app op en trekt alle API-routes uit de JS-bundles.
2. Probeert elke route die met alleen GET en bekende ids aan te roepen is
   (nooit POST/PUT/DELETE; logout/betaal-routes worden overgeslagen).
3. Kijkt in eerdere lessen of het nieuwe 'workouts'-veld gevuld wordt.

De repo is publiek, dus in de Actions-log komt alléén structuur (veldnamen,
types, aantallen) — geen waarden/persoonsgegevens. Volledige responses gaan
naar de gist als 'huppa_explore.json'.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

API = "https://api.huppa.app"
AMS = ZoneInfo("Europe/Amsterdam")
GIST_FILENAME = "huppa_explore.json"
MAX_BUNDLES = 400
MAX_PROBES = 200
SKIP_WORDS = ("logout", "auth/", "password", "impersonat", "stripe", "mollie",
              "payment-link", "checkout", "delete", "cancel", "verify", "export")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("explore")


def shape(value, depth: int = 0, max_depth: int = 3):
    """Structuur van een JSON-waarde zonder de waarden zelf."""
    if isinstance(value, dict):
        if depth >= max_depth:
            return f"{{{len(value)} keys}}"
        return {k: shape(v, depth + 1, max_depth) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return "[]"
        return [f"len={len(value)}", shape(value[0], depth + 1, max_depth)]
    return type(value).__name__


# ── Stap 1: routes uit de web-app ─────────────────────────────

ROUTE_RE = re.compile(r"""[`"'](/(?:[A-Za-z0-9_\-]+|\$\{[^}`]{1,60}\})(?:/(?:[A-Za-z0-9_\-]+|\$\{[^}`]{1,60}\}))*)/?[`"'?]""")
CHUNK_RE = re.compile(r"""["'(/]((?:/?assets/|/?_next/static/|/?js/|\./)[A-Za-z0-9_\-./]+\.js)["')]""")


def extract_routes(subdomain: str) -> tuple[list[str], dict]:
    base = f"https://{subdomain}.huppa.app/"
    meta = {"base": base, "bundles": []}
    try:
        html = requests.get(base, timeout=20).text
    except Exception as e:
        log.error("Web-app niet bereikbaar: %s", e)
        return [], meta
    queue = [urljoin(base, s) for s in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", html)]
    queue += [urljoin(base, s) for s in re.findall(r"""<link[^>]+href=["']([^"']+\.js)["']""", html)]
    seen, routes = set(), set()
    while queue and len(seen) < MAX_BUNDLES:
        url = queue.pop(0)
        if url in seen or "huppa.app" not in url:
            continue
        seen.add(url)
        try:
            js = requests.get(url, timeout=20).text
        except Exception:
            continue
        for m in ROUTE_RE.findall(js):
            norm = re.sub(r"\$\{[^}]*\}", "{id}", m)
            if 2 < len(norm) < 120 and not norm.endswith((".js", ".css", ".png", ".svg")):
                routes.add(norm)
        for c in CHUNK_RE.findall(js):
            queue.append(urljoin(url, c))
    meta["bundles"] = sorted(seen)
    return sorted(routes), meta


# ── Stap 2: probes ────────────────────────────────────────────

def login(s: requests.Session, email, password, subdomain) -> bool:
    s.headers.update({
        "Accept": "application/json", "Content-Type": "application/json",
        "X-Subdomain": subdomain,
        "Origin": f"https://{subdomain}.huppa.app",
        "Referer": f"https://{subdomain}.huppa.app/",
    })
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    return r.status_code == 200


def get(s, path, params=None):
    try:
        r = s.get(f"{API}{path}", params=params, timeout=20)
        try:
            body = r.json()
        except Exception:
            body = r.text[:500]
        return r.status_code, body
    except Exception as e:
        return "error", str(e)


def candidate_paths(routes, ids) -> list[str]:
    """Maak concrete GET-paden van de gevonden routes."""
    out = []
    for r in routes:
        if any(w in r.lower() for w in SKIP_WORDS):
            continue
        # Alleen API-achtige routes (geen front-end pagina's als /login).
        if not re.match(r"^/(users|organizations|me|occurrences|products|memberships|"
                        r"workouts|scores|leaderboards|benchmarks|results|achievements|"
                        r"news|posts|feed|announcements|notifications|check|stats|"
                        r"statistics|activities|trainers|locations|invoices|credits|"
                        r"user|members|challenges|goals|records|exercises|movements|"
                        r"timeline|messages|chats|events)", r):
            continue
        p = r
        p = re.sub(r"(organizations?)/\{id\}", rf"\1/{ids['org']}", p)
        p = re.sub(r"(users?)/\{id\}", rf"\1/{ids['user']}", p)
        if "{id}" in p:
            continue  # onbekende id — niet gokken
        out.append(p)
    return sorted(set(out))


def main():
    email = os.environ["HUPPA_EMAIL"]
    password = os.environ["HUPPA_PASSWORD"]
    subdomain = os.environ["HUPPA_SUBDOMAIN"]

    results = {"generated_at": datetime.now().isoformat(), "routes": [], "probes": {},
               "workouts_samples": {}, "bookings_filters": {}}

    routes, meta = extract_routes(subdomain)
    results["routes"], results["bundle_meta"] = routes, meta
    print("\n" + "=" * 60)
    print(f"ROUTES UIT WEB-APP ({len(routes)} gevonden in {len(meta['bundles'])} bundles)")
    print("=" * 60)
    for r in routes:
        print(f"  {r}")

    s = requests.Session()
    if not login(s, email, password, subdomain):
        log.error("Login mislukt")
        sys.exit(1)
    _, me = get(s, "/users/me")
    me = me if isinstance(me, dict) else {}
    me = me.get("data", me)
    ids = {"user": me.get("id"), "org": me.get("organizationId")}
    print("\n[/users/me STRUCTUUR]")
    print(json.dumps(shape(me), indent=1)[:4000])

    # Bekende + gevonden + gegokte kandidaten
    guesses = [
        "/users/me/products", "/users/me/memberships", "/users/me/credits",
        "/users/me/user-products", "/users/me/check-ins", "/users/me/checkins",
        "/users/me/attendance", "/users/me/statistics", "/users/me/stats",
        "/users/me/workouts", "/users/me/scores", "/users/me/results",
        "/users/me/achievements", "/users/me/badges", "/users/me/goals",
        "/users/me/personal-records", "/users/me/records", "/users/me/benchmarks",
        "/users/me/notifications", "/users/me/invoices", "/users/me/news",
        "/users/me/feed", "/users/me/timeline", "/users/me/history",
        "/users/me/organizations", "/users/me/family", "/users/me/challenges",
        f"/organizations/{ids['org']}/workouts", f"/organizations/{ids['org']}/news",
        f"/organizations/{ids['org']}/leaderboards", f"/organizations/{ids['org']}/benchmarks",
        f"/organizations/{ids['org']}/challenges", f"/organizations/{ids['org']}/posts",
    ]
    paths = sorted(set(candidate_paths(routes, ids) + guesses))[:MAX_PROBES]

    print("\n" + "=" * 60)
    print(f"PROBES ({len(paths)} GET-requests)")
    print("=" * 60)
    for p in paths:
        status, body = get(s, p)
        results["probes"][p] = {"status": status, "body": body}
        label = p.replace(str(ids["org"]), "{org}").replace(str(ids["user"]), "{user}")
        if status == 200:
            print(f"  OK  [200] {label}")
            print("        " + json.dumps(shape(body, max_depth=3))[:700])
        elif status in (400, 422):
            msg = body.get("message") if isinstance(body, dict) else ""
            errs = list((body.get("errors") or {}).keys()) if isinstance(body, dict) else []
            print(f"  --  [{status}] {label}  msg={str(msg)[:150]} velden={errs}")
        elif status != 404:
            print(f"  --  [{status}] {label}")
    n404 = sum(1 for v in results["probes"].values() if v["status"] == 404)
    print(f"  ({n404} routes gaven 404)")

    # Boekingshistorie: welke filters accepteert bookings-and-waitlists?
    print("\n[BOOKINGS-AND-WAITLISTS FILTERS]")
    for f in ("upcoming", "past", "history", "previous", "completed", "attended", "all"):
        status, body = get(s, "/users/me/bookings-and-waitlists", {"filter": f})
        results["bookings_filters"][f] = {"status": status, "body": body}
        n = None
        if status == 200 and isinstance(body, dict):
            n = sum(len(g.get("occurrences", [])) for g in body.get("data", []))
        msg = body.get("message", "") if isinstance(body, dict) and status != 200 else ""
        print(f"  filter={f:10s} [{status}] lessen={n} {str(msg)[:150]}")

    # Workouts-veld: wordt het gevuld bij lessen (afgelopen 14 dagen + komende 3)?
    print("\n[WORKOUTS-VELD PER DAG]")
    today = datetime.now(AMS).date()
    for off in range(-14, 4):
        d = (today + timedelta(days=off)).isoformat()
        status, body = get(s, "/users/me/occurrences", {"date": d})
        if status != 200:
            continue
        items = body if isinstance(body, list) else body.get("data", [])
        filled = [e for e in items if e.get("workouts")]
        print(f"  {d}: {len(items)} lessen, {len(filled)} met workouts")
        if filled and d not in results["workouts_samples"]:
            results["workouts_samples"][d] = filled[0]["workouts"]
            print("        " + json.dumps(shape(filled[0]["workouts"], max_depth=4))[:700])
        if off == 0 and items:
            print("  Velden per les: " + ", ".join(sorted(items[0].keys())))

    # Credits: welke types/tekens bestaan er (geen bedragen per datum loggen).
    print("\n[CREDITS SAMENVATTING]")
    combos, months = {}, {}
    for page in range(1, 6):
        status, body = get(s, "/users/me/credits", {"page": page})
        if status != 200 or not isinstance(body, dict):
            break
        for c in body.get("data", []):
            sign = "+" if (c.get("amount") or 0) > 0 else ("-" if (c.get("amount") or 0) < 0 else "0")
            desc = re.sub(r"\d", "#", str(c.get("description") or ""))[:60]
            k = (c.get("type"), sign, desc, bool(c.get("userMembership")), bool(c.get("userProduct")))
            combos[k] = combos.get(k, 0) + 1
            m = (c.get("createdAt") or "")[:7]
            months[m] = months.get(m, 0) + 1
        if page == 1:
            print("  meta: " + json.dumps({k: body.get("meta", {}).get(k) for k in ("per_page", "total", "last_page")}))
            first = (body.get("data") or [{}])[0]
            print("  userMembership keys: " + str(list((first.get("userMembership") or {}).keys())))
        if not (body.get("links") or {}).get("next"):
            break
    for k, n in sorted(combos.items(), key=lambda x: -x[1]):
        print(f"  type={k[0]} teken={k[1]} membership={k[3]} product={k[4]} n={n}  desc='{k[2]}'")
    print("  per maand: " + json.dumps(dict(sorted(months.items()))))

    # Historie: vorm van een 'past' boeking.
    print("\n[PAST BOOKINGS]")
    status, body = get(s, "/users/me/bookings-and-waitlists", {"filter": "past"})
    if status == 200 and isinstance(body, dict):
        print("  top keys: " + str(list(body.keys())) + " meta=" + json.dumps(body.get("meta"))[:300])
        groups = body.get("data", [])
        print(f"  groepen={len(groups)} datums={[g.get('date') for g in groups][:12]}")
        if groups and groups[0].get("occurrences"):
            occ = groups[0]["occurrences"][0]
            print("  occ keys: " + str(sorted(occ.keys())))
            print("  booking: " + json.dumps(shape(occ.get("booking"), max_depth=2)))
            print("  booking statuses: " + str(sorted({
                str((o.get("booking") or {}).get("status")) for g in groups for o in g.get("occurrences", [])})))
        for p in (2, 3):
            st2, b2 = get(s, "/users/me/bookings-and-waitlists", {"filter": "past", "page": p})
            n2 = sum(len(g.get("occurrences", [])) for g in b2.get("data", [])) if st2 == 200 and isinstance(b2, dict) else None
            print(f"  page={p} [{st2}] lessen={n2} datums={[g.get('date') for g in (b2.get('data', []) if isinstance(b2, dict) else [])][:3]}")
    print(f"\n[/users/me tellers] bookingsThisMonth={me.get('bookingsThisMonth')} totalBooking={me.get('totalBooking')} "
          f"membership={(me.get('activeUserMembership') or {}).get('membershipName')} "
          f"nextCreditDistributionAt={(me.get('activeUserMembership') or {}).get('nextCreditDistributionAt')} "
          f"canSeeWorkouts={me.get('canSeeWorkouts')}")

    gist_id, token = os.environ.get("GIST_ID"), os.environ.get("GITHUB_TOKEN")
    if gist_id and token:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            json={"files": {GIST_FILENAME: {"content": json.dumps(results, indent=2, default=str)}}},
            timeout=30,
        )
        log.info("Gist '%s' opgeslagen: %s", GIST_FILENAME, r.status_code)


if __name__ == "__main__":
    main()
