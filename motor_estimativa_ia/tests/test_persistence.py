import copy
import unittest
from datetime import datetime, timedelta, timezone

from engine import calculate_project
from support import DATABASE, DatabaseTestCase

if DATABASE:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError


class ParameterSetTests(DatabaseTestCase):
    def new_parameters(self, version):
        parameters = copy.deepcopy(self.parameters)
        parameters["config_version"] = version
        return parameters

    def test_current_parameter_set_is_returned(self):
        response = self.client.get("/parameter-sets/current", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], self.parameters)

    def test_new_version_becomes_current_and_future_one_waits(self):
        admin = self.as_user(self.admin)
        response = self.client.post("/parameter-sets", json={"content": self.new_parameters("3.1")}, headers=admin)
        self.assertEqual(response.status_code, 201, response.text)
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        response = self.client.post("/parameter-sets", json={"content": self.new_parameters("4.0"), "effective_at": future},
                                    headers=admin)
        self.assertEqual(response.status_code, 201, response.text)
        current = self.client.get("/parameter-sets/current", headers=admin).json()
        self.assertEqual(current["version"], "3.1")
        versions = [p["version"] for p in self.client.get("/parameter-sets", headers=admin).json()]
        self.assertEqual(versions, ["4.0", "3.1", self.parameters["config_version"]])

    def test_only_admin_creates_parameter_sets(self):
        response = self.client.post("/parameter-sets", json={"content": self.new_parameters("3.1")},
                                    headers=self.as_user(self.tl))
        self.assertEqual(response.status_code, 403)

    def test_duplicate_version_and_invalid_content_are_rejected(self):
        admin = self.as_user(self.admin)
        response = self.client.post("/parameter-sets", json={"content": self.parameters}, headers=admin)
        self.assertEqual(response.status_code, 409)
        invalid = self.new_parameters("3.1")
        invalid["contingency_rate_default"] = 2
        self.assertEqual(self.client.post("/parameter-sets", json={"content": invalid}, headers=admin).status_code, 422)

    def test_no_current_parameter_set_blocks_estimates(self):
        with self.engine.begin() as conn:
            conn.execute(text("TRUNCATE parameter_sets CASCADE"))
        project = self.create_project()
        response = self.client.post(f"/projects/{project['id']}/estimates", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 409)


class ProjectTests(DatabaseTestCase):
    def test_create_and_get_project(self):
        project = self.create_project()
        self.assertEqual(project["revision"], 1)
        self.assertEqual(project["created_by"], str(self.tl.id))
        response = self.client.get(f"/projects/{project['id']}", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["content"]["features"]), len(self.project["features"]))

    def test_content_change_creates_new_revision_but_metadata_change_does_not(self):
        project = self.create_project()
        url, headers = f"/projects/{project['id']}", self.as_user(self.tl)
        self.assertEqual(self.client.patch(url, json={"name": "Renomeado"}, headers=headers).json()["revision"], 1)
        content = self.project_payload()["content"]
        self.assertEqual(self.client.patch(url, json={"content": content}, headers=headers).json()["revision"], 1)
        content["contingency_rate"] = 0.2
        self.assertEqual(self.client.patch(url, json={"content": content}, headers=headers).json()["revision"], 2)

    def test_invalid_content_and_unknown_project(self):
        payload = self.project_payload()
        payload["content"]["features"][0]["tasks"][0]["activities"][0]["optimistic_hours"] = -1
        self.assertEqual(self.client.post("/projects", json=payload, headers=self.as_user(self.po)).status_code, 422)
        response = self.client.get("/projects/00000000-0000-0000-0000-000000000000", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 404)

    def test_list_shows_latest_and_approved_estimates(self):
        with_estimates = self.create_project(name="Com estimativas")
        self.create_project(name="Sem estimativa")
        first = self.create_estimate(with_estimates["id"])
        self.client.post(f"/estimates/{first['id']}/approve", headers=self.as_user(self.tl))
        self.create_estimate(with_estimates["id"])
        items = {p["name"]: p for p in self.client.get("/projects", headers=self.as_user(self.po)).json()}
        self.assertIsNone(items["Sem estimativa"]["latest_estimate"])
        listed = items["Com estimativas"]
        self.assertEqual(listed["feature_count"], len(self.project["features"]))
        self.assertEqual(listed["latest_estimate"]["version"], 2)
        self.assertEqual(listed["latest_estimate"]["status"], "draft")
        self.assertEqual(listed["approved_estimate"]["version"], 1)


