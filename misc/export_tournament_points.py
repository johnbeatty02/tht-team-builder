from __future__ import print_function
import os
import csv
from typing import List, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import matplotlib.pyplot as plt

# =============== CONFIG =====================

SPREADSHEET_ID = "1fDhrscuouut9EGtytYyy3xrULqH0L8_gMHz3iSK7Vtc"

# Auto-generate plots when you hit Run
PLOT_ENABLED = True

OUTPUT_CSV = "tournament_points.csv"

# Colors for each team
TEAM_COLORS = {
    "Red":    "#FF4C4C",
    "Yellow": "#FFD93D",
    "Green":  "#4CAF50",
    "Blue":   "#4C77FF",
    None:     "gray",
}

# Sheets API scope
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# =============================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))

CREDENTIALS_PATH = os.path.join(PARENT_DIR, "credentials.json")
TOKEN_PATH = os.path.join(PARENT_DIR, "token.json")
OUTPUT_PATH = os.path.join(BASE_DIR, OUTPUT_CSV)

GAMES_DIR = os.path.join(BASE_DIR, "games")
PLAYERS_DIR = os.path.join(BASE_DIR, "players")
os.makedirs(GAMES_DIR, exist_ok=True)
os.makedirs(PLAYERS_DIR, exist_ok=True)


