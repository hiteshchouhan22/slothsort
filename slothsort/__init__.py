"""SlothSort — the lazy file tidier.

Scans a messy folder, asks a *local* open-weight model (via Ollama) how each
file should be filed, and — only when you explicitly say so — moves the files
for you. Every move is logged and undoable.
"""

__version__ = "0.1.0"
