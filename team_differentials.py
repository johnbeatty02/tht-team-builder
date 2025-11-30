from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Set

import csv
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    SCOPES,
    CREDENTIALS_PATH,
    TOKEN_PATH,
    TEAMS_SPREADSHEET_ID,
    TEAM_RANGES,
    STATS_DIR,
    TEAM_GRAPHICS_DIR,
    GAME_CONFIGS,
    NON_PVP_GAMES,
    TEAM_COLORS,
    TEAM_COLOR_NAMES,
    FINAL_REPORT_PATH,
    FINAL_REPORT_DIR,
    FINAL_REPORT_FILENAME
)
import stats  # your stats exporter (stats.py)
import team_graphics


# Pillow resampling (handles new + older versions)
try:
    Resampling = Image.Resampling
except AttributeError:  # older Pillow
    class _Resampling:
        LANCZOS = Image.LANCZOS
    Resampling = _Resampling()


# ============================================================
# GOOGLE SHEETS HELPERS (for teams)
# ============================================================

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


def fetch_team_from_sheet(service, range_name: str) -> Tuple[str, List[str]]:
    """
    Fetch team name and 4 players from a column range like Main!A35:A39.

    Row 1: 'Red Team'
    Row 2–5: player IGN.
    """
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=TEAMS_SPREADSHEET_ID,
        range=range_name,
    ).execute()

    values = result.get("values", [])
    if len(values) < 5:
        raise ValueError(f"Expected at least 5 rows in {range_name}, got {len(values)}")

    team_name = values[0][0].strip()
    players = [row[0].strip() for row in values[1:5]]
    return team_name, players


@dataclass
class Team:
    name: str
    players: List[str]
    color_name: str  # 'red', 'gold', 'green', 'blue'


def load_teams_from_sheet() -> List[Team]:
    service = get_sheets_service()

    teams: List[Team] = []
    for idx, rng in enumerate(TEAM_RANGES):
        name, players = fetch_team_from_sheet(service, rng)
        color_name = TEAM_COLOR_NAMES[idx % len(TEAM_COLOR_NAMES)]
        teams.append(Team(name=name, players=players, color_name=color_name))

    return teams


# ============================================================
# STATS LOADING
# ============================================================

