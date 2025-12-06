"""
Script pour récupérer les configurations des routeurs présents depuis NSO en RESTCONF.

Auteur: Marc De Oliveira
Date: 2025
"""

import asyncio
import json
import re
import time
from pprint import pprint
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from ipaddress import IPv4Interface, IPv4Address

import aiohttp
from aiohttp import ClientTimeout, BasicAuth
from jsonpath_ng.ext import parse


# ============================================================
# CONFIGURATION & TYPES
# ============================================================

@dataclass
class RequestConfig:
    """Configuration pour une requête NSO"""
    name: str
    url: str
    payload: dict[str, Any]
    analysis_func: Callable[[dict], dict]
    method: str = "POST"
    username: str = "admin"
    password: str = "admin"
    headers: dict[str, str] = field(default_factory=lambda: {
        "Content-Type": "application/yang-data+json",
        "Accept": "application/yang-data+json"
    })


class NSOQueryBuilder:
    """Constructeur de requêtes NSO immediate-query"""
    
    @staticmethod
    def build(foreach: str, selectors: list[dict[str, str]]) -> dict:
        return {
            "tailf-rest-query:immediate-query": {
                "foreach": foreach,
                "select": selectors
            }
        }


# ============================================================
# HTTP CLIENT
# ============================================================

class NSOClient:
    """Client HTTP pour NSO avec gestion asynchrone"""
    
    def __init__(self, timeout: int = 600):
        self.timeout = ClientTimeout(total=timeout)
    
    async def fetch(
        self,
        session: aiohttp.ClientSession,
        config: RequestConfig,
        semaphore: asyncio.Semaphore
    ) -> tuple[str, dict | None, int | str]:
        """Exécute une requête HTTP asynchrone"""
        
        auth = BasicAuth(config.username, config.password) if config.username else None
        
        try:
            async with semaphore:
                start_time = time.monotonic()
                #print(f"→ Starting: {config.name}")
                
                async with session.request(
                    config.method,
                    config.url,
                    json=config.payload,
                    headers=config.headers,
                    auth=auth,
                    ssl=False
                ) as response:
                    duration = time.monotonic() - start_time
                    print(f"✓ Données collectées : {config.name} ({response.status}) in {duration:.2f}s")
                    
                    if 200 <= response.status < 300:
                        return config.name, await response.json(), response.status
                    
                    error_text = await response.text()
                    return config.name, None, f"{response.status}: {error_text[:200]}"
                    
        except aiohttp.ClientError as e:
            return config.name, None, f"CLIENT_ERROR: {e}"
        except Exception as e:
            return config.name, None, f"UNKNOWN_ERROR: {e}"
    
    async def fetch_all(
        self,
        configs: list[RequestConfig],
        max_concurrent: int = 5
    ) -> dict[str, Any]:
        """Exécute toutes les requêtes en parallèle"""
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self.fetch(session, config, semaphore) for config in configs]
            results = await asyncio.gather(*tasks)
        
        return self._process_results(results, configs)
    
    @staticmethod
    def _process_results(
        results: list[tuple],
        configs: list[RequestConfig]
    ) -> dict[str, Any]:
        """Traite les résultats et applique les fonctions d'analyse"""
        
        processed = {}
        
        for (name, data, status), config in zip(results, configs):
            if data and config.analysis_func:
                processed[name] = config.analysis_func(data)
            elif data:
                processed[name] = {"status": status, "data": data}
            else:
                processed[name] = {"error": status}
        
        return processed


# ============================================================
# DATA PARSERS
# ============================================================

class ResultParser:
    """Parse les résultats des requêtes NSO"""
    
    @staticmethod
    def extract_items(data: dict) -> list[dict]:
        """Extrait les items d'une réponse query"""
        items = data.get('tailf-rest-query:query-result', {}).get('result', [])
        
        return [
            {
                field['label']: field.get('value') or field.get('path') or field.get('data', '')
                for field in item.get('select', [])
            }
            for item in items
        ]


class ASConverter:
    """Convertisseur de format AS"""
    
    @staticmethod
    def plain_to_dot(as_number: str | int) -> str:
        """Convertit AS PLAIN vers AS DOT (ex: 65536 -> 1.0)"""
        try:
            as_int = int(as_number)
            return f"{as_int // 65536}.{as_int % 65536}"
        except (ValueError, TypeError):
            return str(as_number)


# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================

