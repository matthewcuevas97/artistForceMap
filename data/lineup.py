import csv
import os


def load_lineup():
    """
    Read artist lineup data from data/coachella_2026.csv.

    Returns a list of dicts with keys:
        name        - artist display name (str)
        day         - day of performance e.g. "Friday" (str)
        weekend     - which weekend: "1", "2", or "Both" (str)
        stage       - stage name, blank for now (str)
        spotify_id  - Spotify artist ID, populated later by merge (str or None)
        score       - user affinity score 0.0-1.0, populated later by merge (float or None)
    """
    csv_path = os.path.join(os.path.dirname(__file__), "coachella_2026.csv")
    lineup = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_lastfm = row["lastfm_artists"]
            lastfm_artists = [s for s in raw_lastfm.split("|") if s] if raw_lastfm else []
            lineup.append({
                "name": row["name"],
                "day": row["day"],
                "weekend": row["weekend"],
                "stage": row["stage"],
                "spotify_id": None,
                "score": None,
                "lastfm_artists": lastfm_artists,
            })
    return lineup
