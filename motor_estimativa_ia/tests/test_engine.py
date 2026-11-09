import copy
import json
import unittest
from pathlib import Path
from engine import ENGINE_VERSION, calculate_project, iter_activities, pert_hours, validate_allocations

ROOT = Path(__file__).resolve().parents[1]

class EstimationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters = json.loads((ROOT / "parameters.json").read_text(encoding="utf-8"))
        cls.project = json.loads((ROOT / "project_example.json").read_text(encoding="utf-8"))

    def _first_activity(self, project):
        return project["features"][0]["tasks"][0]["activities"][0]

    def _activity_by_id(self, project, activity_id):
        return next(a for _, _, _, a in iter_activities(project) if a["id"] == activity_id)

    def _row(self, result, activity_id):
        return next(x for x in result["activities"] if x["activity_id"] == activity_id)

    def test_pert_standard_formula(self):
        activity = {"id": "x", "optimistic_hours": 2, "most_likely_hours": 4, "pessimistic_hours": 8}
        self.assertAlmostEqual(pert_hours(activity, self.parameters), 4.3333333333, places=6)

    def test_allocations_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            validate_allocations({"desenvolvimento": {"pleno": 0.8}}, "atividade teste")

    def test_project_has_activities_and_positive_hours(self):
        result = calculate_project(self.project, self.parameters)
        self.assertGreater(result["summary"]["activity_count"], 0)
        self.assertGreater(result["summary"]["base_hours"], 0)
        self.assertGreater(result["summary"]["base_total_cost"], 0)

    def test_ai_hours_follow_modality_factors(self):
        result = calculate_project(self.project, self.parameters)
        modalities = self.parameters["ai"]["modalities"]
        for row in result["activities"]:
            if not row["ai_applied"]:
                continue
            m = modalities[row["ai_modality"]]
            expected = row["base_hours"] * (1 - m["eligible_share"] * m["reduction_rate"]
                                            + m["review_hours_per_base_hour"] + m["rework_hours_per_base_hour"])
            self.assertAlmostEqual(row["ai_hours"], expected, places=6)

    def test_custom_ai_assumptions_are_respected(self):
        project = copy.deepcopy(self.project)
        activity = self._first_activity(project)
        activity["ai"] = {
            "eligible_share": 0,
            "reduction_rate": 0.5,
            "review_hours_per_base_hour": 0,
            "rework_hours_per_base_hour": 0
        }
        result = calculate_project(project, self.parameters)
        row = self._row(result, activity["id"])
        self.assertAlmostEqual(row["ai_hours"], row["base_hours"], places=6)

    def test_invalid_optimistic_most_likely_pessimistic_order(self):
        activity = {"id": "x", "optimistic_hours": 5, "most_likely_hours": 4, "pessimistic_hours": 8}
        with self.assertRaises(ValueError):
            pert_hours(activity, self.parameters)

    def test_hour_order_error_names_the_activity_not_its_id(self):
        project = copy.deepcopy(self.project)
        activity = self._first_activity(project)
        activity.update(optimistic_hours=10, most_likely_hours=3, pessimistic_hours=8)
        with self.assertRaises(ValueError) as ctx:
            calculate_project(project, self.parameters)
        self.assertIn(activity["name"], str(ctx.exception))
        self.assertNotIn(f' {activity["id"]}', str(ctx.exception))

    def test_empty_scope_is_rejected(self):
        project = copy.deepcopy(self.project)
        project["features"] = []
        project["transversal_tasks"] = []
        with self.assertRaisesRegex(ValueError, "não tem atividades"):
            calculate_project(project, self.parameters)

    def test_costs_are_nonnegative_and_summary_matches_activity_sum(self):
        result = calculate_project(self.project, self.parameters)
        activity_sum = round(sum(a["base_labor_cost"] for a in result["activities"]), 2)
        self.assertEqual(activity_sum, result["summary"]["base_labor_cost"])
        self.assertGreaterEqual(result["summary"]["ai_total_cost"], 0)

    def test_non_eligible_activity_gets_no_review_or_rework(self):
        project = copy.deepcopy(self.project)
        activity = self._first_activity(project)
        activity["ai"] = {"eligible_share": 0}  # revisão/retrabalho da modalidade são > 0
        result = calculate_project(project, self.parameters)
        row = self._row(result, activity["id"])
        self.assertFalse(row["ai_applied"])
        self.assertAlmostEqual(row["ai_hours"], row["base_hours"], places=6)

    def test_ai_can_increase_effort_and_cost(self):
        project = copy.deepcopy(self.project)
        for _, _, _, activity in iter_activities(project):
            if activity.get("ai_modality"):
                activity["ai"] = {"eligible_share": 0.5, "reduction_rate": 0, "review_hours_per_base_hour": 0.2}
        result = calculate_project(project, self.parameters)
        self.assertLess(result["summary"]["hours_saved_percent"], 0)
        self.assertLess(result["summary"]["cost_savings_percent"], 0)

    def test_contingency_is_reported_in_hours_and_kept_separate(self):
        summary = calculate_project(self.project, self.parameters)["summary"]
        rate = self.project["contingency_rate"]
        self.assertAlmostEqual(summary["base_contingency_hours"], summary["base_hours"] * rate, delta=0.02)
        self.assertAlmostEqual(summary["base_total_hours"], summary["base_hours"] + summary["base_contingency_hours"], delta=0.02)
        self.assertAlmostEqual(summary["ai_total_hours"], summary["ai_hours"] + summary["ai_contingency_hours"], delta=0.02)

    def test_uncertainty_range_is_sum_of_pessimistic_minus_optimistic(self):
        result = calculate_project(self.project, self.parameters)
        expected = sum(a["pessimistic_hours"] - a["optimistic_hours"] for _, _, _, a in iter_activities(self.project))
        self.assertAlmostEqual(result["summary"]["uncertainty_range_hours"], expected, places=2)

    # Custos adicionais

    def test_additional_costs_are_split_by_scenario(self):
        project = copy.deepcopy(self.project)
        project["cost_items"] = [
            {"id": "X1", "cost_type": "infraestrutura", "amount": 400},
            {"id": "X2", "cost_type": "ferramentas_ia", "amount": 150},
        ]
        s = calculate_project(project, self.parameters)["summary"]
        self.assertEqual(s["base_additional_cost"], 400)
        self.assertEqual(s["ai_additional_cost"], 550)
        self.assertAlmostEqual(s["base_total_cost"], s["base_labor_cost"] + s["base_contingency"] + 400, delta=0.02)
        self.assertAlmostEqual(s["ai_total_cost"], s["ai_labor_cost"] + s["ai_contingency"] + 550, delta=0.02)

    def test_cost_without_amount_is_uncounted_not_zero(self):
        result = calculate_project(self.project, self.parameters)
        item = next(i for i in result["additional_costs"]["items"] if i["amount"] is None)
        self.assertFalse(item["counted"])
        self.assertIn(item["cost_type"], result["assumptions"]["uncounted_costs"])

    def test_undeclared_cost_type_is_uncounted_and_declared_zero_is_counted(self):
        project = copy.deepcopy(self.project)
        project["cost_items"] = [{"id": "X1", "cost_type": "servicos_externos", "amount": 0}]
        uncounted = calculate_project(project, self.parameters)["assumptions"]["uncounted_costs"]
        self.assertNotIn("servicos_externos", uncounted)
        self.assertIn("infraestrutura", uncounted)

    def test_ai_only_cost_type_is_not_flagged_when_no_activity_uses_ai(self):
        project = copy.deepcopy(self.project)
        for _, _, _, activity in iter_activities(project):
            activity.pop("ai_modality", None)
        result = calculate_project(project, self.parameters)
        self.assertEqual(result["summary"]["ai_activity_count"], 0)
        self.assertNotIn("ferramentas_ia", result["assumptions"]["uncounted_costs"])

    def test_invalid_cost_items_are_rejected(self):
        for item in ({"id": "X", "cost_type": "inexistente", "amount": 1},
                     {"id": "X", "cost_type": "infraestrutura", "amount": -1},
                     {"id": "X", "cost_type": "infraestrutura", "amount": 1, "applies_to": "nenhum"}):
            project = copy.deepcopy(self.project)
            project["cost_items"] = [item]
            with self.assertRaises(ValueError, msg=item):
                calculate_project(project, self.parameters)

    # Origem e validação dos parâmetros

    def test_unvalidated_parameters_are_listed(self):
        a = calculate_project(self.project, self.parameters)["assumptions"]
        self.assertEqual(a["parameter_provenance"]["pert"]["validation_status"], "validado")
        self.assertNotIn("pert", a["unvalidated_parameters"])
        self.assertIn("roles", a["unvalidated_parameters"])
        self.assertTrue(any(k.startswith("ai.modalities.") for k in a["unvalidated_parameters"]))

    def test_contingency_provenance_follows_its_source(self):
        project = copy.deepcopy(self.project)
        a = calculate_project(project, self.parameters)["assumptions"]
        self.assertEqual(a["contingency_source"], "project")
        self.assertNotIn("contingency_rate_default", a["parameter_provenance"])
        del project["contingency_rate"]
        a = calculate_project(project, self.parameters)["assumptions"]
        self.assertEqual(a["contingency_source"], "parameters")
        self.assertIn("contingency_rate_default", a["unvalidated_parameters"])

    def test_missing_provenance_is_unspecified_and_invalid_status_rejected(self):
        parameters = copy.deepcopy(self.parameters)
        del parameters["provenance"]["roles"]
        a = calculate_project(self.project, parameters)["assumptions"]
        self.assertEqual(a["parameter_provenance"]["roles"]["validation_status"], "unspecified")
        self.assertIn("roles", a["unvalidated_parameters"])
        parameters["provenance"]["pert"]["validation_status"] = "talvez"
        with self.assertRaises(ValueError):
            calculate_project(self.project, parameters)

    def test_engine_version_and_cost_basis_are_recorded(self):
        assumptions = calculate_project(self.project, self.parameters)["assumptions"]
        self.assertEqual(assumptions["engine_version"], ENGINE_VERSION)
        self.assertEqual(assumptions["cost_basis"], "internal")

    def test_cost_savings_percent_matches_formula(self):
        s = calculate_project(self.project, self.parameters)["summary"]
        expected = (s["base_total_cost"] - s["ai_total_cost"]) / s["base_total_cost"] * 100
        self.assertAlmostEqual(s["cost_savings_percent"], expected, delta=0.01)

    def test_product_owner_with_zero_rate_adds_hours_but_no_cost(self):
        project = copy.deepcopy(self.project)
        self._first_activity(project)["allocations"] = {"desenvolvimento": {"pleno": 0.9}, "product_owner": {"pleno": 0.1}}
        result = calculate_project(project, self.parameters)
        po = result["hours_and_cost_by_role_seniority"]["product_owner/pleno"]
        self.assertGreater(po["base_hours"], 0)
        self.assertEqual(po["base_labor_cost"], 0)

    def test_negative_hourly_rate_is_rejected(self):
        parameters = copy.deepcopy(self.parameters)
        parameters["roles"]["desenvolvimento"]["pleno"] = -1
        with self.assertRaises(ValueError):
            calculate_project(self.project, parameters)

    def test_null_optional_fields_behave_as_absent(self):
        """JSON devolvido pela API traz opcionais como null; o resultado deve ser o mesmo de omiti-los."""
        project = copy.deepcopy(self.project)
        del project["contingency_rate"]
        expected = calculate_project(project, self.parameters)
        project["contingency_rate"] = None
        for _, _, _, activity in iter_activities(project):
            activity.setdefault("ai_modality", None)
            activity.setdefault("scope_key", None)
            activity["ai"] = None if activity["ai_modality"] is None else {"eligible_share": None, "reduction_rate": None}
        for item in project["cost_items"]:
            item["applies_to"] = None
        result = calculate_project(project, self.parameters)
        self.assertEqual(result["summary"], expected["summary"])
        self.assertEqual(result["assumptions"]["contingency_source"], "parameters")

    # Tipos de atividade e modalidades de IA

    def test_activity_without_modality_does_not_use_ai(self):
        result = calculate_project(self.project, self.parameters)
        row = self._row(result, "A03")  # revisão de segurança, sem modalidade no exemplo
        self.assertFalse(row["ai_applied"])
        self.assertEqual(row["ai_modality"], "sem_ia")
        self.assertAlmostEqual(row["ai_hours"], row["base_hours"], places=6)

    def test_ai_overrides_without_modality_are_rejected(self):
        project = copy.deepcopy(self.project)
        self._activity_by_id(project, "A03")["ai"] = {"eligible_share": 0.5}
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)

    def test_missing_or_unknown_activity_type_is_rejected(self):
        for value in (None, "inexistente"):
            project = copy.deepcopy(self.project)
            activity = self._first_activity(project)
            if value is None:
                del activity["activity_type"]
            else:
                activity["activity_type"] = value
            with self.assertRaises(ValueError):
                calculate_project(project, self.parameters)

    def test_modality_incompatible_with_activity_type_is_rejected(self):
        project = copy.deepcopy(self.project)
        self._activity_by_id(project, "A02")["ai_modality"] = "vibe_coding"  # A02 é do tipo testes
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)

    def test_unknown_modality_is_rejected(self):
        project = copy.deepcopy(self.project)
        self._first_activity(project)["ai_modality"] = "inexistente"
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)

    def test_modalities_used_are_reported_with_validation_status(self):
        result = calculate_project(self.project, self.parameters)
        used = result["assumptions"]["ai_modalities_used"]
        self.assertEqual(set(used), {r["ai_modality"] for r in result["activities"] if r["ai_applied"]})
        for cfg in used.values():
            self.assertEqual(cfg["validation_status"], "hipotese")

    def test_hours_by_activity_type_and_modality_add_up(self):
        result = calculate_project(self.project, self.parameters)
        for dimension in ("hours_by_activity_type", "hours_by_ai_modality", "hours_by_scope"):
            total = sum(b["base_hours"] for b in result[dimension].values())
            self.assertAlmostEqual(total, result["summary"]["base_hours"], delta=0.05, msg=dimension)

    # Atividades transversais

    def test_transversal_activities_are_consolidated_separately(self):
        result = calculate_project(self.project, self.parameters)
        transversal = [r for r in result["activities"] if r["scope"] == "transversal"]
        self.assertTrue(transversal)
        self.assertTrue(all(r["feature_id"] is None for r in transversal))
        self.assertAlmostEqual(result["hours_by_scope"]["transversal"]["base_hours"],
                               sum(r["base_hours"] for r in transversal), delta=0.01)

    def test_feature_activity_duplicating_transversal_scope_is_rejected(self):
        project = copy.deepcopy(self.project)
        self._first_activity(project)["scope_key"] = "ci_cd"
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)

    def test_transversal_activity_requires_unique_scope_key(self):
        project = copy.deepcopy(self.project)
        activities = project["transversal_tasks"][0]["activities"]
        activities[1]["scope_key"] = activities[0]["scope_key"]
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)
        del activities[1]["scope_key"]
        with self.assertRaises(ValueError):
            calculate_project(project, self.parameters)

if __name__ == "__main__":
    unittest.main()