class DeviceAnalyzer:
    """Analyseurs de données device"""
    
    @staticmethod
    def analyze_logical_interfaces(data: dict) -> dict:
        """Analyse les interfaces logiques"""
        items = ResultParser.extract_items(data)
        result = {'DEVICE': {}}
        
        for item in items:
            device = item.get('device')
            if not device:
                continue
            
            device_dict = result['DEVICE'].setdefault(device, {})
                       
            # Interfaces logiques différentes des loopback et system
            if 'LoopBack' not in item.get('path', '') and 'system' not in item.get('path', ''):
                interface = device_dict.setdefault('LOGICAL', {}).setdefault(item['name'], {})
                
                if item.get('port'):
                    port_parts = item['port'].split(':')
                    interface['ATTACH'] = port_parts[0].split('lag-')[1] if 'lag-' in port_parts[0] else port_parts[0]
                    interface['VLAN'] = port_parts[1] if len(port_parts) > 1 and port_parts[1] != '0' else ''
                
                if item.get('address') and item.get('mask'):
                    ip_interface = IPv4Interface(f"{item['address']}/{item['mask']}")
                    interface.update({
                        'NETWORK': str(ip_interface.network),
                        'MASK': item['mask'],
                        'IP': str(ip_interface.ip)
                    })
        
        return result
    
    @staticmethod
    def analyze_lags(data: dict) -> dict:
        """Analyse les LAGs"""
        items = ResultParser.extract_items(data)
        result = {'DEVICE': {}}
        
        for item in items:
            device = item.get('device')
            if not device:
                continue
            
            device_dict = result['DEVICE'].setdefault(device, {})
            lag_name = item.get('lag-name').split('lag-')[1]
            port = item.get('port')
            
            if lag_name:
                lag_dict = device_dict.setdefault('LAG', {}).setdefault(lag_name, {})
                lag_dict['admin-state'] = item.get('admin-state', '')
                
                if port:
                    port_dict = device_dict.setdefault('PORT', {}).setdefault(port, {})
                    port_dict['LAG'] = lag_name
        
        return result
    
    @staticmethod
    def analyze_isis(data: dict) -> dict:
        """Analyse ISIS"""
        items = ResultParser.extract_items(data)
        result = {'DEVICE': {}, 'ISIS': {}}
        
        for item in items:
            device = item.get('device')
            if not device:
                continue
            
            interface_name = item.get('name', '')
            
            # ISIS metrics et adjacency SID
            if 'LoopBack' not in item.get('path', '') and 'system' not in item.get('path', '') and item.get('metric'):
                isis_dict = result['ISIS'].setdefault(device, {}).setdefault(interface_name, {})
                isis_dict['METRIC'] = int(item['metric'])
                if item.get('adj-sid'):
                    isis_dict['ADJ_SID'] = int(item['adj-sid'])
        
        return result
    

# ============================================================
# DATA PROCESSING
# ============================================================

class DataMerger:
    """Fusion récursive de dictionnaires"""
    
    @staticmethod
    def merge(dict1: dict, dict2: dict) -> dict:
        """Fusionne deux dictionnaires récursivement"""
        merged = dict1.copy()
        
        for key, value in dict2.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = DataMerger.merge(merged[key], value)
            elif key not in merged or (value and value != ""):
                merged[key] = value
        
        return merged


class IPRelationshipBuilder:
    """Construit les relations IP entre devices"""
    
    @staticmethod
    def build(device_data: dict) -> dict:
        """Crée un dictionnaire de relations IP par réseau"""
        ip_relations = {}
        
        query = parse('$..LOGICAL.*')
        interfaces = query.find(device_data)
        
        for interface in interfaces:
            data = interface.value
            
            network = data.get('NETWORK', '')
            ip = data.get('IP', '')
            description = data.get('DESCRIPTION', '')
            
            if not network or not ip:
                continue
            
            # Extraction du device name depuis le path
            path_str = str(interface.full_path).replace("'", "")
            device_match = re.search(r'^(.+)\.LOGICAL', path_str)
            
            if device_match:
                ip_relations.setdefault(network, {})[path_str] = {
                    'IP': ip,
                    'DESCRIPTION': description
                }
        
        return ip_relations


