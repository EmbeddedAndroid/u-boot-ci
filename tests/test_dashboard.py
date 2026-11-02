"""The dashboard page in Chromium, from fixture run documents: the boot
time in every matrix cell, the Boot time section (bars, history with links
to the LAVA log lines, table, boot kind filter) and the boot-time part of
the detail view, in light and dark, with no page error.

Runs in the browser image (docker/Dockerfile.dashboard):
  docker build -t u-boot-ci-dashboard:1 -f docker/Dockerfile.dashboard docker
  UBCI_IMAGE=u-boot-ci-dashboard:1 scripts/in-container.sh python3 -m pytest -q tests/test_dashboard.py
and is skipped where Playwright is not installed."""
import functools
import http.server
import json
import os
import shutil
import threading

import pytest

from fwci import site

import boottime_samples

# In CI (tests.yml sets UBCI_REQUIRE_BROWSER) a missing Playwright fails
# instead of skipping, so a broken browser image cannot pass.
if os.environ.get("UBCI_REQUIRE_BROWSER"):
    import playwright.sync_api as sync_api
else:
    sync_api = pytest.importorskip("playwright.sync_api")

DASHBOARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    d = tmp_path_factory.mktemp("www") / "site"
    shutil.copytree(DASHBOARD, d)
    (d / "runs").mkdir()
    runs = boottime_samples.runs()
    # A branch whose nightly has no boot times at all.
    import samples
    m = samples.run("m1", created="2026-11-01T02:00:00Z")
    m["run"]["base"]["branch"] = "master"
    # A stock health check without an end time is listed, never drawn.
    nodate = json.loads(json.dumps(runs[0]["boot_time_reference"]["boards"]["qcs615-ride"]["boots"][0]))
    nodate.update(job=52, job_url="https://lava.example/scheduler/job/52", end_time=None)
    runs[0]["boot_time_reference"]["boards"]["qcs615-ride"]["boots"].append(nodate)
    for r in runs + [m]:
        (d / "runs" / (r["run"]["id"] + ".json")).write_text(json.dumps(r))
    site.write(str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(d)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % srv.server_address[1]
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, url, scheme="light", width=1280):
    pg = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(url)
    pg.wait_for_selector(".bt-board")
    return pg, errors


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_boot_time_section_renders(browser, url, scheme):
    pg, errors = open_page(browser, url, scheme)
    # Cold boots have too little history in the fixtures: warm resets lead.
    assert pg.locator("#bt-filters button[aria-pressed=true]").inner_text().startswith("warm reset")
    boards = pg.locator(".bt-board h3").all_inner_texts()
    assert any(b.startswith("rb3gen2") for b in boards) and any(b.startswith("qcs615-ride") for b in boards)
    rb3 = pg.locator(".bt-board", has_text="rb3gen2")
    assert rb3.locator("svg.bt-bars path.seg").count() >= 3
    assert "4.75 s" in rb3.locator("svg.bt-bars").inner_html()
    dots = rb3.locator("svg.bt-history a")
    assert dots.count() == 2
    hrefs = [dots.nth(i).get_attribute("href") for i in range(2)]
    assert hrefs[0].startswith("https://lava.example/scheduler/job/1#L") and "/job/3#L" in hrefs[1]
    # A board that never reached Linux: its bar stops at the last stage.
    qcs = pg.locator(".bt-board", has_text="qcs615-ride")
    assert "stopped at U-Boot" in qcs.locator("svg.bt-bars").inner_html()
    assert "No boot of this kind reached Booting Linux" in qcs.inner_text()
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []


def test_kind_filter_and_stock_series(browser, url):
    pg, errors = open_page(browser, url)
    pg.locator("#bt-filters button", has_text="cold boot").click()
    assert pg.locator("#bt-filters button[aria-pressed=true]").inner_text().startswith("cold boot")
    qcs = pg.locator(".bt-board", has_text="qcs615-ride")
    assert "stock" in qcs.locator(".bt-legend").first.inner_text()
    assert "4.66 s" in qcs.locator("svg.bt-bars").inner_html()
    # RB3 Gen 2 health checks boot over fastboot: listed, never drawn.
    rb3 = pg.locator(".bt-board", has_text="rb3gen2")
    assert "no fair reference" in rb3.locator("svg.bt-bars").inner_html()
    assert rb3.locator("svg.bt-history a").count() == 1
    rb3.locator("details summary").click()
    assert "health check 51 (kernel over fastboot)" in rb3.locator("details").inner_text()
    # Warm boots have no stock series.
    pg.locator("#bt-filters button", has_text="warm reboot").click()
    assert "no stock series" in pg.locator("#bt-filters").inner_text()
    assert errors == []


