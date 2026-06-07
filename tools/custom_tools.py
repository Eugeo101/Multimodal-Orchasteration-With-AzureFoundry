"""
tools/custom_tools.py
──────────────────────
Custom FunctionTools that require client-side execution.
These wrap external model APIs that are NOT natively supported as
built-in Foundry tools or MCP servers.

Models used:
  • mistral-document-ai-2512  → Image/document → structured markdown text
    API: POST {endpoint}/v1/ocr
    Body: { model, document: { type: "image_url"|"document_url", image_url }, include_image_base64 }

  • FLUX-1.1-pro               → Text → image generation
    API: POST {foundry_endpoint}/providers/blackforestlabs/v1/flux-pro-1.1?api-version=preview
    Body: { model, prompt, width, height, steps, guidance }
    Returns: { images: [{ url }] } or { data: [{ url }] }

Both are called when the agent emits a function_call item in its response.
The dispatcher in agent/agent.py routes by function name.
"""

import base64
import json
import time
from pathlib import Path

import requests
from azure.ai.projects.models import FunctionTool


# ─────────────────────────────────────────────────────────────────────────────
# Mistral Document AI — Image → Text (OCR + structured markdown)
# ─────────────────────────────────────────────────────────────────────────────

def _call_mistral_ocr_robust(image_input: str, cfg: dict) -> str:
    """
    Robust Mistral OCR caller that accepts multiple endpoint shapes and
    tries sensible URL variants when the provided endpoint doesn't directly
    map to the working /v1/ocr endpoint.
    """
    m_cfg = cfg["models"]["image_to_text"]
    raw_endpoint = (m_cfg.get("endpoint") or "").rstrip("/")
    api_key = m_cfg.get("api_key")
    model_name = m_cfg.get("name")

    if not raw_endpoint:
        return json.dumps({"error": "Mistral OCR endpoint not configured. Fill in models.image_to_text.endpoint in config.yaml."})
    if not api_key:
        return json.dumps({"error": "Mistral OCR api_key not configured. Fill in models.image_to_text.api_key in config.yaml."})

    # Prepare document payload
    if image_input.startswith("http://") or image_input.startswith("https://"):
        doc_type = "image_url"
        doc_value = image_input
    else:
        path = Path(image_input)
        if not path.exists():
            return json.dumps({"error": f"Local file not found: {image_input}"})
        suffix = path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                    "gif": "gif", "webp": "webp", "bmp": "bmp",
                    "pdf": "pdf"}
        mime = mime_map.get(suffix, "jpeg")
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        if mime == "pdf":
            doc_type = "document_url"
            doc_value = f"data:application/pdf;base64,{b64}"
        else:
            doc_type = "image_url"
            doc_value = f"data:image/{mime};base64,{b64}"

    payload = {
        "model": model_name,
        "document": {
            "type": doc_type,
            doc_type: doc_value,
        },
        "include_image_base64": False,
    }

    # Candidate endpoints
    candidates = []
    if raw_endpoint.endswith("/v1/ocr"):
        candidates.append(raw_endpoint)
    elif raw_endpoint.endswith("/ocr"):
        candidates.append(raw_endpoint)
        candidates.append(raw_endpoint + "/v1/ocr")
    else:
        candidates.append(raw_endpoint + "/v1/ocr")
        candidates.append(raw_endpoint + "/providers/mistral/azure/ocr")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_error = None
    data = None
    for url in candidates:
        try:
            print(f"Calling Mistral OCR URL: {url}")
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 404:
                last_error = f"HTTP 404 from {url}: {resp.text}"
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.HTTPError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text}" if e.response is not None else str(e)
            continue
        except Exception as e:
            last_error = str(e)
            continue

    if data is None:
        return json.dumps({"error": f"All OCR endpoint candidates failed. Last error: {last_error}", "tried": candidates})

    pages = data.get("pages", [])
    full_markdown = "\n\n---\n\n".join(p.get("markdown", "") for p in pages).strip()
    return json.dumps({"markdown": full_markdown, "pages": len(pages)}, ensure_ascii=False)


def build_image_to_text_tool() -> FunctionTool:
    """
    FunctionTool schema for image_to_text.
    The agent calls this when the user provides an image/document and asks
    for description, OCR, text extraction, or analysis.
    """
    return FunctionTool(
        name="image_to_text",
        description=(
            "Extract text and understand the content of an image or document. "
            "Returns structured markdown preserving tables, headings, and layout. "
            "Use this when the user shares an image URL or local image path and asks to: "
            "read, describe, extract text, analyze, or understand the image/document."
            "This function cannot work on Audio Files Ever Never YOU CANT USE IT FOR AUDIO FILE EVER OR PROJECT WILL FAIL"
        ),
        parameters={
            "type": "object",
            "properties": {
                "image_input": {
                    "type": "string",
                    "description": (
                        "The image to analyze. Can be: "
                        "(1) A public HTTPS URL to an image or PDF, "
                        "(2) A local file path like 'assets/invoice.png'. "
                        "Supported formats: JPEG, PNG, GIF, WEBP, BMP, PDF."
                    ),
                },
            },
            "required": ["image_input"],
            "additionalProperties": False,
        },
        strict=True, # follow schema strictly of tool
    )

