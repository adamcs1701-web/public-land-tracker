"""Tiny stand-in for an ArcGIS feature layer in the DOR schema, for offline tests
and for generating the app's example dataset. All parcels here are invented."""
import json, random, re, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

BOX = {16: (26.00, 26.32, -80.40, -80.10), 23: (25.55, 25.95, -80.45, -80.15), 60: (26.40, 26.90, -80.30, -80.05)}
CITIES = {16: ["FORT LAUDERDALE", "HOLLYWOOD", "POMPANO BEACH"], 23: ["MIAMI", "HIALEAH", "HOMESTEAD"],
          60: ["WEST PALM BEACH", "BOCA RATON", "RIVIERA BEACH"]}
CNAME = {16: "BROWARD COUNTY", 23: "MIAMI-DADE COUNTY", 60: "PALM BEACH COUNTY"}


def build(seed=7, mutate=False):
    rnd, rows, oid = random.Random(seed), [], 0
    for co in (16, 23, 60):
        owners = [(CNAME[co], 86), (CNAME[co], 80), ("CITY OF " + CITIES[co][0], 89), ("CITY OF " + CITIES[co][1], 80),
                  ("SCHOOL BOARD OF " + CNAME[co], 83), ("STATE OF FLORIDA TIITF", 87), ("UNITED STATES OF AMERICA", 88),
                  ("SOUTH FLORIDA WATER MANAGEMENT DISTRICT", 80), (CITIES[co][2] + " HOUSING AUTHORITY", 80),
                  (CNAME[co] + " PARKS", 82), ("CITY OF " + CITIES[co][2], 10),   # miscoded: vacant commercial
                  ("EXAMPLE HOLDINGS LLC", 10), ("EXAMPLE FAMILY TRUST", 1)]
        for i in range(60):
            own, uc = owners[i % len(owners)]
            oid += 1
            la0, la1, lo0, lo1 = BOX[co]
            sqft = int(43560 * rnd.choice([0.15, 0.4, 0.8, 1.2, 2.5, 4, 7, 12, 30]) * rnd.uniform(0.8, 1.2))
            nb = 0 if uc in (80, 10) or rnd.random() < 0.25 else rnd.randint(1, 4)
            lv = int(sqft * rnd.uniform(8, 60))
            rows.append(dict(OBJECTID=oid, PARCEL_ID="EX-%02d-%04d" % (co, i), CO_NO=co, OWN_NAME=own,
                             DOR_UC="%03d" % uc, LND_SQFOOT=sqft, NO_BULDNG=nb, LND_VAL=lv,
                             JV=lv + (0 if nb == 0 else int(lv * rnd.uniform(0.3, 2))),
                             PHY_ADDR1="EXAMPLE PARCEL %d" % i, PHY_CITY=rnd.choice(CITIES[co]),
                             PUBLIC_LND="", ASMNT_YR=2026,
                             _c=dict(x=round(rnd.uniform(lo0, lo1), 5), y=round(rnd.uniform(la0, la1), 5))))
    if mutate:   # simulate a later week: one sale to a private buyer, one new acquisition, one re-coding
        rows[1]["OWN_NAME"], rows[1]["DOR_UC"] = "EXAMPLE DEVELOPER LLC", "010"
        rows[11]["OWN_NAME"], rows[11]["DOR_UC"] = "BROWARD COUNTY", "080"
        rows[60]["DOR_UC"], rows[60]["NO_BULDNG"] = "080", 0
    return rows


def matches(row, where):
    co = int(re.search(r"CO_NO='?(\d+)", where).group(1))
    if row["CO_NO"] != co:
        return False
    codes = set(re.findall(r"'(\d{3})'", where.split("(")[1]))
    if "NOT IN" in where:
        terms = re.findall(r"LIKE '%(.*?)%'", where)
        return row["DOR_UC"] not in codes and any(t in row["OWN_NAME"] for t in terms)
    return row["DOR_UC"] in codes


def serve(rows, port=8765, page_cap=25):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path.endswith("/query") and "geometry" in q:
                lon, lat = map(float, q["geometry"].split(","))
                east = lon > -80.25      # mock city covers the east half; west half is "unincorporated"
                want_city = "/City/" in u.path
                body = dict(features=[dict(attributes={"ZONECODE": "RM-25" if lat > 26.15 else "B-2", "ZONEDESC": "Mock zone"})] if east == want_city else [])
            elif u.path.endswith("/query"):
                hit = [r for r in rows if matches(r, q["where"])]
                off, n = int(q.get("resultOffset", 0)), min(int(q.get("resultRecordCount", 1000)), page_cap)
                page = hit[off:off + n]
                body = dict(features=[dict(attributes={k: v for k, v in r.items() if k != "_c"}, centroid=r["_c"]) for r in page],
                            exceededTransferLimit=off + n < len(hit))
            else:
                body = dict(fields=[dict(name="DOR_UC", type="esriFieldTypeString"), dict(name="CO_NO", type="esriFieldTypeInteger")],
                            editingInfo=dict(dataLastEditDate=1792763246556))
            b = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