class TechnicalReviewTests(DatabaseTestCase):
    """PO cadastra funcionalidades e critérios de aceite; a parte técnica é do Tech Leader/admin."""

    def setUp(self):
        super().setUp()
        self.project_id = self.create_project()["id"]  # criado pelo Tech Leader, com tarefas
        self.url = f"/projects/{self.project_id}"

    def content(self):
        return self.client.get(self.url, headers=self.as_user(self.tl)).json()["content"]

    def patch_as(self, user, content):
        return self.client.patch(self.url, json={"content": content}, headers=self.as_user(user))

    def test_po_edits_functional_fields_and_costs(self):
        content = self.content()
        content["features"][0]["name"] = "Autenticação (revisada pelo PO)"
        content["features"][0]["acceptance_criteria"] = "Login com e-mail corporativo."
        content["features"].append({"id": "F99", "name": "Nova funcionalidade do PO", "tasks": []})
        content["cost_items"].append({"id": "C99", "cost_type": "licencas", "amount": 50})
        response = self.patch_as(self.po, content)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 2)

    def test_po_cannot_change_technical_scope(self):
        cases = {
            "horas da atividade": lambda c: c["features"][0]["tasks"][0]["activities"][0].update(most_likely_hours=99),
            "nova tarefa": lambda c: c["features"][0]["tasks"].append({"id": "T99", "name": "x", "activities": []}),
            "remover funcionalidade com tarefas": lambda c: c["features"].pop(0),
            "nova funcionalidade com tarefas": lambda c: c["features"].append(
                {"id": "F99", "name": "x", "tasks": [c["features"][0]["tasks"][0]]}),
            "transversal": lambda c: c["transversal_tasks"][0].update(name="outro nome"),
            "contingência": lambda c: c.update(contingency_rate=0.5),
        }
        for label, change in cases.items():
            with self.subTest(label):
                content = self.content()
                change(content)
                response = self.patch_as(self.po, content)
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get(self.url, headers=self.as_user(self.po)).json()["revision"], 1)

    def test_po_removes_feature_without_tasks(self):
        content = self.content()
        content["features"].append({"id": "F99", "name": "Rascunho", "tasks": []})
        self.patch_as(self.tl, content)
        content["features"].pop()
        self.assertEqual(self.patch_as(self.po, content).status_code, 200)

    def test_po_creates_project_only_without_technical_scope(self):
        payload = self.project_payload()
        self.assertEqual(self.client.post("/projects", json=payload, headers=self.as_user(self.po)).status_code, 403)
        features_only = {"name": "Só funcionalidades", "content": {
            "features": [{"id": "F01", "name": "Cadastro", "acceptance_criteria": "CRUD completo", "tasks": []}]}}
        self.assertEqual(self.client.post("/projects", json=features_only, headers=self.as_user(self.po)).status_code, 201)

    def test_tech_leader_and_admin_edit_technical_scope(self):
        for user in (self.tl, self.admin):
            with self.subTest(user.email):
                content = self.content()
                content["features"][0]["tasks"][0]["activities"][0]["most_likely_hours"] += 1
                self.assertEqual(self.patch_as(user, content).status_code, 200)


