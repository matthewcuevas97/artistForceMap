import os
import sys
import time
import requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LASTFM_API_KEY")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Diverse sample across expected genres
SAMPLE = [
    # Electronic
    "Disclosure", "Solomun", "Anyma", "Boys Noize", "Subtronics",
    "Major Lazer", "Kaskade", "Green Velvet", "Duke Dumont", "REZZ",
    # Indie/Alt
    "The Strokes", "The XX", "Interpol", "Wet Leg", "Turnstile",
    "Alex G", "Geese", "Wednesday", "Laufey", "Ethel Cain",
    # Hip-Hop
    "Young Thug", "Sexyy Red", "Central Cee", "Little Simz", "CLIPSE",
    "Swae Lee", "Davido", "BIA",
    # Pop
    "Sabrina Carpenter", "Justin Bieber", "KAROL G", "PinkPantheress",
    "Addison Rae", "Teddy Swims", "KATSEYE", "BINI",
    # Rock/Punk
    "Black Flag", "Suicidal Tendencies", "DRAIN", "Fleshwater",
    "Hot Mulligan", "Joyce Manor", "Blondshell",
    # Other
    "Iggy Pop", "David Byrne", "Moby", "Devo", "FKA twigs",
    "Blood Orange", "Labrinth", "Fujii Kaze",
]

all_tags = []
artist_tags = {}

for i, artist in enumerate(SAMPLE, 1):
    print(f"Fetching {i}/{len(SAMPLE)}: {artist}")
    params = {
        "method": "artist.getInfo",
        "artist": artist,
        "api_key": API_KEY,
        "format": "json",
    }
    r = requests.get(BASE_URL, params=params)
    data = r.json()
    if "error" in data:
        print(f"  NOT FOUND: {artist}")
        continue
    tags = [t["name"].lower() for t in data.get("artist", {}).get("tags", {}).get("tag", [])]
    artist_tags[artist] = tags
    all_tags.extend(tags)
    time.sleep(0.25)

print("\n=== TOP 60 TAGS ACROSS SAMPLE ===")
for tag, count in Counter(all_tags).most_common(60):
    print(f"  {count:3}  {tag}")

print("\n=== PER ARTIST (first 5 tags) ===")
for artist, tags in artist_tags.items():
    print(f"  {artist:25} {tags[:5]}")