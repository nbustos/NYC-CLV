#!/usr/bin/env python3
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
import requests

BASE_URL = "https://webapi.legistar.com/v1/nyc"
TOKEN = os.environ.get("LEGISTAR_TOKEN", "").strip()
YEAR = os.environ.get("TARGET_YEAR", "2026")

# Map Council Member last names / full names to District IDs (1-51)
LAST_NAME_TO_DISTRICT = {
    "Marte": 1, "Harvey": 2, "Bottcher": 3, "Maloney": 4, "Menin": 5,
    "Brewer": 6, "Abreu": 7, "Elsayed": 8, "Salaam": 9, "De La Rosa": 10,
    "Dinowitz": 11, "Riley": 12, "farias": 13, "Farías": 13, "Sanchez": 14,
    "Feliz": 15, "Stevens": 16, "Encarnacion": 17, "utano": 18, "Paladino": 19,
    "Ung": 20, "Shanks": 21, "Cabán": 22, "Caban": 22, "Lee": 23,
    "Gennaro": 24, "Krishnan": 25, "Won": 26, "Williams": 27, "Singh": 28,
    "Schulman": 29, "wong": 30, "Brooks-Powers": 31, "Ariola": 32, "Restler": 33,
    "Gutiérrez": 34, "Gutierrez": 34, "Hudson": 35, "Osse": 36, "Ossé": 36,
    "Nurse": 37, "Avilés": 38, "Aviles": 38, "Hanif": 39, "Joseph": 40,
    "Mealy": 41, "Banks": 42, "Zhuang": 43, "Tischler": 44, "Louis": 45,
    "Narcisse": 46, "Santosuosso": 47, "Vernikov": 48, "Hanks": 49,
    "Carr": 50, "Morano": 51
}

def api_get(endpoint, params=None):
    params = params or {}
    if TOKEN:
        params["token"] = TOKEN
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def _fold(text):
    """Lowercase and strip accents so 'Farías' == 'farias'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()

# Match the surname at the end of the name, so "Joseph" in "Joseph Borelli" or "Lee" in "Fleetwood" can't hit.
_PATTERNS = [(re.compile(r"\b" + re.escape(_fold(k)) + r"$"), d) for k, d in LAST_NAME_TO_DISTRICT.items()]
# Non-voting Public Advocate shares a surname with District 27's member
NOT_DISTRICT_MEMBERS = ("jumaane",)
UNMATCHED = set()

def match_district(person_name):
    name = re.sub(r"\s+(jr|sr|ii|iii)\.?$", "", _fold(person_name).strip())
    if any(n in name for n in NOT_DISTRICT_MEMBERS):
        return None
    for pat, dist_id in _PATTERNS:
        if pat.search(name):
            return dist_id
    UNMATCHED.add(person_name)
    return None

def map_vote_value(val_str):
    if not val_str:
        return "excused"
    v = val_str.lower()
    if "affirmative" in v or v == "yes":
        return "yes"
    if "negative" in v or v == "no":
        return "no"
    return "excused"

def main():
    # 1. Fetch City Council Stated Meetings (BodyId 1 is City Council) for the target year
    odata_filter = (
        f"EventBodyId eq 1 and "
        f"EventDate ge datetime'{YEAR}-01-01' and "
        f"EventDate le datetime'{YEAR}-12-31'"
    )
    events = api_get("events", {"$filter": odata_filter, "$orderby": "EventDate asc"})
    
    bills_output = []
    
    for ev in events:
        event_id = ev["EventId"]
        event_date = ev["EventDate"][:10] # YYYY-MM-DD
        items = api_get(f"events/{event_id}/eventitems")
        
        for item in items:
            # Filter strictly for approved legislation that had a roll call vote
            if item.get("EventItemPassedFlag") == 1 and item.get("EventItemRollCallFlag") == 1:
                matter_file = item.get("EventItemMatterFile") or ""
                if not matter_file.startswith(("Int", "Res")):
                    continue
                
                event_item_id = item["EventItemId"]
                raw_votes = api_get(f"eventitems/{event_item_id}/votes")
                if not raw_votes:
                    continue
                
                district_votes = {}
                for v in raw_votes:
                    person_name = v.get("VotePersonName", "")
                    dist_id = match_district(person_name)
                    if dist_id:
                        district_votes[str(dist_id)] = map_vote_value(v.get("VoteValueName"))
                
                if district_votes:
                    bills_output.append({
                        "id": matter_file,
                        "date": event_date,
                        "title": item.get("EventItemMatterName") or item.get("EventItemTitle") or matter_file,
                        "category": item.get("EventItemMatterType") or "Legislation",
                        "summary": item.get("EventItemTitle") or "",
                        "legistarUrl": f"https://legistar.council.nyc.gov/LegislationDetail.aspx?ID={item.get('EventItemMatterId')}&GUID=",
                        "votes": district_votes
                    })

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / "votes.json", "w", encoding="utf-8") as f:
        json.dump(bills_output, f, indent=2, ensure_ascii=False)
    if UNMATCHED:
        print("WARNING: no district for:", ", ".join(sorted(UNMATCHED)), file=sys.stderr)
    print(f"Saved {len(bills_output)} approved bills to data/votes.json")

if __name__ == "__main__":
    main()
