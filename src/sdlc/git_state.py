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

# Deliberately TIGHTER than `git check-ref-format`, which permits `$`, a
# backtick, `"`, `'`, `;`, `|`, `&`, `(`, `)`, `<` and `>` in a branch name.
# The value is interpolated into DOUBLE-QUOTED shell by the review skill — `git
# -C "<repo>" worktree add -q -b "<branch>" "$worktree"` — where `$(...)` and
# backticks are substituted and a `"` ends the quoting outright, and it arrives
# from two surfaces the agent does not author: the `review-branch` config key
# and `sdlc_review`'s `target` argument. An allowlist is used rather than a
# longer blocklist because a blocklist is only ever as good as its enumeration,
# and the enumeration is what keeps being incomplete.
_ALLOWED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_repo_path(value: str) -> str:
    """Return ``value`` unchanged, or raise if it cannot be a directive line.

    `review-repo` reaches the prompt the same way `review-branch` reaches the
    shell: it is interpolated into the `Review repository:` directive block
    that the reviewing agent reads and step 10(a) commits against. A newline
    in it would let the value forge a SECOND directive line below the genuine
    one, which is the threat `validate_branch_name` exists to close for its
    sibling key — and the unresolved branch, where the raw path is echoed back,
    is reached by nothing more exotic than a path that does not exist yet.

    Deliberately narrower than `validate_branch_name`: a repository path is a
    filesystem path and may legitimately contain spaces, `~` or `..`, none of
    which a branch name may. What it may NOT contain is a control character or
    surrounding whitespace, neither of which names a real directory and both
    of which change how many lines the directive block has.
    """
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if not value.strip():
        raise ValueError("must not be empty")
    if value != value.strip():
        raise ValueError(
            f"must not be padded with whitespace: {value!r}"
        )
    for index, char in enumerate(value):
        if ord(char) < 0x20 or ord(char) == 0x7F:
            raise ValueError(
                f"must not contain a control character (found {char!r} at "
                f"position {index}): the value is interpolated into the "
                f"Review repository directive, so a newline forges a second "
                f"directive line. {value!r}"
            )
    return value


# Where review documents are written, relative to the working directory. The
# path is hardcoded in `pr_state._reviews_dir`, so a review repository that does
# not contain it can never hold a document.
_DOCUMENTS = Path(".sdlc/reviews")


