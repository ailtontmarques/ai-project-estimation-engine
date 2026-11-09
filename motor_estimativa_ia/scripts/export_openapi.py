"""Exporta o OpenAPI da API sem subir o servidor (fonte dos tipos TypeScript do front-end).

Uso:
  python scripts/export_openapi.py [saida.json]     # sem argumento, imprime no stdout
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import app  # noqa: E402


def main() -> None:
    rendered = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