class FileManager:
    """Gestion des fichiers JSON"""
    
    @staticmethod
    def save(data: dict, filename: str, indent: int = 4):
        """Sauvegarde un dictionnaire en JSON"""
        filepath = Path(filename)
        
        try:
            with filepath.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            print(f"\n✓ Données sauvegardées dans {filepath}")
        except Exception as e:
            print(f"\n✗ Error saving {filepath}: {e}")
    
    @staticmethod
    def load(filename: str) -> dict | None:
        """Charge un fichier JSON"""
        filepath = Path(filename)
        
        try:
            with filepath.open('r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"\n✗ File not found: {filepath}")
        except json.JSONDecodeError as e:
            print(f"\n✗ Invalid JSON in {filepath}: {e}")
        except Exception as e:
            print(f"\n✗ Error loading {filepath}: {e}")
        
        return None


# ============================================================
# CONFIGURATION
# ============================================================

def get_request_configs() -> list[RequestConfig]:
    """Définit toutes les configurations de requêtes"""
    
    base_url = "http://localhost:8080/restconf/tailf/query/"
    
    return [
        RequestConfig(
            name="logical_interfaces",
            url=base_url,
            payload=NSOQueryBuilder.build(
                foreach="/devices/device/config/configure/router[router-name='Base']/interface",
                selectors=[
                    {"label": "device", "expression": "../../../../name", "result-type": "string"},
                    {"label": "name", "expression": "./interface-name", "result-type": "string"},
                    {"label": "path", "expression": ".", "result-type": "path"},
                    {"label": "address", "expression": "./ipv4/primary/address", "result-type": "string"},
                    {"label": "mask", "expression": "./ipv4/primary/prefix-length", "result-type": "string"},
                    {"label": "port", "expression": "./port", "result-type": "string"}
                ]
            ),
            analysis_func=DeviceAnalyzer.analyze_logical_interfaces
        ),
        
        RequestConfig(
            name="lags",
            url=base_url,
            payload=NSOQueryBuilder.build(
                foreach="/devices/device/config/configure/lag/port/port-id",
                selectors=[
                    {"label": "device", "expression": "../../../../../name", "result-type": "string"},
                    {"label": "lag-name", "expression": "../../lag-name", "result-type": "string"},
                    {"label": "admin-state", "expression": "../../admin-state", "result-type": "string"},
                    {"label": "port", "expression": ".", "result-type": "string"}
                ]
            ),
            analysis_func=DeviceAnalyzer.analyze_lags
        ),
        
        RequestConfig(
            name="isis",
            url=base_url,
            payload=NSOQueryBuilder.build(
                foreach="/devices/device/config/configure/router[router-name='Base']/isis/interface",
                selectors=[
                    {"label": "device", "expression": "../../../../../name", "result-type": "string"},
                    {"label": "path", "expression": ".", "result-type": "path"},
                    {"label": "node-sid", "expression": "./ipv4-node-sid/index", "result-type": "string"},
                    {"label": "adj-sid", "expression": "./ipv4-adjacency-sid/label", "result-type": "string"},
                    {"label": "metric", "expression": "./level/metric", "result-type": "string"},
                    {"label": "name", "expression": "./interface-name", "result-type": "string"}
                ]
            ),
            analysis_func=DeviceAnalyzer.analyze_isis
        )
    ]


# ============================================================
# MAIN
# ============================================================

async def main():
    """Point d'entrée principal"""
    start_time = time.time()
    
    print("="*60)
    print("NSO Data Collector")
    print("="*60)
    
    # Exécuter les requêtes
    client = NSOClient(timeout=600)
    configs = get_request_configs()
    results = await client.fetch_all(configs, max_concurrent=2)

    # Fusionner les résultats
    final_data = {}
    for analysis_result in results.values():
        if isinstance(analysis_result, dict) and 'error' not in analysis_result:
            final_data = DataMerger.merge(final_data, analysis_result)
    
    # Créer les relations IP
    if 'DEVICE' in final_data:
        final_data['IP_RELATION'] = IPRelationshipBuilder.build(final_data['DEVICE'])
    
    # order execution
    order = "5."

    # Sauvegarder les résultats
    FileManager.save(final_data, f"{order}RESULT_NSO_CDB_ALLinONE.json")
    
    if 'ISIS' in final_data:
        FileManager.save(final_data['ISIS'], f"{order}RESULT_NSO_CDB_ISIS.json")
    
    if 'IP_RELATION' in final_data:
        FileManager.save(final_data['IP_RELATION'], f"{order}RESULT_NSO_CDB_IP_RELATION.json")
    
    if 'DEVICE' in final_data:
        FileManager.save(final_data['DEVICE'], f"{order}RESULT_NSO_CDB_DEVICE.json")
    
    print(f"\n⏱️  Total time: {time.time() - start_time:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
