"""Guide config loading, discovery, and resolution.

Guides are markdown files served as MCP resources. Two namespaces exist:
``test`` and ``style``. Bundled guides ship with the package; user guides
extend or override them via a ``.sdlc/config.json`` file (path overridable
via the ``SDLC_CONFIG`` environment variable).
"""

from __future__ import annotations

import copy
import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

import pathspec

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "config.json"

KINDS = ("test", "style")
ALLOWED_TOP_LEVEL_KEYS = {"guides-dir", "guide-map"}
CAMEL_CASE_HINTS = {"guidesDir": "guides-dir", "guideMap": "guide-map"}


@dataclass(frozen=True)
class GuidesState:
    """Effective state needed to serve guides at runtime.

    ``discovered`` maps ``(kind, stem)`` to the absolute path of each guide
    file. ``guide_map`` is the merged glob-to-stems map keyed by kind. ``config``
    is the full merged config (default + user) for inspection.
    """

    discovered: dict[tuple[str, str], Path]
    guide_map: dict[str, dict[str, list[str]]]
    config: dict


def load_package_default(package_dir: Path | None = None) -> dict:
    """Load and validate the default config shipped with the package."""
    path = (package_dir or PACKAGE_DIR) / "config.json"
    return _load_json(path)


def load_user_config(cwd: Path) -> tuple[dict, Path] | None:
    """Resolve and load the user config, returning ``(config, config_dir)`` or ``None``.

    Resolution order: ``$SDLC_CONFIG`` if set, then ``<cwd>/.sdlc/config.json``,
    then ``None``. A missing env-pointed file raises ``ValueError``.
    """
    env_path = os.environ.get("SDLC_CONFIG")
    if env_path:
        path = Path(env_path)
        if not path.is_file():
            raise ValueError(
                f"SDLC_CONFIG points to non-existent file: {env_path}"
            )
        return _load_json(path), path.parent
    default_path = cwd / ".sdlc" / "config.json"
    if default_path.is_file():
        return _load_json(default_path), default_path.parent
    return None


def merge_configs(default: dict, user: dict | None) -> dict:
    """Deep-merge user config onto default through ``guide-map.{test,style}``.

    Top level: ``guides-dir`` from user replaces default if present.
    ``guide-map``: per-namespace deep merge — user's namespace dict updates
    default's. Inside a namespace, pattern keys are merged shallowly so a user
    pattern key replaces the default's same-pattern entry while disjoint keys
    coexist.
    """
    merged = copy.deepcopy(default)
    if user is None:
        return merged
    if "guides-dir" in user:
        merged["guides-dir"] = user["guides-dir"]
    if "guide-map" in user:
        merged_map = merged.setdefault("guide-map", {})
        for kind, user_patterns in user["guide-map"].items():
            merged_map.setdefault(kind, {}).update(user_patterns)
    return merged


def discover_guides(
    config: dict,
    package_dir: Path,
    cwd: Path,
    user_config_dir: Path | None,
) -> dict[tuple[str, str], Path]:
    """Walk bundled and user guide directories, returning ``(kind, stem)`` paths.

    User guides take precedence on stem collision within a kind. The user
    directory is ``config['guides-dir']`` resolved against the config's parent
    directory if set, otherwise the convention path ``<cwd>/.sdlc/guides``.
    """
    discovered: dict[tuple[str, str], Path] = {}
    for kind in KINDS:
        bundled_dir = package_dir / f"{kind}-guides"
        if bundled_dir.is_dir():
            for guide in sorted(bundled_dir.glob("*.md")):
                discovered[(kind, guide.stem)] = guide
    user_dir, explicitly_configured = _resolve_user_guides_dir(
        config, cwd, user_config_dir
    )
    if user_dir.is_dir():
        for kind in KINDS:
            kind_dir = user_dir / kind
            if kind_dir.is_dir():
                for guide in sorted(kind_dir.glob("*.md")):
                    discovered[(kind, guide.stem)] = guide
    elif explicitly_configured:
        warnings.warn(
            f"guides-dir '{config['guides-dir']}' not found at {user_dir}",
            stacklevel=2,
        )
    return discovered


