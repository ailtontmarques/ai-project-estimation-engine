"""Horas realizadas (estimativas aprovadas) e relatório de calibração."""
import unittest

from support import DatabaseTestCase


class ActualHoursTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.estimate = self.create_estimate(self.create_project()["id"])
        self.rows = {r["activity_id"]: r for r in self.estimate["result"]["activities"]}
        self.url = f"/estimates/{self.estimate['id']}/actuals"

    def approve(self):
        response = self.client.post(f"/estimates/{self.estimate['id']}/approve", headers=self.as_user(self.tl))
        self.assertEqual(response.status_code, 200)

    def item(self, activity_id, hours, ai_used=None, notes=None):
        row = self.rows[activity_id]
        return {"task_id": row["task_id"], "activity_id": activity_id, "actual_hours": hours,
                "ai_used": row["ai_applied"] if ai_used is None else ai_used, "notes": notes}

    def put(self, items, user=None):
        return self.client.put(self.url, json={"items": items}, headers=self.as_user(user or self.tl))

    def test_only_approved_estimates_receive_actuals(self):
        self.assertEqual(self.put([self.item("A01", 10)]).status_code, 409)
        self.approve()
        self.assertEqual(self.put([self.item("A01", 10)]).status_code, 200)

    def test_product_owner_views_but_does_not_record(self):
        self.approve()
        self.assertEqual(self.put([self.item("A01", 10)], user=self.po).status_code, 403)
        self.put([self.item("A01", 10)])
        listed = self.client.get(self.url, headers=self.as_user(self.po)).json()
        self.assertEqual([(a["activity_id"], a["actual_hours"]) for a in listed], [("A01", 10)])

    def test_upsert_keeps_one_value_per_activity(self):
        self.approve()
        self.put([self.item("A01", 10, notes="primeira medição")])
        response = self.put([self.item("A01", 12.5, notes="corrigido"), self.item("A02", 4)])
        values = {a["activity_id"]: (a["actual_hours"], a["notes"]) for a in response.json()}
        self.assertEqual(values, {"A01": (12.5, "corrigido"), "A02": (4, None)})
        self.assertEqual(response.json()[0]["recorded_by"], str(self.tl.id))

    def test_unknown_activity_and_negative_hours_are_rejected(self):
        self.approve()
        unknown = {"task_id": "T99", "activity_id": "A99", "actual_hours": 1, "ai_used": False}
        self.assertEqual(self.put([unknown]).status_code, 422)
        self.assertEqual(self.put([self.item("A01", -1)]).status_code, 422)
        self.assertEqual(self.client.get(self.url, headers=self.as_user(self.tl)).json(), [])

    def test_calibration_compares_with_the_scenario_actually_executed(self):
        self.approve()
        a01, a03 = self.rows["A01"], self.rows["A03"]  # A01 com IA no exemplo; A03 (segurança) sem IA
        self.put([self.item("A01", 15, ai_used=True), self.item("A03", 6, ai_used=False)])
        report = self.client.get("/calibration", headers=self.as_user(self.po)).json()

        overall = report["overall"]
        expected = a01["ai_hours"] + a03["base_hours"]
        self.assertEqual(overall["count"], 2)
        self.assertAlmostEqual(overall["estimated_hours"], expected, delta=0.01)
        self.assertAlmostEqual(overall["ratio"], 21 / expected, delta=0.001)
        self.assertTrue(report["small_sample"])
        self.assertEqual(report["estimates_count"], 1)

        by_modality = {g["key"]: g for g in report["by_ai_modality"]}
        self.assertEqual(set(by_modality), {a01["ai_modality"], "sem_ia"})
        self.assertAlmostEqual(by_modality["sem_ia"]["estimated_hours"], a03["base_hours"], delta=0.01)
        by_type = {g["key"]: g for g in report["by_activity_type"]}
        self.assertEqual(by_type["implementacao"]["actual_hours"], 15)
        mape_a03 = abs(6 - a03["base_hours"]) / a03["base_hours"] * 100
        self.assertAlmostEqual(by_type["seguranca"]["mean_abs_pct_error"], mape_a03, delta=0.1)

    def test_activity_without_ai_in_estimate_counts_as_no_ai_even_if_marked(self):
        self.approve()
        self.put([self.item("A03", 6, ai_used=True)])  # A03 não tinha modalidade na estimativa
        report = self.client.get("/calibration", headers=self.as_user(self.tl)).json()
        self.assertEqual([g["key"] for g in report["by_ai_modality"]], ["sem_ia"])

    def test_empty_report(self):
        report = self.client.get("/calibration", headers=self.as_user(self.tl)).json()
        self.assertEqual(report["overall"]["count"], 0)
        self.assertIsNone(report["overall"]["ratio"])

if __name__ == "__main__":
    unittest.main()
