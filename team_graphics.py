from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from PIL import Image, ImageDraw, ImageFont

from config import (
    SCOPES,
    CREDENTIALS_PATH,
    TOKEN_PATH,
    TEAMS_SPREADSHEET_ID,
    TEAM_RANGES,
    HEAD_LOCATION,
    TEAM_GRAPHICS_DIR,
    AVATAR_BASE_URL,
    AVATAR_SIZE,
    PLAYER_FONT_PATH,
    TITLE_FONT_PATH,
)


# ---------------------------------------------------------------------------
# Pillow compatibility (Resampling enum)
# ---------------------------------------------------------------------------

try:
    Resampling = Image.Resampling  # Pillow 9.1+
except AttributeError:  # older Pillow
    class _Resampling:
        NEAREST = Image.NEAREST
        LANCZOS = Image.LANCZOS
    Resampling = _Resampling()


# ---------------------------------------------------------------------------
# Google Sheets helpers
# ---------------------------------------------------------------------------

def get_sheets_service():
    """
    Build and return an authorized Google Sheets API service
    using the credentials in config.py.
    """
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
    Fetch the team name and 4 player names from a column range like 'Main!A35:A39'.

    Expected layout:
      Row 1: 'Red Team' (team name)
      Row 2–5: player IGN (one per row, first column).
    """
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=TEAMS_SPREADSHEET_ID,
        range=range_name,
    ).execute()

    values = result.get("values", [])
    if len(values) < 5:
        raise ValueError(f"Expected at least 5 rows in range {range_name}, got {len(values)}")

    team_name = values[0][0].strip()
    players = [row[0].strip() for row in values[1:5]]
    return team_name, players


# ---------------------------------------------------------------------------
# Skin download helpers
# ---------------------------------------------------------------------------

def download_player_heads(players: List[str], dest_dir: Path) -> List[Path]:
    """
    Download avatar heads for each player into dest_dir using AVATAR_BASE_URL
    and AVATAR_SIZE from config.py, and return list of file paths.
    """
    print("\nLoading skins...")
    dest_dir.mkdir(parents=True, exist_ok=True)

    head_paths: List[Path] = []

    for name in players:
        avatar_url = f"{AVATAR_BASE_URL}/{name}/{AVATAR_SIZE}.png"
        print(f"Obtaining skin for {name} from {avatar_url}")

        try:
            resp = requests.get(avatar_url, stream=True, timeout=10)
        except requests.RequestException as exc:
            print(f"[ERROR] Request failed for {name}: {exc}")
            continue

        if not resp.ok:
            snippet = resp.text[:200]
            print(
                f"[ERROR] Failed to fetch avatar for {name}: "
                f"{resp.status_code} {snippet!r}"
            )
            continue

        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            snippet = resp.text[:200]
            print(
                f"[ERROR] Non-image content for {name}. "
                f"Content-Type={content_type!r}. Snippet={snippet!r}"
            )
            continue

        head_path = dest_dir / f"{name}.png"
        with head_path.open("wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        print(f"Saved skin for {name} to {head_path}")
        head_paths.append(head_path)

    return head_paths


# ---------------------------------------------------------------------------
# Gradient background helpers
# ---------------------------------------------------------------------------

def team_gradient_colors(team_name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """
    Return (top_color, bottom_color) RGB tuples for a light gradient
    based on the team name (Red / Yellow / Green / Blue).
    """
    base = team_name.split()[0].lower()

    if base == "red":
        # light red → slightly darker red
        return (255, 204, 204), (255, 102, 102)       # #ffcccc → #ff6666
    elif base == "yellow":
        # light yellow → slightly richer yellow
        return (255, 249, 179), (255, 224, 102)       # #fff9b3 → #ffe066
    elif base == "green":
        # light green → medium green
        return (194, 240, 194), (102, 204, 102)       # #c2f0c2 → #66cc66
    elif base == "blue":
        # light blue → medium blue
        return (194, 224, 255), (102, 163, 255)       # #c2e0ff → #66a3ff
    else:
        # fallback neutral gradient
        return (230, 230, 230), (200, 200, 200)


def apply_vertical_gradient(image: Image.Image,
                            top_color: tuple[int, int, int],
                            bottom_color: tuple[int, int, int]) -> None:
    """
    Paint a vertical gradient onto `image` from top_color to bottom_color.
    Operates in-place.
    """
    width, height = image.size
    draw = ImageDraw.Draw(image)

    for y in range(height):
        t = y / (height - 1) if height > 1 else 0
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


# ---------------------------------------------------------------------------
# Team graphic creation
# ---------------------------------------------------------------------------

def create_team_graphic(
    team_name: str,
    players: List[str],
    head_image_paths: List[Path],
    output_dir: Path,
    width: int = 1040,
    height: int = 430,
) -> Path:
    """
    Create a single team graphic with 4 player heads and text.
    Uses a light vertical gradient background based on team color.
    """

    if len(players) != 4:
        raise ValueError(f"Expected exactly 4 players, got {len(players)}")

    if len(head_image_paths) < len(players):
        print("[WARN] Not all head images were downloaded successfully. "
              "Missing players will be skipped.")

    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Gradient background ---
    top_color, bottom_color = team_gradient_colors(team_name)
    image = Image.new("RGB", (width, height), color=top_color)
    apply_vertical_gradient(image, top_color, bottom_color)

    # Layout settings (head size & positions)
    HEAD_SIZE = 150
    thumb_size = (HEAD_SIZE, HEAD_SIZE)

    heads: List[Image.Image] = []
    for path in head_image_paths:
        if path.exists():
            im = Image.open(path)
            im = im.resize(thumb_size, Resampling.NEAREST)
            heads.append(im)
        else:
            print(f"[WARN] Head image not found: {path}")

    # Use your original centering offsets:
    #   x = i * (160 + 80) + 80
    # and align center of head to y=240
    for i, head in enumerate(heads[:4]):
        x = i * (160 + 80) + 80
        y = 240 - (HEAD_SIZE // 2)  # center vertically with the text row
        image.paste(head, (x, y))

    draw = ImageDraw.Draw(image)

    # Fonts from config
    player_font = ImageFont.truetype(str(PLAYER_FONT_PATH), size=30)
    title_font = ImageFont.truetype(str(TITLE_FONT_PATH), size=120)

    # Player labels
    x_positions = [160, 400, 640, 880]
    y_text = 360

    for i, player in enumerate(players):
        bbox = draw.textbbox((0, 0), player, font=player_font)
        text_width = bbox[2] - bbox[0]
        x_centered = x_positions[i] - (text_width / 2)
        draw.text((x_centered, y_text), player, fill=(0, 0, 0), font=player_font)

    # Team name at top
    title_text = team_name.strip()
    bbox_title = draw.textbbox((0, 0), title_text, font=title_font)
    title_width = bbox_title[2] - bbox_title[0]
    title_x = (width / 2) - (title_width / 2)
    title_y = 30
    draw.text((title_x, title_y), title_text, fill=(0, 0, 0), font=title_font)

    output_path = output_dir / f"{title_text}.png"
    image.save(output_path)
    print(f"Saved team graphic: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Overview image (2x2 grid of the 4 team graphics)
# ---------------------------------------------------------------------------

def create_overview_image(team_image_paths: List[Path], output_path: Path) -> None:
    """
    Combine four team images into a 2x2 overview image.
    Assumes all team images are the same size.
    """
    if len(team_image_paths) != 4:
        raise ValueError(f"Expected 4 team images, got {len(team_image_paths)}")

    images = [Image.open(p).convert("RGB") for p in team_image_paths]
    w, h = images[0].size

    overview = Image.new("RGB", (w * 2, h * 2))

    overview.paste(images[0], (0, 0))
    overview.paste(images[1], (w, 0))
    overview.paste(images[2], (0, h))
    overview.paste(images[3], (w, h))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    overview.save(output_path)
    print(f"Saved overview image: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    service = get_sheets_service()

    team_image_paths: List[Path] = []

    for rng in TEAM_RANGES:
        team_name, players = fetch_team_from_sheet(service, rng)
        print(f"\nProcessing range {rng} → team {team_name!r} with players {players}")

        head_paths = download_player_heads(players, HEAD_LOCATION)
        team_img_path = create_team_graphic(
            team_name=team_name,
            players=players,
            head_image_paths=head_paths,
            output_dir=TEAM_GRAPHICS_DIR,
        )
        team_image_paths.append(team_img_path)

    # 2x2 combined image of all four teams
    overview_path = TEAM_GRAPHICS_DIR / "All Teams.png"
    create_overview_image(team_image_paths, overview_path)


if __name__ == "__main__":
    main()
