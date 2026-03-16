"""
Seed artist selection: greedy algorithm to select 5 diverse seed artists.
Uses Maximal Marginal Relevance: maximize rank while minimizing tag overlap.
"""

from typing import Dict, List, Set, Tuple
from backend.user_data import load_user_db, update_user_db


def jaccard_similarity(tags_a: Set[str], tags_b: Set[str]) -> float:
    """
    Calculate Jaccard similarity between two tag sets.
    Returns 0 (completely different) to 1 (identical).
    """
    if not tags_a and not tags_b:
        return 0.0
    intersection = len(tags_a & tags_b)
    union = len(tags_a | tags_b)
    return intersection / union if union > 0 else 0.0


def tag_distance(tags_a: Set[str], tags_b: Set[str]) -> float:
    """
    Calculate tag distance (1 - similarity).
    Higher distance = less overlap (more diverse).
    """
    return 1.0 - jaccard_similarity(tags_a, tags_b)


def calculate_diversity_score(
    candidate_name: str,
    candidate_data: Dict,
    selected_artists: List[str],
    all_artists: Dict,
    lambda_param: float = 0.7,
) -> float:
    """
    Calculate MMR score for a candidate artist.
    Score = lambda * rank_score - (1 - lambda) * avg_similarity_to_selected

    lambda_param: 0-1, weight of rank vs diversity
      - Higher lambda: prioritize rank (affinity to user)
      - Lower lambda: prioritize diversity
    """
    # Rank score: normalized to 0-1 (rank 1 = 1.0, rank 25 = 0.0)
    candidate_rank = candidate_data.get("rank", 25)
    rank_score = 1.0 - (candidate_rank - 1) / 24.0

    # Diversity score: average tag distance from selected artists
    candidate_tags = set(candidate_data.get("tags", []))
    if not selected_artists:
        diversity_score = 1.0  # Max diversity if no artists selected yet
    else:
        tag_distances = []
        for selected_name in selected_artists:
            selected_data = all_artists.get(selected_name, {})
            selected_tags = set(selected_data.get("tags", []))
            dist = tag_distance(candidate_tags, selected_tags)
            tag_distances.append(dist)
        diversity_score = sum(tag_distances) / len(tag_distances)

    # Combined MMR score
    mmr_score = lambda_param * rank_score + (1 - lambda_param) * diversity_score

    return mmr_score


def select_seed_artists(user_id: str, num_seeds: int = 5, lambda_param: float = 0.7) -> Dict:
    """
    Greedy selection of seed artists.
    1. Auto-select the #1 ranked artist.
    2. For remaining slots, pick the artist with highest MMR score.

    Args:
        user_id: User identifier
        num_seeds: Number of seed artists to select (default 5)
        lambda_param: Weight balance (0.7 = 70% rank, 30% diversity)

    Returns:
        Dictionary with seed_artists list and scores.
    """
    db = load_user_db(user_id)
    all_artists = db.get("all_artists", {})

    if not all_artists:
        raise ValueError(f"No enriched artists found for user {user_id}. Run tag_enrichment first.")

    # Step 1: Auto-select rank #1 artist
    rank_1_artist = None
    for name, data in all_artists.items():
        if data.get("rank") == 1:
            rank_1_artist = name
            break

    if not rank_1_artist:
        # Fallback: pick the highest-ranked artist
        rank_1_artist = min(all_artists.items(), key=lambda x: x[1].get("rank", 25))[0]

    selected_artists = [rank_1_artist]
    seed_selection_log = [
        {
            "artist": rank_1_artist,
            "reason": "auto-selected (rank #1)",
            "score": 1.0,
        }
    ]

    print(f"Selecting {num_seeds} seed artists for user {user_id}...")
    print(f"  [1/{num_seeds}] {rank_1_artist} (auto-selected, rank #1)")

    # Step 2: Greedy selection for remaining slots
    for slot in range(2, num_seeds + 1):
        best_candidate = None
        best_score = -1.0
        scores = {}

        for artist_name, artist_data in all_artists.items():
            # Skip already selected artists
            if artist_name in selected_artists:
                continue

            # Calculate MMR score
            score = calculate_diversity_score(
                artist_name,
                artist_data,
                selected_artists,
                all_artists,
                lambda_param=lambda_param,
            )
            scores[artist_name] = score

            if score > best_score:
                best_score = score
                best_candidate = artist_name

        if not best_candidate:
            print(f"  Warning: Could not find {num_seeds} diverse artists")
            break

        selected_artists.append(best_candidate)
        seed_selection_log.append({
            "artist": best_candidate,
            "reason": "greedy MMR selection",
            "score": best_score,
            "rank": all_artists[best_candidate].get("rank"),
        })

        print(f"  [{slot}/{num_seeds}] {best_candidate} (score: {best_score:.3f})")

    # Save seed artists to database
    db["seed_artists"] = selected_artists
    db["seed_selection_log"] = seed_selection_log
    update_user_db(user_id, {
        "seed_artists": selected_artists,
        "seed_selection_log": seed_selection_log,
    })

    return {
        "user_id": user_id,
        "seed_artists": selected_artists,
        "selection_log": seed_selection_log,
    }
