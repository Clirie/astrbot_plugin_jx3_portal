import json
from pathlib import Path

GAME_COMMANDS = json.loads((Path(__file__).resolve().parents[2] / 'data/game_commands.json').read_text())
GAME_MAP = {row['key']: row for row in GAME_COMMANDS}
