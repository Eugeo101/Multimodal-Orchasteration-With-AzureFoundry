"""
agent/agent.py
───────────────
The Agent class is the single entry point for all agent operations.

Public API:
  Agent(config_path)   — load config.yaml, validate, wire up clients
  .create_version()    — push a new versioned agent definition to Azure Foundry
  .run_interactive()   — start a terminal REPL for testing
  .send(message, file) — single-turn send (used by main.py)

Internal helpers are prefixed with _.
"""

from pathlib import Path
import yaml
import json
import re
from urllib.parse import quote, urlparse, urlunparse

# play audio files (mp3)
from pydub import AudioSegment
from pydub.playback import play

# Azure credentials
from azure.ai.projects import AIProjectClient
# from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential

# Blob storage
from azure.storage.blob import BlobClient

## Azure Configurations 
from azure.ai.projects.models import (
    PromptAgentDefinition,
    Tool,
    WebSearchTool,
)

## Prompts
from prompts.prompts import build_system_prompt, IMAGE_OCR_PROMPT

## Tools
from tools.custom_tools import (
    build_image_generation_tool,
    build_image_to_text_tool,
    dispatch_function_call,
)
from tools.mcp_tools import (
    build_knowledge_base_mcp,
    build_language_mcp,
    build_speech_mcp,
)

## Orchasteration Messages:
from openai.types.responses.response_input_param import FunctionCallOutput

