"""
Script qui à partir des données récupérées de GoBGP via gRPC,
des données de la CDB NSO et de LLDP, les pousse dans Neo4j.

Auteur: Marc De Oliveira
Date: 2025
"""

import time
import os
import json
import re
import logging
import time

from functools import wraps
from neo4j import GraphDatabase
from typing import Optional, Any, Dict, List
from dataclasses import dataclass, field


@dataclass
class Neo4jConfig:
    """
    Configuration pour la connexion Neo4j.
    
    Attributes:
        uri (str): L'URI du serveur Neo4j (ex: "neo4j://10.0.27.82:17687")
        user (str): Nom d'utilisateur pour l'authentification
        password (str): Mot de passe pour l'authentification
        encrypted (bool): Utiliser une connexion chiffrée ou non
        max_connection_lifetime (int): Durée de vie maximale d'une connexion en secondes
        max_connection_pool_size (int): Taille maximale du pool de connexions
        connection_acquisition_timeout (int): Timeout pour l'acquisition d'une connexion
        database (str): Nom de la base de données par défaut
    """
    uri: str
    user: str = "neo4j"
    password: str = "password"
    encrypted: bool = False
    max_connection_lifetime: int = 3600
    max_connection_pool_size: int = 50
    connection_acquisition_timeout: int = 60
    database: Optional[str] = None
    
    def __post_init__(self):
        """Validation des paramètres après initialisation."""
        if not self.uri:
            raise ValueError("L'URI ne peut pas être vide")
        if not self.uri.startswith(("neo4j://", "neo4j+s://", "neo4j+ssc://", "bolt://", "bolt+s://", "bolt+ssc://")):
            raise ValueError(f"URI invalide: {self.uri}. Doit commencer par neo4j:// ou bolt://")


