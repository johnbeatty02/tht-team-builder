from __future__ import annotations

import csv
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    SCOPES,
    CREDENTIALS_PATH,
    TOKEN_PATH,
    STATS_SPREADSHEET_ID,
    STATS_DIR,
    GAME_CONFIGS,
    CSV_COLUMNS,
)


def get_sheets_service():
    """Build and return an authorized Google Sheets API service."""
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("sheets", "v4", credentials=creds)


def fetch_range(service, range_name: str) -> List[List[str]]:
    """Fetch a 2-column range (Player, Points) from the stats sheet."""
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=STATS_SPREADSHEET_ID,
        range=range_name,
    ).execute()

    values = result.get("values", [])
    if not values:
        return []
    return values


def export_game(service, game: dict) -> None:
    """Export one gamemode's stats to CSV."""
    range_name = game["sheet_range"]
    csv_name = game["csv_name"]
    label = game.get("long_label", game["name"])

    print(f"Exporting {label} → {csv_name} ({range_name})")

    try:
        values = fetch_range(service, range_name)
    except HttpError as err:
        print(f"[ERROR] Could not fetch {label}: {err}")
        return

    if not values:
        print(f"[WARN] No data found for {label}")
        return

    STATS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = STATS_DIR / csv_name
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)

        for row in values:
            row = (row + [""] * len(CSV_COLUMNS))[:2]
            player = row[0].strip()
            points = row[1].strip()
            if not player or player.startswith("#"):
                continue
            writer.writerow((player, points))

    print(f"  → wrote {csv_path}")


def main() -> None:
    service = get_sheets_service()

    for game in GAME_CONFIGS:
        if not game.get("enabled", True):
            continue
        export_game(service, game)

    print("\nAll stats exported to:", STATS_DIR)


if __name__ == "__main__":
    main()
