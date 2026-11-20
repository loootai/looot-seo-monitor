import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from seo_monitor import __main__ as cli
from seo_monitor import mcp_server
from seo_monitor.checks import run_checks
from seo_monitor.client import Looot, LoootError
from seo_monitor.extract import ai_answer, ai_status, brand_terms, extract_volume, find_rank, mentions, ranked_domains
from seo_monitor.history import load_history, save_history
from seo_monitor.html_report import render_html
from seo_monitor.monitor import clean_domain, dry_run, parse_keywords
from seo_monitor.report import render_markdown
from tests.mock_server import Mock, ai_overview_for, chatgpt_for, serp_for

ALL = ["rank", "ai_overview", "chatgpt", "volume"]


class Base(unittest.TestCase):
    def setUp(self):
        self.mock = Mock()
        self.addCleanup(self.mock.close)
        self.client = Looot(token="t", base_url=self.mock.url)


class ParseTests(unittest.TestCase):
    def test_clean_domain_and_keywords(self):
        self.assertEqual(clean_domain("https://www.Example.com/x?y"), "example.com")
        self.assertEqual(parse_keywords("# c\na\n\na\nb\n"), ["a", "b"])

    def test_find_rank_matches_subdomains_and_nested_results(self):
        self.assertEqual(find_rank(serp_for("ranked"), "example.com"), (2, "https://www.blog.example.com/post"))
        self.assertEqual(find_rank({"organic": []}, "example.com"), (None, ""))
        self.assertEqual(find_rank({"organic": [{"link": "https://notexample.com"}]}, "example.com"), (None, ""))

    def test_live_anyapi_serp_shape(self):
        self.assertEqual(find_rank(serp_for("anyapi"), "example.com")[0], 2)
        self.assertEqual(ranked_domains(serp_for("anyapi")), [(1, "rival.com"), (2, "example.com")])

    def test_ai_overview_shape_cited_and_mentioned(self):
        text, cites = ai_answer(ai_overview_for("ranked"))
        self.assertIn("good pick", text)
        self.assertEqual(cites[0], "https://docs.example.com/guide")
        self.assertEqual(ai_status(text, cites, "example.com", brand_terms("example.com")), "cited")
        self.assertEqual(ai_status(text, cites, "rival.com", brand_terms("rival.com")), "mentioned")
        self.assertEqual(ai_status("", [], "example.com", ["example"]), "no_answer")

    def test_chatgpt_shape_uses_reference_links_not_web_results(self):
        text, cites = ai_answer(chatgpt_for("ranked"))
        self.assertEqual(cites, ["https://other.com/ref"])
        self.assertEqual(ai_status(text, cites, "example.com", brand_terms("example.com")), "mentioned")

    def test_mentions_is_whole_word(self):
        self.assertTrue(mentions("We use Acme daily", ["acme"]))
        self.assertFalse(mentions("acmecorp is different", ["acme"]))

    def test_extract_volume(self):
        v = extract_volume(json.loads(json.dumps({"result": {"tasks": [{"result": [{"keyword": "A", "search_volume": 10, "cpc": 2.0}]}]}})))
        self.assertEqual(v["a"]["search_volume"], 10)


class DryRunTests(Base):
    def test_without_token_only_the_overview_is_called(self):
        lines = "\n".join(dry_run(Looot(token="", base_url=self.mock.url), "example.com", ["a", "b"], ALL, 0.5))
        self.assertEqual([c[1] for c in self.mock.calls], ["/v1/catalog/overview"])
        self.assertIn("job:google.serp.organic | 2 | $0.0009 | $0.0018", lines)
        self.assertIn("job:google.keywords.volume | 1 | $0.0900", lines)
        self.assertIn("Total | | | | $0.1034", lines)

    def test_zero_listed_price_is_not_treated_as_free(self):
        from seo_monitor.checks import format_quote, quote
        q = quote({"rank": 0, "chatgpt": None}, ["rank", "chatgpt"], 1)
        self.assertEqual([round(x["unit"], 4) for x in q["lines"]], [0.004, 0.004])
        self.assertIn("(assumed upper price)", "\n".join(format_quote(q, 1)))

    def test_with_token_reads_balance_but_never_runs(self):
        lines = dry_run(self.client, "example.com", ["a"], ["rank"], 0.5)
        self.assertEqual([c[1] for c in self.mock.calls], ["/v1/catalog/overview", "/v1/balance"])
        self.assertIn("Balance: $5.00", "\n".join(lines))