# -----------------------------------------------------------
# GOOGLE API SERVICE
# -----------------------------------------------------------
def get_service():
    """Authorize and return the Google Sheets API service."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_PATH}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def get_spreadsheet_title(service) -> str:
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()
    return meta["properties"]["title"]


def sanitize_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join(c for c in name if c not in bad).strip() or "file"


# -----------------------------------------------------------
# READ GAME SHEETS + TEAM DETECTION
# -----------------------------------------------------------
def extract_points_from_sheet(
    service, spreadsheet_id: str, sheet_title: str
) -> List[Tuple[str, str, float, str]]:
    """
    Returns list of tuples:
      (player, game, points, team)

    Detects team using header rows like "Red Team:", "Yellow Team:", etc.
    Only reads A1:Z50 to avoid junk tables below.
    """
    game_name = sheet_title
    range_name = f"'{sheet_title}'!A1:Z50"

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    values = result.get("values", [])

    if not values:
        return []

    headers = values[0] if values else []

    # --- Handle completely empty/short header rows safely ---
    if not headers:
        print(f"WARNING: Empty header row in sheet {sheet_title}, skipping.")
        return []

    # Detect initial team in row 1 if header is like "Red Team:"
    first_cell_raw = headers[0] if len(headers) > 0 else ""
    first_cell = first_cell_raw.strip().lower() if first_cell_raw else ""
    if first_cell.startswith("red team"):
        current_team = "Red"
    elif first_cell.startswith("yellow team"):
        current_team = "Yellow"
    elif first_cell.startswith("green team"):
        current_team = "Green"
    elif first_cell.startswith("blue team"):
        current_team = "Blue"
    else:
        current_team = None

    # Find "Total Points:" column anywhere in header row
    points_col = None
    for i, h in enumerate(headers):
        if h and h.strip().lower() == "total points:".lower():
            points_col = i
            break

    if points_col is None:
        print(f"WARNING: No 'Total Points:' column in sheet {sheet_title}")
        return []

    player_col = 0
    output: List[Tuple[str, str, float, str]] = []

    # Now iterate rows AFTER header row
    for row in values[1:]:
        if not row:
            continue

        first_cell_in_row_raw = row[0] if len(row) > 0 else ""
        first_cell_in_row = first_cell_in_row_raw.strip().lower() if first_cell_in_row_raw else ""

        # Team headers in later rows
        if first_cell_in_row.startswith("red team"):
            current_team = "Red"
            continue
        if first_cell_in_row.startswith("yellow team"):
            current_team = "Yellow"
            continue
        if first_cell_in_row.startswith("green team"):
            current_team = "Green"
            continue
        if first_cell_in_row.startswith("blue team"):
            current_team = "Blue"
            continue

        # Skip lines that are just some kind of team label
        if "team" in first_cell_in_row:
            continue

        if len(row) <= max(player_col, points_col):
            continue

        player_cell = row[player_col] if player_col < len(row) else ""
        points_cell = row[points_col] if points_col < len(row) else ""

        player_name = player_cell.strip() if player_cell else ""
        points_str = points_cell.strip() if points_cell else ""

        if not player_name or not points_str:
            continue

        try:
            points_val = float(points_str)
        except ValueError:
            # e.g., "#REF!" or text
            continue

        output.append((player_name, game_name, points_val, current_team))

    return output


# -----------------------------------------------------------
# FILTER GAMES WITH TOO MANY ZERO SCORES
# -----------------------------------------------------------
def filter_games_with_too_many_zeros(
    rows: List[Tuple[str, str, float, str]],
    max_zero_players: int = 6,
) -> List[Tuple[str, str, float, str]]:
    """
    Remove entire games where more than `max_zero_players` players have 0 points.
    """
    from collections import defaultdict

    zero_counts = defaultdict(int)

    for player, game, points, team in rows:
        if points == 0:
            zero_counts[game] += 1

    games_to_remove = {g for g, cnt in zero_counts.items() if cnt > max_zero_players}

    if games_to_remove:
        print("Removing games due to too many zero-point players:")
        for g in games_to_remove:
            print(f"  - {g} (zero players: {zero_counts[g]})")

    filtered = [r for r in rows if r[1] not in games_to_remove]
    return filtered


# -----------------------------------------------------------
# CSV EXPORT
# -----------------------------------------------------------
def write_csv(rows: List[Tuple[str, str, float, str]]) -> List[Tuple[str, str, float, str]]:
    rows_sorted = sorted(rows, key=lambda x: x[2], reverse=True)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Player", "Game", "Points", "Team"])
        for r in rows_sorted:
            w.writerow(r)

    print(f"Wrote CSV: {OUTPUT_PATH}")
    return rows_sorted


# -----------------------------------------------------------
# PLOTTING UTILITIES
# -----------------------------------------------------------
def plot_chart(
    rows: List[Tuple[str, str, float, str]],
    title: str,
    output_path: str,
    label_mode: str = "player",
):
    """
    Generic bar chart.

    rows: list of (player, game, points, team)
    label_mode:
        "player" -> labels above bars are player names
        "game"   -> labels above bars are game names
    """

    if not rows:
        return

    rows_sorted = sorted(rows, key=lambda x: x[2], reverse=True)

    players = [r[0] for r in rows_sorted]
    games = [r[1] for r in rows_sorted]
    points = [r[2] for r in rows_sorted]
    teams = [r[3] for r in rows_sorted]

    colors = [TEAM_COLORS.get(t, "gray") for t in teams]

    fig, ax = plt.subplots(figsize=(max(10, len(rows_sorted) * 0.4), 6))

    x = range(len(rows_sorted))
    bars = ax.bar(x, points, color=colors)

    ax.set_ylabel("Points")
    ax.set_title(title)
    ax.set_xticks([])

    # Determine label above each bar
    if label_mode == "player":
        labels = players
    else:  # "game"
        labels = games

    for bar, label in zip(bars, labels):
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            h,
            label,
            ha="center",
            va="bottom",
            rotation=45,
            fontsize=8,
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved plot: {output_path}")


def plot_overall(rows: List[Tuple[str, str, float, str]], spreadsheet_title: str):
    safe_title = sanitize_filename(spreadsheet_title)
    png_path = os.path.join(BASE_DIR, f"{safe_title}.png")
    plot_chart(rows, spreadsheet_title, png_path, label_mode="player")


def plot_per_game(rows: List[Tuple[str, str, float, str]], spreadsheet_title: str):
    from collections import defaultdict

    rows_by_game = defaultdict(list)
    for r in rows:
        rows_by_game[r[1]].append(r)

    safe_title = sanitize_filename(spreadsheet_title)

    for game, game_rows in rows_by_game.items():
        safe_game = sanitize_filename(game)
        png_path = os.path.join(GAMES_DIR, f"{safe_title} - {safe_game}.png")
        title = f"{spreadsheet_title} - {game}"
        plot_chart(game_rows, title, png_path, label_mode="player")


def plot_per_player(rows: List[Tuple[str, str, float, str]], spreadsheet_title: str):
    from collections import defaultdict

    rows_by_player = defaultdict(list)
    for r in rows:
        rows_by_player[r[0]].append(r)

    safe_title = sanitize_filename(spreadsheet_title)

    for player, player_rows in rows_by_player.items():
        safe_player = sanitize_filename(player)
        png_path = os.path.join(PLAYERS_DIR, f"{safe_title} - {safe_player}.png")
        title = f"{spreadsheet_title} - {player}"
        # For per-player charts, show gamemode names above bars
        plot_chart(player_rows, title, png_path, label_mode="game")


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------
def main():
    service = get_service()
    sheet_title = get_spreadsheet_title(service)
    print(f"Spreadsheet title: {sheet_title}")

    metadata = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()

    all_rows: List[Tuple[str, str, float, str]] = []

    for sheet in metadata["sheets"]:
        name = sheet["properties"]["title"]
        print(f"Processing sheet: {name}")
        rows = extract_points_from_sheet(service, SPREADSHEET_ID, name)
        all_rows.extend(rows)

    # Remove games with > 6 zero-point players
    filtered_rows = filter_games_with_too_many_zeros(all_rows, max_zero_players=6)

    # Write CSV
    sorted_rows = write_csv(filtered_rows)

    # Plots
    if PLOT_ENABLED:
        plot_overall(sorted_rows, sheet_title)
        plot_per_game(sorted_rows, sheet_title)
        plot_per_player(sorted_rows, sheet_title)


if __name__ == "__main__":
    main()
