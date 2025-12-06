# 🤖 Agent Réseau - Automatisation avec IA
Agent conversationnel intelligent pour l'automatisation réseau, combinant Vertex AI Gemini, Neo4j Graph Database et Model Context Protocol (MCP).

## 📁 Structure
```
network_agent_simple/
├── config.py           # Configuration (Vertex AI, Neo4j, MCP)
├── tools.py            # Tools custom (GDS + Traffic Engineering) 
├── network_agent.py    # Code principal (Agent + MCP + Main)
├── .env       # Template configuration
└── README.md          # Documentation (ce fichier)
```


## 🚀 Installation rapide
```bash
# 1. Installer dépendances
pip install -r requirements.txt
pip install mcp-neo4j-cypher

# 2. Configurer
cp .env.example .env
nano .env  # Éditer avec vos credentials

# 3. Lancer
python network_agent.py
```

### Configuration .env
```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
GOOGLE_CLOUD_PROJECT=your-project-id

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
```

## 💡 Exemples
```
💬 Donne moi le schéma de la base
💬 Combien de PROD_ROUTER j'ai ?
💬 Donne moi les propriétés de la relation PROD_ROUTING_LINK ?
💬 Quel est le chemin le plus court entre R1 et R3 ?
💬 Quel est le chemin le plus court entre R1 et R3 selon la distance ?
💬 Donne moi la payload NSO pour réaliser un traffic engineering entre R1 et R3 basé sur l'attribut distance pour le service VPRN TSP?
```

## 📚 Architecture
### 1. config.py - Configuration
- Charge variables `.env`
- Initialise Vertex AI
- Configure Neo4j et MCP


### 2. tools.py - Tools Custom
**Architecture avec classe `NetworkTools`** 🎯

```python
class NetworkTools:
    def __init__(self):
        # Connexion Neo4j réutilisable
        self.driver = GraphDatabase.driver(...)
    
    def find_shortest_path(...)      # Plus court chemin
    def perform_traffic_engineering(...)  # Config NSO
    def close(self)                  # Fermeture propre
```

**Fonctions clés :**
- `create_graph_projection()` - Projection GDS dynamique
- `find_shortest_path()` - Plus court chemin (texte)
- `perform_traffic_engineering()` - Config XML NSO
- `get_*_declaration()` - Déclarations Vertex AI


**Comment ça marche :**
1. Analyse propriétés numériques des relations
2. Crée projection GDS avec mapping sur "weight"
3. Exécute Dijkstra
4. Récupère métadonnées complètes
5. Formate en texte OU XML

### 3. network_agent.py - Agent Principal
**Composants :**
```python
MCPClient           # Connexion serveur MCP + appels tools
GeminiAgent         # Agent conversationnel
  ├─ initialize()   # Charge tous les tools
  ├─ process_query # Traite requête utilisateur
  └─ _handle_tool_call() # Route MCP vs custom
main()              # Boucle conversationnelle
```

**Flux d'une requête :**
```
User → Agent → Gemini décide tool → Route vers MCP/custom → 
Exécution → Résultat → Gemini reformule → User
```