class CheckTests(Base):
    def test_all_surfaces_competitors_and_share_of_voice(self):
        snap = run_checks(self.client, "example.com", ["ranked", "hidden"], ALL, 1.0, competitors=["rival.com"], today="2026-11-20")
        by = {r["keyword"]: r for r in snap["keywords"]}
        self.assertEqual(by["ranked"]["rank"]["position"], 2)
        self.assertEqual(by["ranked"]["rank"]["competitors"], {"rival.com": 3})
        self.assertIsNone(by["hidden"]["rank"]["position"])
        self.assertEqual(by["ranked"]["ai_overview"]["status"], "cited")
        self.assertEqual(by["hidden"]["ai_overview"]["competitors"]["rival.com"], "cited")
        self.assertEqual(by["ranked"]["chatgpt"]["status"], "mentioned")
        self.assertEqual(by["ranked"]["volume"]["search_volume"], 1000)
        # position 2 on one of two keywords: 0.15 / (0.28 * 2)
        self.assertEqual(snap["sov"], {"example.com": 26.8, "rival.com": 30.4})
        self.assertEqual(snap["outrankers"][0]["domain"], "other.com")
        self.assertAlmostEqual(snap["spent"], 2 * (0.002 + 0.0018 + 0.004) + 0.09)
        runs = self.mock.runs()
        self.assertEqual([r["endpointId"] for r in runs[:3]], ["job:google.serp.organic", "job:google.serp.ai-overview", "job:search.chatgpt"])
        self.assertEqual(runs[1]["input"], {"prompt": "ranked"})
        self.assertEqual(runs[2]["input"], {"q": "ranked"})
        self.assertEqual(runs[-1]["input"]["keywords"], ["ranked", "hidden"])

    def test_every_run_carries_the_remaining_cap(self):
        run_checks(self.client, "example.com", ["ranked", "hidden"], ["rank"], 0.01, today="2026-11-20")
        caps = [r["fallback"]["maxCostUsd"] for r in self.mock.runs()]
        self.assertEqual(caps, [0.01, 0.008])

    def test_cap_is_never_exceeded_and_skips_are_free(self):
        snap = run_checks(self.client, "example.com", ["ranked", "hidden", "x"], ["rank", "chatgpt"], 0.007, today="2026-11-20")
        self.assertTrue(snap["capped"])
        self.assertLessEqual(snap["spent"], 0.007)
        self.assertAlmostEqual(snap["spent"], 0.006)
        # keyword 2: the rank call is sent with maxCostUsd 0.001 and refused for free; ChatGPT is not sent at all.
        self.assertEqual(snap["keywords"][1]["chatgpt"]["status"], "skipped")
        self.assertEqual(self.mock.runs()[2]["fallback"]["maxCostUsd"], 0.001)

    def test_idempotency_key_changes_by_day_not_within_a_day(self):
        run_checks(self.client, "example.com", ["ranked"], ["rank"], 1, today="2026-11-20")
        run_checks(self.client, "example.com", ["ranked"], ["rank"], 1, today="2026-11-20")
        run_checks(self.client, "example.com", ["ranked"], ["rank"], 1, today="2026-11-27")
        keys = [r["idempotencyKey"] for r in self.mock.runs()]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])
        self.assertTrue(keys[0].startswith("seomon-"))

    def test_failed_run_is_reported(self):
        mock = Mock(fail_jobs=("search.chatgpt",))
        self.addCleanup(mock.close)
        snap = run_checks(Looot(token="t", base_url=mock.url), "example.com", ["ranked"], ["chatgpt"], 1, today="2026-11-20")
        self.assertEqual(snap["keywords"][0]["chatgpt"]["status"], "failed")

    def test_missing_token_raises(self):
        with self.assertRaises(LoootError):
            Looot(token="", base_url=self.mock.url).balance()


class ReportTests(Base):
    def test_markdown_and_html_with_history(self):
        with tempfile.TemporaryDirectory() as d:
            hist = os.path.join(d, "h.json")
            # a v0.1 history file: {date: {keyword: position}}
            pathlib.Path(hist).write_text(json.dumps({"2026-11-13": {"ranked": 5, "hidden": 3}}))
            snap = run_checks(self.client, "example.com", ["ranked", "hidden"], ALL, 1.0, competitors=["rival.com"], today="2026-11-20")
            prev = load_history(hist)["2026-11-13"]
            md = render_markdown(snap, prev)
            self.assertIn("| ranked | 2 | +3 |", md)
            self.assertIn("| hidden | - | lost |", md)
            self.assertIn("Google AI Overview: named in 1 of 2 answers, cited as a source in 1", md)
            self.assertIn("| rival.com | 30.4% |", md)
            history = save_history(hist, snap)
            self.assertEqual(set(history), {"2026-11-13", "2026-11-20"})
            page = render_html(snap, history)
            self.assertTrue(page.startswith("<!doctype html>"))
            self.assertIn("<svg", page)
            self.assertIn("prefers-color-scheme:dark", page)
            self.assertNotIn("<script", page)

    def test_html_escapes_provider_text(self):
        snap = run_checks(self.client, "example.com", ["<b>x</b>"], ["rank"], 1.0, today="2026-11-20")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", render_html(snap, {}))


