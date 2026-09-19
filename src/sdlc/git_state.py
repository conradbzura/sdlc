"""Git facts `sdlc_review` needs: the review repository and branch-name validity.

Filesystem-only — nothing here spawns `git`. The package's sole subprocess is
`pr_state._run_gh`, and every git operation in the pipeline is performed by the
agent following the skill markdown. This module resolves the deterministic
facts the endpoint injects as directives.

The review repository is **declared**, not inferred. An earlier design walked
from the working directory to the filesystem root looking for a `.git`, which
could silently select a repository the user never intended — a home directory
managed as a dotfiles repo, for instance. Resolution now consults the
`review-repo` config key, falls back to `.sdlc` only when it is already a
repository, and otherwise reports that it is unresolved so the skill can ask.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Characters and sequences `git check-ref-format` rejects in a branch name.
_INVALID_SEQUENCES = ("..", "@{", "//")
_INVALID_CHARS = set(" ~^:?*[\\")


@dataclass(frozen=True)
class ReviewRepo:
    """The repository review-document commits belong in.

    ``root`` is the repository's working-tree root, or ``None`` when no
    repository could be resolved — in which case the skill asks the user rather
    than guessing. ``configured`` records whether the root came from the
    ``review-repo`` config key, so a caller can tell a declared repository from
    the ``.sdlc`` convention fallback.
    """

    root: Path | None
    configured: bool


def _is_repo(directory: Path) -> bool:
    """Return whether ``directory`` is a git working-tree root.

    ``.git`` is a directory in an ordinary clone and a file in a worktree or
    submodule checkout, so only existence is checked. An unreadable path
    answers ``False`` rather than raising: on Python 3.13 ``Path.exists()``
    propagates ``EACCES``, and a permission problem on one candidate must not
    take down the whole review.
    """
    try:
        return (directory / ".git").exists()
    except OSError:
        return False


def resolve_review_repo(
    configured: str | None,
    config_dir: Path | None,
    cwd: Path | None = None,
) -> ReviewRepo:
    """Resolve the repository review documents are committed to.

    ``configured`` is the ``review-repo`` config value. It is resolved relative
    to ``config_dir`` (the config file's parent) exactly as ``guides-dir`` is,
    falling back to ``cwd`` when no config file was found. When it is unset,
    ``<cwd>/.sdlc`` applies if it is already a repository. When neither yields
    one, the root is ``None`` and the caller is responsible for asking the user
    instead of inferring.

    A configured path that does not exist, or is not a repository, resolves to
    ``None`` as well — reported to the user as a misconfiguration rather than
    silently falling back to somewhere they did not name.
    """
    cwd = (cwd or Path.cwd()).resolve()
    if configured is not None:
        base = config_dir.resolve() if config_dir is not None else cwd
        candidate = (base / configured).resolve()
        if _is_repo(candidate):
            return ReviewRepo(root=candidate, configured=True)
        return ReviewRepo(root=None, configured=True)
    sdlc_dir = cwd / ".sdlc"
    if _is_repo(sdlc_dir):
        return ReviewRepo(root=sdlc_dir, configured=False)
    return ReviewRepo(root=None, configured=False)


def validate_branch_name(name: str) -> str:
    """Return ``name`` unchanged, or raise ``ValueError`` explaining why not.

    The value reaches a `git` invocation in the skill and is interpolated into
    the directive block the reviewing agent reads, so it is validated at both
    entry points — the ``review-branch`` config key and the tool's ``target``
    argument. A newline is the dangerous case: it would let a branch name forge
    a second directive line below the genuine one. The remaining rules follow
    ``git check-ref-format``.
    """
    if not isinstance(name, str):
        raise ValueError(f"branch name must be a string, got {type(name).__name__}")
    if not name.strip():
        raise ValueError("branch name must not be empty or whitespace only")
    if name != name.strip():
        raise ValueError(f"branch name must not be padded with whitespace: {name!r}")
    control = [c for c in name if ord(c) < 0x20 or ord(c) == 0x7F]
    if control:
        raise ValueError(
            f"branch name must not contain control characters: {name!r}"
        )
    bad = sorted(_INVALID_CHARS & set(name))
    if bad:
        raise ValueError(
            f"branch name must not contain {''.join(bad)!r}: {name!r}"
        )
    for sequence in _INVALID_SEQUENCES:
        if sequence in name:
            raise ValueError(
                f"branch name must not contain {sequence!r}: {name!r}"
            )
    if name.startswith("-"):
        raise ValueError(f"branch name must not begin with '-': {name!r}")
    if name.startswith("/") or name.endswith("/"):
        raise ValueError(f"branch name must not begin or end with '/': {name!r}")
    if name.endswith("."):
        raise ValueError(f"branch name must not end with '.': {name!r}")
    if name.endswith(".lock"):
        raise ValueError(f"branch name must not end with '.lock': {name!r}")
    if name == "@":
        raise ValueError("branch name must not be '@'")
    return name
