"""
main.py
────────
Entry point. Two modes:

  python main.py                          → interactive REPL
  python main.py "your message here"      → single-turn, prints response
  python main.py "analyze this" assets/photo.jpg  → single-turn with file

The Agent is always created fresh (new version pushed) on startup.
To skip pushing a new version and reuse the latest, call agent.run_interactive()
without calling agent.create_version() first — it will auto-create only if needed.
"""

## Arguments Parsing
import sys
from pathlib import Path

## Make project root importable regardless of where python is invoked from
sys.path.insert(0, str(Path(__file__).parent))

## Agent
from agent.agent import Agent

def main():
    # ── Initialize agent (reads config.yaml) ─────────────────────────────────
    agent = Agent(config_path="config.yaml")

    # ── Push a new version to Azure Foundry ──────────────────────────────────
    agent.create_version()

    # ── Decide mode from CLI args ─────────────────────────────────────────────
    args = sys.argv[1:]

    if len(args) == 0:
        # No args → interactive terminal REPL
        agent.run_interactive()

    elif len(args) == 1:
        # One arg → single message, no file
        message = args[0]
        print(f"\nYou: {message}\n")
        response = agent.send(message=message)
        print(f"Agent: {response}\n")

    elif len(args) == 2:
        # Two args → message + file path
        message = args[0]
        file_path = args[1]

        if not Path(file_path).exists():
            print(f"⚠️  File not found: {file_path}")
            sys.exit(1)

        print(f"\nYou: {message}")
        print(f"File: {file_path}\n")
        response = agent.send(message=message, file_path=file_path)
        print(f"Agent: {response}\n")

    else:
        print("Usage:")
        print("  python main.py                              # interactive mode")
        print('  python main.py "your message"               # single turn')
        print('  python main.py "analyze this" assets/img.jpg  # with file')
        sys.exit(1)


if __name__ == "__main__":
    main()

# transcribe this speech file assets/record_test.wav [Audio Input]
# Analyze this image assets/sample.jpg [Image Input]
# what is AXIAN Company docs / policies say? [RAG]
# what is current news about Microsoft Build? [WEB SEARCH]
# what language is this? 'Hello everyone this is english language" [NLP]
# Say: Hello world [Audio Output]
# Generate Image: a baby white bear [Image Output]