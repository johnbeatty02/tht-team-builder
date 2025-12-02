from __future__ import annotations

import base64
import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import datetime
import os

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
# Last-updated helper
# ----------------------------------------------------------------------

def get_last_stats_updated() -> Optional[str]:
    """
    Look at all CSVs in STATS_DIR and return a formatted timestamp string
    for the most recently modified one.

    Returns something like: "2025-11-30 16:12"
    or None if no CSVs exist.
    """
    csv_paths = list(STATS_DIR.glob("*.csv"))
    if not csv_paths:
        return None

    latest_mtime = max(p.stat().st_mtime for p in csv_paths)
    dt = datetime.datetime.fromtimestamp(latest_mtime)
    # You can customize the format or add timezone info if you want
    return dt.strftime("%Y-%m-%d %H:%M")


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


# ----------------------------------------------------------------------
# Core recompute logic
# ----------------------------------------------------------------------

def recompute_team_stats(
    teams: Dict[str, List[str]],
) -> (Dict[str, List[float]], Dict[int, List[float]]):
    """
    Given a team mapping from the UI:

        teams = { "Red": [...players...], "Yellow": [...], ... }

    Returns:
        per_game_avgs: dict
            game_name -> [avg_points_red, avg_points_yellow, avg_points_green, avg_points_blue]

        team_diffs: dict
            team_index (0..3) -> [difference_per_game_excluding_overall]
    """
    per_game_avgs: Dict[str, List[float]] = {}
    team_totals: Dict[str, List[float]] = {}

    # Compute per-team totals and per-player averages game by game
    for game in GAMES:
        gstats = STATS_DATA.get(game.name, {})
        totals: List[float] = []
        counts: List[int] = []

        for team_name in TEAM_NAMES:
            players = teams.get(team_name, [])
            pts_list = [gstats.get(p, 0.0) for p in players if p.strip()]
            total = float(sum(pts_list))
            count = len(pts_list)
            totals.append(total)
            counts.append(count)

        team_totals[game.name] = totals

        avgs_for_game: List[float] = []
        for total, count in zip(totals, counts):
            if count == 0:
                avgs_for_game.append(0.0)
            else:
                avgs_for_game.append(round(total / count, 2))

        per_game_avgs[game.name] = avgs_for_game

    # Compute per-team differentials (team total – average team total) for non-Overall games
    diffs: Dict[int, List[float]] = {idx: [] for idx in range(len(TEAM_NAMES))}
    for game in GAMES:
        if game.name.lower() == "overall":
            continue

        totals = team_totals[game.name]
        avg_total = float(np.mean(totals)) if totals else 0.0

        for idx in range(len(TEAM_NAMES)):
            diffs[idx].append(totals[idx] - avg_total)

    return per_game_avgs, diffs


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
      gap: 10px;
    }

    .top-bar-left {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .top-bar-title {
      font-size: 16px;
      font-weight: 500;
    }

    .last-updated {
      font-size: 11px;
      color: var(--text-muted);
    }

    .legend {
      display: inline-flex;
      gap: 10px;
      align-items: center;
      background: rgba(15,23,42,0.4);
      border-radius: 999px;
      padding: 4px 10px;
      border: 1px solid rgba(148,163,184,0.3);
      white-space: nowrap;
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
      .legend {
        margin-left: auto;
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

      <!-- New: explicit recompute button -->
      <div class="button-row" style="margin-top: 8px;">
        <button onclick="recalc()">
          <span>Generate graphs</span>
        </button>
      </div>
    </section>
  </aside>

  <!-- RIGHT PANEL -->
  <main class="right-panel">
    <div class="top-bar">
      <div class="top-bar-left">
        <div class="top-bar-title">Live Team Analytics</div>
        <div class="last-updated">
          Stats last updated:
          {% if last_updated %}
            {{ last_updated }}
          {% else %}
            (no CSVs found)
          {% endif %}
        </div>
      </div>
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

<script>
  const TEAM_NAMES = {{ team_names | tojson }};
  let draggedEl = null;

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

    // no auto recalc
  }

  function clearTeams() {
    TEAM_NAMES.forEach(t => {
      document.getElementById('team-' + t).innerHTML = '';
    });
    // no auto recalc
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
        // no auto recalc
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

  async function recalc() {
    const teams = collectTeamsFromDOM();
    try {
      const resp = await fetch('/api/recalc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teams }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
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

</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    last_updated = get_last_stats_updated()
    return render_template_string(
        TEMPLATE,
        team_names=TEAM_NAMES,
        legend_items=TEAM_HEX_ITEMS,
        last_updated=last_updated,
    )


@app.route("/api/recalc", methods=["POST"])
def api_recalc():
    data = request.get_json(force=True)
    teams = data.get("teams", {})

    for name in TEAM_NAMES:
        teams.setdefault(name, [])

    per_game_avgs, team_diffs = recompute_team_stats(teams)

    per_game_img = plot_all_games(per_game_avgs)
    diff_img = plot_differentials(team_diffs)

    return jsonify(
        ok=True,
        per_game_img=per_game_img,
        diff_img=diff_img,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