@dataclass
class Neo4jConnection:
    """
    Classe de gestion de connexion à une base de données Neo4j.
    
    Attributes:
        config (Neo4jConfig): Configuration de la connexion
        driver: Le driver Neo4j pour gérer les connexions
        logger: Logger pour les messages de debug et d'erreur
    """
    config: Neo4jConfig
    driver: Any = field(init=False, default=None, repr=False)
    logger: logging.Logger = field(init=False, repr=False)
    
    def __post_init__(self):
        """Initialise la connexion après création de l'instance."""
        self.logger = logging.getLogger(__name__)
        self._connect()
    
    def _connect(self):
        """Établit la connexion au serveur Neo4j."""
        try:
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.user, self.config.password),
                encrypted=self.config.encrypted,
                max_connection_lifetime=self.config.max_connection_lifetime,
                max_connection_pool_size=self.config.max_connection_pool_size,
                connection_acquisition_timeout=self.config.connection_acquisition_timeout
            )
            self.logger.info(f"Connexion établie avec succès à {self.config.uri}")
        except Exception as e:
            self.logger.error(f"Erreur lors de la connexion à Neo4j: {str(e)}")
            raise
    
    def close(self):
        """Ferme la connexion au driver Neo4j."""
        if self.driver is not None:
            self.driver.close()
            self.driver = None
            self.logger.info("Connexion fermée")
    
    def verify_connectivity(self) -> bool:
        """
        Vérifie que la connexion au serveur est fonctionnelle.
        
        Returns:
            bool: True si la connexion est OK, False sinon
        """
        try:
            self.driver.verify_connectivity()
            self.logger.info("Connectivité vérifiée avec succès")
            return True
        except Exception as e:
            self.logger.error(f"Erreur de connectivité: {str(e)}")
            return False
    
    def query(self, query: str, parameters: Optional[Dict[str, Any]] = None, 
              db: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Exécute une requête Cypher et retourne les résultats.
        
        Args:
            query (str): La requête Cypher à exécuter
            parameters (dict, optional): Paramètres de la requête
            db (str, optional): Nom de la base de données (utilise config.database si non spécifié)
        
        Returns:
            List[Dict]: Liste des résultats sous forme de dictionnaires
        """
        assert self.driver is not None, "Driver non initialisé"
        
        database = db or self.config.database
        session = None
        response = []
        
        try:
            session = self.driver.session(database=database) if database else self.driver.session()
            result = session.run(query, parameters or {})
            
            for record in result:
                response.append(dict(record))
            
            self.logger.debug(f"Requête exécutée avec succès: {len(response)} résultats")
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'exécution de la requête: {str(e)}")
            raise
        finally:
            if session is not None:
                session.close()
        
        return response
    
    def execute_write(self, query: str, parameters: Optional[Dict[str, Any]] = None,
                     db: Optional[str] = None) -> Any:
        """
        Exécute une requête d'écriture dans une transaction.
        
        Args:
            query (str): La requête Cypher à exécuter
            parameters (dict, optional): Paramètres de la requête
            db (str, optional): Nom de la base de données (utilise config.database si non spécifié)
        
        Returns:
            Résultat de la requête
        """
        assert self.driver is not None, "Driver non initialisé"
        
        def _execute_write_tx(tx, query, parameters):
            result = tx.run(query, parameters or {})
            return [dict(record) for record in result]
        
        database = db or self.config.database
        session = None
        try:
            session = self.driver.session(database=database) if database else self.driver.session()
            result = session.execute_write(_execute_write_tx, query, parameters)
            self.logger.debug("Requête d'écriture exécutée avec succès")
            return result
        except Exception as e:
            self.logger.error(f"Erreur lors de l'exécution de la requête d'écriture: {str(e)}")
            raise
        finally:
            if session is not None:
                session.close()
    
    def execute_read(self, query: str, parameters: Optional[Dict[str, Any]] = None,
                    db: Optional[str] = None) -> Any:
        """
        Exécute une requête de lecture dans une transaction.
        
        Args:
            query (str): La requête Cypher à exécuter
            parameters (dict, optional): Paramètres de la requête
            db (str, optional): Nom de la base de données (utilise config.database si non spécifié)
        
        Returns:
            Résultat de la requête
        """
        assert self.driver is not None, "Driver non initialisé"
        
        def _execute_read_tx(tx, query, parameters):
            result = tx.run(query, parameters or {})
            return [dict(record) for record in result]
        
        database = db or self.config.database
        session = None
        try:
            session = self.driver.session(database=database) if database else self.driver.session()
            result = session.execute_read(_execute_read_tx, query, parameters)
            self.logger.debug("Requête de lecture exécutée avec succès")
            return result
        except Exception as e:
            self.logger.error(f"Erreur lors de l'exécution de la requête de lecture: {str(e)}")
            raise
        finally:
            if session is not None:
                session.close()
    
    def __enter__(self):
        """Support du context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ferme automatiquement la connexion à la sortie du context manager."""
        self.close()

def execution_time(func):
    """Décorateur pour mesurer le temps d'exécution d'une fonction."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_duration = end_time - start_time
        print(f"Fonction '{func.__name__}' exécutée en {execution_duration:.2f} secondes")
        return result
    return wrapper


#@execution_time
def set_delete_attribute(
    neo_connection: Neo4jConnection, 
    database: str = "neo4j",    
    delete: bool = True
) -> tuple:
    """
    Définit l'attribut 'delete' sur tous les nœuds et relations commençant par 'PROD_'.
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
        delete (bool): Valeur à définir pour l'attribut delete
    
    Returns:
        tuple: (result_node, result_relationship) résultats des requêtes
    """
    
    query_delete_propriety_node = f"""
        MATCH(n)
        WHERE any(label IN labels(n) WHERE label STARTS WITH 'PROD_')
        SET n.delete = {delete}
        RETURN count(n)
    """
    
    result_node = neo_connection.query(
        query=query_delete_propriety_node,
        parameters=None,
        db=database
    )
    
    query_delete_propriety_relationship = f"""
        MATCH (n)-[r]-(m)
        WHERE any(label IN labels(n) WHERE label STARTS WITH 'PROD_')
        AND any(label IN labels(m) WHERE label STARTS WITH 'PROD_')
        SET r.delete = {delete}
        RETURN count(r)
    """
    
    result_relationship = neo_connection.query(
        query=query_delete_propriety_relationship,
        parameters=None,
        db=database
    )
    
    return result_node, result_relationship


#@execution_time
def check_neo_constraints(
    neo_connection: Neo4jConnection, 
    neo_constraints: Dict[str, List[str]],
    database: str = "neo4j"
) -> None:
    """
    Vérifie et crée si nécessaire les contraintes d'unicité pour les nœuds Neo4j.
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        neo_constraints (dict): Dictionnaire {nom_label: [liste_propriétés_uniques]}
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        None
    """
    
    query_check_constraints = "SHOW CONSTRAINTS"
    
    result = neo_connection.query(
        query=query_check_constraints,
        parameters=None,
        db=database
    )
    
    # Construire une liste de toutes les contraintes attendues
    expected_constraints = []
    for label, properties in neo_constraints.items():
        for prop in properties:
            expected_constraints.append({
                "label": label,
                "property": prop,
                "name": f"{label}_{prop}"  # Nom de contrainte unique
            })
    
    # Vérifier quelles contraintes existent déjà
    existing_constraints = set()
    for constraint in result:
        constraint_name = constraint.get("name", "")
        existing_constraints.add(constraint_name)
    
    # Identifier les contraintes manquantes
    missing_constraints = []
    for expected in expected_constraints:
        if expected["name"] not in existing_constraints:
            missing_constraints.append(expected)
    
    # Afficher le résultat
    if not missing_constraints:
        print("✓ Toutes les contraintes et propriétés d'unicité sont déjà créées")
    else:
        for constraint in missing_constraints:
            print(f"Création de contrainte : {constraint['name']} sur {constraint['label']}.{constraint['property']}")
            
            query_create_constraint = (
                f"CREATE CONSTRAINT {constraint['name']} "
                f"FOR (n:{constraint['label']}) "
                f"REQUIRE n.{constraint['property']} IS UNIQUE"
            )
            
            neo_connection.query(
                query=query_create_constraint,
                parameters=None,
                db=database
            )


#@execution_time
def create_isis_topology_from_gobgp(
    neo_connection: Neo4jConnection,
    gobgp_database: Dict[str, Any],
    date: str,
    database: str = "neo4j"
) -> None:

    """
    Crée la topologie IS-IS dans Neo4j basée sur les données GoBGP.
    
    Cette fonction crée :
        - Nœuds routers : routeurs avec leurs propriétés (loopbacks, AS, etc.)
        - Noeuds IP : adresses IP des interfaces
        - Relations : liens IS-IS entre routeurs basés sur les interfaces IP
    """

    batch_router: List[Dict[str, Any]] = []
    batch_ip: List[Dict[str, Any]] = []
    batch_relation_router_ip: List[Dict[str, Any]] = []
    batch_relation_ip_isis_link: List[Dict[str, Any]] = []
    
    # Construction des batches
    for igp_router_id, attrs in gobgp_database['routers'].items():
        router = {
            "name": attrs['node_info']['node_name'],
            "properties": {
                "update_time": date,
                "delete": False
            }
        }

        local_router_id = attrs['node_info']['local_router_id']

        router_name = attrs['node_info']['node_name']
        router["properties"]["igp_router_id"] = attrs['node_info']['igp_router_id']
        router["properties"]["local_router_id"] = local_router_id
        router["properties"]["asn"] = attrs['node_info']['asn']
        router["properties"]["srgb_start"] = attrs['node_info']['sr_capabilities']['ranges'][0]['begin']
        batch_router.append(router)

        for prefix in attrs['prefixes']:
            if f'{local_router_id}/32' == prefix['prefix']:
                router["properties"]["sr_prefix_sid"] = prefix['sr_prefix_sid']
                router["properties"]["sr_prefix_sid_absolute"] = prefix['sr_prefix_sid'] + router["properties"]["srgb_start"]
                batch_router.append(router)

        for link in attrs['links']:
            ip_address_local = link['local_ip']
            ip_node_local = {
                "uid_isis_igp_router_id": f"{igp_router_id}_{ip_address_local}",
                "properties": {
                    "update_time": date,
                    "delete": False
                }
            }
            ip_node_local["properties"]["node_name"] = router_name
            ip_node_local["properties"]["uid_isis_router_name"] = f"{router_name}_{ip_address_local}"
            ip_node_local["properties"]["ip"] = ip_address_local
            batch_ip.append(ip_node_local)          

            ip_address_remote = link['remote_ip']
            remote_node_igp_router_id = link['remote_node_igp_router_id']
            ip_node_remote = {
                "uid_isis_igp_router_id": f"{remote_node_igp_router_id}_{ip_address_remote}",
                "properties": {
                    "update_time": date,
                    "delete": False
                }
            } 
            ip_node_remote["properties"]["ip"] = ip_address_remote
            batch_ip.append(ip_node_remote)

            relationship_router_ip = {
                "router": router_name,
                "uid_isis_router_name": f"{router_name}_{ip_address_local}",
                "properties": {
                    "update_time": date,
                    "delete": False
                }
            }           
            batch_relation_router_ip.append(relationship_router_ip)

            relationship_router_ip_isis = {
                "uid_isis_local": ip_node_local["uid_isis_igp_router_id"],
                "uid_isis_remote": ip_node_remote["uid_isis_igp_router_id"],
                "properties": {
                    "update_time": date,
                    "delete": False
                }
            }    
            
            relationship_router_ip_isis["properties"]["igp_metric"] = link['igp_metric']    
            relationship_router_ip_isis["properties"]["sr_adjacency_sid"] = link['sr_adjacency_sid'] 
            batch_relation_ip_isis_link.append(relationship_router_ip_isis)    

    # Exécution des requêtes en batch
    _create_router_nodes(neo_connection, batch_router, database)
    _create_ip_nodes(neo_connection, batch_ip, database)
    _create_router_ip_relationships(neo_connection, batch_relation_router_ip, database)
    _create_router_ip_isis_link(neo_connection, batch_relation_ip_isis_link, database)
   

def _add_property_if_exists(
    node: Dict[str, Any],
    attrs: Dict[str, Any],
    key1: str,
    key2: str | None,
    property_name: str
) -> None:
    """
    Ajoute une propriété au nœud si elle existe dans attrs.
    
    Args:
        node: Dictionnaire du nœud à enrichir
        attrs: Dictionnaire source contenant les attributs
        key1: Première clé à rechercher
        key2: Deuxième clé à rechercher (None si direct)
        property_name: Nom de la propriété à créer
    """
    try:
        if key2 is None:
            value = attrs[key1]
        else:
            value = attrs[key1][key2]
        node["properties"][property_name] = value
    except (KeyError, TypeError):
        pass


def _create_router_nodes(
    neo_connection: Neo4jConnection,
    batch_router: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les nœuds routeurs dans Neo4j."""
    if not batch_router:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MERGE (n:PROD_ROUTER {name: row.name})
        SET n += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    # IMPORTANT: Utiliser query() au lieu de execute_write() 
    # car IN TRANSACTIONS nécessite une transaction implicite
    neo_connection.query(
        query=query,
        parameters={"batch": batch_router},
        db=database
    )


def _create_ip_nodes(
    neo_connection: Neo4jConnection,
    batch_ip: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les nœuds routeurs dans Neo4j."""
    if not batch_ip:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MERGE (n:PROD_IP {uid_isis_igp_router_id: row.uid_isis_igp_router_id})
        SET n += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    # IMPORTANT: Utiliser query() au lieu de execute_write() 
    # car IN TRANSACTIONS nécessite une transaction implicite
    neo_connection.query(
        query=query,
        parameters={"batch": batch_ip},
        db=database
    )

def _create_router_ip_relationships(
    neo_connection: Neo4jConnection,
    batch_relation_router_ip: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations entre routeurs et préfixes dans Neo4j."""
    if not batch_relation_router_ip:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (r:PROD_IP {uid_isis_router_name: row.uid_isis_router_name})
        MATCH (p:PROD_ROUTER {name: row.router})
        MERGE (r)-[router_ip:PROD_IP_BELONGS_TO]->(p)
        SET router_ip += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    # IMPORTANT: Utiliser query() au lieu de execute_write() 
    # car IN TRANSACTIONS nécessite une transaction implicite
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_router_ip},
        db=database
    )


def _create_router_ip_isis_link(
    neo_connection: Neo4jConnection,
    batch_relation_ip_isis_link: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations entre routeurs et préfixes dans Neo4j."""
    if not batch_relation_ip_isis_link:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (r:PROD_IP {uid_isis_igp_router_id: row.uid_isis_local})
        MATCH (p:PROD_IP {uid_isis_igp_router_id: row.uid_isis_remote})
        MERGE (r)-[ip_isis_link:PROD_IP_ISIS_LINK]->(p)
        SET ip_isis_link += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    # IMPORTANT: Utiliser query() au lieu de execute_write() 
    # car IN TRANSACTIONS nécessite une transaction implicite
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_ip_isis_link},
        db=database
    )    


#@execution_time
def create_port_attach_logical_relationships(
    neo_connection: Neo4jConnection,
    nso_database: Dict[str, Any],
    date: str,
    database: str = "neo4j"
) -> None:
    """
    Crée les nœuds et relations Neo4j pour les ports, LAGs et interfaces logiques.
    
    Cette fonction crée :
        - Nœuds : ports physiques (PROD_PORT)
        - Nœuds : LAGs (PROD_LAG)
        - Nœuds : interfaces logiques (PROD_INT_LOGICAL)
        - Relations : PROD_IN_LAG entre ports et LAGs
        - Relations : PROD_LOGICAL_OF_LAG entre interfaces logiques et LAGs
        - Relations : PROD_LOGICAL_OF_ROUTER entre interfaces logiques et routeurs
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        nso_database (dict): Dictionnaire contenant les informations NSO
        date (str): Date de mise à jour au format string
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        None
    """
    
    batch_port: List[Dict[str, Any]] = []
    batch_lag: List[Dict[str, Any]] = []
    batch_relation_port_lag: List[Dict[str, Any]] = []
    batch_interface_logical: List[Dict[str, Any]] = []
    batch_relation_logical_lag: List[Dict[str, Any]] = []
    batch_relation_router_logical: List[Dict[str, Any]] = []

    for router, attrs in nso_database.items():
        # Traitement des ports physiques
        if "PORT" in attrs:
            for port, attach in attrs["PORT"].items():
                port_id = {
                    "uid": f"{router}_{port}",
                    "properties": {
                        "portId": port,
                        "update_time": date,
                        "delete": False
                    }
                }
                batch_port.append(port_id)

                if isinstance(attach, dict) and "LAG" in attach and attach["LAG"]:
                    lag_id = {
                        "uid": f"{router}_LAG{attach['LAG']}",
                        "properties": {
                            "name": attach['LAG'],
                            "update_time": date,
                            "delete": False
                        }
                    }
                    batch_lag.append(lag_id)

                    relationship_port_lag = {
                        "uid_port": f"{router}_{port}",
                        "uid_lag": f"{router}_LAG{attach['LAG']}",
                        "properties": {
                            'update_time': date,
                            "delete": False
                        }
                    }
                    batch_relation_port_lag.append(relationship_port_lag)

        # Traitement des interfaces logiques
        if "LOGICAL" in attrs:
            for itf_logical, itf_logical_attrs in attrs["LOGICAL"].items():
                if "IP" in itf_logical_attrs and itf_logical_attrs["IP"] != "":
                    name = itf_logical
                    prefix = itf_logical_attrs["IP"]
                    mask = itf_logical_attrs.get("MASK", "")
                    vlan = itf_logical_attrs.get("VLAN", "")
                    attach = itf_logical_attrs.get("ATTACH", "")

                    node_int = {
                        "uid": f"{router}_{name}",
                        "properties": {
                            "name": name,
                            "ip": prefix,
                            "mask": mask,
                            "vlan": vlan,
                            "router": router,
                            "update_time": date,
                            "delete": False
                        }
                    }
                    batch_interface_logical.append(node_int)

                    if attach:
                        relationship_logical_lag = {
                            "uid_logical": f"{router}_{name}",
                            "uid_lag": f"{router}_LAG{attach}",
                            "properties": {
                                "update_time": date,
                                "delete": False
                            }
                        }
                        batch_relation_logical_lag.append(relationship_logical_lag)

                    relationship_router_logical = {
                        "name_router": router,
                        "uid_logical": f"{router}_{name}",
                        "properties": {
                            "update_time": date,
                            "delete": False
                        }
                    }
                    batch_relation_router_logical.append(relationship_router_logical)

    # Exécution des requêtes en batch
    _create_port_nodes(neo_connection, batch_port, database)
    _create_lag_nodes(neo_connection, batch_lag, database)
    _create_port_lag_relationships(neo_connection, batch_relation_port_lag, database)
    _create_interface_logical_nodes(neo_connection, batch_interface_logical, database)
    _create_logical_lag_relationships(neo_connection, batch_relation_logical_lag, database)
    _create_router_logical_relationships(neo_connection, batch_relation_router_logical, database)
    

def _create_port_nodes(
    neo_connection: Neo4jConnection,
    batch_port: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les nœuds ports dans Neo4j."""
    if not batch_port:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MERGE (n:PROD_PORT {uid: row.uid})
        SET n += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_port},
        db=database
    )


def _create_lag_nodes(
    neo_connection: Neo4jConnection,
    batch_lag: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les nœuds LAG dans Neo4j."""
    if not batch_lag:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MERGE (n:PROD_LAG {uid: row.uid})
        SET n += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_lag},
        db=database
    )


