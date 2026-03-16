"""
Backend module for universal map prototype.
"""

from backend.user_data import (
    load_user_db,
    save_user_db,
    load_user_map,
    save_user_map,
    get_or_create_user,
)
from backend.user_ingestion import (
    login_spotify,
    login_lastfm,
    ingest_user,
)
from backend.tag_enrichment import enrich_top_25_artists
from backend.seed_selection import select_seed_artists
from backend.graph_init import initialize_user_graph
from backend.pipeline import run_full_pipeline, run_pipeline_step

__all__ = [
    "load_user_db",
    "save_user_db",
    "load_user_map",
    "save_user_map",
    "get_or_create_user",
    "login_spotify",
    "login_lastfm",
    "ingest_user",
    "enrich_top_25_artists",
    "select_seed_artists",
    "initialize_user_graph",
    "run_full_pipeline",
    "run_pipeline_step",
]
