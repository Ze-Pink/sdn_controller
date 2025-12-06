"""
Script pour interroger l'état LLDP des routeurs présents dans NSO au travers du protocole RESTCONF.

Auteur: Marc De Oliveira
Date: 2025
"""

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import BasicAuth, ClientTimeout


# ============================================================
# CONFIGURATION & TYPES
# ============================================================

@dataclass
class LLDPNeighbor:
    """Représente un voisin LLDP"""
    local_port: str
    scope: str
    remote_chassis_id: str
    index: int
    remote_port: str
    remote_system_name: str
    
    def to_dict(self) -> dict:
        return {
            "local_port": self.local_port,
            "scope": self.scope,
            "remote_chassis_id": self.remote_chassis_id,
            "index": self.index,
            "remote_port": self.remote_port,
            "remote_system_name": self.remote_system_name
        }


@dataclass
class LLDPResult:
    """Résultat de la collecte LLDP pour un device"""
    device: str
    neighbors: list[LLDPNeighbor]
    error: Optional[str] = None
    
    @property
    def neighbor_count(self) -> int:
        return len(self.neighbors)
    
    def to_dict(self) -> dict:
        if self.error:
            return {"device": self.device, "error": self.error}
        
        return {
            "device": self.device,
            "neighbor_count": self.neighbor_count,
            "neighbors": [n.to_dict() for n in self.neighbors]
        }


# ============================================================
# LLDP PARSER
# ============================================================

class LLDPParser:
    """Parse la sortie CLI LLDP de Nokia SR OS"""
    
    # Pattern regex pour une ligne LLDP
    # Format: 1/1/c1/1      NB    0C:00:AF:C2:4C:00  1      1/1/c1/1, 100-* R2
    LLDP_LINE_PATTERN = re.compile(
        r'(\S+)\s+(\S+)\s+([0-9A-F:]+)\s+(\d+)\s+(.+?)\s+(\S+)\s*$'
    )
    
    @classmethod
    def parse(cls, output: str) -> list[LLDPNeighbor]:
        """Parse la sortie CLI LLDP et retourne une liste de voisins"""
        neighbors = []
        
        for line in output.split('\r\n'):
            match = cls.LLDP_LINE_PATTERN.match(line.strip())
            
            if match:
                neighbors.append(LLDPNeighbor(
                    local_port=match.group(1),
                    scope=match.group(2),
                    remote_chassis_id=match.group(3),
                    index=int(match.group(4)),
                    remote_port=match.group(5).split(',')[0],
                    remote_system_name=match.group(6)
                ))
        
        return neighbors


# ============================================================
# NSO CLIENT
# ============================================================

