"""
Lightweight graph operations for transportation simulation.

This module provides KDTree-based nearest node lookup and scipy-based
shortest path algorithms as replacements for osmnx and networkx.
"""

import json
import gzip
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
from scipy.spatial import KDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path

log = logging.getLogger(__name__)

class LightweightGraph:
    def shortest_path_nodes(self, source, target, adj_matrix=None):
        """
        Return (path_nodes, total_distance). Uses scipy.sparse shortest_path with predecessor backtracking.
        """
        import numpy as np
        from scipy.sparse.csgraph import shortest_path
        if source not in self.nodes or target not in self.nodes:
            return [], float("inf")
    
        matrix = adj_matrix if adj_matrix is not None else self.sparse_adj
        node_to_idx = {nid: i for i, nid in enumerate(self.node_ids)}
        src = node_to_idx.get(source)
        dst = node_to_idx.get(target)
        if src is None or dst is None:
            return [], float("inf")
    
        dist, pred = shortest_path(matrix, directed=False, indices=[src], return_predecessors=True)
        d = dist[0, dst]
        if not np.isfinite(d):
            return [], float("inf")
    
        # reconstruct
        path_idx = []
        i = dst
        while i != -9999 and i != src:
            path_idx.append(i)
            i = pred[0, i]
            if i == -9999:
                break
        path_idx.append(src)
        path_idx.reverse()
        path = [self.node_ids[i] for i in path_idx]
        return path, float(d)
    """Lightweight graph representation using numpy arrays and KDTree."""

    def __init__(self, nodes: Dict[int, Dict], edges: List[Dict]):
        print(f"Initializing LightweightGraph with {len(nodes)} nodes and {len(edges)} edges")
        self.nodes = nodes
        self.edges = edges
        self.node_ids = list(nodes.keys())
        self.node_count = len(self.node_ids)
        print(f"Total nodes: {self.node_count}")    
        # Build coordinate arrays for KDTree
        self.node_coords = np.array([
            [nodes[node_id]['lon'], nodes[node_id]['lat']]  # [lon, lat] for KDTree
            for node_id in self.node_ids
        ])
        print(f"Node coordinates shape: {self.node_coords.shape}")
        
        # Build KDTree for nearest neighbor lookup
        self.kdtree = KDTree(self.node_coords)
        print("KDTree built for nearest node lookup")
        # Build adjacency matrix for shortest path algorithms
        self._build_adjacency_matrix()
        print("Adjacency matrix built for shortest path calculations")

    
    def _build_adjacency_matrix(self):
        """Build a CSR sparse adjacency matrix from edges (always sparse by default)."""
        node_to_idx = {node_id: idx for idx, node_id in enumerate(self.node_ids)}

        # If you really want a dense matrix for tiny graphs, set a low threshold:
        use_dense = (self.node_count <= 1000) and (os.getenv("CF_FORCE_SPARSE", "0") != "1")

        if use_dense:
            # Dense only for tiny graphs; use float32 to halve memory
            self.adj_matrix = np.zeros((self.node_count, self.node_count), dtype=np.float32)
            valid_edges = 0
            for edge in self.edges:
                u, v = edge['u'], edge['v']
                if u in node_to_idx and v in node_to_idx:
                    length = edge['length']
                    ui, vi = node_to_idx[u], node_to_idx[v]
                    self.adj_matrix[ui, vi] = length
                    self.adj_matrix[vi, ui] = length  # undirected
                    valid_edges += 1
            print(f"Built dense adjacency (float32) with {valid_edges} valid edges out of {len(self.edges)} total edges")
            self.sparse_adj = csr_matrix(self.adj_matrix)
        else:
            # Always-safe path for Cloud Run and real city graphs
            self.sparse_adj = self._build_sparse_adjacency_matrix(node_to_idx)

    def _build_sparse_adjacency_matrix(self, node_to_idx):
        """Build CSR adjacency using COO assembly (fast) and convert to CSR."""
        rows = []
        cols = []
        data = []
        valid_edges = 0

        for edge in self.edges:
            u, v = edge['u'], edge['v']
            if u in node_to_idx and v in node_to_idx:
                length = edge['length']
                ui, vi = node_to_idx[u], node_to_idx[v]
                # undirected → add both directions
                rows.append(ui); cols.append(vi); data.append(length)
                rows.append(vi); cols.append(ui); data.append(length)
                valid_edges += 1

        n = self.node_count
        # dtype: choose float64 for maximum numerical parity; float32 halves memory
        rows = np.asarray(rows, dtype=np.int32)
        cols = np.asarray(cols, dtype=np.int32)
        data = np.asarray(data, dtype=np.float64)

        print(f"Built sparse adjacency vectors: edges={len(self.edges)}, valid_pairs={valid_edges*2}, nodes={n}")
        return csr_matrix((data, (rows, cols)), shape=(n, n))

    def nearest_node(self, lon: float, lat: float) -> Optional[int]:
        """
        Find nearest node to given coordinates using KDTree.

        Args:
            lon: Longitude
            lat: Latitude

        Returns:
            Node ID of nearest node, or None if no nodes available
        """
        if self.node_count == 0:
            return None

        query_point = np.array([[lon, lat]])
        distances, indices = self.kdtree.query(query_point, k=1)

        if indices[0] < self.node_count:
            return self.node_ids[indices[0]]

        return None

    def shortest_path_length(self, source: int, target: int, adj_matrix: Optional[csr_matrix] = None) -> float:
        """
        Calculate shortest path length between two nodes.

        Args:
            source: Source node ID
            target: Target node ID
            adj_matrix: Optional traffic-adjusted adjacency matrix

        Returns:
            Shortest path length, or inf if no path exists
        """
        if source not in self.nodes or target not in self.nodes:
            return float('inf')

        source_idx = self.node_ids.index(source)
        target_idx = self.node_ids.index(target)

        # Use provided matrix or default to base matrix
        matrix = adj_matrix if adj_matrix is not None else self.sparse_adj

        # Use scipy's shortest_path with directed=False for undirected graph
        try:
            distances, _ = shortest_path(
                matrix,
                directed=False,
                indices=[source_idx],
                return_predecessors=True
            )

            distance = distances[0, target_idx]
            return distance if distance != np.inf else float('inf')

        except Exception as e:
            log.warning(f"Error calculating shortest path: {e}")
            return float('inf')

    def has_path(self, source: int, target: int, adj_matrix: Optional[csr_matrix] = None) -> bool:
        """
        Check if a path exists between two nodes.

        Args:
            source: Source node ID
            target: Target node ID
            adj_matrix: Optional traffic-adjusted adjacency matrix

        Returns:
            True if path exists, False otherwise
        """
        if source not in self.nodes or target not in self.nodes:
            return False

        source_idx = self.node_ids.index(source)
        target_idx = self.node_ids.index(target)

        # Use provided matrix or default to base matrix
        matrix = adj_matrix if adj_matrix is not None else self.sparse_adj

        # Check if shortest path distance is finite
        try:
            distances, _ = shortest_path(
                matrix,
                directed=False,
                indices=[source_idx],
                return_predecessors=True
            )
            return distances[0, target_idx] != np.inf
        except Exception:
            return False

    def get_node_coordinates(self, node_id: int) -> Optional[Tuple[float, float]]:
        """Get (lat, lon) coordinates for a node."""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            return (node['lat'], node['lon'])
        return None

    def get_traffic_adjusted_matrix(self, traffic_level: str = "off-peak") -> csr_matrix:
        """
        Get adjacency matrix adjusted for traffic conditions.

        Args:
            traffic_level: "off-peak", "peak", "rush hour", etc.

        Returns:
            Traffic-adjusted sparse adjacency matrix
        """
        level = (traffic_level or "").strip().lower()
        is_peak = level in ("peak", "rush hour", "rush-hour", "rushhour")

        if not is_peak:
            # Off-peak: use base matrix
            return self.sparse_adj.copy()

        # Peak traffic: scale non-tram edges by 1.5
        # For large graphs, work with sparse matrix directly
        if hasattr(self, 'adj_matrix') and self.adj_matrix is not None:
            # Dense matrix case (smaller graphs)
            adjusted_matrix = self.adj_matrix.copy()

            # Create node index mapping
            node_to_idx = {node_id: idx for idx, node_id in enumerate(self.node_ids)}

            # Apply traffic scaling to non-tram edges
            scaled_edges = 0
            for edge in self.edges:
                u, v = edge['u'], edge['v']
                length = edge['length']

                # Check if this is a tram edge
                is_tram_edge = edge.get('tram', False)

                if not is_tram_edge and u in node_to_idx and v in node_to_idx:
                    # Scale non-tram edges for peak traffic
                    u_idx, v_idx = node_to_idx[u], node_to_idx[v]
                    adjusted_matrix[u_idx, v_idx] = length * 1.5
                    adjusted_matrix[v_idx, u_idx] = length * 1.5  # Assume undirected
                    scaled_edges += 1

            print(f"Applied traffic scaling to {scaled_edges} edges")
            return csr_matrix(adjusted_matrix)
        else:
            # Sparse matrix case (larger graphs) - modify the sparse matrix
            adjusted_sparse = self.sparse_adj.copy()

            # For large sparse matrices, we can't easily modify in place
            # Return the base matrix for now (traffic adjustment would need different implementation)
            print("Large graph detected - using base matrix for pathfinding")
            return adjusted_sparse

