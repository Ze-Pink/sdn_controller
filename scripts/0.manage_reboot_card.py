#!/usr/bin/env python3
"""
Script de monitoring et récupération automatique des cartes Nokia SROS
Vérifie l'état de la carte 1 et effectue un reboot si nécessaire
"""

import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
from datetime import datetime

# Configuration
ROUTERS = [
    # R1
    {
        'host': 'clab-SDN-R1',
        'username': 'admin',
        'password': 'admin',
    },
    # R2
    {
        'host': 'clab-SDN-R2',
        'username': 'admin',
        'password': 'admin',
    },
    # R3
    {
        'host': 'clab-SDN-R3',
        'username': 'admin',
        'password': 'admin',
    },    
]

# Paramètres
CHECK_INTERVAL = 10      # Intervalle de vérification en secondes (état booting)
REBOOT_TIMEOUT = 180     # Timeout pour attendre le retour après reboot (3 min)
SSH_RETRY_INTERVAL = 10  # Intervalle entre les tentatives de connexion SSH
MAX_RETRIES = 100         # Nombre maximum de tentatives de connexion

# Lock global pour s'assurer qu'un seul reboot se fait à la fois
reboot_lock = threading.Lock()


def log(message, router_host=None):
    """Affiche un message avec timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if router_host:
        print(f"[{timestamp}] [{router_host}] {message}")
    else:
        print(f"[{timestamp}] {message}")


def format_duration(seconds):
    """Formate une durée en secondes en format lisible"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    
    return " ".join(parts)


def connect_to_router(router_config):
    """Établit une connexion SSH au routeur"""
    device = {
        'device_type': 'nokia_sros',
        'host': router_config['host'],
        'username': router_config['username'],
        'password': router_config['password'],
        'timeout': 30,
        'session_log': f"session_{router_config['host']}.log"
    }
    
    try:
        connection = ConnectHandler(**device)
        log("Connexion établie", router_config['host'])
        return connection
    except NetmikoAuthenticationException:
        log("Erreur d'authentification", router_config['host'])
        return None
    except NetmikoTimeoutException:
        log("Timeout de connexion", router_config['host'])
        return None
    except Exception as e:
        log(f"Erreur de connexion: {str(e)}", router_config['host'])
        return None


def get_card_status(connection, router_host):
    """Récupère le statut de la carte 1"""
    try:
        # Commande pour vérifier l'état de la carte 1
        output = connection.send_command("show card 1")
        
        # Parser la sortie pour extraire l'état
        # Format: "1    xcm-1s    up    failed/booting/up    [...]"

        match = re.search(
            r'^1\s+\S+\s+(?P<admin_state>\w+)\s+(?P<oper_state>\w+)',
            output,
            re.MULTILINE
        )
        
        if match:
            admin_state = match.group('admin_state').lower()
            oper_state = match.group('oper_state').lower()
            
            log(f"État de la carte 1 - Admin: {admin_state}, Oper: {oper_state}", router_host)
            
            # On retourne l'état opérationnel (le second)
            return oper_state
            
        log("Impossible de déterminer l'état de la carte", router_host)
        log(f"Sortie reçue:\n{output}", router_host)
        return None
        
    except Exception as e:
        log(f"Erreur lors de la récupération du statut: {str(e)}", router_host)
        return None


def reboot_router(connection, router_host):
    """Effectue un reboot administratif du routeur"""
    try:
        log("Lancement du reboot administratif", router_host)
        
        connection.remote_conn.send("admin reboot now\n")
        time.sleep(3)
        
        log("Commande de reboot envoyée", router_host)
        return True
        
    except:
        # Toute erreur est acceptable ici
        log("Commande de reboot envoyée (connexion interrompue)", router_host)
        return True


def wait_for_router_online(router_config, timeout=REBOOT_TIMEOUT):
    """Attend que le routeur soit accessible en SSH"""
    router_host = router_config['host']
    log(f"Attente de la disponibilité SSH du routeur (timeout: {timeout}s)", router_host)
    
    start_time = time.time()
    attempt = 1
    
    while time.time() - start_time < timeout:
        log(f"Tentative de connexion SSH #{attempt}...", router_host)
        
        # Tenter une connexion SSH
        connection = connect_to_router(router_config)
        
        if connection:
            log("✓ Connexion SSH établie avec succès", router_host)
            connection.disconnect()
            return True
        
        attempt += 1
        time.sleep(SSH_RETRY_INTERVAL)
    
    log("Timeout: le routeur n'est pas accessible en SSH", router_host)
    return False


