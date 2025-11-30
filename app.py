from __future__ import annotations

import base64
import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Set

import matplotlib.pyplot as plt
import numpy as np
from flask import Flask, jsonify, render_template_string, request

from config import STATS_DIR, GAME_CONFIGS, TEAM_COLORS
import stats  # optional auto-refresh of CSVs from Sheets


# ----------------------------------------------------------------------
# Basic configuration
# ----------------------------------------------------------------------

# Display names for the four teams
TEAM_NAMES = ["Red", "Yellow", "Green", "Blue"]

# Color config mapping from config keys to team labels
COLOR_KEY_ORDER = ["red", "gold", "green", "blue"]
COLOR_KEY_TO_TEAM = {
    "red": "Red",
    "gold": "Yellow",
    "green": "Green",
    "blue": "Blue",
}

# Matplotlib RGB (0–1) colors in a fixed order: Red, Yellow, Green, Blue
TEAM_COLOR_SEQ: List[Tuple[float, float, float]] = [
    tuple(c / 255.0 for c in TEAM_COLORS[key]) for key in COLOR_KEY_ORDER
]

# Hex colors for legend + UI
TEAM_HEX_ITEMS = [
    {
        "label": COLOR_KEY_TO_TEAM[key],
        "color": "#{:02x}{:02x}{:02x}".format(*TEAM_COLORS[key]),
    }
    for key in COLOR_KEY_ORDER
]

# Whether to regenerate CSVs from Google Sheets on app start
AUTO_REFRESH_STATS_ON_STARTUP = False


@dataclass
class GameCfg:
    name: str
    csv: str
    short: str


GAMES: List[GameCfg] = [
    GameCfg(name=g["name"], csv=g["csv"], short=g.get("short", g["name"]))
    for g in GAME_CONFIGS
    if g.get("enabled", True)
]


# ----------------------------------------------------------------------
# CSV loading
# ----------------------------------------------------------------------

def load_stats_from_csvs() -> Dict[str, Dict[str, float]]:
    """
    Load all game CSV files into memory.

    Returns:
        stats_by_game: dict of
            game_name -> { player_ign -> points_float }
    """
    stats_by_game: Dict[str, Dict[str, float]] = {}

    for game in GAMES:
        csv_path = STATS_DIR / game.csv
        game_map: Dict[str, float] = {}

        if not csv_path.exists():
            print(f"[WARN] CSV not found for {game.name}: {csv_path}")
            stats_by_game[game.name] = game_map
            continue

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            # Attempt to skip header "Player,Points"
            try:
                header = next(reader)
                if not header or header[0].strip().lower() != "player":
                    # Not a header; rewind
                    f.seek(0)
                    reader = csv.reader(f)
            except StopIteration:
                stats_by_game[game.name] = {}
                continue

            for row in reader:
                if not row:
                    continue
                player = row[0].strip()
                if not player or player.startswith("#"):
                    continue

                pts_str = row[1].strip() if len(row) > 1 else ""
                pts_str = pts_str.replace(",", "")
                if not pts_str:
                    continue
                try:
                    pts_val = float(pts_str)
                except ValueError:
                    continue

                game_map[player] = pts_val

        stats_by_game[game.name] = game_map
        print(f"[INFO] Loaded {len(game_map)} rows for {game.name}")

    return stats_by_game


# Optionally refresh once and load all stats
if AUTO_REFRESH_STATS_ON_STARTUP:
    print("[INFO] Refreshing stats from Google Sheets...")
    stats.main()

STATS_DATA = load_stats_from_csvs()

# Substitution + ignore state (global for the app lifetime)
GLOBAL_SUBSTITUTIONS: Dict[str, str] = {}  # missing_player -> replacement_ign
GLOBAL_IGNORED: Set[str] = set()          # players to ignore entirely


# ----------------------------------------------------------------------
# Core recompute logic (with missing-player handling)
# ----------------------------------------------------------------------

