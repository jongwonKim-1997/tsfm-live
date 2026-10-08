import subprocess


def generate_cards(root):
    subprocess.run(["node", "scripts/cards.mjs"], cwd=root / "site", check=True, timeout=120)
