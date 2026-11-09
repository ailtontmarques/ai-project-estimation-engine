"""Base dos testes que usam o banco: migrações no banco de testes, limpeza, dados mínimos e SSO falso."""
import copy
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    import db  # carrega o .env
    import sso
    from api import app
    from fake_sso import FakeSSO
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False

TEST_URL = os.environ.get("DATABASE_URL_TEST")
_migrated = False


def database_available() -> bool:
    if not (DEPENDENCIES and TEST_URL):
        return False
    engine = create_engine(TEST_URL)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


DATABASE = database_available()
SKIP_REASON = "banco de testes indisponível (docker compose up -d; DATABASE_URL_TEST no .env)"


def migrate_once() -> None:
    """Recria o esquema pelas migrações (downgrade + upgrade), uma vez por execução."""
    global _migrated
    if _migrated:
        return
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["url"] = TEST_URL
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    _migrated = True


@unittest.skipUnless(DATABASE, SKIP_REASON)
class DatabaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migrate_once()
        cls.engine = create_engine(TEST_URL)
        cls.Session = sessionmaker(cls.engine, expire_on_commit=False)

        def override_session():
            with cls.Session() as session:
                yield session

        app.dependency_overrides[db.get_session] = override_session
        cls.client = TestClient(app)
        cls.parameters = json.loads((ROOT / "parameters.json").read_text(encoding="utf-8"))
        cls.project = json.loads((ROOT / "project_example.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        # TRUNCATE não dispara os triggers de linha, então limpa também estimativas aprovadas.
        with self.engine.begin() as conn:
            conn.execute(text("TRUNCATE estimates, projects, parameter_sets, users RESTART IDENTITY CASCADE"))
        with self.Session() as session:
            session.add(db.ParameterSet(version=self.parameters["config_version"], content=self.parameters))
            session.commit()
        # SSO novo a cada teste (cache vazio); os usuários só existem no banco local após o 1º acesso.
        self.sso = FakeSSO()
        self.sso_client = self.sso.client()
        app.dependency_overrides[sso.get_sso_client] = lambda: self.sso_client
        self.admin = self.sso.add_user("admin@teste", ["admin"], full_name="Admin")
        self.po = self.sso.add_user("po@teste", ["product_owner"], full_name="PO")
        self.tl = self.sso.add_user("tl@teste", ["tech_leader"], full_name="TL")

    def as_user(self, user) -> dict:
        return {"Authorization": f"Bearer {user.token}"}

    def project_payload(self, name="Projeto teste") -> dict:
        content = copy.deepcopy({k: v for k, v in self.project.items() if k not in ("project_id", "name")})
        return {"name": name, "objective": "Objetivo de teste", "content": content}

    def create_project(self, user=None, **kwargs) -> dict:
        # Projeto completo (com tarefas técnicas): por padrão, criado pelo Tech Leader.
        response = self.client.post("/projects", json=self.project_payload(**kwargs), headers=self.as_user(user or self.tl))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_estimate(self, project_id, user=None) -> dict:
        response = self.client.post(f"/projects/{project_id}/estimates", headers=self.as_user(user or self.po))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()
