"""The "boots Linux" verdict: did the board reach a login prompt on the
pristine linux-next payload, and if not, where did it stop?

Stages, in boot order:
  not-reached          the console never got to the Linux handoff (the
                       firmware under test or the flash failed first)
  no-efi-stub          the bootloader ran its boot command but no kernel
                       output followed (nothing booted, or the EFI stub
                       died silently)
  hang-before-console  the EFI stub ran but the kernel console never came up
  early-panic          the kernel panicked or oopsed before a login prompt
  no-login             the kernel ran but no login prompt came
  login                the login prompt was reached (verdict pass)
"""
import re

MARKERS = {
    # U-Boot's autoboot countdown reaching 0, or an EFI application taking
    # the console (the terminal size query U-Boot's EFI console sends,
    # logged by LAVA without its ESC bytes).
    "handoff": r"autoboot: +0|\[6n|Booting: |bootefi|EFI stub: ",
    "efi_stub": r"EFI stub: ",
    "kernel": r"Booting Linux on physical CPU|Linux version \d",
    "panic": r"Kernel panic - not syncing|Internal error: |Unable to handle kernel|Oops",
    "login": r"login:",
}
LAST_LINES = 15


def first(lines, pattern):
    rx = re.compile(pattern)
    for idx, text in lines:
        if rx.search(text):
            return idx
    return None


def classify(lines, job_url=None, markers=MARKERS):
    """lines: (log index, console text) of one boot, in order. Returns the
    linux_boot object of the run schema (without versus_baseline)."""
    seen = {k: first(lines, p) for k, p in markers.items()}
    if seen["login"] is not None:
        return {"verdict": "pass", "stage": "login",
                "url": _anchor(job_url, seen["login"])}
    if seen["panic"] is not None:
        stage, at = "early-panic", seen["panic"]
    elif seen["kernel"] is not None:
        stage, at = "no-login", None
    elif seen["efi_stub"] is not None:
        stage, at = "hang-before-console", None
    elif seen["handoff"] is not None:
        stage, at = "no-efi-stub", None
    else:
        stage, at = "not-reached", None
    tail = lines[-LAST_LINES:]
    if at is not None:
        pos = next(i for i, (idx, _) in enumerate(lines) if idx == at)
        tail = lines[max(0, pos - 5):pos + LAST_LINES - 5]
    out = {"verdict": "fail" if stage != "not-reached" else "not-run",
           "stage": stage,
           "last_lines": [t for _, t in tail]}
    if tail:
        out["url"] = _anchor(job_url, at if at is not None else tail[-1][0])
    return out


def _anchor(job_url, index):
    return "%s#L%d" % (job_url, index) if job_url else "#L%d" % index


def versus(run_verdict, baseline_verdict):
    """How a run's boot compares with the same board and stack in its
    baseline: a series that stops booting is a regression it caused; when
    the baseline does not boot either the gap is upstream."""
    if baseline_verdict not in ("pass", "fail"):
        return "unknown"
    if run_verdict == "fail":
        return "regression" if baseline_verdict == "pass" else "upstream-gap"
    if run_verdict == "pass":
        return "fixed" if baseline_verdict == "fail" else "same"
    return "unknown"
