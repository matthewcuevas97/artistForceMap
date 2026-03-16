"""
User data persistence layer using local JSON files.
"""

import json
import os
from typing import Any, Dict, List, Optional

USER_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "users")
os.makedirs(USER_DATA_DIR, exist_ok=True)


def get_user_db_path(user_id: str) -> str:
    """Get the path to a user's database file."""
    return os.path.join(USER_DATA_DIR, f"{user_id}_db.json")


def get_user_map_path(user_id: str) -> str:
    """Get the path to a user's map file."""
    return os.path.join(USER_DATA_DIR, f"{user_id}_map.json")


def load_user_db(user_id: str) -> Dict[str, Any]:
    """Load user database (enriched artist data)."""
    path = get_user_db_path(user_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "user_id": user_id,
        "top_artists": [],  # Top 25 from user's streaming
        "all_artists": {},  # Enriched data: {artist_name: {rank, tags, listeners, ...}}
        "seed_artists": [],  # Selected 5 diverse artists
    }


def save_user_db(user_id: str, data: Dict[str, Any]) -> None:
    """Save user database."""
    path = get_user_db_path(user_id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_user_map(user_id: str) -> Dict[str, Any]:
    """Load user's graph map (nodes and edges for frontend)."""
    path = get_user_map_path(user_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "user_id": user_id,
        "nodes": [],  # Seed artists with full metadata
        "edges": [],  # Connections between seed artists
    }


def save_user_map(user_id: str, data: Dict[str, Any]) -> None:
    """Save user's graph map."""
    path = get_user_map_path(user_id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_or_create_user(user_id: str, auth_data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Get or create a user record."""
    db = load_user_db(user_id)
    if not db.get("auth_provider"):
        db["auth_provider"] = auth_data.get("provider") if auth_data else "unknown"
        db["auth_id"] = auth_data.get("id") if auth_data else user_id
        save_user_db(user_id, db)
    return db


def update_user_db(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update specific fields in user database."""
    db = load_user_db(user_id)
    db.update(updates)
    save_user_db(user_id, db)
    return db