class NSOLiveStatusClient:
    """Client pour exécuter des commandes live-status sur NSO"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        username: str = "admin",
        password: str = "admin",
        timeout: int = 30
    ):
        self.base_url = base_url
        self.auth = BasicAuth(username, password)
        self.headers = {
            "Content-Type": "application/yang-data+json",
            "Accept": "application/yang-data+json"
        }
        self.timeout = ClientTimeout(total=timeout)
    
    def _build_command_url(self, device: str) -> str:
        """Construit l'URL pour exécuter une commande MD-CLI"""
        return (
            f"{self.base_url}/restconf/operations/"
            f"tailf-ncs:devices/device={device}/live-status/"
            f"global-operations/md-cli-raw-command"
        )
    
    async def execute_command(
        self,
        session: aiohttp.ClientSession,
        device: str,
        command: str
    ) -> tuple[str, str | None, str | None]:
        """
        Exécute une commande MD-CLI sur un device
        
        Returns:
            (device, output, error)
        """
        url = self._build_command_url(device)
        payload = {"input": {"md-cli-input-line": command}}
        
        try:
            async with session.post(
                url,
                json=payload,
                headers=self.headers,
                auth=self.auth,
                ssl=False
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    return device, None, f"HTTP {response.status}: {error_text[:200]}"
                
                data = await response.json()
                output = data["nokia-oper-global:output"]["results"]["md-cli-output-block"]
                
                return device, output, None
                
        except aiohttp.ClientError as e:
            return device, None, f"Client error: {e}"
        except KeyError as e:
            return device, None, f"Invalid response format: {e}"
        except Exception as e:
            return device, None, f"Unexpected error: {e}"
    
    async def get_lldp_neighbors(
        self,
        devices: list[str],
        max_concurrent: int = 5
    ) -> list[LLDPResult]:
        """Récupère les voisins LLDP de plusieurs devices en parallèle"""
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def fetch_with_semaphore(session: aiohttp.ClientSession, device: str):
            async with semaphore:
                print(f"→ Fetching LLDP neighbors from {device}")
                device_name, output, error = await self.execute_command(
                    session,
                    device,
                    "show system lldp neighbor"
                )
                print(f"✓ Completed {device_name}")
                
                if error:
                    return LLDPResult(device=device_name, neighbors=[], error=error)
                
                neighbors = LLDPParser.parse(output)
                return LLDPResult(device=device_name, neighbors=neighbors)
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [fetch_with_semaphore(session, device) for device in devices]
            return await asyncio.gather(*tasks)


# ============================================================
# FILE MANAGER
# ============================================================

class FileManager:
    """Gestion des fichiers JSON"""
    
    @staticmethod
    def save(data: dict | list, filename: str, indent: int = 2):
        """Sauvegarde des données en JSON"""
        filepath = Path(filename)
        
        try:
            with filepath.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            print(f"✓ Saved: {filepath}")
        except Exception as e:
            print(f"✗ Error saving {filepath}: {e}")
    
    @staticmethod
    def load(filename: str) -> dict | list | None:
        """Charge un fichier JSON"""
        filepath = Path(filename)
        
        try:
            with filepath.open('r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"✗ File not found: {filepath}")
        except json.JSONDecodeError as e:
            print(f"✗ Invalid JSON in {filepath}: {e}")
        except Exception as e:
            print(f"✗ Error loading {filepath}: {e}")
        
        return None


# ============================================================
# OUTPUT FORMATTER
# ============================================================

class LLDPFormatter:
    """Formatte les résultats LLDP pour l'affichage"""
    
    @staticmethod
    def format_summary(results: list[LLDPResult]) -> str:
        """Génère un résumé formaté des résultats LLDP"""
        lines = ["="*60, "LLDP Neighbors Summary", "="*60]
        
        for result in results:
            lines.append(f"\n{result.device}:")
            
            if result.error:
                lines.append(f"  ✗ Error: {result.error}")
                continue
            
            if result.neighbor_count == 0:
                lines.append("  ℹ No neighbors found")
                continue
            
            lines.append(f"  Total neighbors: {result.neighbor_count}")
            
            for neighbor in result.neighbors:
                lines.append(
                    f"    {neighbor.local_port} → "
                    f"{neighbor.remote_system_name} ({neighbor.remote_port})"
                )
        
        return "\n".join(lines)
    
    @staticmethod
    def to_topology_dict(results: list[LLDPResult]) -> dict:
        """Convertit les résultats en dictionnaire de topologie"""
        topology = {}
        
        for result in results:
            if result.error:
                topology[result.device] = {"error": result.error}
                continue
            
            topology[result.device] = {
                "neighbors": {
                    neighbor.local_port: {
                        "remote_device": neighbor.remote_system_name,
                        "remote_port": neighbor.remote_port,
                        "chassis_id": neighbor.remote_chassis_id
                    }
                    for neighbor in result.neighbors
                }
            }
        
        return topology


# ============================================================
# MAIN
# ============================================================

async def main():
    """Point d'entrée principal"""
    print("="*60)
    print("NSO LLDP Neighbor Collector")
    print("="*60)
    
    # Configuration
    devices = ["R1", "R2", "R3"]
    client = NSOLiveStatusClient(
        base_url="http://localhost:8080",
        username="admin",
        password="admin"
    )
    
    # Récupérer les voisins LLDP
    print(f"\nFetching LLDP data from {len(devices)} devices...\n")
    results = await client.get_lldp_neighbors(devices, max_concurrent=3)
    
    # Afficher le résumé
    print("\n" + LLDPFormatter.format_summary(results))
    
    # Sauvegarder les résultats
    print("\n" + "="*60)
    print("Saving results...")
    print("="*60)
    
    # order execution
    order = "6."

    # Format détaillé
    detailed_results = [result.to_dict() for result in results]
    FileManager.save(detailed_results, f"{order}RESULT_LLDP_DETAILED.json")
    
    # Format topologie
    topology = LLDPFormatter.to_topology_dict(results)
    FileManager.save(topology, f"{order}RESULT_LLDP_TOPOLOGY.json")
    
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())