def recompute_team_stats(
    teams: Dict[str, List[str]],
    new_substitutions: Dict[str, str],
) -> Dict:
    """
    Given a team mapping from the UI:

        teams = { "Red": [...players...], "Yellow": [...], ... }

    And substitutions mapping:

        new_substitutions = { "MissingPlayer": "ReplacementIGN" or "" }

    Returns a dict:
      - If there are unresolved missing players:
           {
             "missing_players": [...],
             "per_game_avgs": null,
             "team_diffs": null
           }

      - Else:
           {
             "missing_players": [],
             "per_game_avgs": { game_name: [avg_red, avg_yellow, avg_green, avg_blue] },
             "team_diffs": { team_index: [diffs_for_each_non_overall_game] }
           }
    """
    global GLOBAL_SUBSTITUTIONS, GLOBAL_IGNORED

    # 1) Merge in new substitutions from the client
    #    "" means "ignore this player globally"
    for player, replacement in (new_substitutions or {}).items():
        replacement = (replacement or "").strip()
        if not replacement:
            GLOBAL_IGNORED.add(player)
            GLOBAL_SUBSTITUTIONS.pop(player, None)
        else:
            GLOBAL_SUBSTITUTIONS[player] = replacement
            GLOBAL_IGNORED.discard(player)

    team_order = TEAM_NAMES  # ["Red", "Yellow", "Green", "Blue"]
    per_game_avgs: Dict[str, List[float]] = {}
    team_totals: Dict[str, List[float]] = {}
    missing_players: Set[str] = set()

    # 2) Compute totals and averages per game, while tracking unresolved missing players
    for game in GAMES:
        gstats = STATS_DATA.get(game.name, {})
        totals: List[float] = []
        counts: List[int] = []

        for team_name in team_order:
            players = teams.get(team_name, [])
            total = 0.0
            count = 0

            for p in players:
                pname = (p or "").strip()
                if not pname:
                    continue
                if pname in GLOBAL_IGNORED:
                    # completely ignored
                    continue

                effective_player = pname

                # If we have a global sub for this player, try that
                if pname in GLOBAL_SUBSTITUTIONS:
                    sub = GLOBAL_SUBSTITUTIONS[pname]
                    if sub in gstats:
                        effective_player = sub
                    else:
                        # substitution not present in this game's stats → still missing
                        missing_players.add(pname)
                        continue
                else:
                    # No substitution configured yet
                    if pname not in gstats:
                        missing_players.add(pname)
                        continue

                pts = float(gstats.get(effective_player, 0.0))
                total += pts
                count += 1

            totals.append(total)
            counts.append(count)

        team_totals[game.name] = totals

        # We'll compute averages *only* if we ultimately have no missing players
        # (but we can precompute here too)
        avgs_for_game: List[float] = []
        for total, count in zip(totals, counts):
            if count == 0:
                avgs_for_game.append(0.0)
            else:
                avgs_for_game.append(round(total / count, 2))
        per_game_avgs[game.name] = avgs_for_game

    # 3) If there are unresolved missing players, stop here and tell the UI
    if missing_players:
        return {
            "missing_players": sorted(missing_players),
            "per_game_avgs": None,
            "team_diffs": None,
        }

    # 4) Compute per-team differentials (team total – average team total) for non-Overall games
    diffs: Dict[int, List[float]] = {idx: [] for idx in range(len(team_order))}
    for game in GAMES:
        if game.name.lower() == "overall":
            continue

        totals = team_totals[game.name]
        avg_total = float(np.mean(totals)) if totals else 0.0

        for idx in range(len(team_order)):
            diffs[idx].append(totals[idx] - avg_total)

    return {
        "missing_players": [],
        "per_game_avgs": per_game_avgs,
        "team_diffs": diffs,
    }


# ----------------------------------------------------------------------
# Plot helpers → base64 PNGs
# ----------------------------------------------------------------------

