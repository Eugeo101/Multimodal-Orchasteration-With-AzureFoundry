"""
app.py
───────
FastAPI wrapper around Agent.send().
Exposes:
  POST /chat          — text message
  POST /chat/file     — message + uploaded file (image or audio)
  GET  /health        — liveness probe for Azure Container Apps
  GET  /              — basic info

The Agent is initialized ONCE at startup (lifespan) and reused for all requests.
Each request gets its own conversation (stateless per-call).

Run locally:
  uvicorn app:app --host 0.0.0.0 --port 8000 --reload

In Docker / Azure Container Apps it runs via the CMD in Dockerfile.
"""

import io
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ── Make project root importable ─────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))

from agent.agent import Agent

# ── Global agent instance (created once at startup) ──────────────────────────
_agent: Agent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent on startup, clean up on shutdown."""
    global _agent
    print("🚀 Starting Ahmed-Agent service...")

    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    _agent = Agent(config_path=config_path)

    # Load the latest existing version — do NOT push a new version on every startup.
    # Push a new version explicitly using: python main.py --push
    latest = _agent.load_latest_version()
    if latest is None:
        print("⚠️  No existing version found — creating first version...")
        _agent.create_version()
    else:
        print(f"✅ Loaded existing agent version: {latest.version}")

    yield

    # Shutdown
    print("👋 Ahmed-Agent service shutting down.")


app = FastAPI(
    title="Ahmed-Agent API",
    description="Multimodal Azure Foundry Agent: OCR, Speech, Image Gen, Web Search, RAG",
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    version = _agent.agent.version if (_agent and _agent.agent) else "not loaded"
    return {
        "service": "Ahmed-Agent",
        "agent_version": version,
        "endpoints": {
            "POST /chat": "Send a text message",
            "POST /chat/file": "Send a message with an image or audio file",
            "GET /health": "Health check",
        },
    }


@app.get("/health")
def health():
    """Liveness probe — Azure Container Apps calls this every 30s."""
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Send a plain text message to the agent.

    Examples:
      {"message": "Hello, who are you?"}
      {"message": "What is the latest news about AI?"}
      {"message": "What language is this? مرحبا بالعالم"}
      {"message": "Generate an image of a sunset over the Nile"}
      {"message": "Say: Welcome to Ahmed-Agent"}
    """
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Each /chat call gets a fresh conversation (stateless)
    _agent.conversation = None

    try:
        reply = _agent.send(message=req.message)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/file", response_model=ChatResponse)
async def chat_with_file(
    message: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Send a message with an attached file (image or audio).

    Form fields:
      message  — text prompt (e.g. "Analyze this image", "Transcribe this")
      file     — image (.jpg .png .pdf) or audio (.wav .mp3 .ogg .flac .m4a)

    The file is saved temporarily, passed to the agent, then cleaned up.
    """
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Save uploaded file to temp dir
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    # Each /chat/file call gets a fresh conversation (stateless)
    _agent.conversation = None

    try:
        reply = _agent.send(message=message, file_path=tmp_path)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)