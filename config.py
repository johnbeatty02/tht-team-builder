from pathlib import Path
import os
import json

# -------------------------------
# Google Sheets API
# -------------------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

BASE_DIR = Path(__file__).resolve().parent

# ----------------------------------------
# Credentials handling (local vs Render)
# ----------------------------------------
#
# If running on Render:
#   - GOOGLE_CREDENTIALS contains the full JSON of credentials.json
#   - GOOGLE_TOKEN contains the full JSON of token.json
#
# We write them into ephemeral files at runtime so googleapiclient can use them.
#
# If running locally:
#   - Fall back to credentials.json and token.json normally


# --- Credentials.json ---
if os.environ.get("GOOGLE_CREDENTIALS"):
    # Running on Render
    creds_file = BASE_DIR / "credentials.json"
    creds_file.write_text(os.environ["GOOGLE_CREDENTIALS"], encoding="utf-8")
    CREDENTIALS_PATH = creds_file
else:
    # Local development
    CREDENTIALS_PATH = Path("credentials.json")


# --- Token.json ---
if os.environ.get("GOOGLE_TOKEN"):
    # Running on Render
    token_file = BASE_DIR / "token.json"
    token_file.write_text(os.environ["GOOGLE_TOKEN"], encoding="utf-8")
    TOKEN_PATH = token_file
else:
    # Local development
    TOKEN_PATH = Path("token.json")

# Team list spreadsheet
TEAMS_SPREADSHEET_ID = "1yJZMiaxCBvMe-D9sHCpgDgbu7wuo2xvxkj9ckLQEriA"

# Per-player stats spreadsheet (Season 7)
STATS_SPREADSHEET_ID = "1qhaOBnESHjYchaORuYl20kLMxjC0kOlM8XWRxTcEXTs"

# Ranges containing team name + 4 players
TEAM_RANGES = [
    "Main!A35:A39",
    "Main!A40:A44",
    "Main!A45:A49",
    "Main!A50:A54",
]

# -------------------------------
# Directories / Paths
# -------------------------------

BASE_DIR = Path(__file__).resolve().parent

STATS_DIR = BASE_DIR / "stats"

# Where Minecraft heads are downloaded
HEAD_LOCATION = BASE_DIR / "team_graphics" / "heads"

# Where generated team graphics go (team PNGs + allGames/differentials)
TEAM_GRAPHICS_DIR = BASE_DIR / "team_graphics"

# Where final summary reports are written (directory)
FINAL_REPORT_PATH = BASE_DIR / "reports"

# Where the final combined sheet (teams + graphs) is saved
FINAL_REPORT_DIR = BASE_DIR / "reports"

FINAL_REPORT_FILENAME = "team_report.png"


# -------------------------------
# Avatar API
# -------------------------------
AVATAR_BASE_URL = "https://mc-heads.net/avatar"
AVATAR_SIZE = 256

# -------------------------------
# Fonts
# -------------------------------

PLAYER_FONT_PATH = BASE_DIR / "team_graphics" / "fonts" / "Minecraft Regular.otf"

TITLE_FONT_PATH = BASE_DIR / "team_graphics" / "fonts" / "Minecraft Evenings.ttf"


# ----------------------------------------
# CSV column definitions for stats output
# ----------------------------------------
CSV_COLUMNS = ["Player", "Points"]

