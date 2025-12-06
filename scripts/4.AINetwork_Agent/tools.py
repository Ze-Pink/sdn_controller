"""
Tools custom pour l'automatisation réseau.
Contient: Neo4j GDS (Graph Data Science) + Traffic Engineering (NSO).

Auteur: Marc De Oliveira
Date: 2025
"""

from neo4j import GraphDatabase, Driver
from vertexai.generative_models import FunctionDeclaration
import config


class NetworkTools:
    """
    Classe regroupant tous les tools custom pour l'automatisation réseau.
    """
    
    def __init__(self):
        """Initialise la connexion Neo4j et la configuration."""
        self.driver: Driver = GraphDatabase.driver(
            config.NEO4J_URI, 
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )
        self.graph_name = config.GDS_GRAPH_PROJECTION_NAME
        self.database = config.NEO4J_DATABASE
        self.weight_property_alias = config.WEIGHT_PROPERTY
        print("   🔌 Connexion Neo4j établie")
    
    def close(self):
        """Ferme la connexion Neo4j."""
        if self.driver:
            self.driver.close()
            print("   🔌 Connexion Neo4j fermée")
    
    def __enter__(self):
        """Support du context manager: with NetworkTools() as tools:"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Fermeture automatique en sortie de context manager."""
        self.close()
    
    # ==============================================
    # Neo4j GDS - Graph Data Science
    # ==============================================
    
    def create_graph_projection(self, weight_property_name: str = 'igp_metric') -> str:
        """Crée une projection GDS avec mapping dynamique des propriétés."""
        try:
            # Supprimer ancienne projection
            try:
                records, _, _ = self.driver.execute_query(
                    "CALL gds.graph.list() YIELD graphName RETURN graphName", 
                    database_=self.database
                )
                if any(r['graphName'] == self.graph_name for r in records):
                    self.driver.execute_query(
                        f"CALL gds.graph.drop('{self.graph_name}')", 
                        database_=self.database
                    )
            except:
                pass
            
            # Récupérer propriétés
            records, _, _ = self.driver.execute_query(
                "MATCH ()-[r:PROD_ROUTING_LINK]->() WITH r LIMIT 1 RETURN properties(r) as props",
                database_=self.database
            )
            if not records:
                return "Erreur: Aucune propriété trouvée"
            
            all_props = records[0]['props']
            numeric_props = [k for k, v in all_props.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            
            if not numeric_props:
                return "Erreur: Aucune propriété numérique"
            
            # Config projection
            props_config = []
            if weight_property_name in numeric_props:
                props_config.append(f"weight: {{ property: '{weight_property_name}', defaultValue: 1.0 }}")
            else:
                props_config.append("weight: { property: 'igp_metric', defaultValue: 1.0 }")
            
            for prop in numeric_props:
                props_config.append(f"{prop}: {{ property: '{prop}', defaultValue: 0.0 }}")
            
            props_string = ", ".join(list(set(props_config)))
            
            # Créer projection
            create_query = f"""
                CALL gds.graph.project(
                    $graph_name,
                    'PROD_ROUTER',
                    {{
                        PROD_ROUTING_LINK: {{
                            orientation: 'NATURAL',
                            properties: {{ {props_string} }}
                        }}
                    }}
                )
                YIELD graphName, nodeCount, relationshipCount
                RETURN graphName, nodeCount, relationshipCount
            """
            records, _, _ = self.driver.execute_query(
                create_query, 
                graph_name=self.graph_name, 
                database_=self.database
            )
            
            if records:
                print(f"   ✅ Projection créée: {records[0]['nodeCount']} nœuds, {records[0]['relationshipCount']} relations")
            return f"Projection '{self.graph_name}' créée"
        except Exception as e:
            return f"Erreur: {e}"
    
    def _calculate_shortest_path_data(self, start_node: str, end_node: str, weight_property: str) -> dict:
        """
        Méthode privée: calcule le plus court chemin (Dijkstra) et retourne les données brutes.
        Utilisée par find_shortest_path() et perform_traffic_engineering().
        """
        create_result = self.create_graph_projection(weight_property)
        if "Erreur" in create_result:
            return {"error": create_result}
        
        dijkstra_query = """
            MATCH (source:PROD_ROUTER {name: $start_node}), (target:PROD_ROUTER {name: $end_node})
            CALL gds.shortestPath.dijkstra.stream($graph_name, { 
                sourceNode: source, targetNode: target, 
                relationshipWeightProperty: $weight_property_alias 
            })
            YIELD totalCost, nodeIds
            RETURN totalCost, [node IN gds.util.asNodes(nodeIds) | node.name] AS nodeNames
            LIMIT 1
        """
        
        try:
            records, _, _ = self.driver.execute_query(
                dijkstra_query,
                start_node=start_node, 
                end_node=end_node,
                graph_name=self.graph_name,
                weight_property_alias=self.weight_property_alias,
                database_=self.database
            )
            
            if not records:
                return {"error": f"Aucun chemin trouvé entre {start_node} et {end_node}"}
            
            node_names = records[0]['nodeNames']
            total_cost = records[0]['totalCost']
            
            # Récupérer les propriétés des segments
            path_parts = []
            for i in range(len(node_names) - 1):
                if i == 0:
                    path_parts.append(f"(n{i}:PROD_ROUTER {{name: $node{i}}})")
                path_parts.append(f"-[r{i}:PROD_ROUTING_LINK]->")
                path_parts.append(f"(n{i+1}:PROD_ROUTER {{name: $node{i+1}}})")
            
            props_query = f"MATCH {' '.join(path_parts)} RETURN " + ", ".join([f"properties(r{i}) AS rel{i}_props" for i in range(len(node_names) - 1)])
            params = {f"node{i}": node_names[i] for i in range(len(node_names))}
            
            prop_records, _, _ = self.driver.execute_query(
                props_query, 
                **params, 
                database_=self.database
            )
            
            if not prop_records:
                return {"error": "Propriétés segments introuvables"}
            
            segments = [prop_records[0][f'rel{i}_props'] for i in range(len(node_names) - 1)]
            
            return {"total_cost": total_cost, "node_names": node_names, "segments": segments}
        except Exception as e:
            return {"error": f"Erreur GDS: {e}"}
    
    def find_shortest_path(self, start_node: str, end_node: str, weight_property: str = 'igp_metric') -> str:
        """Tool: Trouve le plus court chemin et retourne une description textuelle."""
        path_data = self._calculate_shortest_path_data(start_node, end_node, weight_property)
        
        if path_data.get("error"):
            return path_data["error"]
        
        output = f"🛤️  Chemin: {' → '.join(path_data['node_names'])}\n"
        output += f"💰 Coût: {path_data['total_cost']}\n\n"
        output += "📊 Segments:\n" + "=" * 60 + "\n"
        
        for i, segment in enumerate(path_data['segments']):
            output += f"\n🔗 {path_data['node_names'][i]} → {path_data['node_names'][i+1]}\n"
            for k, v in sorted(segment.items()):
                output += f"   • {k}: {v}\n"
        
        return output + "=" * 60
    
    # ==============================================
    # Traffic Engineering - NSO
    # ==============================================
    
    def perform_traffic_engineering(self, start_node: str, end_node: str, service_type: str, 
                                    service_name: str, weight_property: str = 'igp_metric') -> str:
        """Tool: Génère la configuration XML NSO pour traffic engineering."""
        path_data = self._calculate_shortest_path_data(start_node, end_node, weight_property)
        
        if path_data.get("error"):
            return path_data["error"]
        
        # Calcul color
        try:
            color = 100 + int(end_node.lstrip('R'))
        except:
            color = 100
        
        # Extraction SIDs
        label_paths = ""
        for segment in path_data['segments']:
            sid = segment.get('sr_adjacency_sid')
            if not sid:
                return "Erreur: Segment sans 'sr_adjacency_sid'"
            label_paths += f"    <label-path>{sid}</label-path>\n"
        
        # XML
        xml = f"""
<config xmlns="http://tail-f.com/ns/config/1.0">
  <traffic-engineering xmlns="http://example.com/traffic-engineering">
    <source>{start_node}</source>
    <destination>{end_node}</destination>
    <color>{color}</color>
    <service-type>{service_type.lower()}</service-type>
    <service-name>{service_type.upper()}-{service_name.upper()}</service-name>
{label_paths.rstrip()}
  </traffic-engineering>
</config>
"""
        return xml.strip()


# ==============================================
# Déclarations pour Vertex AI (fonctions globales)
# ==============================================

def get_shortest_path_declaration():
    """Déclaration du tool find_shortest_path pour Vertex AI."""
    return FunctionDeclaration(
        name="find_shortest_path",
        description="Trouve le plus court chemin entre deux nœuds PROD_ROUTER. Utilise 'igp_metric' par défaut, mais peut aussi utiliser 'distance' si l'utilisateur le précise. Retourne une description textuelle.",
        parameters={
            "type": "object",
            "properties": {
                "start_node": {"type": "string", "description": "Nœud de départ (ex: R1)"},
                "end_node": {"type": "string", "description": "Nœud d'arrivée (ex: R3)"},
                "weight_property": {"type": "string", "description": "Propriété poids", "enum": ["igp_metric", "distance"], "default": "igp_metric"}
            },
            "required": ["start_node", "end_node"]
        }
    )


def get_traffic_engineering_declaration():
    """Déclaration du tool perform_traffic_engineering pour Vertex AI."""
    return FunctionDeclaration(
        name="perform_traffic_engineering",
        description="Calcule un chemin et génère la configuration XML NSO pour traffic engineering d'un service (ex: VPRN, EVPN).",
        parameters={
            "type": "object",
            "properties": {
                "start_node": {"type": "string", "description": "Nœud source (ex: R1)"},
                "end_node": {"type": "string", "description": "Nœud destination (ex: R3)"},
                "service_type": {"type": "string", "description": "Type de service (vprn, evpn)"},
                "service_name": {"type": "string", "description": "Nom ou suffixe du service (ex: TSP)"},
                "weight_property": {"type": "string", "enum": ["igp_metric", "distance"], "default": "igp_metric", "description": "Propriété pour le calcul du poids (ex: igp_metric, distance)"}
            },
            "required": ["start_node", "end_node", "service_type", "service_name"]
        }
    )
