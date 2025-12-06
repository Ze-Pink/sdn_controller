"""
Agent Réseau - Gemini + MCP Neo4j + Tools Custom
Un agent conversationnel pour l'automatisation réseau combinant:
- Vertex AI Gemini pour l'intelligence
- Neo4j Graph Database pour la topologie
- MCP (Model Context Protocol) pour les outils Cypher
- Tools custom pour GDS et Traffic Engineering

Auteur: Marc De Oliveira
Date: 2025
"""

import os
import sys
import asyncio
import warnings
import traceback
import copy
from contextlib import contextmanager

# Suppression des warnings
warnings.filterwarnings('ignore')
os.environ['PYTHONWARNINGS'] = 'ignore'
import logging
logging.getLogger('vertexai').setLevel(logging.ERROR)

from mcp import ClientSession
from mcp.client.stdio import stdio_client
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration

import config
import tools

# ==============================================
# Utilitaires
# ==============================================

@contextmanager
def suppress_mcp_output():
    """Supprime stderr pour masquer les messages du serveur MCP."""
    stderr_fd = sys.stderr.fileno()
    stderr_backup = os.dup(stderr_fd)
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, stderr_fd)
        os.close(devnull)
        yield
    finally:
        os.dup2(stderr_backup, stderr_fd)
        os.close(stderr_backup)

# ==============================================
# MCP Client
# ==============================================

