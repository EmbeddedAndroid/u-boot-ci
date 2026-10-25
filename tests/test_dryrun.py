"""ubci.dryrun: the combined CI job's dry run matches what the nightly
builds (open stacks with a pending pin are skipped, not built)."""
from ubci import dryrun


def test_ci_job_dry_run_runs_every_step(tmp_path, capsys):
    assert dryrun.ci_jobs(str(tmp_path)) == 0
    assert "UNEXPECTED" not in capsys.readouterr().out