def monitor_card(router_config):
    """
    Surveille l'état de la carte 1 d'un routeur et effectue les actions nécessaires
    """
    router_host = router_config['host']
    log("Démarrage de la surveillance", router_host)
    
    attempt = 0
    while attempt < MAX_RETRIES:
        attempt += 1
        
        # Connexion au routeur
        connection = connect_to_router(router_config)
        if not connection:
            log(f"Tentative {attempt}/{MAX_RETRIES} échouée", router_host)
            time.sleep(30)
            continue
        
        try:
            # Vérification du statut de la carte
            status = get_card_status(connection, router_host)
            
            if status == 'up':
                log("✓ Carte 1 est UP - OK", router_host)
                connection.disconnect()
                return {'host': router_host, 'status': 'OK', 'card_state': 'up'}
            
            elif status == 'booting':
                log("Carte 1 en cours de démarrage, attente...", router_host)
                
                # Attendre que la carte passe à up ou failed
                while True:
                    time.sleep(CHECK_INTERVAL)
                    status = get_card_status(connection, router_host)
                    
                    if status == 'up':
                        log("✓ Carte 1 est maintenant UP", router_host)
                        connection.disconnect()
                        return {'host': router_host, 'status': 'OK', 'card_state': 'up'}
                    
                    elif status == 'failed':
                        log("✗ Carte 1 est FAILED", router_host)
                        break
                    
                    elif status != 'booting':
                        log(f"État inattendu: {status}", router_host)
                        break
            
            elif status == 'failed':
                log("✗ Carte 1 est FAILED", router_host)
            
            else:
                log(f"État inconnu ou problème: {status}", router_host)
                connection.disconnect()
                return {'host': router_host, 'status': 'ERROR', 'card_state': status}
            
            # Si on arrive ici, la carte est failed, il faut rebooter
            # Utiliser le lock pour s'assurer qu'un seul reboot se fait à la fois
            with reboot_lock:
                log("Acquisition du verrou de reboot", router_host)
                
                # Reboot du routeur
                if reboot_router(connection, router_host):
                    connection.disconnect()
                    
                    # Attendre que le routeur redémarre (vérification SSH)
                    if wait_for_router_online(router_config):
                        log("Routeur de nouveau accessible, relance du monitoring...", router_host)
                        # Réinitialiser le compteur pour relancer le monitoring
                        attempt = 0
                        time.sleep(10)
                        continue
                    else:
                        log("Le routeur n'est pas revenu en ligne", router_host)
                        return {'host': router_host, 'status': 'TIMEOUT', 'card_state': 'failed'}
                else:
                    connection.disconnect()
                    return {'host': router_host, 'status': 'REBOOT_FAILED', 'card_state': 'failed'}
        
        except Exception as e:
            log(f"Erreur inattendue: {str(e)}", router_host)
            try:
                connection.disconnect()
            except:
                pass
            time.sleep(30)
    
    log(f"Nombre maximum de tentatives atteint ({MAX_RETRIES})", router_host)
    return {'host': router_host, 'status': 'MAX_RETRIES_EXCEEDED', 'card_state': 'unknown'}


def main():
    """Fonction principale"""
    start_time = time.time()

    log("=" * 80)
    log("Démarrage du monitoring des routeurs Nokia SROS")
    log(f"Nombre de routeurs à surveiller: {len(ROUTERS)}")
    log("=" * 80)
    
    # Exécution en parallèle avec ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(ROUTERS)) as executor:
        # Soumettre toutes les tâches
        futures = {executor.submit(monitor_card, router): router for router in ROUTERS}
        
        # Récupérer les résultats au fur et à mesure
        results = []
        for future in as_completed(futures):
            router = futures[future]
            try:
                result = future.result()
                results.append(result)
                log(f"Terminé pour {result['host']}: {result['status']}")
            except Exception as e:
                log(f"Erreur pour {router['host']}: {str(e)}")
                results.append({'host': router['host'], 'status': 'EXCEPTION', 'error': str(e)})


    # Calcul du temps d'exécution
    end_time = time.time()
    duration = end_time - start_time
    duration_formatted = format_duration(duration)

    # Affichage du résumé
    log("=" * 80)
    log("RÉSUMÉ DES OPÉRATIONS")
    log("=" * 80)
    
    for result in results:
        status_icon = "✓" if result['status'] == 'OK' else "✗"
        log(f"{status_icon} {result['host']}: {result['status']} (Carte: {result.get('card_state', 'N/A')})")
    
    log("=" * 80)
    log(f"Temps d'exécution total: {duration_formatted}")
    log("Fin du monitoring")


if __name__ == "__main__":
    main()