@dataclass(frozen=True)
class ReviewRepo:
    """The repository review-document commits belong in.

    ``root`` is the repository's working-tree root, or ``None`` when no
    repository could be resolved — in which case the skill asks the user rather
    than guessing. ``configured`` records whether the root came from the
    ``review-repo`` config key, so a caller can tell a declared repository from
    the ``.sdlc`` convention fallback. ``reason`` explains an unresolved result
    that is a REFUSAL rather than a miss: the path was declined by policy, and
    the caller must not report it as "not a git repository". ``candidate`` is
    the absolute path a configured value resolved to, carried so a diagnostic
    can NAME it — the raw config value alone is not enough to see what went
    wrong, because it is resolved against the config file's parent rather than
    the working directory.
    """

    root: Path | None
    configured: bool
    reason: str | None = None
    candidate: Path | None = None


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

    Two configured repositories are REFUSED rather than missed, each with a
    ``reason``: one that is the reviewed tree's root or an ancestor of it (the
    snapshot could not exclude it), and one that cannot contain
    ``.sdlc/reviews`` (it could never hold a document). Both resolve perfectly
    well and neither can be used, so the diagnosis belongs here rather than
    several steps downstream.
    """
    cwd = (cwd or Path.cwd()).resolve()
    if configured is not None:
        # Re-checked here and not only at config load: this function is also
        # reached with a value the endpoint supplies, which never passed
        # through `guides._validate_schema`.
        try:
            validate_repo_path(configured)
        except ValueError as exc:
            return ReviewRepo(
                root=None,
                configured=True,
                reason=(
                    f"The configured review-repo is unusable: {exc}. Ask the "
                    "user to correct review-repo in .sdlc/config.json. Do not "
                    "commit anywhere else."
                ),
            )
        base = config_dir.resolve() if config_dir is not None else cwd
        candidate = (base / configured).resolve()
        if candidate == cwd or cwd.is_relative_to(candidate):
            # Declined by policy, whether or not it is a repository: this check
            # runs BEFORE `_is_repo`, so the branch is reached by a non-git
            # ancestor too. What it must not be reported as is "not a git
            # repository", which would send a user whose path IS one to
            # initialize something that already exists.
            #
            # The reviewed tree's own root, or an ancestor of it. The snapshot
            # excludes the review repository from the reviewed tree by a
            # top-anchored relative pathspec, and there is no such pathspec for
            # a directory that CONTAINS the tree: the relative path is `.` or
            # empty, which excludes nothing, so the capture embeds the review
            # repository in the snapshot of the code it reviews and the tree
            # SHA churns every pass regardless of the code — silently, because
            # the empty-tree sentinel never fires on a non-empty tree.
            #
            # Equality alone was not enough. The property depends on the
            # candidate's relation to the reviewed tree, and a strict ancestor
            # (`review-repo: "../.."` from a `.sdlc` one level down) is reached
            # by a configuration the skill actively recommends.
            return ReviewRepo(
                root=None,
                configured=True,
                reason=(
                    f"The configured review-repo resolves to {candidate.as_posix()!r}, "
                    f"which {'is' if candidate == cwd else 'contains'} the tree "
                    "under review. The snapshot excludes "
                    "the review repository by a relative pathspec, and no such "
                    "pathspec exists for a directory that contains the tree, so "
                    "the review repository would be captured into the snapshot of "
                    "the code it reviews. Ask the user to move it to a "
                    "subdirectory such as .sdlc, or outside the reviewed tree "
                    "entirely."
                ),
                candidate=candidate,
            )
        if not _is_repo(candidate):
            return ReviewRepo(root=None, configured=True, candidate=candidate)
        documents = (cwd / _DOCUMENTS).resolve()
        if not documents.is_relative_to(candidate):
            # Resolves fine, and can never commit. The document path is
            # hardcoded under `.sdlc/reviews/`, so a repository that does not
            # contain it reports `Review document in repository: unresolved` on
            # every call. Refusing here is symmetric with the ancestor case
            # above and moves the diagnosis to where the configuration is read,
            # instead of leaving the skill to reconcile a split verdict —
            # `Review repository: <path>` beside an unresolved document — at
            # step 10(a), one step before it would have committed.
            return ReviewRepo(
                root=None,
                configured=True,
                reason=(
                    f"The configured review-repo resolves to {candidate.as_posix()!r}, "
                    f"which does not contain {documents.as_posix()}. Review "
                    "documents are written under .sdlc/reviews/, so this "
                    "repository could never hold them and every call would "
                    "report the document unresolved. Ask the user to name a "
                    "repository that contains .sdlc/reviews — .sdlc itself is "
                    "the convention."
                ),
                candidate=candidate,
            )
        return ReviewRepo(root=candidate, configured=True, candidate=candidate)
    # Resolved, exactly as the configured branch resolves its candidate. Left
    # unresolved, a symlinked `.sdlc` — a sibling reviews repository linked into
    # the tree — yields a root that the document path, which resolves THROUGH
    # the symlink, is not relative to. The endpoint then reports the document
    # outside the repository, which is false, and step 10(a) STOPs on every
    # pass so the round can never commit.
    sdlc_dir = (cwd / ".sdlc").resolve()
    if _is_repo(sdlc_dir):
        return ReviewRepo(root=sdlc_dir, configured=False)
    return ReviewRepo(root=None, configured=False)


def validate_branch_name(name: str) -> str:
    """Return ``name`` unchanged, or raise ``ValueError`` explaining why not.

    The value reaches a `git` invocation in the skill and is interpolated into
    the directive block the reviewing agent reads, so it is validated at both
    entry points — the ``review-branch`` config key and the tool's ``target``
    argument. A newline would let a branch name forge a second directive line
    below the genuine one; a shell metacharacter would let it forge a command,
    since the skill interpolates the value into double-quoted shell strings.

    The rules follow ``git check-ref-format`` and then go beyond it: the final
    check is a positive allowlist, so the accepted set is stated rather than
    inferred from everything the rules below happened to name. Names git would
    accept are therefore refused here — anything outside
    ``[A-Za-z0-9][A-Za-z0-9._/-]*``, including non-ASCII letters — which is the
    intended trade.
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
    # Per COMPONENT, not per string. `git check-ref-format` forbids any
    # slash-separated component from beginning with '.' or ending in '.lock',
    # so a whole-string check accepts `feat/.x` and `a.lock/b` — which then
    # pass the config schema, reach the directive block, and fail only inside
    # the skill's own `git` invocation.
    for part in name.split("/"):
        if part.startswith("."):
            raise ValueError(
                f"branch name components must not begin with '.': {name!r}"
            )
        if part.endswith("."):
            raise ValueError(
                f"branch name components must not end with '.': {name!r}"
            )
        if part.endswith(".lock"):
            raise ValueError(
                f"branch name components must not end with '.lock': {name!r}"
            )
    if name == "@":
        raise ValueError("branch name must not be '@'")
    if _ALLOWED_NAME.match(name) is None:
        raise ValueError(
            "branch name must match [A-Za-z0-9][A-Za-z0-9._/-]* — the value is "
            f"interpolated into a shell command, so this is deliberately "
            f"stricter than git check-ref-format: {name!r}"
        )
    return name
