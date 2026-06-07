"""
main.py
────────
Entry point. Modes:

  python main.py                           → interactive REPL (loads latest version)
  python main.py --push                    → push new version THEN interactive REPL
  python main.py "your message"            → single-turn (loads latest version)
  python main.py --push "your message"     → push new version THEN single-turn
  python main.py "analyze this" assets/photo.jpg → single-turn with file

RULE: Never push a new version automatically.
      Always require --push flag to be explicit.
      The deployed service (app.py) only loads, never pushes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.agent import Agent


def main():
    # ── Parse --push flag ─────────────────────────────────────────────────────
    args = sys.argv[1:]
    push_new_version = "--push" in args
    args = [a for a in args if a != "--push"]   # remove flag, keep rest

    # ── Initialize agent ──────────────────────────────────────────────────────
    agent = Agent(config_path="config.yaml")

    if push_new_version:
        agent.create_version()
        print(f"✅ Pushed new version to Azure Foundry.\n")
    else:
        latest = agent.load_latest_version()
        if latest is None:
            print("⚠️  No existing version found. Use --push to create first version.")
            sys.exit(1)

    # ── Decide mode ───────────────────────────────────────────────────────────
    if len(args) == 0:
        agent.run_interactive()

    elif len(args) == 1:
        message = args[0]
        print(f"\nYou: {message}\n")
        response = agent.send(message=message)
        print(f"Agent: {response}\n")

    elif len(args) == 2:
        message = args[0]
        file_path = args[1]
        if not Path(file_path).exists():
            print(f"⚠️  File not found: {file_path}")
            sys.exit(1)
        print(f"\nYou: {message}\nFile: {file_path}\n")
        response = agent.send(message=message, file_path=file_path)
        print(f"Agent: {response}\n")

    else:
        print("Usage:")
        print("  python main.py                               # interactive (latest version)")
        print("  python main.py --push                        # push new version + interactive")
        print('  python main.py "your message"                # single turn')
        print('  python main.py --push "your message"         # push + single turn')
        print('  python main.py "analyze this" assets/img.jpg # with file')
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

# Test Server using POST request or Swagger
# curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message": "Hello!"}'
# Swagger: http://localhost:8000/docs