def load_game_stats(
    csv_path: Path,
    playing_players: List[str],
    game_label: str,
    global_subs: Dict[str, str],
    global_ignored: Set[str],
) -> Dict[str, float]:
    """
    Load a CSV of form: Player,Points → dict[player] = float(points).
    Handle missing players by prompting for subs / ignore.

    Behavior:
      - If player already in global_subs, use that sub's points if available,
        otherwise 0.0 (still counted as a player).
      - If player in global_ignored, skip them entirely (no entry).
      - If player missing and not in the above:
          - Ask for a replacement IGN present in this CSV, or Enter for no sub.
          - If sub given and valid → ask if it should be reused for ALL gamemodes.
              - If yes → store in global_subs and reuse silently later.
              - If no  → only used for this game.
          - If Enter → player is globally ignored (for all games).
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing stats file: {csv_path}")

    base_stats: Dict[str, float] = {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        # Skip header
        try:
            next(reader)
        except StopIteration:
            return {}

        for row in reader:
            if not row:
                continue
            player = row[0].strip()
            pts_str = row[1].strip() if len(row) > 1 else ""

            if not player or player.startswith("#") or pts_str.startswith("#"):
                continue

            pts_str_clean = pts_str.replace(",", "")
            try:
                pts_val = float(pts_str_clean) if pts_str_clean else 0.0
            except ValueError:
                continue

            base_stats[player] = pts_val

    stats_for_game: Dict[str, float] = {}

    for player in playing_players:
        # If globally ignored, skip entirely
        if player in global_ignored:
            continue

        # Known global sub?
        if player in global_subs:
            sub = global_subs[player]
            if sub in base_stats:
                stats_for_game[player] = base_stats[sub]
            else:
                print(
                    f"[WARN] Global sub '{sub}' for '{player}' has no stats in "
                    f"{csv_path.name} ({game_label}); using 0.0."
                )
                stats_for_game[player] = 0.0
            continue

        # Direct stats available?
        if player in base_stats:
            stats_for_game[player] = base_stats[player]
            continue

        # Missing player → interactive resolution
        print(
            f"\n[WARN] Player '{player}' is missing in {csv_path.name} "
            f"({game_label})."
        )

        while True:
            replacement = input(
                f"Enter a replacement IGN whose stats to use for '{player}' "
                f"(must exist in {csv_path.name}),\n"
                f"or press Enter to IGNORE '{player}' in ALL gamemodes: "
            ).strip()

            if not replacement:
                # Ignore this player globally
                global_ignored.add(player)
                print(
                    f"  → '{player}' will be ignored in ALL gamemodes; "
                    f"averages will rely on remaining teammates."
                )
                break

            if replacement not in base_stats:
                print(
                    f"[ERROR] '{replacement}' not found in {csv_path.name}. "
                    "Try again or press Enter to ignore."
                )
                continue

            pts_val = base_stats[replacement]
            stats_for_game[player] = pts_val

            use_global = input(
                f"Use '{replacement}' as a sub for '{player}' in ALL gamemodes? [y/N]: "
            ).strip().lower()

            if use_global.startswith("y"):
                global_subs[player] = replacement
                print(
                    f"  → Using '{replacement}' as a global sub for '{player}' "
                    f"in all gamemodes."
                )
            else:
                print(
                    f"  → Using '{replacement}' as a sub for '{player}' in "
                    f"{game_label} only."
                )

            break

    return stats_for_game


# ============================================================
# CORE CALCULATION
# ============================================================

def diff_games() -> List[dict]:
    """Games included in the per-game and differential graphs."""
    return [g for g in GAME_CONFIGS if g.get("include_in_differentials", False)]


def compute_team_totals_and_counts(
    teams: List[Team],
    games: List[dict],
    per_game_stats: Dict[str, Dict[str, float]],
) -> Tuple[Dict[str, List[float]], Dict[str, List[int]], Dict[str, float]]:
    """
    For each game, compute:
      - team_totals[game_key][team_idx] = sum of points for players with stats
      - team_counts[game_key][team_idx] = #players with stats (after subs/ignores)
      - game_team_averages[game_key]    = mean team total for that game
    """
    team_totals: Dict[str, List[float]] = {}
    team_counts: Dict[str, List[int]] = {}
    game_team_averages: Dict[str, float] = {}

    for game in games:
        key = game["key"]
        stats_for_game = per_game_stats[key]

        totals_for_game: List[float] = []
        counts_for_game: List[int] = []

        for team in teams:
            total = 0.0
            count = 0
            for player in team.players:
                if player in stats_for_game:
                    total += stats_for_game[player]
                    count += 1
            totals_for_game.append(total)
            counts_for_game.append(count)

        team_totals[key] = totals_for_game
        team_counts[key] = counts_for_game
        game_team_averages[key] = float(np.mean(totals_for_game))

    return team_totals, team_counts, game_team_averages


def compute_per_player_averages(
    games: List[dict],
    team_totals: Dict[str, List[float]],
    team_counts: Dict[str, List[int]],
) -> Dict[str, List[float]]:
    """
    Per-game, per-team averages used for the "allGames" grid.

    - Most games: avg = team_total / #players_with_stats
    - Non-PvP aggregate: avg = team_total / (#players_with_stats * NON_PVP_GAMES)
    - If a team has 0 players with stats for a game, average is 0.
    """
    per_player_avgs: Dict[str, List[float]] = {}

    for game in games:
        key = game["key"]
        totals = team_totals[key]
        counts = team_counts[key]

        is_non_pvp_agg = game.get("is_non_pvp_aggregate", False)

        avgs_for_game: List[float] = []
        for total, count in zip(totals, counts):
            if count == 0:
                avgs_for_game.append(0.0)
                continue

            denom = count * NON_PVP_GAMES if is_non_pvp_agg else count
            avgs_for_game.append(round(total / denom, 2))

        per_player_avgs[key] = avgs_for_game

    return per_player_avgs


def compute_differentials(
    games: List[dict],
    team_totals: Dict[str, List[float]],
    game_team_averages: Dict[str, float],
) -> Dict[int, List[float]]:
    """
    For each team index (0..3), compute a list of differentials:
        differential = team_total_for_game - average_team_total_for_game
    """
    team_count = len(next(iter(team_totals.values())))
    diffs: Dict[int, List[float]] = {i: [] for i in range(team_count)}

    for game in games:
        key = game["key"]
        totals = team_totals[key]
        avg_total = game_team_averages[key]

        for team_idx in range(team_count):
            diff_val = totals[team_idx] - avg_total
            diffs[team_idx].append(diff_val)

    return diffs


# ============================================================
# PLOTTING HELPERS
# ============================================================

def plot_all_games_grid(
    games: List[dict],
    per_player_avgs: Dict[str, List[float]],
    output_path: Path,
) -> None:
    """
    4x3 grid of small bar charts — no title, no wasted vertical space.
    """

    # Order to display games in the grid
    game_keys_ordered = [
        "overall", "bedwars", "bridge_duels", "build_battle",
        "mini_walls", "parkour_duels", "party_games",
        "skywars", "uhc_duels", "wobtafitv",
        "pvp", "non_pvp",
    ]

    game_config_by_key = {g["key"]: g for g in games}

    # Smaller vertical figure to eliminate extra padding.
    fig, axs = plt.subplots(4, 3, figsize=(10, 5))

    labels = np.arange(1, 5)
    team_bar_colors = ["red", "gold", "green", "blue"]

    positions = [(0, 0), (0, 1), (0, 2),
                 (1, 0), (1, 1), (1, 2),
                 (2, 0), (2, 1), (2, 2),
                 (3, 0), (3, 1), (3, 2)]

    for idx, key in enumerate(game_keys_ordered):
        if key not in per_player_avgs:
            continue

        r, c = positions[idx]
        ax = axs[r, c]

        avgs = per_player_avgs[key]
        cfg = game_config_by_key[key]

        ax.bar(labels, avgs, color=team_bar_colors)

        # Small title inside the top-left corner of each subplot
        ax.text(
            0.02,
            0.92,
            cfg.get("long_label", cfg["name"]),
            transform=ax.transAxes,
            fontsize=8,
            fontweight="bold",
            va="top",
        )

        ymin = min(avgs) * 0.9 if any(avgs) else -1
        ymax = max(avgs) * 1.1 if any(avgs) else 1
        if ymin == ymax:
            ymin, ymax = -1, 1
        ax.set_ylim(ymin, ymax)

        ax.set_xticks([])
        ax.set_yticks([])

    # Hide unused subplot if any
    for idx in range(len(game_keys_ordered), len(positions)):
        r, c = positions[idx]
        axs[r, c].axis("off")

    # No suptitle, minimal padding
    fig.tight_layout(pad=0.3)
    plt.subplots_adjust(top=0.98, bottom=0.02, hspace=0.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def plot_differentials(
    games: List[dict],
    team_diffs: Dict[int, List[float]],
    output_path: Path,
) -> None:
    """
    2x2 grid of bar charts for team differentials.
    - Excludes 'Overall' from the differential plots.
    - No team labels drawn inside the charts.
    """

    # Build the list of games to actually show (skip Overall)
    games_for_diff: List[dict] = []
    indices_for_diff: List[int] = []  # indices into the original games order

    for idx, g in enumerate(games):
        if g.get("is_overall", False):
            continue
        games_for_diff.append(g)
        indices_for_diff.append(idx)

    short_labels = [g["short_label"] for g in games_for_diff]

    # Re-slice the per-team differentials so they line up with games_for_diff
    sliced_diffs: Dict[int, List[float]] = {}
    for team_idx, diffs in team_diffs.items():
        sliced_diffs[team_idx] = [diffs[i] for i in indices_for_diff]

    fig, axs = plt.subplots(2, 2, figsize=(10, 6))
    positions = [(0, 0), (0, 1), (1, 0), (1, 1)]

    team_bar_colors = ["red", "gold", "green", "blue"]

    for team_idx in range(4):
        r, c = positions[team_idx]
        ax = axs[r, c]
        diffs = sliced_diffs[team_idx]

        ax.bar(short_labels, diffs, color=team_bar_colors[team_idx])

        ymin = min(diffs + [0]) * 1.1
        ymax = max(diffs + [0]) * 1.1
        if ymin == ymax:
            ymin, ymax = -1, 1
        ax.set_ylim(ymin, ymax)

        ax.axhline(0, color="black", linewidth=0.8)

        # X labels: small + rotated so they don't get cut off
        ax.tick_params(axis="x", labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_ha("right")

    # No suptitle; use space for plots + labels
    fig.tight_layout(pad=0.5)
    plt.subplots_adjust(bottom=0.18, top=0.98, hspace=0.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


# ============================================================
# FINAL SUMMARY SHEET (stack 3 images, each 1/3 height)
# ============================================================

def build_summary_sheet(
    all_teams_path: Path,
    all_games_path: Path,
    diffs_path: Path,
    output_path: Path,
) -> None:
    """
    Build a summary sheet where:
      - All Teams (top), allGames grid (middle), differentials grid (bottom)
      - Each occupies exactly 1/3 of the final height.
      - Images are scaled with LANCZOS to keep text crisp.
    """

    def load_or_blank(path: Path) -> Image.Image:
        if path.exists():
            return Image.open(path).convert("RGB")
        return Image.new("RGB", (1, 1), color=(255, 255, 255))

    img_top = load_or_blank(all_teams_path)
    img_mid = load_or_blank(all_games_path)
    img_bot = load_or_blank(diffs_path)

    # Use the smallest original height as the target so we never upscale too hard.
    section_height = min(img_top.height, img_mid.height, img_bot.height)

    # Safe Resampling.LANCZOS (handles older Pillow too)
    try:
        resample_lanczos = Image.Resampling.LANCZOS
    except AttributeError:
        resample_lanczos = Image.LANCZOS

    def resize_to_height(img: Image.Image, h: int) -> Image.Image:
        if img.height == h:
            return img
        ratio = h / img.height
        new_w = int(img.width * ratio)
        return img.resize((new_w, h), resample_lanczos)

    img_top = resize_to_height(img_top, section_height)
    img_mid = resize_to_height(img_mid, section_height)
    img_bot = resize_to_height(img_bot, section_height)

    final_width = max(img_top.width, img_mid.width, img_bot.width)
    final_height = section_height * 3  # three equal bands

    page = Image.new("RGB", (final_width, final_height), color=(255, 255, 255))

    def paste_centered(base: Image.Image, img: Image.Image, y_offset: int) -> None:
        x = (base.width - img.width) // 2
        base.paste(img, (x, y_offset))

    # No extra gaps — each occupies exactly 1/3 vertically
    paste_centered(page, img_top, 0)
    paste_centered(page, img_mid, section_height)
    paste_centered(page, img_bot, section_height * 2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(output_path, dpi=(300, 300))
    print(f"\nSaved final summary sheet → {output_path}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    # 1) Always regenerate CSV stats first
    print("Refreshing stats from Google Sheets...")
    stats.main()

    # 2) Regenerate team graphics from the team sheet
    print("\nRegenerating team graphics from Google Sheets...")
    team_graphics.main()   # <-- this ensures All Teams.png is fresh

    # 3) Load teams from the team sheet
    print("\nLoading teams from Google Sheets...")
    teams = load_teams_from_sheet()
    for t in teams:
        print(f"  {t.name}: {t.players}")

    games = diff_games()
    playing_players = [p for team in teams for p in team.players]

    # Global substitution / ignore maps
    global_subs: Dict[str, str] = {}
    global_ignored: Set[str] = set()

    # 4) Load per-game stats, with interactive handling for missing players
    per_game_stats: Dict[str, Dict[str, float]] = {}

    for game in games:
        key = game["key"]
        csv_path = STATS_DIR / game["csv"]
        label = game["long_label"]

        print(f"\nLoading stats for {label} ({csv_path.name})...")
        stats_for_game = load_game_stats(
            csv_path, playing_players, label, global_subs, global_ignored
        )
        per_game_stats[key] = stats_for_game

    # 5) Compute team totals, player counts, and game averages
    print("\nComputing team totals and averages...")
    team_totals, team_counts, game_team_averages = compute_team_totals_and_counts(
        teams, games, per_game_stats
    )

    # 6) Per-player averages per game for the allGames grid
    per_player_avgs = compute_per_player_averages(games, team_totals, team_counts)

    # 7) Differentials per team vs average team total
    team_diffs = compute_differentials(games, team_totals, game_team_averages)

    # 8) Plot grids (HD)
    all_games_img = TEAM_GRAPHICS_DIR / "allGames.png"
    diff_img = TEAM_GRAPHICS_DIR / "differentials.png"

    print("\nGenerating allGames grid...")
    plot_all_games_grid(games, per_player_avgs, all_games_img)

    print("Generating differentials grid...")
    plot_differentials(games, team_diffs, diff_img)

    # 9) Build final stacked sheet, using fresh All Teams.png at top
    all_teams_img = TEAM_GRAPHICS_DIR / "All Teams.png"
    final_report_path = FINAL_REPORT_DIR / FINAL_REPORT_FILENAME

    build_summary_sheet(all_teams_img, all_games_img, diff_img, final_report_path)


if __name__ == "__main__":
    main()
