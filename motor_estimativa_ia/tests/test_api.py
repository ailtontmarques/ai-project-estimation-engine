import copy
import json
import unittest

from engine import ENGINE_VERSION, calculate_project
from support import DEPENDENCIES, ROOT, DatabaseTestCase

if DEPENDENCIES:
    from fastapi.testclient import TestClient
    from pydantic import ValidationError
    from api import app
    from models import EstimateResult, Parameters, Project


@unittest.skipUnless(DEPENDENCIES, "dependências da API não instaladas (pip install -r requirements.txt)")
class ContractTests(unittest.TestCase):
    """Contrato de dados e rotas que não dependem do banco."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.parameters = json.loads((ROOT / "parameters.json").read_text(encoding="utf-8"))
        cls.project = json.loads((ROOT / "project_example.json").read_text(encoding="utf-8"))

    def test_example_files_match_the_data_contract(self):
        Project.model_validate(self.project)
        Parameters.model_validate(self.parameters)

    def test_health_reports_engine_version(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine_version"], ENGINE_VERSION)

    def _result_variants(self):
        """Resultados do motor cobrindo valores opcionais: sem IA, custo nulo, sem transversais, origem não informada."""
        yield "exemplo", self.project, self.parameters
        no_ai = copy.deepcopy(self.project)
        for feature in no_ai["features"]:
            for task in feature["tasks"]:
                for activity in task["activities"]:
                    activity.pop("ai_modality", None)
        for task in no_ai["transversal_tasks"]:
            for activity in task["activities"]:
                activity.pop("ai_modality", None)
        yield "sem_ia", no_ai, self.parameters
        minimal = copy.deepcopy(self.project)
        minimal.pop("transversal_tasks")
        minimal.pop("contingency_rate")
        minimal["cost_items"] = [{"id": "X1", "cost_type": "licencas", "amount": None}]
        parameters = copy.deepcopy(self.parameters)
        parameters["provenance"] = {}
        yield "minimo", minimal, parameters

    def test_engine_output_matches_result_contract(self):
        for label, project, parameters in self._result_variants():
            with self.subTest(label):
                result = calculate_project(project, parameters)
                validated = EstimateResult.model_validate(result)
                self.assertEqual(validated.model_dump(), result)

    def test_contract_detects_engine_drift(self):
        result = calculate_project(self.project, self.parameters)
        result["summary"]["campo_novo"] = 1
        with self.assertRaises(ValidationError):
            EstimateResult.model_validate(result)
        result = calculate_project(self.project, self.parameters)
        del result["summary"]["cost_savings_percent"]
        with self.assertRaises(ValidationError):
            EstimateResult.model_validate(result)

    def test_openapi_documents_estimate_response(self):
        schema = self.client.get("/openapi.json").json()
        response = schema["paths"]["/estimate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(response["$ref"], "#/components/schemas/EstimateResult")
        self.assertIn("Summary", schema["components"]["schemas"])


class SimulationTests(DatabaseTestCase):
    """POST /estimate: cálculo sem registro, com os parâmetros vigentes no banco ou informados."""

    def test_estimate_matches_engine_result(self):
        response = self.client.post("/estimate", json={"project": self.project}, headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), calculate_project(self.project, self.parameters))

    def test_estimate_requires_identified_user(self):
        response = self.client.post("/estimate", json={"project": self.project})
        self.assertEqual(response.status_code, 401)

    def test_estimate_with_custom_parameters(self):
        parameters = copy.deepcopy(self.parameters)
        parameters["config_version"] = "simulacao"
        parameters["roles"]["desenvolvimento"]["pleno"] = 0
        response = self.client.post("/estimate", json={"project": self.project, "parameters": parameters},
                                    headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["assumptions"]["parameters_version"], "simulacao")
        self.assertEqual(body["hours_and_cost_by_role_seniority"]["desenvolvimento/pleno"]["base_labor_cost"], 0)

    def test_omitted_contingency_falls_back_to_parameters(self):
        project = copy.deepcopy(self.project)
        del project["contingency_rate"]
        body = self.client.post("/estimate", json={"project": project}, headers=self.as_user(self.po)).json()
        self.assertEqual(body["assumptions"]["contingency_source"], "parameters")

    def test_business_rule_violation_returns_422_with_engine_message(self):
        project = copy.deepcopy(self.project)
        project["features"][0]["tasks"][0]["activities"][0]["allocations"] = {"desenvolvimento": {"pleno": 0.8}}
        response = self.client.post("/estimate", json={"project": project}, headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 422)
        self.assertIn("Alocações devem somar 100%", response.json()["detail"])

    def test_contract_violations_return_422(self):
        activity_path = ("features", 0, "tasks", 0, "activities", 0)
        for field, value in (("optimistic_hours", -1), ("ai_modalidade", "geracao_codigo")):
            project = copy.deepcopy(self.project)
            activity = project
            for key in activity_path:
                activity = activity[key]
            activity[field] = value
            response = self.client.post("/estimate", json={"project": project}, headers=self.as_user(self.po))
            self.assertEqual(response.status_code, 422, msg=field)

if __name__ == "__main__":
    unittest.main()
