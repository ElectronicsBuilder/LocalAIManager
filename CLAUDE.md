# CLAUDE.md

All project instructions for Claude Code live in **[AGENTS.md](AGENTS.md)**,
which is shared with every other coding agent on this project. Read it in full
before doing anything, then read `docs/PROJECT_HANDOFF.md`.

@AGENTS.md

Key reminders (AGENTS.md is authoritative if anything here disagrees):

- Run `uv run pytest -v` before and after changes; report real results only.
- Update `docs/PROJECT_HANDOFF.md`, `docs/DECISIONS.md`, and
  `docs/CHANGELOG.md` as described in AGENTS.md §1.
- Never modify Windows startup, the registry, WSL configuration, or sudo
  permissions, and never stop Ollama or unload models, without explicit
  authorization from the user.
- English only.