class EstimateTests(DatabaseTestCase):
    def test_estimate_records_snapshot_parameters_and_engine_result(self):
        project = self.create_project()
        estimate = self.create_estimate(project["id"])
        self.assertEqual(estimate["version"], 1)
        self.assertEqual(estimate["status"], "draft")
        self.assertEqual(estimate["project_revision"], 1)
        self.assertEqual(estimate["parameters_version"], self.parameters["config_version"])
        self.assertEqual(estimate["result"], calculate_project(estimate["project_snapshot"], self.parameters))
        self.assertEqual(estimate["project_snapshot"]["project_id"], project["id"])
        self.assertEqual(estimate["base_total_hours"], estimate["result"]["summary"]["base_total_hours"])

        fetched = self.client.get(f"/estimates/{estimate['id']}", headers=self.as_user(self.po)).json()
        self.assertEqual(fetched["result"], estimate["result"])

    def test_versions_increment_per_project(self):
        project = self.create_project()
        other = self.create_project(name="Outro")
        self.assertEqual(self.create_estimate(project["id"])["version"], 1)
        self.assertEqual(self.create_estimate(project["id"])["version"], 2)
        self.assertEqual(self.create_estimate(other["id"])["version"], 1)
        listed = self.client.get(f"/projects/{project['id']}/estimates", headers=self.as_user(self.po)).json()
        self.assertEqual([e["version"] for e in listed], [1, 2])

    def test_engine_rule_violation_is_not_recorded(self):
        payload = self.project_payload()
        payload["content"]["features"][0]["tasks"][0]["activities"][0]["allocations"] = {"qa": {"pleno": 0.5}}
        project = self.client.post("/projects", json=payload, headers=self.as_user(self.tl)).json()
        response = self.client.post(f"/projects/{project['id']}/estimates", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/projects/{project['id']}/estimates", headers=self.as_user(self.po)).json(), [])

    def test_archived_project_does_not_receive_estimates(self):
        project = self.create_project()
        self.client.patch(f"/projects/{project['id']}", json={"status": "archived"}, headers=self.as_user(self.po))
        response = self.client.post(f"/projects/{project['id']}/estimates", headers=self.as_user(self.po))
        self.assertEqual(response.status_code, 409)


class ApprovalTests(DatabaseTestCase):
    def approve(self, estimate_id, user):
        return self.client.post(f"/estimates/{estimate_id}/approve", headers=self.as_user(user))

    def test_product_owner_cannot_approve(self):
        estimate = self.create_estimate(self.create_project()["id"])
        self.assertEqual(self.approve(estimate["id"], self.po).status_code, 403)

    def test_tech_leader_approves_once(self):
        estimate = self.create_estimate(self.create_project()["id"])
        response = self.approve(estimate["id"], self.tl)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["approved_by"], str(self.tl.id))
        self.assertIsNotNone(body["approved_at"])
        self.assertEqual(self.approve(estimate["id"], self.tl).status_code, 409)

    def test_admin_can_approve(self):
        estimate = self.create_estimate(self.create_project()["id"])
        self.assertEqual(self.approve(estimate["id"], self.admin).status_code, 200)

    def test_estimate_from_outdated_requirements_cannot_be_approved(self):
        project = self.create_project()
        estimate = self.create_estimate(project["id"])
        content = self.project_payload()["content"]
        content["contingency_rate"] = 0.3
        self.client.patch(f"/projects/{project['id']}", json={"content": content}, headers=self.as_user(self.tl))
        response = self.approve(estimate["id"], self.tl)
        self.assertEqual(response.status_code, 409)
        self.assertIn("requisitos mudaram", response.json()["detail"])


class ImmutabilityTests(DatabaseTestCase):
    """RN-07 garantida no próprio banco, mesmo para acessos fora da API."""

    def assert_rejected_by_database(self, sql, **params):
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(text(sql), params)

    def test_approved_estimate_cannot_be_changed_or_deleted(self):
        estimate = self.create_estimate(self.create_project()["id"])
        self.client.post(f"/estimates/{estimate['id']}/approve", headers=self.as_user(self.tl))
        self.assert_rejected_by_database("UPDATE estimates SET status = 'draft' WHERE id = :id", id=estimate["id"])
        self.assert_rejected_by_database("DELETE FROM estimates WHERE id = :id", id=estimate["id"])

    def test_draft_calculation_cannot_be_changed(self):
        estimate = self.create_estimate(self.create_project()["id"])
        self.assert_rejected_by_database("UPDATE estimates SET base_total_hours = 1 WHERE id = :id", id=estimate["id"])
        self.assert_rejected_by_database("UPDATE estimates SET result = '{}'::jsonb WHERE id = :id", id=estimate["id"])

    def test_parameter_sets_cannot_be_changed(self):
        self.assert_rejected_by_database("UPDATE parameter_sets SET content = '{}'::jsonb")


class ReproductionTests(DatabaseTestCase):
    def test_old_estimate_remains_reproducible_after_parameters_change(self):
        project = self.create_project()
        old = self.create_estimate(project["id"])
        self.client.post(f"/estimates/{old['id']}/approve", headers=self.as_user(self.tl))

        parameters = copy.deepcopy(self.parameters)
        parameters["config_version"] = "3.1"
        parameters["roles"]["desenvolvimento"]["pleno"] = 200
        response = self.client.post("/parameter-sets", json={"content": parameters}, headers=self.as_user(self.admin))
        self.assertEqual(response.status_code, 201)
        new = self.create_estimate(project["id"])

        self.assertEqual(new["parameters_version"], "3.1")
        self.assertGreater(new["base_total_cost"], old["base_total_cost"])
        for estimate in (old, new):
            check = self.client.get(f"/estimates/{estimate['id']}/reproduction", headers=self.as_user(self.po)).json()
            self.assertTrue(check["reproducible"], estimate["version"])
        stored = self.client.get(f"/estimates/{old['id']}", headers=self.as_user(self.po)).json()
        self.assertEqual(stored["result"], old["result"])

if __name__ == "__main__":
    unittest.main()