def load_lightweight_graph(city_name: str) -> Optional[LightweightGraph]:
    """
    Load lightweight graph for a city.

    Args:
        city_name: Name of the city (e.g., 'london_central')

    Returns:
        LightweightGraph instance or None if loading fails
    """
    graphs_dir = Path("transport_sim/data/graphs")

    # Try to load compressed JSON files
    nodes_path = graphs_dir / f"{city_name}_nodes.json.gz"
    edges_path = graphs_dir / f"{city_name}_edges.json.gz"

    if not (nodes_path.exists() and edges_path.exists()):
        log.warning(f"Lightweight graph files not found for {city_name}")
        print(f"Graph files not found for {city_name} at {nodes_path} and {edges_path}")
        return None
    try:
        # Load nodes
        print(f"Loading nodes from {nodes_path}")
        with gzip.open(nodes_path, 'rt', encoding='utf-8') as f:
            nodes_raw = json.load(f)
        # Coerce node IDs back to ints because JSON object keys are strings
        nodes = {int(k): v for k, v in nodes_raw.items()}

        # Load edges
        with gzip.open(edges_path, 'rt', encoding='utf-8') as f:
            edges_raw = json.load(f)
        # Ensure u,v are ints and length is float
        edges = []
        for e in edges_raw:
            try:
                u = int(e.get('u'))
                v = int(e.get('v'))
                length = float(e.get('length', 1.0))
                edges.append({'u': u, 'v': v, 'length': length, **{k:v for k,v in e.items() if k not in ('u','v','length')}})
            except Exception:
                # skip malformed edge
                continue

        log.info(f"Loaded lightweight graph for {city_name}: {len(nodes)} nodes, {len(edges)} edges")
        print(f"Loaded lightweight graph for {city_name}: {len(nodes)} nodes, {len(edges)} edges")
        lw_graph = None
        try:
            lw_graph =  LightweightGraph(nodes, edges)
        except Exception as e:
            print(f"Error initializing LightweightGraph: {e}")
        
        return lw_graph
        


    except Exception as e:
        log.error(f"Failed to load lightweight graph for {city_name}: {e}")
        return None

def load_city_graph(city_name: str) -> Optional[LightweightGraph]:
    """
    Load city graph using lightweight format.

    This is a drop-in replacement for the old NetworkX-based loader.
    """
    return load_lightweight_graph(city_name)