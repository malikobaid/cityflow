import networkx as nx
import random

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

    def get_weight(self, u, v, data):
        length = data.get("length", 1)

        if self.mode == "walk":
            return length  # base distance
        elif self.mode == "cycle":
            if data.get("highway") in ["motorway", "trunk", "motorway_link"]:
                return float("inf")  # avoid dangerous roads
            return length * 1.1
        elif self.mode == "drive":
            speed = data.get("speed_kph", 30)
            return length / speed  # simulate time-based cost
        elif self.mode == "tram":
            return 0.1 if data.get("tram") else float("inf")

        return length  # fallback

    def plan_route(self):
        try:
            self.route = nx.shortest_path(self.graph, self.home_node, self.hub_node, weight='length')
            self.total_distance = nx.shortest_path_length(self.graph, self.home_node, self.hub_node, weight='length')
        except:
            if self.mode == "tram":
                # Fallback to walk
                self.mode = "walk"
                self.plan_route()
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
