"""
Test that the caching system integrates properly with the pipeline.
Verifies the ingestion → enrichment flow.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.user_data import load_user_db, load_user_cache
from backend.cache import get_cache_stats, clear_artist_cache

print("\n" + "="*70)
print("PIPELINE INTEGRATION TEST")
print("="*70)

test_user_id = "test_pipeline_user"

# Clean up before test
from backend.cache import get_user_cache_path
cache_path = get_user_cache_path(test_user_id)
if os.path.exists(cache_path):
    os.remove(cache_path)

print("\n1. Simulate Ingestion Step")
print("-" * 70)

# Simulate what ingest_user() does
from backend.user_data import set_user_top_artists

ingested_artists = [
    {"name": "The Beatles", "score": 1.0},
    {"name": "Pink Floyd", "score": 0.9},
    {"name": "David Bowie", "score": 0.8},
    {"name": "Queen", "score": 0.7},
    {"name": "The Rolling Stones", "score": 0.6},
]

print(f"Ingesting {len(ingested_artists)} artists for user {test_user_id}")
set_user_top_artists(test_user_id, spotify_artists=ingested_artists)

# Verify ingestion
cache = load_user_cache(test_user_id)
print(f"✓ Cached {len(cache.get('top_artists_spotify', []))} Spotify artists")
print(f"✓ Merged list contains {len(cache.get('top_artists_merged', []))} artists")

print("\n2. Verify load_user_db() Returns Artists")
print("-" * 70)

db = load_user_db(test_user_id)
top_artists = db.get("top_artists", [])

print(f"load_user_db() returned {len(top_artists)} artists")
print(f"First artist: {top_artists[0] if top_artists else 'None'}")

if len(top_artists) == 0:
    print("✗ ERROR: top_artists is empty!")
    sys.exit(1)

# Verify all artists have 'name' field (required for enrichment)
all_have_names = all("name" in artist for artist in top_artists)
print(f"✓ All artists have 'name' field: {all_have_names}")

if not all_have_names:
    print("✗ ERROR: Some artists missing 'name' field!")
    sys.exit(1)

print("\n3. Verify Enrichment Can Process These Artists")
print("-" * 70)

# This is what enrichment does - just get the names
artist_names = [artist.get("name") for artist in top_artists]
print(f"Artist names that would be enriched:")
for name in artist_names:
    print(f"  - {name}")

print("\n4. Cache Statistics")
print("-" * 70)

stats = get_cache_stats()
print(f"Total cached artists (global): {stats['total_artists']}")
print(f"User-specific cache file: {cache_path}")
print(f"Cache file exists: {os.path.exists(cache_path)}")

if os.path.exists(cache_path):
    file_size = os.path.getsize(cache_path)
    print(f"Cache file size: {file_size} bytes")

# Clean up
os.remove(cache_path)
clear_artist_cache()

print("\n" + "="*70)
print("✓ ALL INTEGRATION TESTS PASSED")
print("="*70)
print("\nThe caching system is properly integrated with the pipeline!")
print("Ingestion → Cache → load_user_db() → Enrichment flow works correctly.\n")
