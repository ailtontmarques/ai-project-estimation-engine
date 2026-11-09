"""Carga inicial do banco (idempotente): importa parameters.json como conjunto de parâmetros.

Usuários e roles não são criados aqui: são administrados no UNE AI SSO (veja scripts/sso_bootstrap.py).
A carga inicial fica sem created_by; as versões seguintes são criadas por um admin via API.

Uso:
  python seed.py [--parameters parameters.json]
"""
from __future__ import annotations
import argparse
from pathlib import Path

from sqlalchemy import select

from db import ParameterSet, get_sessionmaker
from engine import load_json
from models import Parameters

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga inicial do banco")
    parser.add_argument("--parameters", default=str(ROOT / "parameters.json"))
    args = parser.parse_args()

    parameters = Parameters.model_validate(load_json(args.parameters))
    with get_sessionmaker()() as session:
        existing = session.scalars(select(ParameterSet).where(ParameterSet.version == parameters.config_version)).first()
        if existing is None:
            existing = ParameterSet(version=parameters.config_version,
                                    content=parameters.model_dump(mode="json", exclude_none=True))
            session.add(existing)
            session.commit()
        print(f"parâmetros  {existing.id}  versão {existing.version}")


if __name__ == "__main__":
    main()