# -------------------------------
# Game Definitions
# -------------------------------
# These are used by BOTH stats.py and team_differentials.py
# key           : internal key
# name         : human-readable long name
# long_label   : label used on plots / logs
# short_label  : short label (x-axis, etc.)
# csv          : filename under STATS_DIR
# csv_name     : same as csv (for convenience)
# sheet_range  : range on STATS_SPREADSHEET_ID
# is_pvp       : base PvP game (for NON_PVP_GAMES / PvP aggregation)
# is_non_pvp   : base non-PvP game
# is_non_pvp_aggregate : True only for the Non-PvP aggregate row
# include_in_differentials : show in allGames / differentials charts
# enabled      : export from sheets → CSV (default True)
GAME_CONFIGS = [
    {
        "key": "overall",
        "name": "Overall",
        "long_label": "Overall",
        "short_label": "All",  # label used in the diff graph
        "csv": "overall.csv",
        "csv_name": "overall.csv",
        "sheet_range": "Main!P3:Q52",
        "is_overall": True,
        "is_pvp": False,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,  # <--- IMPORTANT
        "enabled": True,
    },
    {
        "key": "bedwars",
        "name": "Bedwars",
        "long_label": "Bedwars",
        "short_label": "BW",
        "csv": "bedwars.csv",
        "csv_name": "bedwars.csv",
        "sheet_range": "Bedwars!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "bridge_duels",
        "name": "Bridge Duels",
        "long_label": "Bridge Duels",
        "short_label": "BD",
        "csv": "bridgeDuels.csv",
        "csv_name": "bridgeDuels.csv",
        "sheet_range": "Bridge Duels!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "build_battle",
        "name": "Build Battle",
        "long_label": "Build Battle",
        "short_label": "BB",
        "csv": "buildBattle.csv",
        "csv_name": "buildBattle.csv",
        "sheet_range": "Build Battle!P3:Q52",
        "is_pvp": False,
        "is_non_pvp": True,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "mini_walls",
        "name": "Mini Walls",
        "long_label": "Mini Walls",
        "short_label": "MW",
        "csv": "miniWalls.csv",
        "csv_name": "miniWalls.csv",
        "sheet_range": "Mini Walls!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "parkour_duels",
        "name": "Parkour Duels",
        "long_label": "Parkour Duels",
        "short_label": "PD",
        "csv": "parkourDuels.csv",
        "csv_name": "parkourDuels.csv",
        "sheet_range": "Parkour Duels!P3:Q52",
        "is_pvp": False,
        "is_non_pvp": True,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "party_games",
        "name": "Party Games",
        "long_label": "Party Games",
        "short_label": "PG",
        "csv": "partyGames.csv",
        "csv_name": "partyGames.csv",
        "sheet_range": "Party Games!P3:Q52",
        "is_pvp": False,
        "is_non_pvp": True,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "skywars",
        "name": "Skywars",
        "long_label": "Skywars",
        "short_label": "SW",
        "csv": "skywars.csv",
        "csv_name": "skywars.csv",
        "sheet_range": "Skywars!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "survival_games",
        "name": "Survival Games",
        "long_label": "Survival Games",
        "short_label": "SG",
        "csv": "survivalGames.csv",
        "csv_name": "survivalGames.csv",
        "sheet_range": "Survival Games!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": False,
        "enabled": False,
    },
    {
        "key": "uhc_duels",
        "name": "UHC Duels",
        "long_label": "UHC Duels",
        "short_label": "UD",
        "csv": "uhcDuels.csv",
        "csv_name": "uhcDuels.csv",
        "sheet_range": "UHC Duels!P3:Q52",
        "is_pvp": True,
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "wobtafitv",
        "name": "WOBTAFITV",
        "long_label": "WOBTAFITV",
        "short_label": "WO",
        "csv": "wobtafitv.csv",
        "csv_name": "wobtafitv.csv",
        "sheet_range": "WOBTAFITV!P3:Q52",
        "is_pvp": False,
        "is_non_pvp": True,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": True,
    },
    {
        "key": "pvp",
        "name": "PvP",
        "long_label": "PvP",
        "short_label": "PvP",
        "csv": "pvp.csv",
        "csv_name": "pvp.csv",
        "sheet_range": "PvP!P3:Q52",
        "is_pvp": False,               # already aggregate
        "is_non_pvp": False,
        "is_non_pvp_aggregate": False,
        "include_in_differentials": True,
        "enabled": False,
    },
    {
        "key": "non_pvp",
        "name": "Non-PvP",
        "long_label": "Non-PvP",
        "short_label": "nP",
        "csv": "nonPvP.csv",
        "csv_name": "nonPvP.csv",
        "sheet_range": "Non-PvP!P3:Q52",
        "is_pvp": False,
        "is_non_pvp": False,           # this row is the aggregate
        "is_non_pvp_aggregate": True,  # used for averaging logic
        "include_in_differentials": True,
        "enabled": False,
    },
]

# Derive PvP / non-PvP counts from GAME_CONFIGS
PVP_GAMES = sum(1 for g in GAME_CONFIGS if g["is_pvp"])
NON_PVP_GAMES = sum(1 for g in GAME_CONFIGS if g["is_non_pvp"])


# ----------------------------------------
# Team Colors
# ----------------------------------------
# These RGB values are mainly for image generation / gradients.
TEAM_COLORS = {
    "red":    (255, 80, 80),
    "gold":   (255, 220, 120),
    "green":  (120, 220, 120),
    "blue":   (120, 180, 255),
}

# Stable order for teams (used by graphs)
TEAM_COLOR_NAMES = ["red", "gold", "green", "blue"]
