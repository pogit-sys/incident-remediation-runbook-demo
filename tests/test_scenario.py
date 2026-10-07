"""Scenario tests: the scenario facts should produce what the memo calls for.

Run: python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runbook  # noqa: E402


class IncidentScenario(unittest.TestCase):
    def setUp(self):
        self.facts = runbook.gather_facts("NewAI")
        self.vendor = {v["name"]: v for v in runbook.load("subprocessors.yaml")}["NewAI"]
        self.customers = {c["name"]: c for c in runbook.load("customers.yaml")}
        self.flag_list = runbook.evaluate_flags(self.facts, self.vendor, self.customers)
        self.flags = {f["id"]: f["text"] for f in self.flag_list}

    def test_uk_eu_customers_found(self):
        affected = {n for n, f in self.facts["customers"].items() if f["eu_uk"]}
        self.assertEqual(affected, {"Thames Payroll Ltd", "Hartmann Steuerberatung"})

    def test_expected_flags(self):
        for flag in ["processor_notice", "data_chain", "special_category", "german_tax_adviser",
                     "no_transfer_mechanism", "no_dpa", "approval_required", "us_customer_notice",
                     "outside_counsel", "insurers"]:
            self.assertIn(flag, self.flags)

    def test_tax_adviser_flag_names_hartmann_only(self):
        self.assertIn("Hartmann Steuerberatung", self.flags["german_tax_adviser"])
        self.assertNotIn("Thames", self.flags["german_tax_adviser"])

    def test_us_notice_flag_names_brightline(self):
        self.assertIn("Brightline CPA", self.flags["us_customer_notice"])

    def test_ftc_flag_not_triggered_below_500_us_people(self):
        self.assertNotIn("us_ftc_500", self.flags)


class MatchesMemo(unittest.TestCase):
    def setUp(self):
        self.plan = runbook.load("plan.yaml")
        self.vendor = {v["name"]: v for v in runbook.load("subprocessors.yaml")}["NewAI"]
        self.customers = {c["name"]: c for c in runbook.load("customers.yaml")}

    def test_nine_steps_in_memo_order(self):
        self.assertEqual([s["key"] for s in self.plan],
                         ["channel", "confirm", "stop", "size", "transfer", "delete", "respond", "plan", "privilege"])

    def test_customer_clock_starts_at_step_7(self):
        self.assertEqual([s["id"] for s in self.plan if s.get("starts_customer_clock")], [7])

    def test_email_does_not_claim_a_contract_without_a_dpa(self):
        self.assertFalse(self.vendor["dpa_signed"])
        self.assertNotIn("works under a contract", runbook.contract_sentence("NewAI", self.vendor))

    def test_email_says_transfer_mechanism_is_open(self):
        text = runbook.transfer_sentence(self.vendor)
        self.assertIn("still confirming", text)
        self.assertNotIn("was covered by", text)

    def test_plan_requires_written_approval_where_contract_does(self):
        self.assertIn("written approval", runbook.reenable_text(self.customers["Thames Payroll Ltd"]))
        self.assertNotIn("written approval", runbook.reenable_text(self.customers["Hartmann Steuerberatung"]))


if __name__ == "__main__":
    unittest.main()
