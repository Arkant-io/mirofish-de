# Hinweise für Codex und andere Agenten

Betrieb, Deploy-Regel und erlaubte Handgriffe stehen in `RUNBOOK.md`. Vor jeder Aufgabe lesen; die Regeln gelten für alle Agenten, nicht nur für Claude Code.

- Backend-Abhängigkeiten: maßgeblich sind `backend/pyproject.toml` und `backend/uv.lock` (Docker, `setup-mac.sh` und `package.json` nutzen `uv sync`). `backend/requirements.txt` wird nur aus dem Lockfile exportiert, nie von Hand pflegen.
- Die Sicherheits-Overrides in `[tool.uv] override-dependencies` nicht entfernen: `camel-oasis` pinnt sonst Pakete mit kritischen Lücken (pillow, unstructured, sentence-transformers, pytest).
