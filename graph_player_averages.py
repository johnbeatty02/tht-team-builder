from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Tuple, List

import matplotlib.pyplot as plt

# ===== USER SETTINGS =====
PLAYER_NAME = "BeanGangTingle"   # exact or case-insensitive match


# ===== CONFIG =====

BASE_DIR = Path(__file__).resolve().parent
STATS_DIR = BASE_DIR / "stats"

# Map simple gamemode keys to (csv filename, human-readable label)
GAME_FILES: Dict[str, Tuple[str, str]] = {
    # "overall":      ("overall.csv",      "Overall"),
    "bedwars":      ("bedwars.csv",      "Bed Wars"),
    "skywars":      ("skywars.csv",      "Skywars"),
    "build_battle": ("buildBattle.csv",  "Build Battle"),
    "bridge_duels": ("bridgeDuels.csv",  "Bridge Duels"),
    "mini_walls":   ("miniWalls.csv",    "Mini Walls"),
    "parkour_duels":("parkourDuels.csv", "Parkour Duels"),
    "party_games":  ("partyGames.csv",   "Party Games"),
    "survival_games": ("survivalGames.csv", "Survival Games"),
    "wobtafitv":    ("wobtafitv.csv",    "WOBTAFITV"),
    "uhc_duels":    ("uhcDuels.csv",     "UHC Duels"),
    "pvp":          ("pvp.csv",          "PvP"),
    "non_pvp":      ("nonPvP.csv",       "Non-PvP"),
}


# ===== DATA LOADING =====

def find_player_points_in_csv(csv_path: Path, player_name: str) -> float | None:
    """
    Look for the given player in the CSV and return their points as a float.
    Returns None if the player isn't found or the value is invalid.
    """
    if not csv_path.exists():
        return None

    player_lower = player_name.lower()

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)

        # Skip header
        try:
            header = next(reader)
        except StopIteration:
            return None

        for row in reader:
            if not row:
                continue

            name = row[0].strip()
            pts_str = row[1].strip() if len(row) > 1 else ""

            if not name:
                continue

            # Case-insensitive name match
            if name.lower() != player_lower:
                continue

            # Skip obvious bad rows like "#N/A"
            if name.startswith("#") or pts_str.startswith("#"):
                return None

            pts_str_clean = pts_str.replace(",", "")
            try:
                return float(pts_str_clean) if pts_str_clean else 0.0
            except ValueError:
                return None

    return None


def load_player_averages(player_name: str) -> tuple[list[str], list[float]]:
    """
    For a given player, collect their points in every game where they appear.
    Returns:
        game_labels: list of human-readable game names
        points:      list of floats (points/averages)
    """
    game_labels: List[str] = []
    points: List[float] = []

    for key, (csv_name, label) in GAME_FILES.items():
        csv_path = STATS_DIR / csv_name
        pts = find_player_points_in_csv(csv_path, player_name)

        if pts is None:
            # Player not present or invalid in this game
            continue

        game_labels.append(label)
        points.append(pts)

    return game_labels, points


# ===== PLOTTING =====

def sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


def plot_player_averages(player_name: str, game_labels: list[str], points: list[float]) -> Path:
    """
    Create a bar chart of the player's points per game and save as PNG in stats/.
    """
    if not game_labels:
        raise ValueError(f"No stats found for player '{player_name}' in any game.")

    STATS_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(player_name)
    output_path = STATS_DIR / f"{safe_name}_per_game.png"

    x_positions = range(len(game_labels))

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.bar(x_positions, points)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(game_labels, rotation=45, ha="right")

    ax.set_ylabel("Points")
    ax.set_title(f"{player_name} – Average / Points per Game")

    max_points = max(points)
    offset = max_points * 0.01 if max_points > 0 else 1.0

    # Label each bar with value (1 decimal place)
    for i, v in enumerate(points):
        ax.text(i, v + offset, f"{v:.1f}", ha="center", va="bottom", fontsize=9)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path


# ===== MAIN =====

def main() -> None:
    player = PLAYER_NAME.strip()
    if not player:
        raise ValueError("PLAYER_NAME is empty. Set it at the top of the script.")

    game_labels, points = load_player_averages(player)
    saved_path = plot_player_averages(player, game_labels, points)
    print(f"Saved per-game stats graph for {player} → {saved_path}")


if __name__ == "__main__":
    main()
