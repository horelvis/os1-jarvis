"""The gate policy is a list of substrings over Bash commands, and only that.

Only Bash is gated: an Edit inside the project is one `git checkout` from
undone, while a push or an rm is not. The spec's list, verbatim: git push,
recursive deletes, sudo — `git commit` only if the user adds it.
"""
import gates


def test_push_is_dangerous_and_pytest_is_not():
    assert gates.dangerous("Bash", {"command": "git push origin main"})
    assert gates.dangerous("Bash", {"command": "cd x && git push"})
    assert gates.dangerous("Bash", {"command": "pytest -q"}) is None


def test_deletes_and_sudo_are_dangerous():
    assert gates.dangerous("Bash", {"command": "rm -rf build/"})
    assert gates.dangerous("Bash", {"command": "rm -r old"})
    assert gates.dangerous("Bash", {"command": "sudo systemctl restart nginx"})


def test_only_bash_is_gated():
    assert gates.dangerous("Edit", {"file_path": "a.py"}) is None
    assert gates.dangerous("Write", {"command": "git push"}) is None


def test_the_description_is_the_command_trimmed():
    long = "git push " + "x" * 400
    desc = gates.dangerous("Bash", {"command": long})
    assert desc is not None and len(desc) <= 160 and desc.startswith("git push")


def test_env_replaces_the_defaults_when_set():
    """Set, the variable IS the policy — so `git commit` can be added and
    a default can be removed without editing code."""
    assert gates.load_patterns(None) == gates.DEFAULT_PATTERNS
    assert gates.load_patterns("") == gates.DEFAULT_PATTERNS
    assert gates.load_patterns("git commit, git push") == ("git commit", "git push")


def test_matching_folds_case():
    assert gates.dangerous("Bash", {"command": "Git PUSH origin"})
