"""
Main pipeline orchestrator for user-specific map initialization.
Chains together all steps: ingestion → enrichment → seed selection → graph init.
"""

from typing import Dict, Any

from backend.user_ingestion import ingest_user
from backend.tag_enrichment import enrich_top_25_artists
from backend.seed_selection import select_seed_artists
from backend.graph_init import initialize_user_graph


def run_full_pipeline(auth_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the complete pipeline for a new user.

    Steps:
    1. User Ingestion: Fetch top 25 artists
    2. Tag Enrichment: Enrich with Last.fm data
    3. Seed Selection: Select 5 diverse seed artists
    4. Graph Init: Build initial graph with seed artists

    Args:
        auth_data: {provider, id, name, token/refresh_token}

    Returns:
        Pipeline result with all outputs
    """
    user_id = auth_data.get("id")
    print(f"\n{'='*60}")
    print(f"STARTING PIPELINE FOR USER: {user_id}")
    print(f"{'='*60}\n")

    # Step 1: User Ingestion
    print("STEP 1: User Ingestion")
    print("-" * 60)
    try:
        ingestion_result = ingest_user(auth_data)
        print(f"✓ Fetched {ingestion_result['top_artists_count']} top artists\n")
    except Exception as e:
        print(f"✗ Ingestion failed: {str(e)}\n")
        raise

    # Step 2: Tag Enrichment
    print("STEP 2: Tag Enrichment")
    print("-" * 60)
    try:
        enrichment_result = enrich_top_25_artists(user_id)
        print(f"✓ Enriched {enrichment_result['enriched_count']} artists\n")
    except Exception as e:
        print(f"✗ Enrichment failed: {str(e)}\n")
        raise

    # Step 3: Seed Selection
    print("STEP 3: Seed Artist Selection (Maximal Marginal Relevance)")
    print("-" * 60)
    try:
        selection_result = select_seed_artists(user_id, num_seeds=5, lambda_param=0.7)
        print(f"✓ Selected {len(selection_result['seed_artists'])} seed artists")
        for item in selection_result['selection_log']:
            print(f"  - {item['artist']} (score: {item.get('score', 'N/A')})\n")
    except Exception as e:
        print(f"✗ Seed selection failed: {str(e)}\n")
        raise

    # Step 4: Graph Initialization
    print("STEP 4: Graph Initialization")
    print("-" * 60)
    try:
        graph_result = initialize_user_graph(user_id)
        print(f"✓ Graph initialized with {len(graph_result['graph']['nodes'])} nodes")
        print(f"✓ Edges: {len(graph_result['graph']['edges'])}")
        print(f"✓ Saved to user_map.json\n")
    except Exception as e:
        print(f"✗ Graph init failed: {str(e)}\n")
        raise

    print(f"{'='*60}")
    print(f"PIPELINE COMPLETE FOR USER: {user_id}")
    print(f"{'='*60}\n")

    return {
        "user_id": user_id,
        "provider": auth_data.get("provider"),
        "ingestion": ingestion_result,
        "enrichment": enrichment_result,
        "seed_selection": selection_result,
        "graph_init": graph_result,
    }


def run_pipeline_step(
    user_id: str,
    step: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Run a single pipeline step (for re-running or partial updates).

    Args:
        user_id: User identifier
        step: One of ['enrichment', 'seed_selection', 'graph_init']
        **kwargs: Additional arguments for the step

    Returns:
        Step result
    """
    step_functions = {
        "enrichment": lambda: enrich_top_25_artists(user_id),
        "seed_selection": lambda: select_seed_artists(
            user_id,
            num_seeds=kwargs.get("num_seeds", 5),
            lambda_param=kwargs.get("lambda_param", 0.7),
        ),
        "graph_init": lambda: initialize_user_graph(user_id),
    }

    if step not in step_functions:
        raise ValueError(f"Unknown step: {step}. Must be one of {list(step_functions.keys())}")

    print(f"Running step: {step} for user: {user_id}")
    return step_functions[step]()
