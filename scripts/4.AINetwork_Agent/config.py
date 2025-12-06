"""
Configuration de l'agent réseau.
Charge les variables d'environnement et initialise Vertex AI + MCP.

Auteur: Marc De Oliveira
Date: 2025
"""

import os
from dotenv import load_dotenv
import vertexai
from mcp import StdioServerParameters

load_dotenv()

# === Vertex AI ===
GOOGLE_CREDS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

if not GOOGLE_CREDS or not os.path.exists(GOOGLE_CREDS):
    raise ValueError("❌ GOOGLE_APPLICATION_CREDENTIALS manquant")
if not PROJECT_ID:
    raise ValueError("❌ GOOGLE_CLOUD_PROJECT manquant")

vertexai.init(project=PROJECT_ID, location=LOCATION)
print(f"✅ Vertex AI init (projet: {PROJECT_ID})")

# === Neo4j ===
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
GDS_GRAPH_PROJECTION_NAME = 'my_graph'
WEIGHT_PROPERTY = 'weight'

# === MCP Neo4j Cypher ===
args = ["--db-url", NEO4J_URI, "--username", NEO4J_USER, "--password", NEO4J_PASSWORD, "--database", NEO4J_DATABASE]
MCP_SERVER_PARAMS = StdioServerParameters(
    command="mcp-neo4j-cypher",
    args=args,
    env={**os.environ.copy(), "PYTHONWARNINGS": "ignore"}
)
