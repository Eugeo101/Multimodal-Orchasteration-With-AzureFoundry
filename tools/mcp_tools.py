"""
tools/mcp_tools.py
──────────────────
Builds every MCPTool the agent uses.
All configuration is passed in from config.yaml via the cfg dict.

MCP tools are server-side — Azure runs them. No client-side execution needed.
"""

from azure.ai.projects.models import MCPTool

def build_speech_mcp(cfg: dict) -> MCPTool:
    """
    Azure Speech MCP Server — SpeechToText + TextToSpeech.

    HOW CREDENTIALS ACTUALLY WORK:
    ─────────────────────────────
    You do NOT pass headers (api_key, foundry-resource-name, X-Blob-Container-Url)
    in code. Instead, you set them ONCE in the Foundry portal when you connect
    the Azure Speech MCP Server tool:
      Tools → Add → Catalog → "Azure Speech MCP Server" → Create
        Parameters → foundry-resource-name: <your resource name>
        Authorization → Bearer (API Key): <KEY1 or KEY2>
        Authorization → X-Blob-Container-Url: <your container SAS URL>
      → Connect

    That creates a project connection named "UniqueMCPSpeechServer".
    In code you just reference it by project_connection_id.
    """
    speech = cfg["models"]["speech"]
    return MCPTool(
        server_label=speech["project_connection_id"],
        server_url=speech["server_url"],
        project_connection_id=speech["project_connection_id"], # authenticate with built server
        require_approval="never",
    )


def build_language_mcp(cfg: dict) -> MCPTool:
    """
    Azure Language MCP Server — LanguageDetection, NER, Sentiment, etc.

    Separate server from Speech. Uses the same resource api_key.
    allowed_tools is read from config so you can easily trim capabilities.
    """
    lang = cfg["models"]["language"]
    return MCPTool(
        server_label=lang["project_connection_id"],
        server_url=lang["server_url"],
        project_connection_id=lang["project_connection_id"],
        require_approval="never",
    )


def build_knowledge_base_mcp(cfg: dict) -> MCPTool:
    """
    Azure AI Search Knowledge Base MCP — knowledge_base_retrieve.

    Preserved from your original config.yaml (kb-knowledgebase703).
    """
    kb = cfg["existing_tools"]["knowledge_base"]
    return MCPTool(
        server_label=kb["server_label"],
        server_url=kb["server_url"],
        project_connection_id=kb["project_connection_id"],
        allowed_tools=[kb["allowed_tool"]],
        require_approval="never",
    )
