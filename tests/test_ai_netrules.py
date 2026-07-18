"""Tests für Netzwerkregeln: Wildcard-Matching, Host-Extraktion, Verstöße."""
import unittest

from ai_systems.netrules import (
    extract_host_findings,
    host_matches,
    normalize_host,
    validate_against_rules,
)


def wf_with_params(params, node_type="n8n-nodes-base.httpRequest"):
    return {
        "name": "T",
        "nodes": [{"id": "n", "name": "Knoten", "type": node_type,
                   "typeVersion": 1, "position": [0, 0], "parameters": params}],
        "connections": {},
    }


class HostMatchTest(unittest.TestCase):
    def test_exact_match_case_and_port_insensitive(self):
        self.assertTrue(host_matches("ERP.Example.com", "erp.example.com"))
        self.assertTrue(host_matches("erp.example.com:8443", "erp.example.com"))
        self.assertFalse(host_matches("erp.example.com", "example.com"))

    def test_wildcard_matches_subdomains_not_apex(self):
        self.assertTrue(host_matches("a.example.com", "*.example.com"))
        self.assertTrue(host_matches("a.b.example.com", "*.example.com"))
        self.assertFalse(host_matches("example.com", "*.example.com"))
        self.assertFalse(host_matches("evilexample.com", "*.example.com"))

    def test_userinfo_trick_is_normalized(self):
        # https://gut.de@boese.de/ -> tatsächlicher Host ist boese.de
        self.assertEqual(normalize_host("gut.de@boese.de"), "boese.de")
        self.assertFalse(host_matches("gut.de@boese.de", "gut.de"))


class ExtractTest(unittest.TestCase):
    def test_finds_urls_in_nested_params(self):
        wf = wf_with_params({"options": {"redirect": {"url": "https://Api.Example.com/v1"}},
                             "liste": [{"value": "http://zwei.example.org/x"}]})
        hosts = sorted(f["host"] for f in extract_host_findings(wf))
        self.assertEqual(hosts, ["api.example.com", "zwei.example.org"])

    def test_finds_url_inside_expression_with_static_host(self):
        wf = wf_with_params(
            {"url": "=https://login.microsoftonline.com/{{$env.AZURE_TENANT_ID}}/oauth2/token"})
        findings = extract_host_findings(wf)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["verifiable"])
        self.assertEqual(findings[0]["host"], "login.microsoftonline.com")

    def test_dynamic_host_is_unverifiable(self):
        for value in ("={{ $json.url }}", "=https://{{$json.domain}}/pfad"):
            wf = wf_with_params({"url": value})
            findings = extract_host_findings(wf)
            self.assertEqual(len(findings), 1, value)
            self.assertFalse(findings[0]["verifiable"], value)

    def test_schemeless_url_key(self):
        wf = wf_with_params({"host": "smtp.example.com"})
        findings = extract_host_findings(wf)
        self.assertEqual(findings[0]["host"], "smtp.example.com")
        self.assertTrue(findings[0]["verifiable"])


class ValidateRulesTest(unittest.TestCase):
    def test_allowed_hosts_pass(self):
        wf = wf_with_params({"url": "https://erp.example.com/api/resource/Kunde"})
        self.assertEqual(validate_against_rules(wf, ["erp.example.com"]), [])

    def test_disallowed_host_reported(self):
        wf = wf_with_params({"url": "https://boese.example.net/x"})
        violations = validate_against_rules(wf, ["erp.example.com", "*.example.com"])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["host"], "boese.example.net")
        self.assertEqual(violations[0]["node"], "Knoten")
        self.assertIn("Allowlist", violations[0]["reason"])

    def test_unverifiable_host_is_violation(self):
        wf = wf_with_params({"url": "={{ $json.url }}"})
        violations = validate_against_rules(wf, ["*.example.com"])
        self.assertEqual(len(violations), 1)
        self.assertIsNone(violations[0]["host"])
        self.assertIn("nicht statisch prüfbar", violations[0]["reason"])

    def test_union_of_patterns(self):
        wf = wf_with_params({"url": "https://sub.example.com/a",
                             "backup": "https://api.anthropic.com/v1/messages"})
        violations = validate_against_rules(wf, ["*.example.com", "api.anthropic.com"])
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
