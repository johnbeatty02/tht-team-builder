from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Tuple, List

import matplotlib.pyplot as plt

# ===== USER SETTINGS =====
GAMEMODE = "non_pvp"     # e.g. "bedwars", "skywars", "overall", "pvp", "non_pvp", etc.
TOP_N = 20               # number of players to show


# ===== CONFIG =====

BASE_DIR = Path(__file__).resolve().parent
STATS_DIR = BASE_DIR / "stats"

# Map simple gamemode keys to (csv filename, human-readable label)
GAME_FILES: Dict[str, Tuple[str, str]] = {
    "overall":      ("overall.csv",      "Overall"),
    "bedwars":      ("bedwars.csv",      "Bed Wars"),
    "skywars":      ("skywars.csv",      "Skywars"),
    "build_battle": ("buildBattle.csv",  "Build Battle"),
    "bridge_duels": ("bridgeDuels.csv",  "Bridge Duels"),
    "mini_walls":   ("miniWalls.csv",    "Mini Walls"),
    "parkour_duels":("parkourDuels.csv", "Parkour Duels"),
    "party_games":  ("partyGames.csv",   "Party Games"),
    # "survival_games": ("survivalGames.csv", "Survival Games"),
    "wobtafitv":    ("wobtafitv.csv",    "WOBTAFITV"),
    "uhc_duels":    ("uhcDuels.csv",     "UHC Duels"),
    "pvp":          ("pvp.csv",          "PvP"),
    "non_pvp":      ("nonPvP.csv",       "Non-PvP"),
}


# ===== DATA LOADING =====

def load_leaderboard(mode: str, top_n: int) -> Tuple[List[str], List[float], str]:
    """
    Load the top N players for a given mode from stats/<file>.csv.

    Expects the export script format:
        Header: Player,Points
        Rows:   <name>,<points>  where points may be a float (e.g. 675.6)
    """
    if mode not in GAME_FILES:
        raise ValueError(
            f"Unknown mode '{mode}'. Valid: {', '.join(GAME_FILES.keys())}"
        )

    csv_name, label = GAME_FILES[mode]
    csv_path = STATS_DIR / csv_name

    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV for mode '{mode}' does not exist: {csv_path}\n"
            f"Run your stats export script first."
        )

    players: List[str] = []
    points: List[float] = []

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)

        # First row should be header: Player,Points
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{csv_path} is empty.")

        # Process data rows
        for row in reader:
            if not row:
                continue  # empty line

            name = row[0].strip() if len(row) > 0 else ""
            pts_str = row[1].strip() if len(row) > 1 else ""

            if not name:
                continue

            # Skip obvious non-data rows like "#N/A,#N/A"
            if name.startswith("#") or pts_str.startswith("#"):
                continue

            # Remove commas and parse as float
            pts_str_clean = pts_str.replace(",", "")
            try:
                pts = float(pts_str_clean) if pts_str_clean else 0.0
            except ValueError:
                # If it's something weird (e.g. "N/A"), skip this row
                continue

            players.append(name)
            points.append(pts)

    if not players:
        raise ValueError(f"No valid player rows found in {csv_path}")

    # Sort by points descending and slice top N
    combined = list(zip(players, points))
    combined.sort(key=lambda x: x[1], reverse=True)
    top = combined[:top_n]

    top_players, top_points = zip(*top)
    return list(top_players), list(top_points), label


# ===== PLOTTING =====

def plot_leaderboard(players: List[str], points: List[float], label: str, top_n: int) -> Path:
    """
    Create a bar graph and save as PNG in stats/.
    """
    output_path = STATS_DIR / f"{GAMEMODE}_top{top_n}.png"

    # Reverse so highest score appears at the top
    players_plot = players[::-1]
    points_plot = points[::-1]

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.barh(players_plot, points_plot)
    ax.set_xlabel("Points")
    ax.set_ylabel("Player")
    ax.set_title(f"{label} – Top {top_n} Players")

    max_points = max(points_plot)
    offset = max_points * 0.01 if max_points > 0 else 1.0

    # Label bars with 1 decimal place (matches your 675.6 style nicely)
    for i, v in enumerate(points_plot):
        ax.text(v + offset, i, f"{v:.1f}", va="center", fontsize=9)

    plt.tight_layout()
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path


# ===== MAIN =====

def main() -> None:
    players, points, label = load_leaderboard(GAMEMODE, TOP_N)
    saved_path = plot_leaderboard(players, points, label, TOP_N)
    print(f"Saved leaderboard graph → {saved_path}")


if __name__ == "__main__":
    main()