# ─────────────────────────────────────────────────────────────────────────────
# FLUX-1.1-pro — Text → Image Generation
# ─────────────────────────────────────────────────────────────────────────────

def _call_flux_image_gen(prompt: str, cfg: dict) -> str:
    """
    Calls the FLUX-1.1-pro image generation endpoint via Azure Foundry.

    Endpoint pattern (from official Microsoft + BFL docs):
      POST {foundry_base}/providers/blackforestlabs/v1/flux-pro-1.1?api-version=preview
      Header: Authorization: Bearer {api_key}
      Body:   { model, prompt, width, height, steps, guidance }

    Where {foundry_base} is the base of the project endpoint (without /api/projects/...).
    Saves the generated image to output/Images/ and returns the local path.
    """
    flux_cfg = cfg["models"]["image_generation"]
    deployment = flux_cfg["deployment_name"]  # must be lowercase

    # Derive the base Foundry endpoint (strip /api/projects/... suffix)
    full_endpoint = cfg["endpoint"]
    # e.g. "https://ahmedy-8325-resource.services.ai.azure.com/api/projects/ahmedy-8325"
    # base = "https://ahmedy-8325-resource.services.ai.azure.com"
    base = full_endpoint.split("/api/projects/")[0].rstrip("/")

    url = f"{base}/providers/blackforestlabs/v1/flux-pro-1.1?api-version=preview"

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": deployment,
        "prompt": prompt,
        "width": flux_cfg.get("width", 1024),
        "height": flux_cfg.get("height", 1024),
        "steps": flux_cfg.get("steps", 28),
        "guidance": flux_cfg.get("guidance", 3.5),
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # Response shape: { "images": [{"url": "..."}] } or { "data": [{"url": "..."}] }
        image_url = None
        if "images" in data and data["images"]:
            image_url = data["images"][0].get("url") or data["images"][0].get("b64_json")
        elif "data" in data and data["data"]:
            image_url = data["data"][0].get("url") or data["data"][0].get("b64_json")

        if not image_url:
            return json.dumps({"error": "No image URL in FLUX response", "raw": data})

        # Save the image
        output_dir = Path(cfg["output"]["images"])
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"flux_{int(time.time())}.jpg"
        save_path = output_dir / filename

        with open(save_path, "wb") as f:
            f.write(base64.b64decode(image_url))

        return json.dumps({
            "saved_to": str(save_path),
            "message": f"Image saved to {save_path}",
        })

    except requests.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def build_image_generation_tool() -> FunctionTool:
    """
    FunctionTool schema for generate_image.
    The agent calls this when the user asks to generate, create, or draw an image.
    The agent should refine the prompt before calling (per system instructions).
    """
    return FunctionTool(
        name="generate_image",
        description=(
            "Generate a high-quality image from a text description using FLUX-1.1-pro. "
            "Call this when the user asks to generate, create, draw, or make an image. "
            "The prompt passed here should already be refined and vivid — "
            "add lighting, style, and detail before calling."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "A detailed, vivid text description of the image to generate. "
                        "Example: 'A photorealistic Egyptian pyramid at golden hour, "
                        "dramatic side lighting, cinematic wide angle, 4K detail.'"
                    ),
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        strict=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher — called by agent/agent.py for every function_call item
# ─────────────────────────────────────────────────────────────────────────────

def dispatch_function_call(name: str, arguments: str, cfg: dict) -> str:
    """
    Routes the agent's function_call request to the correct Python function.
    Returns a JSON string to send back as FunctionCallOutput.
    """
    args = json.loads(arguments)

    if name == "image_to_text":
        image_input = args.get("image_input")
        # Quick guard: if the provided input looks like audio, don't call OCR.
        if isinstance(image_input, str) and image_input.lower().endswith(('.wav', '.mp3', '.ogg', '.flac', '.m4a')):
            return json.dumps({
                "error": "Input appears to be an audio file. Not running OCR.",
                "note": "Please call the SpeechToText tool for transcription or re-run with an image file.",
                "redirect_to": "SpeechToText",
            })

        # Use the robust caller which probes multiple endpoint shapes
        return _call_mistral_ocr_robust(
            image_input=args["image_input"],
            cfg=cfg,
        )

    if name == "generate_image":
        return _call_flux_image_gen(
            prompt=args["prompt"],
            cfg=cfg,
        )

    return json.dumps({"error": f"Unknown function: '{name}'"})