class Agent:
    """
    Wraps Azure Foundry Agent creation, versioning, and interaction.

    Everything is read from config.yaml in __init__ so the rest of the
    code never hard-codes credentials or URLs.
    """

    def __init__(self, config_path: str = "config.yaml"):
        # ── Load & validate config ────────────────────────────────────────────
        cfg_file = Path(config_path)
        if not cfg_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(cfg_file, "r", encoding="utf-8") as f:
            self.cfg: dict = yaml.safe_load(f)

        # ── Audio mode flag (set by send() when user asks to transcribe) ──────
        self._audio_mode = False

        # ── Create output directories ───────────────────────────────────
        for key in ("audios", "images", "base"):
            Path(self.cfg["output"][key]).mkdir(parents=True, exist_ok=True)

        # ── Azure Foundry project client (key auth) ───────────────────────────
        self.project_client = AIProjectClient(
            endpoint=self.cfg["endpoint"],
            credential=DefaultAzureCredential(),
        )

        # ── OpenAI Responses client (for Responses API calls) ─────────────────
        self.client = self.project_client.get_openai_client()

        # ── Build tool list ───────────────────────────────────────────────────
        self.tools: list[Tool] = self._build_tools()

        # ── Current agent version (set after create_version) ──────────────────
        self.agent = None
        self.conversation = None
        # If set, forces using a specific tool (e.g., "SpeechToText") for the next send
        self._forced_tool: str | None = None

        print(f"✅ Agent initialized — project: {self.cfg['endpoint']}")

    # ─────────────────────────────────────────────────────────────────────────
    # Public: create / push a new agent version to Azure Foundry
    # ─────────────────────────────────────────────────────────────────────────

    def create_version(self) -> object:
        """
        Push a new versioned agent definition to Azure Foundry.
        Returns the created agent version object.
        """
        system_prompt = build_system_prompt(self.cfg)

        self.agent = self.project_client.agents.create_version(
            agent_name=self.cfg["agent_name"],
            definition=PromptAgentDefinition(
                model=self.cfg["orchestrator_model"],
                instructions=system_prompt,
                tools=self.tools,
                # temperature=1.0,
                # top_p=1.0,
            ),
            description=(
                "Multimodal agent: image OCR (Mistral), image gen (FLUX), "
                "Speech STT/TTS, Language detection, web search, knowledge base RAG."
            ),
        )

        print(f"\n{'─'*55}")
        print(f"  ✅ New agent version pushed to Azure Foundry")
        print(f"  Name    : {self.agent.name}")
        print(f"  Version : {self.agent.version}")
        print(f"  ID      : {self.agent.id}")
        print(f"{'─'*55}\n")
        return self.agent

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: upload & download & play audio files to/from blob storage
    # ─────────────────────────────────────────────────────────────────────────

    def _upload_audio_to_blob(self, file_path: str) -> str:
        """
        Upload a local audio file to blob storage.
        Returns the blob URL (with SAS token).
        """
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        blob_sas_url = self.cfg.get("blob_sas_url")
        if not blob_sas_url:
            raise ValueError("blob_sas_url not configured in config.yaml")

        file_name = Path(file_path).name
        
        try:
            parsed = urlparse(blob_sas_url)
            base_path = parsed.path.rstrip("/") + "/" + quote(file_name)
            
            blob_url_without_sas = urlunparse((parsed.scheme, parsed.netloc, base_path, "", "", ""))

            blob_url_with_sas = blob_url_without_sas + "?" + parsed.query if parsed.query else blob_url_without_sas
            
            with open(file_path, "rb") as audio_file:
                blob_client = BlobClient.from_blob_url(blob_url=blob_url_with_sas)
                blob_client.upload_blob(audio_file, overwrite=True)
            
            print(f"✅ Audio uploaded to blob: {blob_url_with_sas[:80]}...")
            return blob_url_with_sas
        except Exception as error:
            print(f"❌ Blob upload failed: {error}")
            raise

    def download_audio_from_blob(self, blob_url: str) -> str:
        """
        Download audio from Azure Blob Storage into:
            outputs/Audios/synthetic_audio_N.wav

        Returns local file path.
        """

        output_dir = Path("output/Audios")
        output_dir.mkdir(parents=True, exist_ok=True)

        next_id = len(list(output_dir.glob("synthetic_audio_*.wav"))) + 1
        ext = Path(urlparse(blob_url).path).suffix # save with mp3 extension
        local_path = output_dir / f"synthetic_audio_{next_id}{ext}"

        blob_client = BlobClient.from_blob_url(blob_url)

        with open(local_path, "wb") as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())

        print(f"✅ Audio downloaded: {local_path}")
        return str(local_path)

    def play_audio(self, path: str):
        audio = AudioSegment.from_file(path)
        play(audio)

    # ─────────────────────────────────────────────────────────────────────────
    # Public: single-turn message send
    # ─────────────────────────────────────────────────────────────────────────

    def send(self, message: str, file_path: str | None = None) -> str:
        """
        Entry router (regex-only, no keyword matching).
        Decides:
        - image → direct OCR tool
        - audio → rewrite for MCP Speech
        - else → agent reasoning loop
        """

        if self.agent is None:
            raise RuntimeError("No agent version loaded. Call create_version() first.")

        text = message or ""

        # ─────────────────────────────
        # REGEX PATTERNS ONLY
        # ─────────────────────────────
        audio_re = re.compile(r'(\S+\.(wav|mp3|ogg|flac|m4a))', re.IGNORECASE)
        image_re = re.compile(r'(\S+\.(png|jpg|jpeg|gif|webp|bmp|pdf))', re.IGNORECASE)

        audio_match = audio_re.search(text)
        image_match = image_re.search(text)

        file_path = file_path or (audio_match.group(1) if audio_match else None) or (image_match.group(1) if image_match else None)

        # ─────────────────────────────
        # IMAGE → DIRECT EXECUTION
        # ─────────────────────────────
        if image_match:
            print("🖼 IMAGE detected via regex")

            ocr_output = dispatch_function_call(
                name="image_to_text",
                arguments=json.dumps({"image_input": image_match.group(1)}),
                cfg=self.cfg,
            )
            ocr_output = json.loads(ocr_output)
            ocr_output_text = ocr_output['markdown'] if isinstance(ocr_output['pages'], int) else ("\n\n".join(page.get("markdown", "") for page in ocr_output['pages']))
            text = IMAGE_OCR_PROMPT.format(text=text, ocr_output=ocr_output_text)

        # ─────────────────────────────
        # AUDIO → UPLOAD & MCP ROUTING
        # ─────────────────────────────
        if audio_match:
            print("🎧 AUDIO detected via regex")
            local_audio_path = audio_match.group(1)
            
            try:
                blob_url = self._upload_audio_to_blob(local_audio_path)
                text = f"transcribe this speech file: {blob_url}"
                print(f"✅ Audio rewritten with blob URL")
            except Exception as error:
                print(f"❌ Audio upload failed: {error}")
                text = f"transcribe this speech file: {local_audio_path}"

        # ─────────────────────────────
        # DEFAULT → REACT LOOP
        # ─────────────────────────────
        if self.conversation is None:
            self.conversation = self.client.conversations.create()

        return self._send_with_function_loop(text)

    # ─────────────────────────────────────────────────────────────────────────
    # Public: interactive terminal REPL
    # ─────────────────────────────────────────────────────────────────────────

    def run_interactive(self) -> None:
        """
        Start a terminal REPL to test the agent interactively.
        Type 'exit' or 'quit' to stop.
        Type 'file: <path>' on a line to attach a local file to your next message.
        """
        if self.agent is None:
            print("⚠️  No agent version loaded. Creating one now...")
            self.create_version()

        self.conversation = self.client.conversations.create()
        print(f"\n{'═'*55}")
        print(f"  Ahmed-Agent Interactive Mode")
        print(f"  Type 'exit' to quit.")
        print(f"  Tip: prefix with 'file: <path>' to attach a file.")
        print(f"{'═'*55}\n")

        pending_file: str | None = None

        while True:
            try:
                user_input = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n\nSession ended.")
                break

            if not user_input:
                continue

            low = user_input.lower()
            if low in ("exit", "quit", "bye"):
                print("Goodbye! 👋")
                break

            # Allow attaching a file on its own line
            if low.startswith("file:"):
                pending_file = user_input[5:].strip()
                print(f"  📎 File queued: {pending_file}")
                continue

            # Build full message
            msg = user_input
            if pending_file:
                msg = f"{msg}\n\nFile: {pending_file}"
                pending_file = None

            print()
            response_text = self.send(msg)
            print(f"Agent: {response_text}\n")

        # Cleanup conversation
        try:
            self.client.conversations.delete(conversation_id=self.conversation.id)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _send_with_function_loop(self, message: str) -> str:
        """
        Foundry ReACT loop (clean separation):
        - MCP tools: ignored (Azure handles them)
        - FunctionTools: executed locally via dispatcher
        - everything else: normal response
        """

        response = self.client.responses.create(
            input=message,
            conversation=self.conversation.id,
            extra_body={
                "agent_reference": {
                    "name": self.agent.name,
                    "type": "agent_reference",
                }
            },
        )

        print("\n════════ TURN START ════════")

        input_list = []
        has_function_calls = False

        # ─────────────────────────────
        # FUNCTION TOOL REGISTRY
        # ─────────────────────────────
        FUNCTION_TOOLS = [
            "image_to_text",
            "generate_image",
        ]

        # ─────────────────────────────
        # NORMALIZER
        # ─────────────────────────────
        def convert_item_tool_to_dict(item):
            return {
                "type": getattr(item, "type", None),
                "name": getattr(item, "name", None) or getattr(item, "tool_name", None),
                "args": getattr(item, "arguments", None) or getattr(item, "input", None),
                "id": getattr(item, "call_id", None) or getattr(item, "id", None),
            }

        # ─────────────────────────────
        # PROCESS OUTPUTS
        # ─────────────────────────────
        for i, item in enumerate(response.output):
            item_tool = convert_item_tool_to_dict(item)
            
            # ── IGNORE MCP HANDSHAKE / SERVER TOOLS ──
            if item_tool["type"] == "mcp_list_tools":
                print("⊘ MCP handshake ignored")
                continue

            # if audio generated
            if item_tool['name'] == 'text_to_speech':
                audio_json_output = json.loads(item.output)
                audio_url = audio_json_output.get('audio_url', "")
                audio_local_path = self.download_audio_from_blob(blob_url=audio_url) # downloaded with correct index
                self.play_audio(audio_local_path)
                continue

            # ── FUNCTION TOOL EXECUTION ──
            is_function = (
                item_tool["type"] in ("function_call", "tool_call")
                or item_tool["name"] in FUNCTION_TOOLS
            )

            if is_function:
                print(f"EXECUTING FUNCTION item_tool[{i}] ⚡, name={item_tool['name']}, type={item_tool['type']}")

                args = item_tool["args"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                result = dispatch_function_call(
                    name=item_tool["name"],
                    arguments=json.dumps(args),
                    cfg=self.cfg,
                )

                input_list.append(
                    FunctionCallOutput(
                        type="function_call_output",
                        call_id=item_tool["id"] or "",
                        output=result,
                    )
                )

                has_function_calls = True
                continue

            # ── MCP + NORMAL MODEL OUTPUT → IGNORE HERE ──
            print("   → MCP or assistant output (handled by Azure)")
            continue

        # ─────────────────────────────
        # SECOND PASS (ONLY IF FUNCTION EXECUTION HAPPENED)
        # ─────────────────────────────
        if has_function_calls:
            response = self.client.responses.create(
                input=input_list,
                conversation=self.conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": self.agent.name,
                        "type": "agent_reference",
                    }
                },
            )

        print("════════ TURN END ════════\n")
        return response.output_text or "(no response)"

    def _build_tools(self) -> list[Tool]:
        """
        Assembles the full tool list from config.
        FunctionTools + MCPTools + WebSearchTool.
        """
        return [
            # ── Custom FunctionTools (client-side execution) ──────────────
            build_image_to_text_tool(),    # Mistral Document AI
            build_image_generation_tool(), # FLUX-1.1-pro

            # ── MCP Tools (server-side, Azure handles execution) ──────────
            build_speech_mcp(self.cfg),         # STT + TTS
            build_language_mcp(self.cfg),       # LanguageDetection + NER + etc.
            build_knowledge_base_mcp(self.cfg), # RAG knowledge base

            # ── Built-in tools ────────────────────────────────────────────
            WebSearchTool(),
        ]