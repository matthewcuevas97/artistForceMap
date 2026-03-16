"""
Example: Running the full universal map pipeline.

This demonstrates how to use the backend pipeline directly (without Flask).
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline import run_full_pipeline


def example_spotify():
    """
    Example: Create a map for a Spotify user.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE: Creating Universal Map for Spotify User")
    print("=" * 70 + "\n")

    # For this example, we'll mock the auth_data
    # In real usage, you'd get this from OAuth callback
    auth_data = {
        "provider": "spotify",
        "id": "spotify_user_example",
        "name": "Example User",
        "token": "your_spotify_access_token_here",
    }

    try:
        result = run_full_pipeline(auth_data)
        print("\n✓ Pipeline completed successfully!")
        print(f"\nResults saved to:")
        print(f"  - data/users/{auth_data['id']}_db.json")
        print(f"  - data/users/{auth_data['id']}_map.json")
        return result
    except Exception as e:
        print(f"\n✗ Pipeline failed: {str(e)}")
        return None


def example_lastfm():
    """
    Example: Create a map for a Last.fm user.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE: Creating Universal Map for Last.fm User")
    print("=" * 70 + "\n")

    auth_data = {
        "provider": "lastfm",
        "id": "lastfm_username_here",
        "name": "Last.fm User",
    }

    try:
        result = run_full_pipeline(auth_data)
        print("\n✓ Pipeline completed successfully!")
        print(f"\nResults saved to:")
        print(f"  - data/users/{auth_data['id']}_db.json")
        print(f"  - data/users/{auth_data['id']}_map.json")
        return result
    except Exception as e:
        print(f"\n✗ Pipeline failed: {str(e)}")
        return None


def example_individual_steps():
    """
    Example: Running individual pipeline steps.
    Useful for debugging or partial updates.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE: Running Individual Pipeline Steps")
    print("=" * 70 + "\n")

    from backend.user_ingestion import ingest_user
    from backend.tag_enrichment import enrich_top_25_artists
    from backend.seed_selection import select_seed_artists
    from backend.graph_init import initialize_user_graph

    user_id = "example_user_123"

    # Step 1: Ingest
    print("Step 1: Ingesting user data...")
    auth_data = {
        "provider": "lastfm",
        "id": user_id,
        "name": "Example",
    }
    ingest_result = ingest_user(auth_data)
    print(f"✓ Fetched {ingest_result['top_artists_count']} top artists\n")

    # Step 2: Enrich
    print("Step 2: Enriching with Last.fm data...")
    enrich_result = enrich_top_25_artists(user_id)
    print(f"✓ Enriched {enrich_result['enriched_count']} artists\n")

    # Step 3: Seed Selection
    print("Step 3: Selecting seed artists...")
    selection_result = select_seed_artists(user_id, num_seeds=5, lambda_param=0.7)
    print(f"✓ Selected {len(selection_result['seed_artists'])} seed artists\n")

    # Step 4: Graph Init
    print("Step 4: Initializing graph...")
    graph_result = initialize_user_graph(user_id)
    print(f"✓ Created graph with {len(graph_result['graph']['nodes'])} nodes\n")

    return {
        "ingestion": ingest_result,
        "enrichment": enrich_result,
        "seed_selection": selection_result,
        "graph_init": graph_result,
    }


def example_custom_seed_selection():
    """
    Example: Customizing seed artist selection parameters.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE: Custom Seed Selection Parameters")
    print("=" * 70 + "\n")

    from backend.seed_selection import select_seed_artists

    user_id = "example_user_123"

    # More diverse selection (lower lambda)
    print("Scenario 1: Maximize diversity (lambda=0.3)")
    print("-" * 70)
    result_diverse = select_seed_artists(
        user_id,
        num_seeds=5,
        lambda_param=0.3,  # Prioritize diversity over rank
    )
    print(f"Selected: {result_diverse['seed_artists']}\n")

    # More rank-focused selection (higher lambda)
    print("Scenario 2: Maximize user affinity (lambda=0.9)")
    print("-" * 70)
    result_rank = select_seed_artists(
        user_id,
        num_seeds=5,
        lambda_param=0.9,  # Prioritize user's top artists
    )
    print(f"Selected: {result_rank['seed_artists']}\n")


def main():
    """
    Run examples.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Universal Map Pipeline Examples")
    parser.add_argument(
        "example",
        nargs="?",
        default="spotify",
        choices=["spotify", "lastfm", "steps", "params"],
        help="Which example to run",
    )

    args = parser.parse_args()

    if args.example == "spotify":
        example_spotify()
    elif args.example == "lastfm":
        example_lastfm()
    elif args.example == "steps":
        example_individual_steps()
    elif args.example == "params":
        example_custom_seed_selection()


if __name__ == "__main__":
    main()
