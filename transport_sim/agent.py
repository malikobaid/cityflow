import random
from transport_sim.lightweight_graph import LightweightGraph

class Agent:
    def __init__(self, id, home_node, graph, hub_node, mode='walk'):
        self.id = id
        self.home_node = home_node
        self.graph = graph
        self.hub_node = hub_node
        self.mode = mode
        self.route = []
        self.total_distance = 0
        self.status = 'active'

    def plan_route(self, adj_matrix=None):
        """Plan route using lightweight graph pathfinding."""
        try:
            if isinstance(self.graph, LightweightGraph):
                # Use lightweight graph methods with optional traffic-adjusted matrix
                self.total_distance = self.graph.shortest_path_length(self.home_node, self.hub_node, adj_matrix)

                if self.total_distance == float('inf'):
                    raise ValueError("No path found")

                # For route, we'll use a simplified approach since we don't have full path
                # In a complete implementation, you'd want to store the actual path
                self.route = [self.home_node, self.hub_node]

            else:
                # Fallback for NetworkX graphs (during transition)
                import networkx as nx
                self.route = nx.shortest_path(self.graph, self.home_node, self.hub_node, weight='length')
                self.total_distance = nx.shortest_path_length(self.graph, self.home_node, self.hub_node, weight='length')

        except Exception:
            if self.mode == "tram":
                # Fallback to walk
                self.mode = "walk"
                self.plan_route(adj_matrix)
            else:
                self.status = 'unreachable'
                self.route = []

    def switch_mode(self, new_mode):
        self.mode = new_mode
        self.plan_route()

    def step(self):
        # Not implemented: placeholder for future simulation steps
        pass

    def to_dict(self):
        return {
            "id": self.id,
            "home_node": self.home_node,
            "hub_node": self.hub_node,
            "mode": self.mode,
            "status": self.status,
            "distance": self.total_distance,
            "route": self.route,
        }