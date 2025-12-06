"""
Script pour shutdown/no shutdown l'interface d'un routeur depuis NSO en RESTCONF.

Auteur: Marc De Oliveira
Date: 2025
"""

import asyncio
import sys
from dataclasses import dataclass
from typing import Literal

import aiohttp
from aiohttp import ClientTimeout, BasicAuth


# ============================================================
# CONFIGURATION & TYPES
# ============================================================

@dataclass
class NSOConfig:
    """Configuration de connexion NSO"""
    base_url: str = "http://localhost:8080"
    username: str = "admin"
    password: str = "admin"
    timeout: int = 30


@dataclass
class InterfaceAction:
    """Action sur une interface"""
    device_name: str
    interface_name: str
    router_name: str = "Base"
    action: Literal["shutdown", "no-shutdown"] = "shutdown"


# ============================================================
# NSO RESTCONF CLIENT
# ============================================================

class NSORestconfClient:
    """Client RESTCONF pour NSO"""
    
    def __init__(self, config: NSOConfig):
        self.config = config
        self.timeout = ClientTimeout(total=config.timeout)
        self.auth = BasicAuth(config.username, config.password)
        self.headers = {
            "Content-Type": "application/yang-data+json",
            "Accept": "application/yang-data+json"
        }
    
    def _build_interface_url(self, device: str, router: str, interface: str) -> str:
        """Construit l'URL RESTCONF pour une interface"""
        # Encoder les caractères spéciaux dans l'interface name si nécessaire
        interface_encoded = interface.replace("/", "%2F")
        
        return (
            f"{self.config.base_url}/restconf/data/"
            f"devices/device={device}/config/"
            f"configure/router={router}/interface={interface_encoded}"
        )
    
    async def set_interface_admin_state(
        self,
        action: InterfaceAction
    ) -> dict:
        """Configure l'admin-state d'une interface (shutdown/no-shutdown)"""
        
        url = self._build_interface_url(
            action.device_name,
            action.router_name,
            action.interface_name
        )
        
        # Payload pour modifier l'admin-state
        # Pour Nokia SR OS: enable = up, disable = shutdown
        admin_state = "disable" if action.action == "shutdown" else "enable"
        
        payload = {
            "nokia-conf:interface": {
                "admin-state": admin_state
            }
        }
        
        print(f"\n{'='*60}")
        print(f"{'SHUTDOWN' if action.action == 'shutdown' else 'NO SHUTDOWN'} Interface")
        print(f"{'='*60}")
        print(f"Device: {action.device_name}")
        print(f"Router: {action.router_name}")
        print(f"Interface: {action.interface_name}")
        print(f"Admin State: {admin_state}")
        print(f"URL: {url}")
        print(f"{'='*60}\n")
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.patch(
                    url,
                    json=payload,
                    headers=self.headers,
                    auth=self.auth,
                    ssl=False
                ) as response:
                    
                    status = response.status
                    response_text = await response.text()
                    
                    if 200 <= status < 300:
                        print(f"✓ SUCCESS ({status}): Interface {action.interface_name} "
                              f"{'shutdown' if action.action == 'shutdown' else 'activated'}")
                        
                        return {
                            "success": True,
                            "status": status,
                            "device": action.device_name,
                            "interface": action.interface_name,
                            "admin_state": admin_state,
                            "response": response_text
                        }
                    else:
                        print(f"✗ ERROR ({status}): {response_text[:200]}")
                        
                        return {
                            "success": False,
                            "status": status,
                            "error": response_text
                        }
                        
        except aiohttp.ClientError as e:
            print(f"✗ CLIENT ERROR: {e}")
            return {"success": False, "error": f"CLIENT_ERROR: {e}"}
        
        except Exception as e:
            print(f"✗ UNKNOWN ERROR: {e}")
            return {"success": False, "error": f"UNKNOWN_ERROR: {e}"}
    
    async def get_interface_status(
        self,
        device: str,
        router: str,
        interface: str
    ) -> dict:
        """Récupère le statut actuel d'une interface"""
        
        url = self._build_interface_url(device, router, interface)
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    url,
                    headers=self.headers,
                    auth=self.auth,
                    ssl=False
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        return {"success": True, "data": data}
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "status": response.status,
                            "error": error_text
                        }
                        
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def print_usage():
    """Affiche l'aide d'utilisation"""
    print("""
Usage: python nso_shutdown_interface.py <device> <interface> [action] [router]

Arguments:
    device      : Nom du device dans NSO (ex: R1, R2, R3)
    interface   : Nom de l'interface (ex: to-R3, to-R1)
    action      : shutdown | no-shutdown (défaut: shutdown)
    router      : Nom du router (défaut: Base)

Exemples:
    python nso_shutdown_interface.py R1 to-R3
    python nso_shutdown_interface.py R1 to-R3 shutdown
    python nso_shutdown_interface.py R1 to-R3 no-shutdown
    """)


# ============================================================
# MAIN
# ============================================================

async def main():
    """Point d'entrée principal"""
    
    # Parsing des arguments
    if len(sys.argv) < 3:
        print("✗ Error: Missing required arguments")
        print_usage()
        sys.exit(1)
    
    device_name = sys.argv[1]
    interface_name = sys.argv[2]
    action = sys.argv[3] if len(sys.argv) > 3 else "shutdown"
    router_name = sys.argv[4] if len(sys.argv) > 4 else "Base"
    
    # Validation de l'action
    if action not in ["shutdown", "no-shutdown"]:
        print(f"✗ Error: Invalid action '{action}'. Must be 'shutdown' or 'no-shutdown'")
        print_usage()
        sys.exit(1)
    
    # Configuration
    nso_config = NSOConfig()
    client = NSORestconfClient(nso_config)
    
    # Action sur l'interface
    interface_action = InterfaceAction(
        device_name=device_name,
        interface_name=interface_name,
        router_name=router_name,
        action=action
    )
    
    # Exécution
    result = await client.set_interface_admin_state(interface_action)
    
    # Affichage du résultat
    print(f"\n{'='*60}")
    print("Result:")
    print(f"{'='*60}")
    
    if result.get("success"):
        print(f"✓ Operation completed successfully")
        print(f"  Device: {result.get('device')}")
        print(f"  Interface: {result.get('interface')}")
        print(f"  Admin State: {result.get('admin_state')}")
    else:
        print(f"✗ Operation failed")
        print(f"  Error: {result.get('error')}")
        sys.exit(1)
    
    print(f"{'='*60}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n✗ Operation cancelled by user")
        sys.exit(130)
