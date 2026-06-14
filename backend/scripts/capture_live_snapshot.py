"""
Capture a REAL snapshot of the live rail feed, to commit as the rate-limit fallback.

Run this once with a valid API key (e.g. the day before judging):

    cd backend && source .venv/bin/activate
    RAILSETU_RAIL_API_KEY=xxxx RAILSETU_DEMAND_PROVIDER=live \
        python scripts/capture_live_snapshot.py

It writes `fixtures/live_snapshot.json` (real train arrivals for the station).
Commit that file. When the live API later errors or rate-limits, the LiveDemand
provider serves this snapshot instead of the synthetic fixture — so the "live"
view still shows real trains. The API key is NEVER written to the file.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.clients.rail_api import RailApiClient  # noqa: E402
from app.config import get_settings  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "fixtures", "live_snapshot.json")


def main():
    s = get_settings()
    if not s.rail_api_key:
        print("ERROR: set RAILSETU_RAIL_API_KEY (and RAILSETU_DEMAND_PROVIDER=live).")
        sys.exit(1)

    client = RailApiClient(s)
    print(f"Fetching {s.rail_api_source} board for {s.station_code} …")
    if s.rail_api_source == "liveboard":
        records = client.live_station(s.station_code)
        endpoint = "getLiveStation"
    else:
        records = client.trains_by_station(s.station_code)
        endpoint = "getTrainsByStation"

    records = records[: s.live_max_trains]
    if not records:
        print("WARNING: feed returned no records — nothing captured.")
        sys.exit(1)

    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "station": s.station_code,
        "source": s.rail_api_source,
        "endpoint": endpoint,
        "count": len(records),
        "records": records,            # normalised arrivals — NO api key, no secrets
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(snapshot, open(OUT, "w"), indent=2)
    print(f"Wrote {len(records)} trains -> {os.path.abspath(OUT)}")
    print("Commit fixtures/live_snapshot.json so it ships with the deployment.")


if __name__ == "__main__":
    main()
