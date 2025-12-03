from __future__ import annotations

import csv
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    SCOPES,
    CREDENTIALS_PATH,
    TOKEN_PATH,
    STATS_SPREADSHEET_ID,
    TEAMS_SPREADSHEET_ID,
    TEAM_RANGES,
    STATS_DIR,
    GAME_CONFIGS,
)


def get_sheets_service():
    """Authenticate with Google Sheets using credentials.json / token.json."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh existing token
            creds.refresh(Request())
        else:
            # Do the OAuth flow in browser
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        TOKEN_PATH.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def export_game_csvs(service):
    """Export all enabled games in GAME_CONFIGS to CSV under STATS_DIR."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    sheets = service.spreadsheets()

    for game in GAME_CONFIGS:
        if not game.get("enabled", True):
            continue

        sheet_range = game["sheet_range"]
        csv_filename = game["csv"]
        csv_path = STATS_DIR / csv_filename

        print(f"Exporting {game['key']} → {csv_path} ({sheet_range})")

        resp = sheets.values().get(
            spreadsheetId=STATS_SPREADSHEET_ID,
            range=sheet_range,
        ).execute()

        values = resp.get("values", [])
        if not values:
            print(f"  [WARN] No data returned for {sheet_range}, skipping.")
            continue

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write values exactly as they come from Sheets
            writer.writerows(values)


def export_team_csv(service, output_path: Path):
    """
    Export team rows from TEAMS_SPREADSHEET_ID + TEAM_RANGES into one CSV.

    Adjust `output_path` if your app expects a specific name/location.
    """
    sheets = service.spreadsheets()
    all_rows: list[list[str]] = []

    for r in TEAM_RANGES:
        print(f"Fetching team range {r}...")
        resp = sheets.values().get(
            spreadsheetId=TEAMS_SPREADSHEET_ID,
            range=r,
        ).execute()
        values = resp.get("values", [])
        all_rows.extend(values)

    if not all_rows:
        print("[WARN] No team rows returned; skipping team CSV.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Exporting teams → {output_path}")

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(all_rows)


def main():
    service = get_sheets_service()
    export_game_csvs(service)

    # 🔧 If your web app uses a different filename for team data,
    # change "teams.csv" here to match.
    export_team_csv(service, STATS_DIR / "teams.csv")

    print("All CSVs updated ✅")


if __name__ == "__main__":
    main()