def test_history_hover_lists_every_stage(browser, url):
    pg, errors = open_page(browser, url)
    rb3 = pg.locator(".bt-board", has_text="rb3gen2")
    rb3.locator("rect.hit").scroll_into_view_if_needed()
    box = rb3.locator("rect.hit").bounding_box()
    pg.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2)
    tip = pg.locator(".bt-tip")
    assert tip.is_visible()
    text = tip.inner_text()
    for words in ("to Booting Linux", "TF-A BL31", "OP-TEE", "U-Boot", "n2"):
        assert words in text, words
    pg.locator(".bt-board", has_text="qcs615-ride").locator("path.seg").first.hover()
    assert "XBL" in tip.inner_text()
    assert errors == []


def test_matrix_cell_and_detail(browser, url):
    pg, errors = open_page(browser, url)
    cell = pg.locator("#matrix td.cell", has_text="boot → Linux").first
    text = cell.inner_text()
    assert "boot → Linux" in text and "cold" in text and "slower +0.50 s" in text
    cell.click()
    pg.wait_for_selector("#detail h3:has-text('Boot time')")
    detail = pg.locator("#detail").inner_text()
    for words in ("cold boot", "headline", "warm reset", "On target, from the kernel's own clock",
                  "pre-kernel", "3.982 s", "no timestamped line"):
        assert words in detail, words
    link = pg.locator("#detail table.cases a", has_text="cold boot").first.get_attribute("href")
    assert link.startswith("https://lava.example/scheduler/job/3#L")
    assert errors == []


def test_names_are_text_never_html(browser, url):
    pg, errors = open_page(browser, url)
    pg.locator("#bt-filters button", has_text="warm reset").click()
    assert boottime_samples.HOSTILE in pg.locator("#boottime").inner_text()
    assert pg.evaluate("window.__pwned") is None
    assert errors == []


def test_phone_width(browser, url):
    pg, errors = open_page(browser, url, width=390)
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []


def test_branch_without_boot_times_clears_the_section(browser, url):
    pg, errors = open_page(browser, url)
    pg.locator("#branches button", has_text="master").click()
    # The stock series is not per branch; nothing of main's runs stays.
    assert pg.locator(".bt-board").count() == 0
    assert pg.locator("#boottime").inner_text().startswith("No warm reset measured yet")
    pg.locator("#bt-filters button", has_text="cold boot").click()
    assert "downstream" not in pg.locator("#boottime").inner_text()
    assert pg.locator(".bt-board", has_text="qcs615-ride").count() == 1
    pg.locator("#branches button", has_text="main").click()
    pg.wait_for_selector(".bt-board")
    assert errors == []


def test_hidden_fastboot_reference_does_not_set_the_scale(browser, url):
    pg, errors = open_page(browser, url)
    pg.locator("#bt-filters button", has_text="cold boot").click()
    ticks = pg.locator(".bt-board", has_text="rb3gen2").locator("svg.bt-bars text.tick").all_text_contents()
    # The CI boots end near 5 s; the fastboot health check (16.6 s) is not drawn.
    assert ticks[-1] in ("5 s", "10 s"), ticks
    qcs = pg.locator(".bt-board", has_text="qcs615-ride")
    qcs.locator("details summary").click()
    assert "health check 52" in qcs.locator("details").inner_text()
    assert errors == []


def test_detail_verdict_only_on_the_compared_boot(browser, url):
    pg, errors = open_page(browser, url)
    pg.locator("#matrix td.cell", has_text="boot → Linux").first.click()
    pg.wait_for_selector("#detail h3:has-text('Boot time')")
    rows = pg.locator("#detail table.cases").first.locator("tr")
    texts = [rows.nth(i).inner_text() for i in range(rows.count())]
    assert sum("slower" in t for t in texts) == 1
    assert any(t.startswith("cold boot") and "slower" in t for t in texts)
    assert errors == []


def test_no_boot_data_at_all(browser, url):
    pg, errors = open_page(browser, url)
    pg.evaluate("renderBoottime({}, {})")
    assert pg.locator("#boottime").inner_text() == "No boot times yet."
    assert pg.locator("#bt-filters button").count() == 0
    assert errors == []