def _create_port_lag_relationships(
    neo_connection: Neo4jConnection,
    batch_relation_port_lag: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations entre ports et LAGs dans Neo4j."""
    if not batch_relation_port_lag:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (p:PROD_PORT {uid: row.uid_port})
        MATCH (l:PROD_LAG {uid: row.uid_lag})
        MERGE (p)-[port_lag:PROD_IN_LAG]->(l)
        SET port_lag += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_port_lag},
        db=database
    )


def _create_interface_logical_nodes(
    neo_connection: Neo4jConnection,
    batch_interface_logical: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les nœuds interfaces logiques dans Neo4j."""
    if not batch_interface_logical:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MERGE (n:PROD_INT_LOGICAL {uid: row.uid})
        SET n += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_interface_logical},
        db=database
    )


def _create_logical_lag_relationships(
    neo_connection: Neo4jConnection,
    batch_relation_logical_lag: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations entre interfaces logiques et LAGs dans Neo4j."""
    if not batch_relation_logical_lag:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (logical:PROD_INT_LOGICAL {uid: row.uid_logical})
        MATCH (lag:PROD_LAG {uid: row.uid_lag})
        MERGE (logical)-[logical_of:PROD_LOGICAL_OF_LAG]->(lag)
        SET logical_of += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_logical_lag},
        db=database
    )


def _create_router_logical_relationships(
    neo_connection: Neo4jConnection,
    batch_relation_router_logical: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations entre interfaces logiques et routeurs dans Neo4j."""
    if not batch_relation_router_logical:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (r:PROD_ROUTER {name: row.name_router})
        MATCH (logical:PROD_INT_LOGICAL {uid: row.uid_logical})
        MERGE (logical)-[l:PROD_LOGICAL_OF_ROUTER]->(r)
        SET l += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_router_logical},
        db=database
    )


