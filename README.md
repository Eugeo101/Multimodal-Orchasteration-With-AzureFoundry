# Ahmed-Agent — Azure Foundry Multimodal Agent

## Project Structure

```
agent_project/
├── config.yaml              ← All credentials, model names, URLs (edit this)
├── main.py                  ← Entry point
├── requirements.txt
│
├── tools/
│   ├── mcp_tools.py         ← MCPTool builders: Speech, Language, Knowledge Base
│   └── custom_tools.py      ← FunctionTool builders + callers: Mistral OCR, FLUX image gen
│
├── prompts/
│   └── prompts.py           ← System prompt + model-specific prompt strings
│
├── agent/
│   └── agent.py             ← Agent class: init, create_version, send, run_interactive
│
├── output/
│   ├── Audios/              ← TTS output audio files saved here
│   └── Images/              ← FLUX generated images saved here
│
└── assets/                  ← Drop local files here (images, audio) to pass to agent
```

## Setup

```bash
pip install -r requirements.txt
az login          # for DefaultAzureCredential (or use api_key in config.yaml)
```

## Configuration

Open `config.yaml` and fill in:

| Key | Where to find it |
|-----|-----------------|
| `models.image_to_text.endpoint` | Foundry → your Mistral deployment → Endpoint |
| `models.image_to_text.api_key`  | Foundry → your Mistral deployment → Key |
| `models.image_generation.deployment_name` | Must match your FLUX deployment name exactly (lowercase) |
| `blob_sas_url` | Already filled in — regenerate when it expires |

Everything else is already populated from your existing config.

## Usage Examples

```bash
# Interactive REPL — starts a multi-turn chat loop
python main.py
```

### 1) 🖼️ Image Input
```bash
Analyze this image assets/sample.jpg
```

### 2) 🎙️ Audio Input — Transcription
```bash
Transcribe this speech file assets/record_test.wav
```

### 3) 📄 RAG — Query your documents
```bash
What does the company policy say about remote work?
```

### 4) 🌐 Web Search — Live information retrieval
```bash
What are the latest news about Microsoft Build?
# → Searches the web in real time and summarizes results
```

### 5) 🔤 NLP — Language & text analysis
```bash
What language is this? 'Bonjour tout le monde'
```

### 6) 🔊 Audio Output — Text-to-speech
```bash
Say: Hello world
# → Generates and plays back spoken audio
```

### 7) 🎨 Image Output — Generation
```bash
Generate Image: a baby white bear
# → Returns a generated image saved to outputs/
```

## What each tool does

| User says | Tool called | Output |
|-----------|------------|--------|
| "speech mode" + audio file | `SpeechToText` MCP | Text transcript |
| "say: Hello world" | `TextToSpeech` MCP | `output/Audios/tts_output.mp3` |
| Image URL or path | `image_to_text` FunctionTool | Markdown text + OCR |
| "generate an image of..." | `generate_image` FunctionTool | `output/Images/flux_<ts>.png` |
| "what language is this?" | `LanguageDetection` MCP | Language name + confidence |
| Current events / news | `web_search` built-in | Search results |
| Company docs / policies | `knowledge_base_retrieve` MCP | RAG answer |
| Everything else | (none) | Direct answer |

## Notes

- **FLUX SAS URL**: The `blob_sas_url` in config.yaml expires on `2026-06-06T12:12:10Z`.
  Generate a new one from Azure Portal → Storage Account → Containers → your container → Shared access tokens.
- **Mistral endpoint**: After deploying `mistral-document-ai-2512` in Foundry,
  copy the endpoint from the deployment page (looks like `https://mistral-doc-xxx.eastus2.models.ai.azure.com`).
- **FLUX deployment name**: Must be lowercase in config. If you named it `FLUX-1.1-pro` in the portal,
  set `deployment_name: flux-1.1-pro` in config.yaml.
