import pytest

from fwci import schema

from samples import run, target


def test_sample_run_is_valid():
    assert schema.errors(run()) == []


@pytest.mark.parametrize("mutate,where", [
    (lambda r: r.pop("targets"), "(root)"),
    (lambda r: r["targets"][0].update(state="sleeping"), "targets/0/state"),
    (lambda r: r["linux"].update(tag="v7.3"), "linux/tag"),
    (lambda r: r["targets"][0]["linux_boot"].update(stage="somewhere"), "targets/0/linux_boot/stage"),
    (lambda r: r["targets"][0].update(surprise=1), "targets/0"),
    (lambda r: r["run"].update(id="has space"), "run/id"),
    (lambda r: r["targets"][0]["components"][1]["upstream"].update(distance=-1),
     "targets/0/components/1/upstream/distance"),
])
def test_invalid_documents_are_rejected(mutate, where):
    r = run()
    mutate(r)
    errs = schema.errors(r)
    assert errs and any(e.startswith(where) for e in errs)
    with pytest.raises(ValueError):
        schema.check(r)


def test_linux_may_be_null_before_the_kernel_is_built():
    r = run()
    r["linux"] = None
    assert schema.errors(r) == []
