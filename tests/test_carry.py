import json
import subprocess

from fwci import carry


def sh(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True)


def commit(repo, name, text, msg):
    with open("%s/%s" % (repo, name), "w") as f:
        f.write(text)
    sh(repo, "add", name)
    sh(repo, "commit", "-q", "-m", msg)


def test_carried_ignores_upstreamed_patches(tmp_path):
    r = str(tmp_path)
    sh(r, "init", "-q", "-b", "master")
    sh(r, "config", "user.email", "t@example.com")
    sh(r, "config", "user.name", "T")
    commit(r, "a", "base\n", "base")
    sh(r, "checkout", "-q", "-b", "pin")
    commit(r, "b", "b\n", "feat(b): same patch")
    commit(r, "c", "c\n", "feat(c): merged after review")
    commit(r, "d", "d\n", "feat(d): carried\n\nLink: https://lore.example/d")
    commit(r, "e", "e\n", "fix(e): on gerrit\n\nChange-Id: I" + "1" * 40)
    sh(r, "checkout", "-q", "master")
    commit(r, "b", "b\n", "feat(b): same patch")
    commit(r, "c", "c changed\n", "feat(c): merged after review")
    got = carry.carried(r, "master", "pin", resolve=lambda cid: "https://review.example/q/" + cid)
    assert got["distance"] == 2
    assert [(c["subject"], c["review"]) for c in got["carried"]] == [
        ("feat(d): carried", "https://lore.example/d"),
        ("fix(e): on gerrit", "https://review.example/q/I" + "1" * 40)]


def test_resolve_gerrit():
    found = ")]}'\n" + json.dumps([{"_number": 55532}])
    assert carry.resolve_gerrit("https://review.example/", "TF-A/trusted-firmware-a", "I1",
                                fetch=lambda u: found) == \
        "https://review.example/c/TF-A/trusted-firmware-a/+/55532"
    assert carry.resolve_gerrit("https://review.example", "p", "I2", fetch=lambda u: ")]}'\n[]") is None


def test_review_link_without_a_resolver_is_none():
    assert carry.review_link("fix: x\n\nChange-Id: I" + "2" * 40) is None


def test_a_pending_pin_is_not_fetched(monkeypatch):
    from ubci import carry as ucarry, config
    pins = {"b": {"tf-a": {"repo": "r", "commit": "c", "upstream": {}, "pending": "not pushed yet"},
                  "optee": {"repo": "r2", "commit": "d", "upstream": {}}}}
    monkeypatch.setattr(config, "pins", lambda: pins)
    monkeypatch.setattr(ucarry, "component", lambda pin: {"pin": pin["commit"]})
    assert ucarry.generate() == {"b": {"optee": {"pin": "d"}}}
