import os
import pathlib
import tempfile
import unittest

from seo_monitor import __main__ as cli
from seo_monitor.client import Looot, LoootError
from seo_monitor.monitor import (
    check_rankings, clean_domain, dry_run, find_rank, parse_keywords, render_report,
)
from tests.mock_server import Mock


class Base(unittest.TestCase):
    def setUp(self):
        self.mock = Mock()
        self.addCleanup(self.mock.close)


class ParseTests(unittest.TestCase):
    def test_clean_domain_and_keywords(self):
        self.assertEqual(clean_domain("https://www.Example.com/x?y"), "example.com")
        self.assertEqual(parse_keywords("# c\na\n\na\nb\n"), ["a", "b"])

    def test_find_rank_matches_subdomains_and_nested_results(self):
        pos, url = find_rank(serp_ranked(), "example.com")
        self.assertEqual(pos, 2)
        self.assertEqual(url, "https://www.blog.example.com/post")
        self.assertEqual(find_rank({"organic": []}, "example.com"), (None, ""))
        # notexample.com must not match example.com
        self.assertEqual(find_rank({"organic": [{"link": "https://notexample.com"}]}, "example.com"), (None, ""))


def serp_ranked():
    from tests.mock_server import serp_for
    return serp_for("ranked")


class DryRunTests(Base):
    def test_without_token_only_the_overview_is_called(self):
        lines = dry_run(Looot(token="", base_url=self.mock.url), "example.com", ["a", "b"])
        self.assertEqual([c[1] for c in self.mock.calls], ["/v1/catalog/overview"])
        self.assertIn("$0.0009", "\n".join(lines))

    def test_with_token_adds_balance_and_search_but_never_a_run(self):
        lines = dry_run(Looot(token="t", base_url=self.mock.url), "example.com", ["a"])
        self.assertEqual([c[1] for c in self.mock.calls], ["/v1/catalog/overview", "/v1/balance", "/v1/catalog/search"])
        self.assertIn("Balance: $5.00", "\n".join(lines))


class LiveTests(Base):
    def test_check_rankings_and_report(self):
        client = Looot(token="t", base_url=self.mock.url)
        snap = check_rankings(client, "example.com", ["ranked", "hidden"], "us", 1.0)
        by = {r["keyword"]: r for r in snap["rows"]}
        self.assertEqual(by["ranked"]["position"], 2)
        self.assertIsNone(by["hidden"]["position"])
        runs = [c for c in self.mock.calls if c[1] == "/v1/runs"]
        self.assertEqual(runs[0][3]["input"], {"query": "ranked", "country": "us"})
        self.assertTrue(runs[0][3]["idempotencyKey"].startswith("seomon-"))
        report = render_report(snap, {"ranked": 5, "hidden": 3})
        self.assertIn("| ranked | 2 | +3 |", report)
        self.assertIn("| hidden | - | lost |", report)

    def test_cost_cap_skips_the_rest(self):
        client = Looot(token="t", base_url=self.mock.url)
        snap = check_rankings(client, "example.com", ["ranked", "hidden", "ranked2"], None, 0.002)
        self.assertTrue(snap["capped"])
        self.assertEqual(len([c for c in self.mock.calls if c[1] == "/v1/runs"]), 1)

    def test_missing_token_raises(self):
        with self.assertRaises(LoootError):
            Looot(token="", base_url=self.mock.url).balance()


class CliTests(Base):
    def test_live_cli_writes_report_and_history(self):
        os.environ["LOOOT_BASE_URL"] = self.mock.url
        os.environ["LOOOT_TOKEN"] = "t"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOOT_BASE_URL", "LOOOT_TOKEN")])
        with tempfile.TemporaryDirectory() as d:
            kw = os.path.join(d, "k.txt")
            pathlib.Path(kw).write_text("ranked\n")
            out, hist = os.path.join(d, "r.md"), os.path.join(d, "h.json")
            self.assertEqual(cli.main(["--domain", "example.com", "--keywords", kw, "--out", out, "--history", hist, "--live"]), 0)
            self.assertIn("# Google rankings for example.com", pathlib.Path(out).read_text())
            self.assertIn('"ranked": 2', pathlib.Path(hist).read_text())

    def test_cli_default_is_dry_run(self):
        os.environ["LOOOT_BASE_URL"] = self.mock.url
        os.environ.pop("LOOOT_TOKEN", None)
        self.addCleanup(lambda: os.environ.pop("LOOOT_BASE_URL", None))
        with tempfile.TemporaryDirectory() as d:
            kw = os.path.join(d, "k.txt")
            pathlib.Path(kw).write_text("ranked\n")
            self.assertEqual(cli.main(["--domain", "example.com", "--keywords", kw]), 0)
        self.assertFalse([c for c in self.mock.calls if c[1] == "/v1/runs"])


if __name__ == "__main__":
    unittest.main()
