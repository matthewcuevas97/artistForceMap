import json
import os
import random
import requests

# --- Configuration ---
API_KEY = os.environ.get("LASTFM_API_KEY")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"
GRAPH_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
NUM_ARTISTS_TO_TEST = 5

def fetch_tags_from_endpoint(artist_name, method):
    """Makes a raw request to the Last.fm API and returns the list of tags."""
    if not API_KEY:
        raise ValueError("LASTFM_API_KEY environment variable not set.")

    params = {
        "method": method,
        "artist": artist_name,
        "api_key": API_KEY,
        "format": "json",
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()

        if "error" in data:
            print(f"  API Error for '{artist_name}' ({method}): {data.get('message')}")
            return []

        if method == "artist.getInfo":
            return data.get("artist", {}).get("tags", {}).get("tag", [])
        elif method == "artist.getTopTags":
            return data.get("toptags", {}).get("tag", [])

    except requests.exceptions.RequestException as e:
        print(f"  HTTP Error for '{artist_name}' ({method}): {e}")
    except json.JSONDecodeError:
        print(f"  JSON Decode Error for '{artist_name}' ({method}).")

    return []

def main():
    """Main function to run the API comparison test."""
    print("--- Last.fm API Tag Comparison Test ---")

    # 1. Parse graph_static.json and select random artists
    try:
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            graph = json.load(f)
        all_artists = [node["name"] for node in graph["nodes"]]
        if len(all_artists) < NUM_ARTISTS_TO_TEST:
            print(f"Error: Not enough artists in graph_static.json to test {NUM_ARTISTS_TO_TEST} artists.")
            return
        selected_artists = random.sample(all_artists, NUM_ARTISTS_TO_TEST)
        print(f"Selected {NUM_ARTISTS_TO_TEST} random artists for testing.\n")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading or parsing '{GRAPH_PATH}': {e}")
        return

    # 2. Make requests and compare tag counts for each artist
    for artist_name in selected_artists:
        print(f"Artist: {artist_name}")

        # Fetch from artist.getInfo
        info_tags = fetch_tags_from_endpoint(artist_name, "artist.getInfo")
        info_tag_count = len(info_tags)
        print(f"  - `artist.getInfo` returned: {info_tag_count} tags")

        # Fetch from artist.getTopTags
        top_tags = fetch_tags_from_endpoint(artist_name, "artist.getTopTags")
        top_tag_count = len(top_tags)
        print(f"  - `artist.getTopTags` returned: {top_tag_count} tags")

        # 4. Print comparison notes
        if info_tag_count < top_tag_count:
            note = f"Note: `getInfo` appears to be capped (at {info_tag_count}), while `getTopTags` provides a more extensive list."
        elif info_tag_count == top_tag_count and info_tag_count > 0:
            note = "Note: Both endpoints returned the same number of tags."
        else:
            note = "Note: No significant difference in tag counts observed."
        print(f"  {note}\n")

if __name__ == "__main__":
    main()
