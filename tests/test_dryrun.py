"""ubci.dryrun: the combined CI job's dry run matches what the nightly
builds (open stacks with a pending pin are skipped, not built)."""
from ubci import dryrun


def test_ci_job_dry_run_runs_every_step(tmp_path, capsys):
    assert dryrun.ci_jobs(str(tmp_path)) == 0
    assert "UNEXPECTED" not in capsys.readouterr().out


def test_every_job_has_the_cold_boot_and_the_boot_time_case(tmp_path):
    import glob

    import yaml
    seen = []
    assert dryrun.render_jobs(str(tmp_path), lambda text: seen.append(text) or "Job valid.") == 0
    files = glob.glob(str(tmp_path / "jobs" / "*.yaml"))
    assert files and len(seen) == len(files)
    for f in files:
        acts = yaml.safe_load(open(f))["actions"]
        names = [a["test"]["interactive"][0]["name"] for a in acts if "interactive" in a.get("test", {})]
        assert names[-2:] == ["boot-time", "cold-poweroff"], f
        assert any(m["name"] == "firmware-fingerprint-cold" for a in acts for m in a.get("test", {}).get("monitors", []))
    assert dryrun.render_jobs(str(tmp_path / "x"), lambda text: "Job invalid: no") == len(files)