def fig_to_data_url(fig) -> str:
    """Convert a Matplotlib Figure to a base64-encoded PNG data URL."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def plot_all_games(per_game_avgs: Dict[str, List[float]]) -> str:
    """
    Redesigned grid of per-game averages.

    - 4×3 grid of mini charts
    - Game name appears inside each subplot
    - Clean look (no axes labels, just relative bars)
    """
    rows, cols = 4, 3
    fig, axs = plt.subplots(rows, cols, figsize=(11, 6))
    axs_flat = axs.flatten()
    labels = np.arange(1, len(TEAM_NAMES) + 1)

    # Soft background
    fig.patch.set_facecolor("#fafafa")

    for idx, game in enumerate(GAMES[: rows * cols]):
        ax = axs_flat[idx]
        vals = per_game_avgs.get(game.name, [0.0] * len(TEAM_NAMES))

        # Draw bars
        ax.bar(labels, vals, color=TEAM_COLOR_SEQ)

        # Game label
        ax.text(
            0.02,
            0.93,
            game.name,
            transform=ax.transAxes,
            fontsize=8,
            fontweight="bold",
            va="top",
        )

        # Y-limits
        if any(vals):
            ymin = min(vals) * 0.9
            ymax = max(vals) * 1.1
            if ymin == ymax:
                ymin, ymax = -1, 1
            ax.set_ylim(ymin, ymax)

        # Clean axes
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    # Hide extra panels if fewer games than slots
    for j in range(len(GAMES), rows * cols):
        axs_flat[j].axis("off")

    fig.tight_layout(pad=0.3)
    plt.subplots_adjust(top=0.96, bottom=0.05, hspace=0.65)
    return fig_to_data_url(fig)


def plot_differentials(team_diffs: Dict[int, List[float]]) -> str:
    """
    2×2 grid of differential charts (one per team).

    - Horizontal layout for labels
    - Shared style, consistent spacing
    - No team labels text on plots; colors + legend handle that
    """
    games_for_diff = [g for g in GAMES if g.name.lower() != "overall"]
    short_labels = [g.short for g in games_for_diff]

    fig, axs = plt.subplots(2, 2, figsize=(11, 6))
    axs_flat = axs.flatten()
    fig.patch.set_facecolor("#fafafa")

    for team_idx, ax in enumerate(axs_flat):
        diffs = team_diffs.get(team_idx, [])
        # Match number of labels
        diffs = diffs[: len(short_labels)]
        x = np.arange(len(short_labels))

        ax.bar(x, diffs, color=TEAM_COLOR_SEQ[team_idx])

        # Zero line
        ax.axhline(0, color="#444444", linewidth=0.8, alpha=0.6)

        # X labels
        ax.set_xticks(x)
        ax.set_xticklabels(short_labels, rotation=40, ha="right", fontsize=8)

        # Y range
        ymin = min(diffs + [0]) * 1.15
        ymax = max(diffs + [0]) * 1.15
        if ymin == ymax:
            ymin, ymax = -1, 1
        ax.set_ylim(ymin, ymax)

        # Subtle grid
        ax.yaxis.grid(True, linestyle=":", linewidth=0.5, alpha=0.3)
        ax.set_axisbelow(True)

        # Remove frame style noise
        for spine in ax.spines.values():
            spine.set_alpha(0.4)

        ax.tick_params(axis="y", labelsize=8)

    fig.tight_layout(pad=0.4)
    plt.subplots_adjust(top=0.96, bottom=0.18, hspace=0.55)
    return fig_to_data_url(fig)


# ----------------------------------------------------------------------
# Flask app & UI
# ----------------------------------------------------------------------

app = Flask(__name__)


TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>THT Team Builder</title>

  <!-- Google Font -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

  <style>
    :root {
      --bg-body: #0f172a;
      --bg-panel-left: #020617;
      --bg-panel-right: #0b1120;
      --card-bg: #020617;
      --border-subtle: #1e293b;
      --accent: #38bdf8;
      --accent-soft: rgba(56,189,248,0.18);
      --text-main: #e5e7eb;
      --text-muted: #9ca3af;
      --shadow-soft: 0 18px 40px rgba(15,23,42,0.6);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top left, #1e293b 0, #020617 42%, #000000 100%);
      color: var(--text-main);
    }

    .layout {
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    .left-panel {
      width: 360px;
      background: linear-gradient(150deg, #020617 0%, #020617 40%, #0b1120 100%);
      border-right: 1px solid var(--border-subtle);
      padding: 18px 16px 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      box-shadow: var(--shadow-soft);
      z-index: 2;
    }

    .right-panel {
      flex: 1;
      padding: 16px 18px 18px;
      overflow-y: auto;
      background:
        radial-gradient(circle at top right, rgba(37,99,235,0.3) 0, transparent 55%),
        radial-gradient(circle at bottom left, rgba(16,185,129,0.3) 0, transparent 60%),
        var(--bg-panel-right);
    }

    .app-title {
      font-size: 19px;
      font-weight: 600;
      margin-bottom: 4px;
      letter-spacing: 0.03em;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .app-title span.logo {
      display: inline-flex;
      width: 22px;
      height: 22px;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      background: radial-gradient(circle at 30% 0%, #38bdf8, #4f46e5);
      font-size: 13px;
      font-weight: 700;
      color: #e5e7eb;
      box-shadow: 0 0 0 1px rgba(15,23,42,0.7);
    }

    .app-subtitle {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 10px;
    }

    .section-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .16em;
      color: var(--text-muted);
      margin-bottom: 4px;
    }

    .card {
      background: radial-gradient(circle at top, rgba(148,163,184,0.12) 0, #020617 48%, #020617 100%);
      border-radius: 14px;
      border: 1px solid var(--border-subtle);
      padding: 10px 10px 9px;
      box-shadow: 0 12px 25px rgba(15,23,42,0.75);
    }

    textarea {
      width: 100%;
      min-height: 70px;
      resize: vertical;
      border-radius: 9px;
      border: 1px solid var(--border-subtle);
      background: rgba(15,23,42,0.8);
      color: var(--text-main);
      font-size: 12px;
      padding: 6px 7px;
      font-family: "JetBrains Mono", SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      outline: none;
    }
    textarea::placeholder {
      color: #6b7280;
    }
    textarea:focus {
      box-shadow: 0 0 0 1px var(--accent-soft);
      border-color: var(--accent);
    }

    .button-row {
      display: flex;
      gap: 6px;
      margin-top: 7px;
    }

    button {
      border-radius: 999px;
      border: 1px solid transparent;
      font-size: 11px;
      padding: 5px 10px;
      cursor: pointer;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--accent);
      color: #0b1120;
      box-shadow: 0 8px 20px rgba(56,189,248,0.5);
      transition: transform 0.08s ease, box-shadow 0.08s ease, background 0.12s ease;
    }
    button:hover {
      transform: translateY(-0.5px);
      box-shadow: 0 10px 26px rgba(56,189,248,0.7);
      background: #0ea5e9;
    }
    button.secondary {
      background: transparent;
      color: var(--text-muted);
      border-color: var(--border-subtle);
      box-shadow: none;
    }
    button.secondary:hover {
      background: rgba(15,23,42,0.5);
      color: var(--text-main);
    }

    .pool-card, .teams-card {
      margin-top: 6px;
    }

    .pool-list, .player-list {
      min-height: 64px;
      border-radius: 9px;
      padding: 4px;
      background: radial-gradient(circle at top left, rgba(15,23,42,0.9), #020617 70%);
      border: 1px dashed rgba(148,163,184,0.4);
      overflow-y: auto;
      max-height: 180px;
    }

    .player {
      background: linear-gradient(135deg, rgba(148,163,184,0.9), rgba(148,163,184,0.7));
      border-radius: 6px;
      padding: 3px 7px;
      margin: 2px 0;
      font-size: 12px;
      cursor: grab;
      user-select: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #020617;
      font-weight: 500;
    }
    .player span.tag {
      font-size: 10px;
      padding: 1px 5px;
      border-radius: 999px;
      background: rgba(15,23,42,0.1);
      color: #020617;
    }

    .dropzone.drag-over {
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent-soft);
    }

    .teams-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 6px;
    }

    .team-box {
      background: radial-gradient(circle at top, rgba(15,23,42,0.95), rgba(15,23,42,0.97));
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
      padding: 8px 8px 7px;
    }

    .team-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;
      font-size: 12px;
      font-weight: 500;
    }

    .team-pill {
      font-size: 10px;
      padding: 2px 7px;
      border-radius: 999px;
      border: 1px solid rgba(148,163,184,0.5);
      color: var(--text-muted);
    }

    /* RIGHT PANEL */

    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }

    .top-bar-title {
      font-size: 16px;
      font-weight: 500;
    }

    .legend {
      display: inline-flex;
      gap: 10px;
      align-items: center;
      background: rgba(15,23,42,0.4);
      border-radius: 999px;
      padding: 4px 10px;
      border: 1px solid rgba(148,163,184,0.3);
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      color: var(--text-muted);
    }

    .legend-swatch {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      box-shadow: 0 0 0 1px rgba(15,23,42,0.8);
    }

    .graphs-layout {
      display: grid;
      grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
      gap: 12px;
      height: calc(100vh - 56px);
    }

    .graph-card {
      background: radial-gradient(circle at top, rgba(15,23,42,0.97), #020617);
      border-radius: 16px;
      border: 1px solid rgba(30,64,175,0.7);
      box-shadow: var(--shadow-soft);
      padding: 10px 10px 8px;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    .graph-card-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 6px;
    }

    .graph-title {
      font-size: 14px;
      font-weight: 500;
      letter-spacing: 0.02em;
    }

    .graph-subtitle {
      font-size: 11px;
      color: var(--text-muted);
    }

    .graph-inner {
      flex: 1;
      min-height: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-radius: 12px;
      background: radial-gradient(circle at top left, rgba(15,23,42,0.7), #020617 60%);
      border: 1px solid rgba(15,23,42,0.9);
    }

    .graph-img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      image-rendering: auto;
    }

    /* Missing players modal */

    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15,23,42,0.75);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 40;
    }
    .modal-backdrop.hidden {
      display: none;
    }

    .modal {
      background: radial-gradient(circle at top, #020617, #020617 60%);
      border-radius: 14px;
      border: 1px solid rgba(148,163,184,0.7);
      box-shadow: 0 18px 45px rgba(15,23,42,0.9);
      padding: 14px 16px 12px;
      width: 360px;
      max-width: 90vw;
      color: var(--text-main);
    }

    .modal h2 {
      margin: 0 0 4px;
      font-size: 15px;
      font-weight: 600;
    }

    .modal p {
      margin: 0 0 8px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .missing-list {
      max-height: 200px;
      overflow-y: auto;
      margin-bottom: 8px;
      padding-right: 2px;
    }

    .missing-row {
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding: 5px 0;
      border-bottom: 1px solid rgba(31,41,55,0.7);
    }

    .missing-name {
      font-size: 12px;
      font-weight: 500;
    }

    .missing-input {
      width: 100%;
      border-radius: 7px;
      border: 1px solid rgba(31,41,55,0.9);
      background: rgba(15,23,42,0.85);
      color: var(--text-main);
      font-size: 11px;
      padding: 5px 7px;
      outline: none;
    }
    .missing-input::placeholder {
      color: #6b7280;
    }
    .missing-input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent-soft);
    }

    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 6px;
      margin-top: 4px;
    }

    .modal-hint {
      margin-top: 6px;
      font-size: 11px;
      color: var(--text-muted);
    }

    @media (max-width: 980px) {
      .layout {
        flex-direction: column;
      }
      .left-panel {
        width: 100%;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--border-subtle);
      }
      .right-panel {
        height: calc(100vh - 260px);
      }
      .graphs-layout {
        height: auto;
      }
    }
  </style>
</head>
<body>
<div class="layout">
  <!-- LEFT PANEL -->
  <aside class="left-panel">
    <header>
      <div class="app-title">
        <span class="logo">H</span> THT Team Builder
      </div>
      <div class="app-subtitle">
        Drag players into four teams and see live balance analytics.
      </div>
    </header>

    <section>
      <div class="section-label">Player pool</div>
      <div class="card">
        <textarea id="pool-input"
                  placeholder="Paste comma-separated or one name per line:
CluelessGamer18, JJ22FTW, QuinnQuimby, ..."></textarea>
        <div class="button-row">
          <button onclick="loadPool()">
            <span>Load to pool</span>
          </button>
          <button class="secondary" onclick="clearTeams()">
            Clear teams
          </button>
        </div>
      </div>
    </section>

    <section class="pool-card">
      <div class="section-label">Unassigned</div>
      <div class="card">
        <div id="pool-list" class="pool-list dropzone"></div>
      </div>
    </section>

    <section class="teams-card">
      <div class="section-label">Teams</div>
      <div class="teams-grid">
        {% for name in team_names %}
        <div class="team-box">
          <div class="team-header">
            <div>{{ name }} Team</div>
            <div class="team-pill">drag players here</div>
          </div>
          <div id="team-{{ name }}" class="player-list dropzone"></div>
        </div>
        {% endfor %}
      </div>
    </section>
  </aside>

  <!-- RIGHT PANEL -->
  <main class="right-panel">
    <div class="top-bar">
      <div class="top-bar-title">Live Team Analytics</div>
      <div class="legend">
        {% for item in legend_items %}
        <div class="legend-item">
          <span class="legend-swatch" style="background: {{ item.color }}"></span>
          <span>{{ item.label }}</span>
        </div>
        {% endfor %}
      </div>
    </div>

    <div class="graphs-layout">
      <section class="graph-card">
        <header class="graph-card-header">
          <div class="graph-title">Per-game average points</div>
          <div class="graph-subtitle">Average per player by team · Overall included</div>
        </header>
        <div class="graph-inner">
          <img id="per-game-img" class="graph-img" alt="Per-game graphs will appear here">
        </div>
      </section>

      <section class="graph-card">
        <header class="graph-card-header">
          <div class="graph-title">Team differentials</div>
          <div class="graph-subtitle">Total team score versus average team score · Overall excluded</div>
        </header>
        <div class="graph-inner">
          <img id="diff-img" class="graph-img" alt="Differential graphs will appear here">
        </div>
      </section>
    </div>
  </main>
</div>

<!-- Missing players modal -->
<div id="missing-backdrop" class="modal-backdrop hidden">
  <div class="modal">
    <h2>Missing players in stat pool</h2>
    <p>
      These players are not present in the stat sheets. Enter a replacement IGN
      (with stats) or leave blank to ignore that player in all games.
    </p>
    <form id="missing-form">
      <div id="missing-list" class="missing-list"></div>
      <div class="modal-actions">
        <button type="button" class="secondary" id="missing-cancel">Cancel</button>
        <button type="submit">Apply &amp; recompute</button>
      </div>
      <p class="modal-hint">
        Replacements will be used for that player across all gamemodes. Ignored
        players will not affect any averages.
      </p>
    </form>
  </div>
</div>

<script>
  const TEAM_NAMES = {{ team_names | tojson }};
  let draggedEl = null;

  // client-side record of substitutions (player -> replacement IGN or "")
  window.currentSubstitutions = {};

  function createPlayerElement(name) {
    const div = document.createElement('div');
    div.className = 'player';
    div.dataset.name = name;
    div.draggable = true;

    const label = document.createElement('span');
    label.textContent = name;

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = 'player';

    div.appendChild(label);
    div.appendChild(tag);

    return div;
  }

  function loadPool() {
    const text = document.getElementById('pool-input').value || '';
    const names = text
      .split(/[\\n,]+/)
      .map(s => s.trim())
      .filter(s => s.length > 0);

    const pool = document.getElementById('pool-list');
    pool.innerHTML = '';

    // Clear teams
    TEAM_NAMES.forEach(t => {
      document.getElementById('team-' + t).innerHTML = '';
    });

    const seen = new Set();
    for (const name of names) {
      if (seen.has(name)) continue;
      seen.add(name);
      pool.appendChild(createPlayerElement(name));
    }

    recalc();
  }

  function clearTeams() {
    TEAM_NAMES.forEach(t => {
      document.getElementById('team-' + t).innerHTML = '';
    });
    recalc();
  }

  // Drag & drop
  document.addEventListener('dragstart', (e) => {
    const target = e.target;
    if (target.classList.contains('player')) {
      draggedEl = target;
      e.dataTransfer.effectAllowed = 'move';
    }
  });

  document.addEventListener('dragend', () => {
    draggedEl = null;
    document.querySelectorAll('.dropzone').forEach(z => z.classList.remove('drag-over'));
  });

  document.querySelectorAll('.dropzone').forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      if (draggedEl) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        zone.classList.add('drag-over');
      }
    });
    zone.addEventListener('dragleave', () => {
      zone.classList.remove('drag-over');
    });
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      if (draggedEl) {
        zone.appendChild(draggedEl);
        recalc();
      }
    });
  });

  function collectTeamsFromDOM() {
    const teams = {};
    TEAM_NAMES.forEach(t => {
      const container = document.getElementById('team-' + t);
      const players = [];
      container.querySelectorAll('.player').forEach(p => {
        players.push(p.dataset.name);
      });
      teams[t] = players;
    });
    return teams;
  }

  // ---------- Missing players modal ----------

  function showMissingModal(missingPlayers) {
    const backdrop = document.getElementById('missing-backdrop');
    const list = document.getElementById('missing-list');
    list.innerHTML = '';

    missingPlayers.forEach(player => {
      const row = document.createElement('div');
      row.className = 'missing-row';

      const label = document.createElement('span');
      label.className = 'missing-name';
      label.textContent = player;

      const input = document.createElement('input');
      input.className = 'missing-input';
      input.name = player;
      input.placeholder = "Replacement IGN (blank = ignore)";

      row.appendChild(label);
      row.appendChild(input);
      list.appendChild(row);
    });

    backdrop.classList.remove('hidden');
  }

  document.getElementById('missing-cancel').addEventListener('click', () => {
    document.getElementById('missing-backdrop').classList.add('hidden');
  });

  document.getElementById('missing-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const inputs = form.querySelectorAll('.missing-input');

    const newSubs = {};
    inputs.forEach(input => {
      newSubs[input.name] = (input.value || '').trim(); // "" means ignore
    });

    // Merge into global map
    window.currentSubstitutions = {
      ...(window.currentSubstitutions || {}),
      ...newSubs,
    };

    document.getElementById('missing-backdrop').classList.add('hidden');

    await recalc();
  });

  // ---------- Recalc ----------

  async function recalc() {
    const teams = collectTeamsFromDOM();
    try {
      const resp = await fetch('/api/recalc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          teams: teams,
          substitutions: window.currentSubstitutions || {}
        }),
      });
      if (!resp.ok) return;
      const data = await resp.json();

      if (data.missing_players && data.missing_players.length > 0) {
        // Show modal; do not overwrite graphs yet
        showMissingModal(data.missing_players);
        return;
      }

      if (data.per_game_img) {
        document.getElementById('per-game-img').src = data.per_game_img;
      }
      if (data.diff_img) {
        document.getElementById('diff-img').src = data.diff_img;
      }
    } catch (err) {
      console.error('Recalc error', err);
    }
  }

  // Initial empty state
  recalc();
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        TEMPLATE,
        team_names=TEAM_NAMES,
        legend_items=TEAM_HEX_ITEMS,
    )


@app.route("/api/recalc", methods=["POST"])
def api_recalc():
    data = request.get_json(force=True)
    teams = data.get("teams", {}) or {}
    substitutions = data.get("substitutions", {}) or {}

    # Ensure all names exist as keys
    for name in TEAM_NAMES:
        teams.setdefault(name, [])

    result = recompute_team_stats(teams, substitutions)

    if result["missing_players"]:
        # Missing players → tell frontend to show modal; no new graphs yet
        return jsonify(
            ok=True,
            missing_players=result["missing_players"],
            per_game_img=None,
            diff_img=None,
        )

    per_game_avgs = result["per_game_avgs"]
    team_diffs = result["team_diffs"]

    per_game_img = plot_all_games(per_game_avgs)
    diff_img = plot_differentials(team_diffs)

    return jsonify(
        ok=True,
        missing_players=[],
        per_game_img=per_game_img,
        diff_img=diff_img,
    )


if __name__ == "__main__":
    app.run(debug=True)
