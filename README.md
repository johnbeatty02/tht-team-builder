# THT Team Builder

The **THT Team Builder** is a lightweight web application for constructing balanced teams for Thomas’s Hypixel Tournament.  
It provides real-time analytics, visualizations, and substitution logic based on pre-generated game statistics.

---

## Overview

The application loads a set of stat CSVs (one per game mode) and exposes an interactive UI for organizing players into four teams:

- Red  
- Yellow  
- Green  
- Blue  

As the team composition changes, the app recomputes:

- **Per-game average points per player**
- **Team total score differentials** vs. the global mean
- **Substitution logic** for players without available stats

Graphs are rendered on-demand and update only when the user explicitly requests a recalculation.

---

## Features

### Team Construction UI
- Paste player names (comma-separated or newline-separated) into the pool input.
- Drag players between the unassigned pool and team containers.
- Team assignments persist until modified.

### Substitution Workflow
If a player is missing from a game’s stats:
- The API returns the unresolved players and the set of available statistical substitutes.
- A modal prompts the user to assign a substitute or mark the player as ignored.
- Substitutions may be applied per-game or globally at the user’s choice.

Computation does not proceed until all missing players are resolved.

### Analytics
Two visualization types are produced:

1. **Per-Game Averages**  
   - A fixed grid of small charts  
   - Shows per-player average points for each team

2. **Team Differentials**  
   - One chart per team  
   - Displays `(team total − average team total)` across all non-overall game modes

Plots are rendered to in-memory PNGs and returned to the UI as Base64 data URLs.

### Data Freshness Indicators
The UI displays standardized EST timestamps for:
- Last modification time of any CSV in `/stats`
- The currently loaded CSV revision

---

## User Workflow

1. Paste player names → click **Load to pool**  
2. Drag players into the four teams  
3. Click **Recalculate Graphs**  
4. Resolve missing-player substitutions when prompted  
5. Updated analytics appear in the right panel

Recalculation is *only* triggered by the button, not by drag-and-drop.

---

## CSV Requirements

Filenames must match `GAME_CONFIGS` in `config.py`.

Stat CSVs must be regenerated externally before use.  
A helper script (`generate_csvs.py`) may be used for this purpose.

---

## Technology Stack

- **Flask** — backend service + API routes  
- **Matplotlib / NumPy** — visualization and numeric computation  
- **Vanilla JS + HTML/CSS** — interactive dragging UI  
- **Render** — recommended hosting platform  

No database is required; the application is stateless.

---

## Deployment Notes

- Designed to run as a single Flask web service.  
- CSV files must exist in `/stats` at startup.  
- Substitution mappings are maintained in-memory per session.  
- The server listens on `$PORT` (compatible with Render’s platform requirements).

---
