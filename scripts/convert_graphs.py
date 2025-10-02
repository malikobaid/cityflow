#!/usr/bin/env python3
"""
Convert NetworkX .gpickle graphs to lightweight JSON format.

This script processes existing .gpickle graph files and converts them
to compressed JSON format with only essential node and edge data.

Usage:
    python scripts/convert_graphs.py
"""

import os
import json
import gzip
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any

import pickle
import networkx as nx
import numpy as np

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPHS_DIR = PROJECT_ROOT / "transport_sim" / "data" / "graphs"
OUTPUT_DIR = GRAPHS_DIR  # Convert in place

def load_graph(file_path: Path):
    """Load NetworkX graph from .gpickle file."""
    try:
        # NetworkX gpickle files are pickled NetworkX graphs
        with open(file_path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        log.error(f"Failed to load {file_path}: {e}")
        return None

def extract_minimal_graph_data(G: nx.Graph) -> Tuple[Dict, List]:
    """
    Extract only essential node and edge data from NetworkX graph.
    Returns: (nodes_dict, edges_list)
    """
    nodes = {}
    edges = []

    # First pass: collect all valid nodes
    valid_node_ids = set()
    for node_id, node_data in G.nodes(data=True):
        # Keep only lat/lon if available, otherwise skip
        if 'x' in node_data and 'y' in node_data:
            nodes[node_id] = {
                'lat': float(node_data['y']),  # NetworkX uses y for lat, x for lon
                'lon': float(node_data['x'])
            }
            valid_node_ids.add(node_id)
        elif 'lon' in node_data and 'lat' in node_data:
            nodes[node_id] = {
                'lat': float(node_data['lat']),
                'lon': float(node_data['lon'])
            }
            valid_node_ids.add(node_id)
        else:
            log.warning(f"Node {node_id} missing coordinates, skipping")

    # Second pass: collect only edges where both nodes are valid
    valid_edges = 0
    for u, v, edge_data in G.edges(data=True):
        # Only include edges where both nodes are valid
        if u in valid_node_ids and v in valid_node_ids:
            # Keep only length if available
            length = edge_data.get('length', 1.0)
            if isinstance(length, str):
                try:
                    length = float(length)
                except ValueError:
                    length = 1.0

            edges.append({
                'u': u,
                'v': v,
                'length': float(length)
            })
            valid_edges += 1

    log.info(f"Extracted {len(nodes)} nodes and {valid_edges} valid edges (out of {len(G.edges())} total edges)")
    return nodes, edges

def save_lightweight_graph(city_name: str, nodes: Dict, edges: List) -> Tuple[Path, Path]:
    """Save nodes and edges as compressed JSON files."""
    # Save nodes
    nodes_path = OUTPUT_DIR / f"{city_name}_nodes.json.gz"
    with gzip.open(nodes_path, 'wt', encoding='utf-8') as f:
        json.dump(nodes, f, indent=2)

    # Save edges
    edges_path = OUTPUT_DIR / f"{city_name}_edges.json.gz"
    with gzip.open(edges_path, 'wt', encoding='utf-8') as f:
        json.dump(edges, f, indent=2)

    log.info(f"Saved {nodes_path} ({nodes_path.stat().st_size} bytes)")
    log.info(f"Saved {edges_path} ({edges_path.stat().st_size} bytes)")

    return nodes_path, edges_path

def convert_single_graph(file_path: Path) -> bool:
    """Convert a single .gpickle file to lightweight format."""
    city_name = file_path.stem

    log.info(f"Converting {city_name}...")

    # Load original graph
    G = load_graph(file_path)
    if G is None:
        return False

    # Extract minimal data
    nodes, edges = extract_minimal_graph_data(G)

    if not nodes or not edges:
        log.warning(f"No valid data extracted from {city_name}")
        return False

    # Save lightweight version
    save_lightweight_graph(city_name, nodes, edges)

    return True

def main():
    """Convert all .gpickle files in graphs directory."""
    log.info("Starting graph conversion process...")

    if not GRAPHS_DIR.exists():
        log.error(f"Graphs directory not found: {GRAPHS_DIR}")
        return

    # Find all .gpickle files
    gpickle_files = list(GRAPHS_DIR.glob("*.gpickle"))

    if not gpickle_files:
        log.warning(f"No .gpickle files found in {GRAPHS_DIR}")
        return

    log.info(f"Found {len(gpickle_files)} .gpickle files to convert")

    success_count = 0
    total_original_size = 0
    total_new_size = 0

    for file_path in gpickle_files:
        original_size = file_path.stat().st_size
        total_original_size += original_size

        if convert_single_graph(file_path):
            success_count += 1

            # Calculate new size
            city_name = file_path.stem
            nodes_path = OUTPUT_DIR / f"{city_name}_nodes.json.gz"
            edges_path = OUTPUT_DIR / f"{city_name}_edges.json.gz"

            if nodes_path.exists() and edges_path.exists():
                new_size = nodes_path.stat().st_size + edges_path.stat().st_size
                total_new_size += new_size

                compression_ratio = (1 - new_size / original_size) * 100
                log.info(f"  Compression: {original_size:,} - {new_size:,} bytes ({compression_ratio:.1f}% reduction)")

    log.info(f"Conversion complete: {success_count}/{len(gpickle_files)} successful")
    log.info(f"Total size: {total_original_size:,} → {total_new_size:,} bytes ({(1 - total_new_size/total_original_size)*100:.1f}% reduction)")

    if success_count > 0:
        log.info("Lightweight graphs saved to transport_sim/data/graphs/")
        log.info("You can now remove the original .gpickle files to save space")

if __name__ == "__main__":
    main()