def _create_lldp_relationships(
    neo_connection: Neo4jConnection,
    batch_relation_lldp: List[Dict[str, Any]],
    database: str
) -> None:
    """Crée ou met à jour les relations LLDP entre ports dans Neo4j."""
    if not batch_relation_lldp:
        return
    
    query = """
    CALL () {
        UNWIND $batch as row
        MATCH (p1:PROD_PORT {uid: row.uid_local_port})
        MATCH (p2:PROD_PORT {uid: row.uid_remote_port})
        MERGE (p1)-[l:PROD_LLDP_LINK]->(p2)
        SET l += row.properties
    }
    IN TRANSACTIONS OF 1000 ROWS
    """
    
    neo_connection.query(
        query=query,
        parameters={"batch": batch_relation_lldp},
        db=database
    )


#@execution_time
def create_lldp_link(
    neo_connection: Neo4jConnection,
    nso_lldp_database: Dict[str, Any],
    date: str,
    database: str = "neo4j"
) -> None:
    """
    Crée les relations LLDP entre les interfaces physiques basées sur les données NSO.
    
    Cette fonction crée :
        - Relations : PROD_LLDP_LINK entre ports physiques de différents routeurs
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        nso_lldp_database (dict): Dictionnaire contenant les informations NSO
        date (str): Date de mise à jour au format string
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        None
    
    Example:
            >>> config = Neo4jConfig(uri="neo4j://10.0.27.82:17687", user="neo4j", password="pwd")
            >>> neo = Neo4jConnection(config)
            >>> create_lldp_link(neo, nso_lldp_database, "2024-11-02")
    """
    
    batch_relation_lldp: List[Dict[str, Any]] = []
    
    # Construction des batches
    for router, attrs in nso_lldp_database.items():
        
        # Traitement des loopbacks
        if "neighbors" in attrs and isinstance(attrs["neighbors"], dict):
            for local_port, neighbor_attrs in attrs["neighbors"].items():
                remote_device = neighbor_attrs["remote_device"]
                remote_port = neighbor_attrs["remote_port"]
                
                relationship_lldp = {
                    "uid_local_port": f"{router}_{local_port}",
                    "uid_remote_port": f"{remote_device}_{remote_port}",
                    "properties": {
                        "update_time": date,
                        "delete": False
                    }
                }
                batch_relation_lldp.append(relationship_lldp)
    
    # Exécution des requêtes en batch
    _create_lldp_relationships(neo_connection, batch_relation_lldp, database)


