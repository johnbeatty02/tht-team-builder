# THT Team Builder

Drag-and-drop team builder for the Hypixel Tournament. Players are assigned to 4 teams,
and the app shows per-game averages + team differentials live.

## Local setup

```bash
git clone https://github.com/<your-username>/tht-team-builder.git
cd tht-team-builder

# (Optional) create venv
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Run the web app
python app.py