def resolve_guides(
    paths: list[str],
    kind: str,
    guide_map: dict[str, dict[str, list[str]]],
    discovered: dict[tuple[str, str], Path],
) -> list[str]:
    """Return the de-duplicated, ordered stems whose patterns match any of ``paths``.

    Stems referenced in the map but missing from ``discovered`` are silently
    skipped — only guides that exist as files are returned.
    """
    namespace = guide_map.get(kind, {})
    seen: set[str] = set()
    result: list[str] = []
    for pattern, stems in namespace.items():
        spec = pathspec.PathSpec.from_lines("gitignore", [pattern])
        if not any(spec.match_file(p) for p in paths):
            continue
        for stem in stems:
            if (kind, stem) in discovered and stem not in seen:
                seen.add(stem)
                result.append(stem)
    return result


def read_guide(
    kind: str,
    stem: str,
    discovered: dict[tuple[str, str], Path],
) -> str:
    """Return the content of a discovered guide, or an error message if absent."""
    path = discovered.get((kind, stem))
    if path is None:
        return f"Error: guide '{kind}/{stem}' not found"
    return path.read_text()


def load_state(
    cwd: Path | None = None,
    package_dir: Path | None = None,
) -> GuidesState:
    """Build the runtime guides state from the package default and user config."""
    cwd = cwd or Path.cwd()
    package_dir = package_dir or PACKAGE_DIR
    default = load_package_default(package_dir)
    loaded = load_user_config(cwd)
    if loaded is None:
        user_config = None
        user_config_dir = None
    else:
        user_config, user_config_dir = loaded
    merged = merge_configs(default, user_config)
    discovered = discover_guides(merged, package_dir, cwd, user_config_dir)
    return GuidesState(
        discovered=discovered,
        guide_map=merged.get("guide-map", {}),
        config=merged,
    )


def _resolve_user_guides_dir(
    config: dict,
    cwd: Path,
    user_config_dir: Path | None,
) -> tuple[Path, bool]:
    guides_dir = config.get("guides-dir")
    if guides_dir is not None:
        base = user_config_dir if user_config_dir is not None else cwd
        return (base / guides_dir).resolve(), True
    return (cwd / ".sdlc" / "guides").resolve(), False


def _load_json(path: Path) -> dict:
    try:
        with path.open() as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path}: {exc}") from exc
    _validate_schema(data, path)
    return data


def _validate_schema(data: object, path: Path) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a JSON object")
    unknown = set(data.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        for bad in unknown:
            if bad in CAMEL_CASE_HINTS:
                raise ValueError(
                    f"{path}: unknown key '{bad}' — did you mean "
                    f"'{CAMEL_CASE_HINTS[bad]}'? (config uses kebab-case)"
                )
        raise ValueError(
            f"{path}: unknown top-level keys: {sorted(unknown)} "
            f"(allowed: {sorted(ALLOWED_TOP_LEVEL_KEYS)})"
        )
    if "guides-dir" in data and not isinstance(data["guides-dir"], str):
        raise ValueError(f"{path}: 'guides-dir' must be a string")
    if "guide-map" in data:
        guide_map = data["guide-map"]
        if not isinstance(guide_map, dict):
            raise ValueError(f"{path}: 'guide-map' must be an object")
        unknown_kinds = set(guide_map.keys()) - set(KINDS)
        if unknown_kinds:
            raise ValueError(
                f"{path}: 'guide-map' has unknown kinds: "
                f"{sorted(unknown_kinds)} (allowed: {list(KINDS)})"
            )
        for kind, patterns in guide_map.items():
            if not isinstance(patterns, dict):
                raise ValueError(
                    f"{path}: 'guide-map.{kind}' must be an object"
                )
            for pattern, stems in patterns.items():
                if not isinstance(stems, list) or not all(
                    isinstance(s, str) for s in stems
                ):
                    raise ValueError(
                        f"{path}: 'guide-map.{kind}[{pattern!r}]' must be "
                        f"a list of strings"
                    )
