"""Decomposição assistida por IA: saneamento, chamada à OpenAI (cliente falso) e rota da API."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from support import DATABASE, DatabaseTestCase

try:
    import httpx2
    import openai
    import ai
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = json.loads((ROOT / "parameters.json").read_text(encoding="utf-8"))


def llm_activity(**overrides):
    base = {"name": "API de cadastro", "activity_type": "implementacao", "ai_modality": "geracao_codigo",
            "optimistic_hours": 6, "most_likely_hours": 10, "pessimistic_hours": 16,
            "allocations": [{"role": "desenvolvimento", "seniority": "pleno", "share": 1}],
            "rationale": "CRUD com validações."}
    base.update(overrides)
    return base


def decomposition(*activities):
    return ai.LLMDecomposition.model_validate({
        "tasks": [{"name": "Backend", "activities": list(activities)}],
        "open_questions": ["Haverá integração com o ERP?"], "risks": ["LGPD"], "assumptions": ["Postgres existente"]})


@unittest.skipUnless(DEPENDENCIES, "dependências da IA não instaladas")
class SanitizeTests(unittest.TestCase):
    def test_valid_activity_is_kept_without_warnings(self):
        tasks, warnings = ai.sanitize(decomposition(llm_activity()), PARAMETERS)
        self.assertEqual(warnings, [])
        activity = tasks[0]["activities"][0]
        self.assertEqual(activity["ai_modality"], "geracao_codigo")
        self.assertEqual(activity["allocations"], {"desenvolvimento": {"pleno": 1}})

    def test_unknown_activity_type_is_dropped(self):
        tasks, warnings = ai.sanitize(decomposition(llm_activity(activity_type="marketing")), PARAMETERS)
        self.assertEqual(tasks, [])
        self.assertIn("tipo de atividade desconhecido", warnings[0])

    def test_incompatible_modality_becomes_no_ai(self):
        tasks, warnings = ai.sanitize(decomposition(llm_activity(activity_type="testes", ai_modality="vibe_coding")), PARAMETERS)
        self.assertNotIn("ai_modality", tasks[0]["activities"][0])
        self.assertIn("não se aplica", warnings[0])

    def test_hours_are_ordered_and_allocations_normalized(self):
        activity = llm_activity(optimistic_hours=12, most_likely_hours=8, pessimistic_hours=-1, allocations=[
            {"role": "desenvolvimento", "seniority": "pleno", "share": 0.6},
            {"role": "desenvolvimento", "seniority": "senior", "share": 0.6},
            {"role": "inexistente", "seniority": "pleno", "share": 0.5},
        ])
        result = ai.sanitize(decomposition(activity), PARAMETERS)[0][0]["activities"][0]
        self.assertEqual((result["optimistic_hours"], result["most_likely_hours"], result["pessimistic_hours"]), (0, 8, 12))
        shares = result["allocations"]["desenvolvimento"]
        self.assertAlmostEqual(sum(shares.values()), 1, places=6)
        self.assertAlmostEqual(shares["senior"], 0.5, places=3)

    def test_empty_allocation_falls_back_with_warning(self):
        tasks, warnings = ai.sanitize(decomposition(llm_activity(allocations=[])), PARAMETERS)
        self.assertEqual(sum(sum(s.values()) for s in tasks[0]["activities"][0]["allocations"].values()), 1)
        self.assertIn("alocação inválida", warnings[0])


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(responses):
    return SimpleNamespace(responses=responses)


def parsed_response(parsed, status="completed", output=(), incomplete=None):
    return SimpleNamespace(output_parsed=parsed, status=status, output=list(output), model="gpt-5.5",
                           incomplete_details=SimpleNamespace(reason=incomplete) if incomplete else None)


def api_error(cls, status, code=None, message="erro"):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    body = {"message": message, "type": "invalid_request_error", "code": code, "param": None}
    return cls(message, response=httpx2.Response(status, request=request), body=body)


@unittest.skipUnless(DEPENDENCIES, "dependências da IA não instaladas")
class OpenAIDecomposerTests(unittest.TestCase):
    project = {"name": "Portal", "objective": "Atender clientes", "content": {"features": [
        {"id": "F01", "name": "Cadastro", "acceptance_criteria": "CRUD", "tasks": []},
        {"id": "F02", "name": "Relatórios", "tasks": []}], "transversal_tasks": []}}

    def suggest(self, responses, effort="medium"):
        decomposer = ai.OpenAIDecomposer(client=fake_client(responses), model="gpt-5.5", effort=effort)
        return decomposer.suggest(self.project, self.project["content"]["features"][0], PARAMETERS)

    def test_request_uses_structured_output_and_reasoning_effort(self):
        responses = FakeResponses(parsed_response(decomposition(llm_activity())))
        result = self.suggest(responses)
        call = responses.calls[0]
        self.assertEqual(call["model"], "gpt-5.5")
        self.assertIs(call["text_format"], ai.LLMDecomposition)
        self.assertEqual(call["reasoning"], {"effort": "medium"})
        self.assertFalse(call["store"])
        self.assertIn("Tech Leader", call["instructions"])
        prompt = call["input"]
        self.assertIn("Cadastro", prompt)
        self.assertIn("Relatórios", prompt)          # outras funcionalidades como contexto
        self.assertIn("geracao_codigo", prompt)      # catálogo de modalidades
        self.assertEqual(result["open_questions"], ["Haverá integração com o ERP?"])
        self.assertEqual(len(result["tasks"][0]["activities"]), 1)
        self.assertEqual(result["model"], "gpt-5.5")

    def test_empty_effort_omits_reasoning(self):
        responses = FakeResponses(parsed_response(decomposition(llm_activity())))
        self.suggest(responses, effort="")
        self.assertNotIn("reasoning", responses.calls[0])

    def test_refusal_and_truncation(self):
        refusal = SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="não posso")])
        with self.assertRaises(ai.AIRefused):
            self.suggest(FakeResponses(parsed_response(None, output=[refusal])))
        with self.assertRaises(ai.AIRefused):
            self.suggest(FakeResponses(parsed_response(None, status="incomplete", incomplete="content_filter")))
        with self.assertRaises(ai.AIUnavailable):
            self.suggest(FakeResponses(parsed_response(None, status="incomplete", incomplete="max_output_tokens")))

    def test_missing_credentials_is_reported_before_calling(self):
        import os
        names = ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY")
        saved = {k: os.environ.pop(k, None) for k in names}
        try:
            with self.assertRaises(ai.AIUnavailable) as ctx:
                ai.OpenAIDecomposer().suggest(self.project, self.project["content"]["features"][0], PARAMETERS)
            self.assertIn("OPENAI_API_KEY", ctx.exception.message)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_api_errors_become_unavailable(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        cases = {
            "auth": (api_error(openai.AuthenticationError, 401), "OPENAI_API_KEY"),
            "rate": (api_error(openai.RateLimitError, 429, code="rate_limit_exceeded"), "Limite de uso"),
            "quota": (api_error(openai.RateLimitError, 429, code="insufficient_quota"), "sem créditos"),
            "model": (api_error(openai.NotFoundError, 404, code="model_not_found", message="no gpt-x"), "no gpt-x"),
            "other": (api_error(openai.BadRequestError, 400, message="bad schema"), "erro 400: bad schema"),
            "server": (api_error(openai.InternalServerError, 500), "erro 500"),
            "conn": (openai.APIConnectionError(request=request), "conectar"),
        }
        for name, (error, expected) in cases.items():
            with self.subTest(name), self.assertRaises(ai.AIUnavailable) as ctx:
                self.suggest(FakeResponses(error=error))
            self.assertIn(expected, ctx.exception.message)


class FakeDecomposer:
    def __init__(self):
        self.calls = []

    def suggest(self, project, feature, parameters):
        self.calls.append((project, feature))
        return {"tasks": [{"name": "Backend", "activities": [dict(llm_activity(), allocations={"desenvolvimento": {"pleno": 1}})]}],
                "open_questions": [], "risks": [], "assumptions": [], "warnings": [], "model": "fake"}


@unittest.skipUnless(DATABASE, "banco de testes indisponível")
class DecompositionRouteTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        from api import app
        self.fake = FakeDecomposer()
        app.dependency_overrides[ai.get_decomposer] = lambda: self.fake
        self.project = self.create_project()

    def url(self, feature_id):
        return f"/projects/{self.project['id']}/features/{feature_id}/decomposition"

    def test_returns_suggestion_for_saved_feature_and_po_can_request(self):
        feature_id = self.project["content"]["features"][0]["id"]
        response = self.client.post(self.url(feature_id), headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tasks"][0]["activities"][0]["rationale"], "CRUD com validações.")
        project, feature = self.fake.calls[0]
        self.assertEqual(feature["id"], feature_id)
        self.assertEqual(project["name"], self.project["name"])
        # Sugestão não altera o projeto.
        self.assertEqual(self.client.get(f"/projects/{self.project['id']}", headers=self.as_user(self.po)).json()["revision"], 1)

    def test_unknown_feature_is_404(self):
        self.assertEqual(self.client.post(self.url("F404"), headers=self.as_user(self.tl)).status_code, 404)

    def test_requires_authentication(self):
        self.assertEqual(self.client.post(self.url("F01")).status_code, 401)

if __name__ == "__main__":
    unittest.main()
