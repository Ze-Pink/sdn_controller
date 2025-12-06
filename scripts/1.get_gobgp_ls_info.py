"""
Script pour récupérer et standardiser les routes BGP-LS depuis GoBGP via gRPC.

Auteur: Marc De Oliveira
Date: 2025
"""

import sys
import os
import json
import grpc
import argparse
from typing import Dict, List, Optional, Any
from datetime import datetime
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.json_format import MessageToDict

mod_path = os.path.expanduser("~/sdn_controller/containerlab/lab/sdn_controller/gobgp/gobgp-3.37.0/api/")
if mod_path not in sys.path:
    sys.path.insert(0, mod_path)

try:
    import gobgp_pb2 
    import gobgp_pb2_grpc 
    import attribute_pb2
except ImportError:
    print("❌ Erreur: Le module gobgp-api n'est pas installé.")
    print("Installation: pip install gobgp-api")
    sys.exit(1)



class BGPLSParserGRPC:
    """Parse et standardise les données BGP-LS depuis GoBGP via gRPC."""
    
    def __init__(self, grpc_host: str = "localhost", grpc_port: int = 50051):
        """
        Initialise le parser avec connexion gRPC.
        
        Args:
            grpc_host: Adresse du serveur gRPC GoBGP
            grpc_port: Port du serveur gRPC (défaut: 50051)
        """
        self.grpc_host = grpc_host
        self.grpc_port = grpc_port
        self.grpc_address = f"{grpc_host}:{grpc_port}"
        self.channel = None
        self.stub = None
        
        self.nodes = {}
        self.links = []
        self.prefixes = []
    
    def connect(self) -> bool:
        """Établit la connexion gRPC avec GoBGP."""
        try:
            print(f"🔌 Connexion à GoBGP via gRPC ({self.grpc_address})...")
            self.channel = grpc.insecure_channel(self.grpc_address)
            self.stub = gobgp_pb2_grpc.GobgpApiStub(self.channel)
            
            # Test de connexion
            request = gobgp_pb2.GetBgpRequest()
            response = self.stub.GetBgp(request)
            global_info = getattr(response, 'global', None)
            
            print(f"✓ Connecté à GoBGP")
            print(f"  AS: {global_info.asn}")
            print(f"  Router ID: {global_info.router_id}")
            return True
            
        except grpc.RpcError as e:
            print(f"❌ Erreur de connexion gRPC: {e}")
            return False
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return False
    
    def disconnect(self):
        """Ferme la connexion gRPC."""
        if self.channel:
            self.channel.close()
    
    def get_bgpls_routes(self) -> List[Dict]:
        """
        Récupère les routes BGP-LS via gRPC et les convertit en dict.
        
        Returns:
            Liste des destinations BGP-LS en format dict
        """
        try:
            print("\n📡 Récupération des routes BGP-LS...")
            
            # Construction de la famille BGP-LS
            family = gobgp_pb2.Family(
                afi=gobgp_pb2.Family.AFI_LS,
                safi=gobgp_pb2.Family.SAFI_LS
            )
            
            request = gobgp_pb2.ListPathRequest(
                table_type=gobgp_pb2.TableType.GLOBAL,
                family=family
            )
            
            destinations = []
            for response in self.stub.ListPath(request):
                # Convertir la destination en dict en gardant les noms de champs protobuf
                dest_dict = MessageToDict(
                    response.destination,
                    preserving_proto_field_name=True,
                )
                destinations.append(dest_dict)
            
            print(f"✓ {len(destinations)} destination(s) BGP-LS récupérée(s)")   
            
            return destinations
            
        except grpc.RpcError as e:
            print(f"❌ Erreur lors de la récupération des routes: {e}")
            print(f"   Détails: {e.details()}")
            return []
        except Exception as e:
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
            return []
    

    
    def parse_node_nlri(self, destination: Dict) -> Optional[Dict]:
        """
        Parse un NLRI de type Node depuis une Destination (en dict).
        
        Args:
            destination: Dict de la destination
            
        Returns:
            Dictionnaire standardisé du node ou None
        """
        try:
            # Récupérer le premier path
            paths = destination.get('paths', [])
            if not paths:
                return None
            
            path = paths[0]
            
            # Le NLRI est dans un objet Any - chercher la clé qui contient les données
            nlri_any = path.get('nlri', {})
            if not nlri_any:
                return None
            
            # Dans MessageToDict, le contenu du Any est sous une clé spéciale
            # Chercher la clé qui contient type_url
            nlri_dict = None
            if '@type' in nlri_any:
                # C'est déjà converti, chercher les données réelles
                # Les données sont dans les autres clés
                nlri_dict = {k: v for k, v in nlri_any.items() if k != '@type'}
            else:
                nlri_dict = nlri_any
            
            # Vérifier le type de NLRI
            nlri_type = nlri_dict.get('type', '')
            if nlri_type != 'LS_NLRI_NODE':
                return None
            
            node_data = {
                "type": "node",
                "protocol_id": nlri_dict.get('protocol_id', 'unknown'),
                "igp_router_id": None,
                "local_router_id": None,
                "node_name": None,
                "asn": None,
                "sr_capabilities": {},

            }
            
            # Extraire les informations du NLRI spécifique
            # Le NLRI imbriqué peut être dans 'nlri' ou directement accessible
            nested_nlri = nlri_dict.get('nlri', nlri_dict)
            
            # Informations du node local
            local_node = nested_nlri.get('local_node', {})
            if local_node:
                node_data["asn"] = local_node.get('asn')
                node_data["igp_router_id"] = local_node.get('igp_router_id')
            
            # Parser les attributs du path
            for pattr in path.get('pattrs', []):
                if '@type' in pattr:
                    # Attribut LS
                    node_attr = pattr.get('node', {})
                    if node_attr:
                        node_data["node_name"] = node_attr.get('name')
                        node_data["local_router_id"] = node_attr.get('local_router_id')
                        
                        # SR Capabilities
                        sr_caps = node_attr.get('sr_capabilities', {})
                        if sr_caps:
                            node_data["sr_capabilities"] = {
                                "ranges": sr_caps.get('ranges', [])
                            }
            
            return node_data
            
        except Exception as e:
            print(f"⚠️  Erreur lors du parsing du node: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def parse_link_nlri(self, destination: Dict) -> Optional[Dict]:
        """
        Parse un NLRI de type Link depuis une Destination (en dict).
        
        Args:
            destination: Dict de la destination
            
        Returns:
            Dictionnaire standardisé du link ou None
        """
        try:
            paths = destination.get('paths', [])
            if not paths:
                return None
            
            path = paths[0]
            nlri_any = path.get('nlri', {})
            if not nlri_any:
                return None
            
            # Extraire les données du Any
            nlri_dict = {k: v for k, v in nlri_any.items() if k != '@type'}
            
            # Vérifier le type
            if nlri_dict.get('type') != 'LS_NLRI_LINK':
                return None
            
            link_data = {
                "type": "link",
                "protocol_id": nlri_dict.get('protocol_id', 'unknown'),
                "local_node": {},
                "remote_node": {},
                "local_ip": None,
                "remote_ip": None,
                "igp_metric": None,
                "sr_adjacency_sid": None,
            }
            
            # NLRI imbriqué
            nested_nlri = nlri_dict.get('nlri', nlri_dict)
            
            # Node local
            local_node = nested_nlri.get('local_node', {})
            if local_node:
                link_data["local_node"] = {
                    "asn": local_node.get('asn'),
                    "igp_router_id": local_node.get('igp_router_id')
                }
            
            # Node remote
            remote_node = nested_nlri.get('remote_node', {})
            if remote_node:
                link_data["remote_node"] = {
                    "asn": remote_node.get('asn'),
                    "igp_router_id": remote_node.get('igp_router_id')
                }
            
            # Descripteurs du link
            link_desc = nested_nlri.get('link_descriptor', {})
            if link_desc:
                link_data["local_ip"] = link_desc.get('interface_addr_ipv4')
                link_data["remote_ip"] = link_desc.get('neighbor_addr_ipv4')
            
            # Parser les attributs
            for pattr in path.get('pattrs', []):
                link_attr = pattr.get('link', {})
                if link_attr:
                    link_data["igp_metric"] = link_attr.get('igp_metric')
                    link_data["sr_adjacency_sid"] = link_attr.get('sr_adjacency_sid')
            
            return link_data
            
        except Exception as e:
            print(f"⚠️  Erreur lors du parsing du link: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def parse_prefix_nlri(self, destination: Dict) -> Optional[Dict]:
        """
        Parse un NLRI de type Prefix depuis une Destination (en dict).
        
        Args:
            destination: Dict de la destination
            
        Returns:
            Dictionnaire standardisé du prefix ou None
        """
        try:
            paths = destination.get('paths', [])
            if not paths:
                return None
            
            path = paths[0]
            nlri_any = path.get('nlri', {})
            if not nlri_any:
                return None
            
            # Extraire les données du Any
            nlri_dict = {k: v for k, v in nlri_any.items() if k != '@type'}
            
            # Vérifier le type
            nlri_type = nlri_dict.get('type', '')
            if nlri_type not in ['LS_NLRI_PREFIX_V4', 'LS_NLRI_PREFIX_V6']:
                return None
            
            prefix_data = {
                "type": "prefix",
                "protocol_id": nlri_dict.get('protocol_id', 'unknown'),
                "local_node": {},
                "prefix": None,
                "sr_prefix_sid": [],
            }
            
            # NLRI imbriqué
            nested_nlri = nlri_dict.get('nlri', nlri_dict)
            
            # Node local
            local_node = nested_nlri.get('local_node', {})
            if local_node:
                prefix_data["local_node"] = {
                    "asn": local_node.get('asn'),
                    "igp_router_id": local_node.get('igp_router_id')
                }
            
            # Descripteur du prefix
            prefix_desc = nested_nlri.get('prefix_descriptor', {})
            if prefix_desc:
                ip_reach = prefix_desc.get('ip_reachability', [])
                if ip_reach:
                    prefix_data["prefix"] = ip_reach[0]
            
            # Parser les attributs
            for pattr in path.get('pattrs', []):
                prefix_attr = pattr.get('prefix', {})
                if prefix_attr:                   
                    # Prefix SIDs
                    sr_prefix_sid = prefix_attr.get('sr_prefix_sid', [])
                    if sr_prefix_sid:
                        prefix_data["sr_prefix_sid"] = sr_prefix_sid
            
            return prefix_data
            
        except Exception as e:
            print(f"⚠️  Erreur lors du parsing du prefix: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def parse_routes(self, destinations: List[Dict]):
        """
        Parse toutes les destinations BGP-LS.
        
        Args:
            destinations: Liste des destinations (en dict)
        """
        print("\n🔍 Parsing des routes BGP-LS...")
        
        for destination in destinations:
            # Essayer de parser en tant que Node
            node = self.parse_node_nlri(destination)
            if node:
                node_id = node.get("igp_router_id") or str(node.get("asn", "unknown"))
                if node_id:
                    self.nodes[node_id] = node
                continue
            
            # Essayer de parser en tant que Link
            link = self.parse_link_nlri(destination)
            if link:
                self.links.append(link)
                continue
            
            # Essayer de parser en tant que Prefix
            prefix = self.parse_prefix_nlri(destination)
            if prefix:
                self.prefixes.append(prefix)
        
        print(f"✓ Parsing terminé")
        print(f"  - Nodes: {len(self.nodes)}")
        print(f"  - Links: {len(self.links)}")
        print(f"  - Prefixes: {len(self.prefixes)}")
    
    def generate_output(self) -> Dict:
        """
        Génère le fichier JSON standardisé.
        
        Returns:
            Dictionnaire avec les données standardisées
        """
        output = {
            "topology": {
                "nodes": list(self.nodes.values()),
                "links": self.links,
                "prefixes": self.prefixes
            },
            "statistics": {
                "node_count": len(self.nodes),
                "link_count": len(self.links),
                "prefix_count": len(self.prefixes)
            }
        }
        
        return output
    
    def save_to_file(self, output: Dict, filename: str):
        """
        Sauvegarde les données dans un fichier JSON.
        
        Args:
            output: Les données à sauvegarder
            filename: Nom du fichier de sortie
        """
        with open(filename, 'w', encoding='utf-8') as f:
            file = json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Données sauvegardées dans {filename}")


def reorganize_by_igp_router_id(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reorganize BGP-LS topology data by IGP Router ID
    
    Args:
        input_data: Original JSON structure with nodes, links, and prefixes
        
    Returns:
        Reorganized JSON structure grouped by IGP Router ID
    """
    
    # Initialize the output structure
    output = {
        "routers": {}
    }

    # Process nodes - create router entries
    for node in input_data["topology"]["nodes"]:
        igp_router_id = node["igp_router_id"]
        output["routers"][igp_router_id] = {
            "node_info": node,
            "links": [],
            "prefixes": []
        }
    
    # Process links - only add links where router is the source (local_node)
    for link in input_data["topology"]["links"]:
        local_igp_router_id = link["local_node"]["igp_router_id"]
        remote_igp_router_id = link["remote_node"]["igp_router_id"]
        
        # Create simplified link object
        link_obj = {
            "remote_node_igp_router_id": remote_igp_router_id,
            "local_ip": link["local_ip"],
            "remote_ip": link["remote_ip"],
            "igp_metric": link["igp_metric"],
            "sr_adjacency_sid": link["sr_adjacency_sid"]
        }
        
        # Add link to the source router
        if local_igp_router_id in output["routers"]:
            output["routers"][local_igp_router_id]["links"].append(link_obj)
    
    # Process prefixes
    for prefix in input_data["topology"]["prefixes"]:
        local_igp_router_id = prefix["local_node"]["igp_router_id"]
        
        # Create simplified prefix object
        prefix_obj = {
            "prefix": prefix["prefix"],
            "sr_prefix_sid": prefix.get("sr_prefix_sid") if prefix.get("sr_prefix_sid") else None
        }
        
        # Add prefix to the router
        if local_igp_router_id in output["routers"]:
            output["routers"][local_igp_router_id]["prefixes"].append(prefix_obj)
    
    # Add statistics
    output["statistics"] = {
        "router_count": len(output["routers"]),
        "total_links": input_data["statistics"]["link_count"],
        "total_prefixes": input_data["statistics"]["prefix_count"]
    }
    
    return output


def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Parser BGP-LS depuis GoBGP via gRPC (v3.37.0)"
    )
    parser.add_argument(
        "-H", "--host",
        default="localhost",
        help="Adresse du serveur gRPC GoBGP (défaut: localhost)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=50051,
        help="Port du serveur gRPC (défaut: 50051)"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Mode debug - affiche les données brutes"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Parser BGP-LS pour GoBGP (gRPC v3.37.0)")
    print("=" * 60)
    
    # Créer le parser
    bgpls_parser = BGPLSParserGRPC(
        grpc_host=args.host,
        grpc_port=args.port
    )
    
    # Se connecter à GoBGP
    if not bgpls_parser.connect():
        print("\n❌ Impossible de se connecter à GoBGP")
        print(f"   Vérifiez que GoBGP tourne sur {args.host}:{args.port}")
        import sys
        sys.exit(1)
    
    try:
        # Récupérer les routes
        destinations = bgpls_parser.get_bgpls_routes()
        
        if args.debug and destinations:
            print("\n🔍 DEBUG - Première destination:")
            import pprint
            pprint.pprint(destinations[0])
        
        if not destinations:
            print("\n⚠️  Aucune route BGP-LS trouvée")
            print("   Vérifiez que:")
            print("   1. Le peering BGP est établi")
            print("   2. ISIS distribue les informations (database-export)")
            print("   3. Le routeur annonce des routes BGP-LS")
        else:
            # Parser les routes
            bgpls_parser.parse_routes(destinations)

            order = "1."
            # Générer et sauvegarder le résultat brut
            raw_bgp_ls_output = bgpls_parser.save_to_file(destinations, f"{order}RESULT_RAW_BGPLS_GRPC.json")            
            
            # Générer et sauvegarder le résultat
            output = bgpls_parser.generate_output()
            bgp_ls_output = bgpls_parser.save_to_file(output, f"{order}RESULT_BGPLS_GRPC.json")

            # Reorganiser par IGP Router ID
            with open(f"{order}RESULT_BGPLS_GRPC.json", 'r') as f:
                input_data = json.load(f)            
            reorganized_output = reorganize_by_igp_router_id(input_data)
            bgp_ls_reorganized_output = bgpls_parser.save_to_file(reorganized_output, f"{order}RESULT_BGPLS_GRPC_REORGANIZED.json")
             
            
            print("\n" + "=" * 60)
            print("✓ Traitement terminé avec succès!")
            print("=" * 60)
    
    finally:
        # Déconnecter
        bgpls_parser.disconnect()


if __name__ == "__main__":
    main()