#@execution_time
def create_routing_relationship(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> List[Dict[str, Any]]:
    """
    Crée des relations de routage globales en combinant les relations ISIS.
    
    Cette fonction parcourt toutes les relations PROD_ISIS_LINK 
    entre interfaces logiques et crée des relations PROD_ROUTING_LINK directes 
    entre les routeurs correspondants, avec les métriques et informations de routage.
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        List[Dict]: Résultat de la requête Neo4j
    
    Example:
        >>> result = create_routing_relationship(neo)
    """
    
    # IMPORTANT: Relation directionnelle pour mapper exactement ISIS l1->l2 vers ROUTING r1->r2
    # Chaque relation ISIS crée une relation ROUTING correspondante dans la même direction
    query = """
        MATCH (r1)<-[:PROD_IP_BELONGS_TO]-(l1)-[ip:PROD_IP_ISIS_LINK]->(l2)-[:PROD_IP_BELONGS_TO]->(r2)
        MERGE (r1)-[routing:PROD_ROUTING_LINK]->(r2)
        SET routing.igp_metric = toInteger(ip.igp_metric),
            routing.sr_adjacency_sid = ip.sr_adjacency_sid,
            routing.src_rtr = r1.name,
            routing.dest_rtr = r2.name,              
            routing.src_ip = l1.ip,
            routing.dest_ip = l2.ip,
            routing.update_time = ip.update_time,
            routing.delete = ip.delete
        RETURN count(routing) as routing_links_created
    """
    
    result = neo_connection.query(
        query=query,
        parameters=None,
        db=database
    )

    return result


#@execution_time
def create_ip_logical_relationship(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> List[Dict[str, Any]]:
    """
    Crée des relations IP vers interfaces logiques.
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        List[Dict]: Résultat de la requête Neo4j
    
    Example:
        >>> result = create_ip_logical_relationship(neo)
    """
    
    query = """
        MATCH (ip:PROD_IP)-[:PROD_IP_BELONGS_TO]->(:PROD_ROUTER)<-[:PROD_LOGICAL_OF_ROUTER]-(logical:PROD_INT_LOGICAL)
        WHERE ip.uid_isis_router_name = logical.router+'_'+logical.ip
        MERGE (ip)-[ipof:PROD_IP_OF_INTERFACE]->(logical)
        SET ipof.update_time = ip.update_time,
            ipof.delete = ip.delete
        RETURN count(ipof) as ipof_links_created
    """
    
    result = neo_connection.query(
        query=query,
        parameters=None,
        db=database
    )
    
    return result


#@execution_time
def add_distance_attribute(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> None:
    """Crée un attribut distance sur la relation PROD_ROUTING_LINK dans Neo4j."""

    query = """
        UNWIND [
            {from: 'R1', to: 'R2', distance: 20},
            {from: 'R2', to: 'R1', distance: 20},
            {from: 'R1', to: 'R3', distance: 100},
            {from: 'R3', to: 'R1', distance: 100},
            {from: 'R2', to: 'R3', distance: 50},
            {from: 'R3', to: 'R2', distance: 50}
        ] AS data

        // 1. Trouver les nœuds de départ (n1) et d'arrivée (n2)
        MATCH (n1 {name: data.from})-[r:PROD_ROUTING_LINK]->(n2 {name: data.to})

        // 2. Mettre à jour la relation
        SET r.distance = data.distance

        // 3. Retourner les relations mises à jour (optionnel, pour vérification)
        RETURN n1.name, n2.name, r.distance
    """
    
    neo_connection.query(
        query=query,
        db=database
    )

def get_node_statistics(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> list:
    """Récupère les statistiques des nœuds par label dans Neo4j.
    
    Returns:
        Liste de dictionnaires contenant 'label' et 'NombreDeNoeuds'
    """
    
    query = """
        MATCH (n)
        UNWIND labels(n) AS label
        RETURN label, count(n) AS NombreDeNoeuds
        ORDER BY NombreDeNoeuds DESC
    """
    
    result = neo_connection.query(
        query=query,
        db=database
    )
    
    return result


def get_relationship_statistics(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> list:
    """Récupère les statistiques des relations par type dans Neo4j.
    
    Returns:
        Liste de dictionnaires contenant 'TypeRelation' et 'NombreDeRelations'
    """
    
    query = """
        MATCH ()-[r]->()
        RETURN type(r) AS TypeRelation, count(r) AS NombreDeRelations
        ORDER BY NombreDeRelations DESC
    """
    
    result = neo_connection.query(
        query=query,
        db=database
    )
    
    return result

#@execution_time
def delete_marked_elements(
    neo_connection: Neo4jConnection,
    database: str = "neo4j"
) -> tuple:
    """
    Supprime tous les nœuds et relations ayant l'attribut delete = True.
    
    Cette fonction effectue le nettoyage en deux étapes :
    1. Supprime d'abord les relations marquées delete = True
    2. Puis supprime les nœuds marqués delete = True
    
    Args:
        neo_connection (Neo4jConnection): Instance de connexion Neo4j
        database (str): Nom de la base de données Neo4j (défaut: "neo4j")
    
    Returns:
        tuple: (relationships_deleted, nodes_deleted) nombre d'éléments supprimés
    
    Example:
        >>> rel_count, node_count = delete_marked_elements(neo)
    """
    
    # Étape 1: Supprimer les relations avec delete = True
    query_delete_relationships = """
        MATCH ()-[r]->()
        WHERE r.delete = true
        DELETE r
        RETURN count(r) as deleted_count
    """
    
    result_relationships = neo_connection.query(
        query=query_delete_relationships,
        parameters=None,
        db=database
    )
    
    relationships_deleted = result_relationships[0]['deleted_count'] if result_relationships else 0
    
    # Étape 2: Supprimer les nœuds avec delete = True
    # IMPORTANT: Utiliser DETACH DELETE pour supprimer aussi les relations restantes
    query_delete_nodes = """
        MATCH (n)
        WHERE n.delete = true
        DETACH DELETE n
        RETURN count(n) as deleted_count
    """
    
    result_nodes = neo_connection.query(
        query=query_delete_nodes,
        parameters=None,
        db=database
    )
    
    nodes_deleted = result_nodes[0]['deleted_count'] if result_nodes else 0
    
    print(f"✓ {relationships_deleted} relations supprimées")
    print(f"✓ {nodes_deleted} nœuds supprimés")
    
    return relationships_deleted, nodes_deleted
    

if __name__ == "__main__":

    # Configuration du logging
    logging.basicConfig(level=logging.INFO)

    date = time.strftime("%Y%m%d-%H%M%S")

    # Open file coming from GoBGP
    with open(f"1.RESULT_BGPLS_GRPC_REORGANIZED.json") as json_file:
        gobgp_info = json.load(json_file)        

    # Open file coming from NSO CDB
    with open(f"5.RESULT_NSO_CDB_DEVICE.json") as json_file:
        nso_router_info = json.load(json_file)     

    # Open file coming from NSO Live Status LLDP
    with open(f"6.RESULT_LLDP_TOPOLOGY.json") as json_file:
        nso_lldp_info = json.load(json_file)                  
                         
    # Configuration et connexion
    config = Neo4jConfig(
        uri="bolt://localhost:7687",
        user="",
        password=""
    )
    
    # Utilisation avec context manager
    with Neo4jConnection(config) as neo:
        if neo.verify_connectivity():
            print("=" * 60)
            print("Début de l'import des données dans Neo4j")
            print("=" * 60)
            
            # NEO4J constraints name and uniqueness property
            neo_constraints = {
                "PROD_ROUTER": ["name"],
                "PROD_IP": ["uid_isis_igp_router_id", "uid_isis_igp_router_name"],
                "PROD_INT_LOGICAL": ["uid"],
                "PROD_LAG": ["uid"],
                "PROD_PORT": ["uid"],
            }

            check_neo_constraints(
                neo_connection=neo,
                neo_constraints=neo_constraints
)
            # Set attribute delete to True
            result_node, result_relationship = set_delete_attribute(
                neo_connection=neo, 
                delete=True
            )

            # Création de la topologie réseau depuis GoBGP
            create_isis_topology_from_gobgp(
                neo_connection=neo,
                gobgp_database=gobgp_info,
                date=date
            )                
            
            # Création des relations de routage globales
            create_routing_relationship(
                neo_connection=neo
            )
            
            # Création de l'attribut distance sur les relations de routage
            add_distance_attribute(
                neo_connection=neo,
            )

            # Création des relations port, LAG et interfaces logiques
            create_port_attach_logical_relationships(
                neo_connection=neo,
                nso_database=nso_router_info,
                date=date
            )
            
            # Création des relations IP vers interfaces logiques
            create_ip_logical_relationship(
                neo_connection=neo
            )            

            # Création des relations LLDP entre ports
            create_lldp_link(
                neo_connection=neo,
                nso_lldp_database=nso_lldp_info,
                date=date
            )
                        
            # Suppression des éléments marqués delete = True
            print("=" * 60)
            print("Nettoyage des éléments marqués à supprimer")
            print("=" * 60)
            
            delete_marked_elements(
                neo_connection=neo
            )
            print("=" * 60)

            print("Synthèse noeuds et relations dans la base Neo4j:")
            # Statistiques des nœuds
            node_stats = get_node_statistics(neo_connection=neo)
            for stat in node_stats:
                print(f"NODE --> {stat['label']}: {stat['NombreDeNoeuds']} nœuds")

            # Statistiques des relations
            rel_stats = get_relationship_statistics(neo_connection=neo)
            for stat in rel_stats:
                print(f"RELATION --> {stat['TypeRelation']}: {stat['NombreDeRelations']} relations")            

            print("=" * 60)
            print("Import terminé avec succès!")
            print("=" * 60)
        else:
            print("❌ Échec de la connexion à Neo4j")