class MCPClient:
    """Gère la connexion au serveur MCP Neo4j Cypher."""
    
    def __init__(self):
        self.cypher_tools = []
        self.server_params = config.MCP_SERVER_PARAMS
    
    async def initialize(self):
        """Initialise et récupère les tools MCP."""
        print("🔄 Connexion au serveur MCP Neo4j Cypher...")
        try:
            with suppress_mcp_output():
                async with stdio_client(self.server_params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        self.cypher_tools = tools_result.tools
            
            print(f"✅ Serveur Cypher: {len(self.cypher_tools)} tools")
            for tool in self.cypher_tools:
                print(f"   - {tool.name}")
        except Exception as e:
            print(f"❌ Erreur serveur Cypher: {e}")
            raise
    
    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Appelle un tool MCP en créant une session isolée."""
        if not any(t.name == tool_name for t in self.cypher_tools):
            return f"❌ Tool '{tool_name}' non trouvé"
        
        try:
            print(f"   🔧 Appel MCP: {tool_name}")
            with suppress_mcp_output():
                async with stdio_client(self.server_params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments)
                        return result.content[0].text if result and result.content else "Aucun résultat"
        except Exception as e:
            return f"❌ Erreur MCP: {str(e)}"

# ==============================================
# Conversion MCP → Vertex AI
# ==============================================

def clean_schema_for_vertexai(schema: dict) -> dict:
    """Nettoie un schéma JSON pour Vertex AI."""
    if not isinstance(schema, dict):
        return schema
    
    cleaned = copy.deepcopy(schema)
    unsupported = ['prefixItems', '$ref', '$defs', 'const', 'allOf', 'oneOf', 'not', '$schema', '$id']
    
    def clean_recursive(obj):
        if isinstance(obj, dict):
            for key in unsupported:
                obj.pop(key, None)
            
            if 'anyOf' in obj:
                any_of = obj.pop('anyOf')
                for option in any_of:
                    if isinstance(option, dict) and option.get('type') != 'null':
                        obj.update(option)
                        break
            
            for value in obj.values():
                if isinstance(value, dict):
                    clean_recursive(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            clean_recursive(item)
        return obj
    
    return clean_recursive(cleaned)


def mcp_tools_to_vertexai(mcp_tools_list) -> list[FunctionDeclaration]:
    """Convertit les tools MCP en FunctionDeclarations Vertex AI."""
    vertexai_tools = []
    for mcp_tool in mcp_tools_list:
        try:
            cleaned_schema = clean_schema_for_vertexai(mcp_tool.inputSchema or {"type": "object", "properties": {}})
            vertexai_tools.append(FunctionDeclaration(
                name=mcp_tool.name,
                description=mcp_tool.description or f"Tool: {mcp_tool.name}",
                parameters=cleaned_schema
            ))
        except Exception as e:
            print(f"⚠️ Impossible de convertir '{mcp_tool.name}': {e}")
    return vertexai_tools

# ==============================================
# Agent Gemini
# ==============================================

class GeminiAgent:
    """Agent conversationnel avec Gemini + MCP + Tools custom."""
    
    def __init__(self):
        self.mcp_client = MCPClient()
        self.network_tools = tools.NetworkTools()  # Instance de la classe NetworkTools
        self.model = None
        self.chat_session = None
    
    async def initialize(self):
        """Initialise l'agent avec tous les tools."""
        await self.mcp_client.initialize()
        
        # Convertir tools MCP
        gemini_mcp_tools = mcp_tools_to_vertexai(self.mcp_client.cypher_tools)
        print(f"✅ {len(gemini_mcp_tools)} tools MCP convertis")
        
        # Ajouter tools custom
        custom_tools = [
            tools.get_shortest_path_declaration(),
            tools.get_traffic_engineering_declaration()
        ]
        print(f"✅ {len(custom_tools)} tools custom ajoutés")
        
        # Combiner
        all_tools = gemini_mcp_tools + custom_tools
        print(f"\n📦 Total: {len(all_tools)} tools ({len(gemini_mcp_tools)} MCP + {len(custom_tools)} custom)")
        
        # Créer modèle
        tool_obj = Tool(function_declarations=all_tools)
        self.model = GenerativeModel("gemini-2.0-flash-001", tools=[tool_obj])
        self.chat_session = self.model.start_chat()
        print("✅ Session Gemini initialisée\n")
    
    def close(self):
        """Ferme proprement les ressources."""
        if self.network_tools:
            self.network_tools.close()
    
    def _confirm_execution(self, tool_name: str, arguments: dict) -> bool:
        """Demande confirmation pour les opérations d'écriture."""
        print("\n" + "!" * 50)
        print(f"⚠️  ATTENTION: MODIFICATION DE DONNÉES")
        print(f"   Tool: {tool_name}")
        if tool_name == "write_neo4j_cypher":
            print(f"   Query: {arguments.get('query', 'N/A')}")
        print("!" * 50)
        
        while True:
            response = input("   Autoriser l'exécution ? (oui/non) > ").strip().lower()
            if response in ['oui', 'o']:
                return True
            elif response in ['non', 'n']:
                return False
            print("   Répondre par 'oui' ou 'non'")
    
    async def _handle_tool_call(self, tool_name: str, arguments: dict) -> str:
        """Route les appels de tools vers MCP ou custom."""
        # Tools custom (méthodes de la classe NetworkTools)
        if tool_name == "find_shortest_path":
            return self.network_tools.find_shortest_path(
                arguments.get("start_node"),
                arguments.get("end_node"),
                arguments.get("weight_property", 'igp_metric')
            )
        
        if tool_name == "perform_traffic_engineering":
            return self.network_tools.perform_traffic_engineering(
                arguments.get("start_node"),
                arguments.get("end_node"),
                arguments.get("service_type"),
                arguments.get("service_name"),
                arguments.get("weight_property", 'igp_metric')
            )
        
        # Tools MCP
        return await self.mcp_client.call_tool(tool_name, arguments)
    
    async def process_query(self, user_query: str) -> str:
        """Traite une requête utilisateur avec tool calling."""
        response = self.chat_session.send_message(user_query)
        
        if not response.candidates:
            return "❌ Pas de réponse de Gemini"
        
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                func = part.function_call
                tool_name = func.name
                tool_args = dict(func.args)
                
                print(f"\n🔧 Gemini appelle: {tool_name}")
                print(f"   Paramètres: {tool_args}")
                
                # Confirmation pour write
                if tool_name == "write_neo4j_cypher":
                    if not self._confirm_execution(tool_name, tool_args):
                        print("   🚫 Exécution annulée")
                        return "Opération annulée par l'utilisateur"
                    print("   ✅ Exécution autorisée")
                
                # Appeler le tool
                result = await self._handle_tool_call(tool_name, tool_args)
                
                # Afficher résultat tronqué
                display = result[:500] + "..." if len(result) > 500 else result
                print(f"   ✅ Résultat: {display}")
                
                # Renvoyer à Gemini
                response = self.chat_session.send_message(f"Le résultat de {tool_name} est:\n{result}")
                return response.text
            
            elif hasattr(part, 'text') and part.text:
                return part.text
        
        return "❌ Gemini n'a pas fourni de réponse"

# ==============================================
# Main
# ==============================================

async def main():
    """Fonction principale."""
    print("\n" + "="*60)
    print("🤖 Agent Gemini + MCP Neo4j + Tools Custom")
    print("="*60 + "\n")
    
    # Initialiser l'agent
    try:
        agent = GeminiAgent()
        await agent.initialize()
    except Exception as e:
        print(f"\n❌ Erreur initialisation agent: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    # Exemples
    print("="*60)
    print("💡 Exemples de questions")
    print("="*60)
    print("  • Donne moi le schéma de la base")
    print("  • Combien de PROD_ROUTER j'ai ?")
    print("  • Donne moi les propriétés de la relation PROD_ROUTING_LINK ?")      
    print("  • Quel est le chemin le plus court entre R1 et R3 ?")
    print("  • Quel est le chemin le plus court entre R1 et R3 selon la distance ?")
    print("  • Donne moi la payload NSO pour réaliser un traffic engineering entre R1 et R3 basé sur l'attribut distance pour le service VPRN TSP?")
    print("\n  Tapez 'exit' pour quitter")
    print("="*60 + "\n")
    
    # Boucle conversationnelle
    while True:
        try:
            user_input = input("\n💬 Votre question > ").strip()
            
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n👋 Au revoir !")
                break
            
            if not user_input:
                continue
            
            print("\n" + "-"*60)
            response = await agent.process_query(user_input)
            print("\n🤖 Réponse:")
            print("-"*60)
            print(response)
            print("-"*60)
        
        except KeyboardInterrupt:
            print("\n\n👋 Au revoir !")
            break
        
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            traceback.print_exc()
    
    # Nettoyage
    agent.close()
    print("✅ Ressources fermées")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Au revoir !")
        sys.exit(0)