class CliTests(Base):
    def env(self, token="t"):
        os.environ["LOOOT_BASE_URL"] = self.mock.url
        if token:
            os.environ["LOOOT_TOKEN"] = token
        else:
            os.environ.pop("LOOOT_TOKEN", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("LOOOT_BASE_URL", "LOOOT_TOKEN")])

    def test_live_cli_writes_reports_and_history(self):
        self.env()
        with tempfile.TemporaryDirectory() as d:
            kw = os.path.join(d, "k.txt")
            pathlib.Path(kw).write_text("ranked\n")
            out, html, hist = (os.path.join(d, n) for n in ("r.md", "r.html", "h.json"))
            code = cli.main(["--domain", "example.com", "--keywords", kw, "--out", out, "--html", html, "--history", hist,
                             "--competitor", "rival.com", "--all", "--live"])
            self.assertEqual(code, 0)
            self.assertIn("# SEO report for example.com", pathlib.Path(out).read_text())
            self.assertIn("Share of voice", pathlib.Path(html).read_text())
            saved = json.loads(pathlib.Path(hist).read_text())
            entry = next(iter(saved.values()))
            self.assertEqual(entry["rank"], {"ranked": 2})
            self.assertEqual(entry["ai_overview"], {"ranked": "cited"})

    def test_cli_default_is_dry_run(self):
        self.env(token="")
        with tempfile.TemporaryDirectory() as d:
            kw = os.path.join(d, "k.txt")
            pathlib.Path(kw).write_text("ranked\n")
            self.assertEqual(cli.main(["--domain", "example.com", "--keywords", kw, "--all"]), 0)
        self.assertFalse(self.mock.runs())


class McpTests(Base):
    def rpc(self, method, params=None, mid=1):
        return mcp_server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}, self.client)

    def test_initialize_and_list(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["capabilities"])
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["seo_quote", "seo_check", "seo_history"])
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_quote_is_free(self):
        res = self.rpc("tools/call", {"name": "seo_quote", "arguments": {"domain": "example.com", "keywords": ["a"], "surfaces": ["rank", "chatgpt"]}})
        self.assertFalse(res["result"]["isError"])
        self.assertIn("job:search.chatgpt", res["result"]["content"][0]["text"])
        self.assertFalse(self.mock.runs())

    def test_check_requires_a_cap_then_runs(self):
        res = self.rpc("tools/call", {"name": "seo_check", "arguments": {"domain": "example.com", "keywords": ["ranked"]}})
        self.assertTrue(res["result"]["isError"])
        self.assertFalse(self.mock.runs())
        with tempfile.TemporaryDirectory() as d:
            args = {"domain": "example.com", "keywords": ["ranked"], "max_cost_usd": 0.05, "surfaces": ["rank", "ai_overview"],
                    "history_path": os.path.join(d, "h.json"), "html_path": os.path.join(d, "r.html")}
            res = self.rpc("tools/call", {"name": "seo_check", "arguments": args})
            self.assertFalse(res["result"]["isError"])
            self.assertIn("| ranked | 2 |", res["result"]["content"][0]["text"])
            self.assertTrue(os.path.exists(args["html_path"]))

    def test_stdio_transport(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        out = io.StringIO()
        mcp_server.serve(io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"), out)
        replies = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([r.get("id") for r in replies], [1, 2, None])
        self.assertEqual(replies[2]["error"]["code"], -32700)

    def test_module_starts_as_a_process(self):
        p = subprocess.run([sys.executable, "-m", "seo_monitor.mcp_server"], input='{"jsonrpc":"2.0","id":7,"method":"ping"}\n',
                           capture_output=True, text=True, timeout=20, cwd=pathlib.Path(__file__).resolve().parents[1])
        self.assertEqual(json.loads(p.stdout)["id"], 7)


if __name__ == "__main__":
    unittest.main()
