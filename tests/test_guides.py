"""Tests for sdlc.guides — config loading, merging, discovery, and resolution."""

import json

import pytest

from sdlc.guides import (
    discover_guides,
    files_for_role,
    globs_for_role,
    list_roles,
    load_package_default,
    load_state,
    load_user_config,
    merge_configs,
    read_guide,
    resolve_guides,
)


def test_load_package_default_should_return_shipped_config():
    """Test the shipped src/sdlc/config.json is loaded with expected structure.

    Given:
        The package ships src/sdlc/config.json with a default guide-map.
    When:
        load_package_default() is called with no arguments.
    Then:
        It should return a dict with kebab-case 'guide-map' covering test, style, and role.
    """
    # Act
    result = load_package_default()

    # Assert
    assert "guide-map" in result
    assert result["guide-map"]["test"]["**/*.py"] == ["python"]
    assert result["guide-map"]["style"]["**/*.md"] == ["markdown"]
    assert result["guide-map"]["role"]["**/*"] == ["general-purpose"]


def test_load_user_config_should_return_none_when_file_and_env_missing(tmp_path, monkeypatch):
    """Test no user config is found when the conventional file is missing.

    Given:
        No .sdlc/config.json exists under cwd, no SDLC_CONFIG env var.
    When:
        load_user_config(cwd) is called.
    Then:
        It should return None.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)

    # Act
    result = load_user_config(tmp_path)

    # Assert
    assert result is None


def test_load_user_config_should_read_file_when_at_default_path(tmp_path, monkeypatch):
    """Test the conventional .sdlc/config.json path is read with its parent dir.

    Given:
        A valid .sdlc/config.json under cwd.
    When:
        load_user_config(cwd) is called.
    Then:
        It should return the parsed config and the .sdlc/ directory.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('{"guides-dir": "guides"}')

    # Act
    result = load_user_config(tmp_path)

    # Assert
    assert result is not None
    config, config_dir = result
    assert config == {"guides-dir": "guides"}
    assert config_dir == sdlc_dir


def test_load_user_config_should_honor_env_var_when_set(tmp_path, monkeypatch):
    """Test SDLC_CONFIG env var takes precedence over the conventional path.

    Given:
        SDLC_CONFIG points to a custom file and a conventional .sdlc/config.json
        also exists.
    When:
        load_user_config(cwd) is called.
    Then:
        It should read the env-pointed file and return its parent directory.
    """
    # Arrange
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    custom_path = custom_dir / "sdlc.json"
    custom_path.write_text('{"guides-dir": "elsewhere"}')
    monkeypatch.setenv("SDLC_CONFIG", str(custom_path))
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('{"guides-dir": "ignored"}')

    # Act
    result = load_user_config(tmp_path)

    # Assert
    assert result is not None
    config, config_dir = result
    assert config["guides-dir"] == "elsewhere"
    assert config_dir == custom_dir


def test_load_user_config_should_raise_when_env_var_points_to_missing_file(tmp_path, monkeypatch):
    """Test SDLC_CONFIG pointing to a nonexistent file raises ValueError.

    Given:
        SDLC_CONFIG is set to a path that does not exist.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError naming SDLC_CONFIG.
    """
    # Arrange
    monkeypatch.setenv("SDLC_CONFIG", str(tmp_path / "no-such-file.json"))

    # Act & assert
    with pytest.raises(ValueError, match="SDLC_CONFIG"):
        load_user_config(tmp_path)


def test_load_user_config_should_raise_when_json_malformed(tmp_path, monkeypatch):
    """Test malformed JSON surfaces a clear error.

    Given:
        A .sdlc/config.json with invalid JSON syntax.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError mentioning the file.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text("{ not valid json")

    # Act & assert
    with pytest.raises(ValueError, match="Malformed JSON"):
        load_user_config(tmp_path)


def test_load_user_config_should_raise_when_top_level_key_unknown(tmp_path, monkeypatch):
    """Test unknown top-level keys are rejected.

    Given:
        A .sdlc/config.json with an unrecognized top-level key.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError naming the bad key.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('{"unknown": "value"}')

    # Act & assert
    with pytest.raises(ValueError, match="unknown"):
        load_user_config(tmp_path)


def test_load_user_config_should_hint_kebab_case_when_key_is_camel_case(tmp_path, monkeypatch):
    """Test camelCase key variants are rejected with a helpful kebab-case hint.

    Given:
        A .sdlc/config.json using 'guidesDir' (camelCase).
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError suggesting 'guides-dir'.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('{"guidesDir": "guides"}')

    # Act & assert
    with pytest.raises(ValueError, match="guides-dir"):
        load_user_config(tmp_path)


def test_load_user_config_should_hint_kebab_case_when_mixed_unknown_keys(tmp_path, monkeypatch):
    """Test a camelCase hint is surfaced even when accompanied by other unknown keys.

    Given:
        A .sdlc/config.json with both 'guidesDir' (camelCase) and an unrelated
        unknown key 'foobar'.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError suggesting 'guides-dir', regardless of set
        iteration order over the unknown keys.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text(
        '{"guidesDir": "guides", "foobar": 1}'
    )

    # Act & assert
    with pytest.raises(ValueError, match="guides-dir"):
        load_user_config(tmp_path)


def test_load_user_config_should_raise_when_guides_dir_not_string(tmp_path, monkeypatch):
    """Test guides-dir must be a string.

    Given:
        A config with 'guides-dir' set to a non-string value.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError mentioning 'guides-dir'.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('{"guides-dir": 42}')

    # Act & assert
    with pytest.raises(ValueError, match="guides-dir"):
        load_user_config(tmp_path)


def test_load_user_config_should_raise_when_guide_map_kind_unknown(tmp_path, monkeypatch):
    """Test guide-map can only contain 'test' or 'style' kinds.

    Given:
        A guide-map with an unknown namespace 'docs'.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError naming the bad kind.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text(
        '{"guide-map": {"docs": {"**/*.py": ["python"]}}}'
    )

    # Act & assert
    with pytest.raises(ValueError, match="docs"):
        load_user_config(tmp_path)


def test_load_user_config_should_accept_guide_map_role_kind(tmp_path, monkeypatch):
    """Test guide-map accepts the 'role' kind as a first-class namespace.

    Given:
        A guide-map declaring a 'role' namespace.
    When:
        load_user_config(cwd) is called.
    Then:
        It should return the parsed config with the role namespace intact.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text(
        '{"guide-map": {"role": {"src/**/*.py": ["architect"]}}}'
    )

    # Act
    result = load_user_config(tmp_path)

    # Assert
    assert result is not None
    config, _ = result
    assert config["guide-map"]["role"]["src/**/*.py"] == ["architect"]


def test_load_user_config_should_raise_when_top_level_not_object(tmp_path, monkeypatch):
    """Test valid JSON whose top-level value is not an object is rejected.

    Given:
        A .sdlc/config.json containing a JSON array (valid JSON, wrong shape).
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError mentioning 'top-level'.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text('["guides-dir", "guides"]')

    # Act & assert
    with pytest.raises(ValueError, match="top-level"):
        load_user_config(tmp_path)


def test_load_user_config_should_raise_when_stems_not_a_list(tmp_path, monkeypatch):
    """Test pattern values must be lists of strings.

    Given:
        A guide-map where a pattern maps to a string instead of a list.
    When:
        load_user_config(cwd) is called.
    Then:
        It should raise ValueError mentioning the offending pattern.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text(
        '{"guide-map": {"test": {"**/*.py": "python"}}}'
    )

    # Act & assert
    with pytest.raises(ValueError, match=r"\*\*/\*\.py"):
        load_user_config(tmp_path)


def test_merge_configs_should_return_default_copy_when_user_is_none():
    """Test None user yields a value equal to the default config.

    Given:
        A default config and no user config.
    When:
        merge_configs(default, None) is called.
    Then:
        It should return a dict equal to the default.
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}

    # Act
    result = merge_configs(default, None)

    # Assert
    assert result == default


def test_merge_configs_should_not_mutate_default():
    """Test the merge does not mutate the input default dict.

    Given:
        A default config and a user config that adds a pattern.
    When:
        merge_configs(default, user) is called.
    Then:
        The original default dict is unchanged.
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}
    user = {"guide-map": {"test": {"tests/**/*.py": ["pytest"]}}}

    # Act
    merge_configs(default, user)

    # Assert
    assert default == {"guide-map": {"test": {"**/*.py": ["python"]}}}


def test_merge_configs_should_override_guides_dir_when_user_provides_it():
    """Test guides-dir from user replaces the default value.

    Given:
        Default has guides-dir 'a' and user has guides-dir 'b'.
    When:
        merge_configs(default, user) is called.
    Then:
        Result has guides-dir 'b'.
    """
    # Arrange
    default = {"guides-dir": "a"}
    user = {"guides-dir": "b"}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guides-dir"] == "b"


def test_merge_configs_should_add_user_pattern_to_existing_namespace():
    """Test user pattern is added alongside default patterns in same namespace.

    Given:
        Default test namespace has '**/*.py' and user adds 'tests/**/*.py'.
    When:
        merge_configs is called.
    Then:
        Both patterns are present in the merged test namespace.
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}
    user = {"guide-map": {"test": {"tests/**/*.py": ["pytest"]}}}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guide-map"]["test"] == {
        "**/*.py": ["python"],
        "tests/**/*.py": ["pytest"],
    }


def test_merge_configs_should_replace_default_when_user_pattern_key_matches():
    """Test same pattern key in user replaces the default value.

    Given:
        Default has '**/*.py' → ['python'] and user has '**/*.py' → ['custom'].
    When:
        merge_configs is called.
    Then:
        Result has '**/*.py' → ['custom'].
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}
    user = {"guide-map": {"test": {"**/*.py": ["custom"]}}}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guide-map"]["test"]["**/*.py"] == ["custom"]


def test_merge_configs_should_preserve_default_namespace_when_user_omits_it():
    """Test default namespaces not mentioned in user config are preserved.

    Given:
        Default has both 'test' and 'style' namespaces; user only sets 'test'.
    When:
        merge_configs is called.
    Then:
        The 'style' namespace is preserved from the default.
    """
    # Arrange
    default = {
        "guide-map": {
            "test": {"**/*.py": ["python"]},
            "style": {"**/*.md": ["markdown"]},
        }
    }
    user = {"guide-map": {"test": {"**/*.rs": ["rust"]}}}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guide-map"]["style"] == {"**/*.md": ["markdown"]}


def test_merge_configs_should_disable_pattern_when_user_stems_empty():
    """Test user setting a pattern to [] disables guides for that pattern.

    Given:
        Default has '**/*.py' → ['python'] and user sets '**/*.py' → [].
    When:
        merge_configs is called.
    Then:
        Result has '**/*.py' → [].
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}
    user = {"guide-map": {"test": {"**/*.py": []}}}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guide-map"]["test"]["**/*.py"] == []


def test_merge_configs_should_add_namespace_when_user_introduces_it():
    """Test user introducing a namespace absent from default is included.

    Given:
        Default has only 'test' and user adds a 'style' namespace.
    When:
        merge_configs is called.
    Then:
        Result has both namespaces.
    """
    # Arrange
    default = {"guide-map": {"test": {"**/*.py": ["python"]}}}
    user = {"guide-map": {"style": {"**/*.md": ["markdown"]}}}

    # Act
    result = merge_configs(default, user)

    # Assert
    assert result["guide-map"]["style"] == {"**/*.md": ["markdown"]}


def test_discover_guides_should_find_bundled_only_when_no_user_dir(tmp_path):
    """Test bundled guides are discovered when no user dir exists.

    Given:
        A package dir with test-guides/python.md, no user guides dir.
    When:
        discover_guides is called.
    Then:
        Only the bundled guide is discovered.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "test-guides").mkdir(parents=True)
    (pkg / "test-guides" / "python.md").write_text("# Python guide")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert result[("test", "python")] == pkg / "test-guides" / "python.md"


def test_discover_guides_should_merge_user_guides_at_convention_path(tmp_path):
    """Test user guides at the default .sdlc/guides/ convention path are discovered.

    Given:
        Bundled python guide and user pytest-patterns guide at .sdlc/guides/test/.
    When:
        discover_guides is called with no user_config_dir.
    Then:
        Both bundled and user guides are present.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "test-guides").mkdir(parents=True)
    (pkg / "test-guides" / "python.md").write_text("# Python")
    cwd = tmp_path / "proj"
    (cwd / ".sdlc" / "guides" / "test").mkdir(parents=True)
    (cwd / ".sdlc" / "guides" / "test" / "pytest-patterns.md").write_text("# PP")
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert ("test", "python") in result
    assert ("test", "pytest-patterns") in result


def test_discover_guides_should_prefer_user_when_stems_collide(tmp_path):
    """Test a user guide with the same stem replaces the bundled one.

    Given:
        Bundled and user 'test/python' guides both exist.
    When:
        discover_guides is called.
    Then:
        The discovered path for ('test', 'python') is the user file.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "test-guides").mkdir(parents=True)
    (pkg / "test-guides" / "python.md").write_text("bundled")
    cwd = tmp_path / "proj"
    user_guides = cwd / ".sdlc" / "guides" / "test"
    user_guides.mkdir(parents=True)
    (user_guides / "python.md").write_text("user")
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert result[("test", "python")].read_text() == "user"


def test_discover_guides_should_resolve_guides_dir_relative_to_config_dir(tmp_path):
    """Test guides-dir is resolved relative to user_config_dir, not cwd.

    Given:
        Config provides guides-dir='guides' and is loaded from custom_dir.
    When:
        discover_guides is called with user_config_dir=custom_dir.
    Then:
        Guides at custom_dir/guides/test/ are discovered.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    cwd = tmp_path / "proj"
    cwd.mkdir()
    custom = tmp_path / "custom"
    guides_dir = custom / "guides" / "test"
    guides_dir.mkdir(parents=True)
    (guides_dir / "python.md").write_text("custom location")
    config = {"guides-dir": "guides", "guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, custom)

    # Assert
    assert result[("test", "python")].read_text() == "custom location"


def test_discover_guides_should_warn_when_guides_dir_missing(tmp_path, recwarn):
    """Test a missing configured guides-dir surfaces a warning.

    Given:
        Config provides guides-dir pointing to a nonexistent directory.
    When:
        discover_guides is called.
    Then:
        A warning is emitted naming the missing path.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    cwd = tmp_path / "proj"
    cwd.mkdir()
    config = {"guides-dir": "nope", "guide-map": {}}

    # Act
    discover_guides(config, pkg, cwd, cwd)

    # Assert
    assert any("nope" in str(w.message) for w in recwarn)


def test_discover_guides_should_find_bundled_role_when_role_guides_present(tmp_path):
    """Test bundled role guides are discovered under role-guides/.

    Given:
        A package dir with role-guides/general-purpose.md and no user dir.
    When:
        discover_guides is called.
    Then:
        The bundled role is discovered as ('role', 'general-purpose').
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "role-guides").mkdir(parents=True)
    (pkg / "role-guides" / "general-purpose.md").write_text("# Role")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert result[("role", "general-purpose")] == (
        pkg / "role-guides" / "general-purpose.md"
    )


def test_discover_guides_should_find_bundled_aie_role_when_role_guides_present(tmp_path):
    """Test the bundled aie role is discovered alongside general-purpose.

    Given:
        A package dir bundling both role-guides/general-purpose.md and
        role-guides/aie.md, and no user dir.
    When:
        discover_guides is called.
    Then:
        Both ('role', 'general-purpose') and ('role', 'aie') are discovered.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "role-guides").mkdir(parents=True)
    (pkg / "role-guides" / "general-purpose.md").write_text("# GP")
    (pkg / "role-guides" / "aie.md").write_text("# AIE")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert result[("role", "general-purpose")] == (
        pkg / "role-guides" / "general-purpose.md"
    )
    assert result[("role", "aie")] == pkg / "role-guides" / "aie.md"


def test_discover_guides_should_merge_user_role_at_convention_path(tmp_path):
    """Test user role guides at .sdlc/guides/role/ are discovered.

    Given:
        A bundled role and a user role at .sdlc/guides/role/architect.md.
    When:
        discover_guides is called with no user_config_dir.
    Then:
        Both the bundled and user roles are present.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "role-guides").mkdir(parents=True)
    (pkg / "role-guides" / "general-purpose.md").write_text("# GP")
    cwd = tmp_path / "proj"
    (cwd / ".sdlc" / "guides" / "role").mkdir(parents=True)
    (cwd / ".sdlc" / "guides" / "role" / "architect.md").write_text("# Arch")
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert ("role", "general-purpose") in result
    assert ("role", "architect") in result


def test_discover_guides_should_prefer_user_role_when_stems_collide(tmp_path):
    """Test a user role with the same stem replaces the bundled one.

    Given:
        Bundled and user 'role/general-purpose' guides both exist.
    When:
        discover_guides is called.
    Then:
        The discovered path for ('role', 'general-purpose') is the user file.
    """
    # Arrange
    pkg = tmp_path / "pkg"
    (pkg / "role-guides").mkdir(parents=True)
    (pkg / "role-guides" / "general-purpose.md").write_text("bundled")
    cwd = tmp_path / "proj"
    user_roles = cwd / ".sdlc" / "guides" / "role"
    user_roles.mkdir(parents=True)
    (user_roles / "general-purpose.md").write_text("user")
    config = {"guide-map": {}}

    # Act
    result = discover_guides(config, pkg, cwd, None)

    # Assert
    assert result[("role", "general-purpose")].read_text() == "user"


def test_resolve_guides_should_return_stems_when_single_pattern_matches(tmp_path):
    """Test a single matching pattern returns its mapped stems.

    Given:
        A guide-map mapping '**/*.py' to ['python'] and one matching path.
    When:
        resolve_guides is called.
    Then:
        ['python'] is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": ["python"]}}
    discovered = {("test", "python"): tmp_path / "x.md"}

    # Act
    result = resolve_guides(["foo.py"], "test", guide_map, discovered)

    # Assert
    assert result == ["python"]


def test_resolve_guides_should_union_stems_when_multiple_patterns_match(tmp_path):
    """Test multiple matching patterns union their stems with no duplicates.

    Given:
        Two patterns both match 'tests/foo.py' with overlapping stems.
    When:
        resolve_guides is called.
    Then:
        The de-duplicated union of stems is returned.
    """
    # Arrange
    guide_map = {
        "test": {
            "**/*.py": ["python"],
            "tests/**/*.py": ["python", "pytest"],
        }
    }
    discovered = {
        ("test", "python"): tmp_path / "p.md",
        ("test", "pytest"): tmp_path / "pt.md",
    }

    # Act
    result = resolve_guides(["tests/foo.py"], "test", guide_map, discovered)

    # Assert
    assert sorted(result) == ["pytest", "python"]


def test_resolve_guides_should_return_empty_when_no_pattern_matches(tmp_path):
    """Test no matching pattern yields an empty list.

    Given:
        A guide-map for Python files and a non-Python path.
    When:
        resolve_guides is called.
    Then:
        An empty list is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": ["python"]}}
    discovered = {("test", "python"): tmp_path / "p.md"}

    # Act
    result = resolve_guides(["README.md"], "test", guide_map, discovered)

    # Assert
    assert result == []


def test_resolve_guides_should_skip_undiscovered_stems(tmp_path):
    """Test stems referenced in the map but missing from discovered are skipped.

    Given:
        A pattern maps to ['python', 'ghost'] but only 'python' is discovered.
    When:
        resolve_guides is called.
    Then:
        Only 'python' is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": ["python", "ghost"]}}
    discovered = {("test", "python"): tmp_path / "p.md"}

    # Act
    result = resolve_guides(["foo.py"], "test", guide_map, discovered)

    # Assert
    assert result == ["python"]


def test_resolve_guides_should_match_extensionless_filenames(tmp_path):
    """Test patterns can match files without extensions.

    Given:
        A pattern 'Dockerfile' and a path 'Dockerfile'.
    When:
        resolve_guides is called.
    Then:
        The mapped stem is returned.
    """
    # Arrange
    guide_map = {"style": {"Dockerfile": ["docker"]}}
    discovered = {("style", "docker"): tmp_path / "d.md"}

    # Act
    result = resolve_guides(["Dockerfile"], "style", guide_map, discovered)

    # Assert
    assert result == ["docker"]


def test_resolve_guides_should_scope_matches_to_directory_patterns(tmp_path):
    """Test directory-scoped patterns match only paths under that directory.

    Given:
        A pattern 'tests/**/*.py' and both an in-tests and out-of-tests path.
    When:
        resolve_guides is called for each path separately.
    Then:
        Only the in-tests path resolves to the stem.
    """
    # Arrange
    guide_map = {"test": {"tests/**/*.py": ["pytest"]}}
    discovered = {("test", "pytest"): tmp_path / "p.md"}

    # Act
    in_tests = resolve_guides(["tests/foo.py"], "test", guide_map, discovered)
    out_of_tests = resolve_guides(["src/foo.py"], "test", guide_map, discovered)

    # Assert
    assert in_tests == ["pytest"]
    assert out_of_tests == []


def test_resolve_guides_should_return_empty_when_kind_unknown(tmp_path):
    """Test querying an unknown kind yields an empty list.

    Given:
        A guide-map with only 'test' and a query for 'style'.
    When:
        resolve_guides is called with kind='style'.
    Then:
        An empty list is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": ["python"]}}
    discovered = {("test", "python"): tmp_path / "p.md"}

    # Act
    result = resolve_guides(["foo.py"], "style", guide_map, discovered)

    # Assert
    assert result == []


def test_resolve_guides_should_return_empty_when_stems_list_empty(tmp_path):
    """Test a pattern mapped to [] yields no stems even on match.

    Given:
        A pattern '**/*.py' mapped to [] (disabled by user).
    When:
        resolve_guides is called for a Python path.
    Then:
        An empty list is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": []}}
    discovered = {("test", "python"): tmp_path / "p.md"}

    # Act
    result = resolve_guides(["foo.py"], "test", guide_map, discovered)

    # Assert
    assert result == []


def test_resolve_guides_should_union_matches_across_multiple_paths(tmp_path):
    """Test the path argument is treated as a union — any matching path counts.

    Given:
        A guide-map where 'tests/**/*.py' adds a stem and the input includes
        both src/foo.py and tests/bar.py.
    When:
        resolve_guides is called with both paths.
    Then:
        The union covers stems from both '**/*.py' and 'tests/**/*.py'.
    """
    # Arrange
    guide_map = {
        "test": {
            "**/*.py": ["python"],
            "tests/**/*.py": ["pytest"],
        }
    }
    discovered = {
        ("test", "python"): tmp_path / "p.md",
        ("test", "pytest"): tmp_path / "pt.md",
    }

    # Act
    result = resolve_guides(
        ["src/foo.py", "tests/bar.py"], "test", guide_map, discovered
    )

    # Assert
    assert sorted(result) == ["pytest", "python"]


def test_read_guide_should_return_file_content_when_stem_known(tmp_path):
    """Test a discovered guide returns its file content.

    Given:
        A discovered guide path with known content.
    When:
        read_guide is called for that (kind, stem).
    Then:
        The file content is returned.
    """
    # Arrange
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("# Hello")
    discovered = {("test", "python"): guide_path}

    # Act
    result = read_guide("test", "python", discovered)

    # Assert
    assert result == "# Hello"


def test_read_guide_should_return_error_when_stem_unknown():
    """Test an unknown (kind, stem) returns an error message.

    Given:
        An empty discovered map.
    When:
        read_guide is called for a stem not present.
    Then:
        An error message mentioning the stem is returned.
    """
    # Act
    result = read_guide("test", "missing", {})

    # Assert
    assert "missing" in result
    assert "not found" in result.lower()


def test_list_roles_should_return_sorted_role_stems(tmp_path):
    """Test list_roles returns only role stems, sorted, ignoring other kinds.

    Given:
        A discovered map with several role stems plus test and style entries.
    When:
        list_roles is called.
    Then:
        Only the role stems are returned, in sorted order.
    """
    # Arrange
    discovered = {
        ("role", "security"): tmp_path / "s.md",
        ("role", "architect"): tmp_path / "a.md",
        ("test", "python"): tmp_path / "p.md",
        ("style", "markdown"): tmp_path / "m.md",
    }

    # Act
    result = list_roles(discovered)

    # Assert
    assert result == ["architect", "security"]


def test_list_roles_should_return_empty_when_no_roles(tmp_path):
    """Test list_roles returns an empty list when no role guides are discovered.

    Given:
        A discovered map containing only test and style guides.
    When:
        list_roles is called.
    Then:
        An empty list is returned.
    """
    # Arrange
    discovered = {
        ("test", "python"): tmp_path / "p.md",
        ("style", "markdown"): tmp_path / "m.md",
    }

    # Act
    result = list_roles(discovered)

    # Assert
    assert result == []


def test_globs_for_role_should_return_patterns_mapped_to_role():
    """Test the reverse lookup returns every glob mapped to the role.

    Given:
        A guide-map.role mapping two globs to 'architect'.
    When:
        globs_for_role('architect', guide_map) is called.
    Then:
        Both globs are returned in map order.
    """
    # Arrange
    guide_map = {
        "role": {
            "src/**/*.py": ["architect"],
            "lib/**/*.py": ["architect"],
        }
    }

    # Act
    result = globs_for_role("architect", guide_map)

    # Assert
    assert result == ["src/**/*.py", "lib/**/*.py"]


def test_globs_for_role_should_return_only_patterns_listing_the_role():
    """Test the reverse lookup ignores globs that do not list the role.

    Given:
        A guide-map.role where one glob lists 'architect' and another lists
        only 'security'.
    When:
        globs_for_role('architect', guide_map) is called.
    Then:
        Only the glob that lists 'architect' is returned.
    """
    # Arrange
    guide_map = {
        "role": {
            "src/**/*.py": ["architect"],
            "tests/**/*.py": ["security"],
        }
    }

    # Act
    result = globs_for_role("architect", guide_map)

    # Assert
    assert result == ["src/**/*.py"]


def test_globs_for_role_should_match_role_among_multiple_stems():
    """Test the reverse lookup matches a role sharing a glob with other roles.

    Given:
        A glob mapped to a list containing 'architect' alongside another role.
    When:
        globs_for_role('architect', guide_map) is called.
    Then:
        The shared glob is returned.
    """
    # Arrange
    guide_map = {"role": {"src/**/*.py": ["architect", "security"]}}

    # Act
    result = globs_for_role("architect", guide_map)

    # Assert
    assert result == ["src/**/*.py"]


def test_globs_for_role_should_return_empty_when_role_unmapped():
    """Test the reverse lookup returns an empty list for an unmapped role.

    Given:
        A guide-map.role with no glob listing the requested role.
    When:
        globs_for_role('ghost', guide_map) is called.
    Then:
        An empty list is returned.
    """
    # Arrange
    guide_map = {"role": {"src/**/*.py": ["architect"]}}

    # Act
    result = globs_for_role("ghost", guide_map)

    # Assert
    assert result == []


def test_globs_for_role_should_return_empty_when_role_namespace_absent():
    """Test the reverse lookup returns an empty list when no role namespace exists.

    Given:
        A guide-map with only test and style namespaces.
    When:
        globs_for_role('architect', guide_map) is called.
    Then:
        An empty list is returned.
    """
    # Arrange
    guide_map = {"test": {"**/*.py": ["python"]}}

    # Act
    result = globs_for_role("architect", guide_map)

    # Assert
    assert result == []


def test_globs_for_role_should_return_whole_diff_glob_for_general_purpose():
    """Test the bundled general-purpose role maps to the whole-diff glob.

    Given:
        The shipped default config's guide-map.
    When:
        globs_for_role('general-purpose', guide_map) is called for the default map.
    Then:
        The '**/*' whole-diff glob is returned.
    """
    # Arrange
    guide_map = load_package_default()["guide-map"]

    # Act
    result = globs_for_role("general-purpose", guide_map)

    # Assert
    assert result == ["**/*"]


def test_files_for_role_should_return_paths_matching_the_role_globs():
    """Test the scope lookup returns only paths matching the role's globs.

    Given:
        A guide-map.role mapping 'src/**/*.py' to 'architect' and a mix of
        in-scope and out-of-scope paths.
    When:
        files_for_role(paths, 'architect', guide_map) is called.
    Then:
        Only the paths under src/ that match the glob are returned.
    """
    # Arrange
    guide_map = {"role": {"src/**/*.py": ["architect"]}}
    paths = ["src/foo.py", "tests/bar.py", "README.md"]

    # Act
    result = files_for_role(paths, "architect", guide_map)

    # Assert
    assert result == ["src/foo.py"]


def test_files_for_role_should_union_matches_across_multiple_globs():
    """Test the scope lookup unions matches from every glob mapped to the role.

    Given:
        Two globs both mapped to 'architect' and paths matching each.
    When:
        files_for_role(paths, 'architect', guide_map) is called.
    Then:
        Paths matching either glob are returned, in input order.
    """
    # Arrange
    guide_map = {
        "role": {
            "src/**/*.py": ["architect"],
            "lib/**/*.py": ["architect"],
        }
    }
    paths = ["src/foo.py", "lib/bar.py", "docs/x.md"]

    # Act
    result = files_for_role(paths, "architect", guide_map)

    # Assert
    assert result == ["src/foo.py", "lib/bar.py"]


def test_files_for_role_should_preserve_input_order_and_dedupe():
    """Test the scope lookup preserves input order and drops duplicate paths.

    Given:
        An input list containing a duplicate in-scope path.
    When:
        files_for_role(paths, 'architect', guide_map) is called.
    Then:
        The path appears once, in its first-seen position.
    """
    # Arrange
    guide_map = {"role": {"src/**/*.py": ["architect"]}}
    paths = ["src/b.py", "src/a.py", "src/b.py"]

    # Act
    result = files_for_role(paths, "architect", guide_map)

    # Assert
    assert result == ["src/b.py", "src/a.py"]


def test_files_for_role_should_return_empty_when_role_unmapped():
    """Test the scope lookup returns an empty list for a role with no globs.

    Given:
        A guide-map.role with no glob listing the requested role.
    When:
        files_for_role(paths, 'ghost', guide_map) is called.
    Then:
        An empty list is returned even though paths are supplied.
    """
    # Arrange
    guide_map = {"role": {"src/**/*.py": ["architect"]}}
    paths = ["src/foo.py", "tests/bar.py"]

    # Act
    result = files_for_role(paths, "ghost", guide_map)

    # Assert
    assert result == []


def test_files_for_role_should_return_all_paths_for_general_purpose():
    """Test the general-purpose role scopes the whole diff via its '**/*' glob.

    Given:
        The shipped default config's guide-map and arbitrary changed paths.
    When:
        files_for_role(paths, 'general-purpose', guide_map) is called.
    Then:
        Every input path is returned, since '**/*' matches the whole diff.
    """
    # Arrange
    guide_map = load_package_default()["guide-map"]
    paths = ["src/foo.py", "README.md", "Dockerfile"]

    # Act
    result = files_for_role(paths, "general-purpose", guide_map)

    # Assert
    assert result == paths


def test_load_state_should_use_package_default_when_no_user_config(tmp_path, monkeypatch):
    """Test load_state with no user config falls back to the package default map.

    Given:
        A working directory with no .sdlc/config.json and no SDLC_CONFIG.
    When:
        load_state is called.
    Then:
        The state's guide_map mirrors the shipped default.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)

    # Act
    state = load_state(cwd=tmp_path)

    # Assert
    assert state.guide_map["test"]["**/*.py"] == ["python"]
    assert state.guide_map["style"]["**/*.md"] == ["markdown"]


def test_load_state_should_merge_user_config_into_default(tmp_path, monkeypatch):
    """Test load_state merges user config on top of package default.

    Given:
        A user .sdlc/config.json adding a tests/**/*.py pattern.
    When:
        load_state is called.
    Then:
        Both the default '**/*.py' and the user's 'tests/**/*.py' are present.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    sdlc_dir = tmp_path / ".sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "config.json").write_text(
        json.dumps(
            {"guide-map": {"test": {"tests/**/*.py": ["pytest-patterns"]}}}
        )
    )

    # Act
    state = load_state(cwd=tmp_path)

    # Assert
    assert state.guide_map["test"]["**/*.py"] == ["python"]
    assert state.guide_map["test"]["tests/**/*.py"] == ["pytest-patterns"]


def test_load_state_should_discover_bundled_guides(tmp_path, monkeypatch):
    """Test the state's discovered map includes the package-bundled guides.

    Given:
        A clean working directory with no user guides.
    When:
        load_state is called.
    Then:
        Bundled python and markdown guides are present in discovered.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)

    # Act
    state = load_state(cwd=tmp_path)

    # Assert
    assert ("test", "python") in state.discovered
    assert ("style", "markdown") in state.discovered


def test_load_state_should_discover_bundled_general_purpose_role(tmp_path, monkeypatch):
    """Test the state's discovered map includes the bundled general-purpose role.

    Given:
        A clean working directory with no user guides.
    When:
        load_state is called.
    Then:
        The bundled ('role', 'general-purpose') guide is present in discovered.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)

    # Act
    state = load_state(cwd=tmp_path)

    # Assert
    assert ("role", "general-purpose") in state.discovered


def test_load_state_should_discover_bundled_aie_role(tmp_path, monkeypatch):
    """Test the state's discovered map includes the bundled aie role.

    Given:
        A clean working directory with no user guides.
    When:
        load_state is called.
    Then:
        The bundled ('role', 'aie') guide is present in discovered, alongside
        ('role', 'general-purpose').
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)

    # Act
    state = load_state(cwd=tmp_path)

    # Assert
    assert ("role", "aie") in state.discovered
    assert ("role", "general-purpose") in state.discovered


def test_load_state_should_honor_custom_package_dir(tmp_path, monkeypatch):
    """Test load_state uses the provided package_dir for defaults and bundled guides.

    Given:
        A custom package directory with its own config.json and bundled guide.
    When:
        load_state is called with package_dir pointing to the custom directory.
    Then:
        The returned state reflects the custom package's config and discovered
        guides rather than the installed package's.
    """
    # Arrange
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    custom_pkg = tmp_path / "custom_pkg"
    custom_pkg.mkdir()
    (custom_pkg / "config.json").write_text(
        json.dumps({"guide-map": {"test": {"**/*.rs": ["rust"]}}})
    )
    (custom_pkg / "test-guides").mkdir()
    (custom_pkg / "test-guides" / "rust.md").write_text("# Rust guide")

    # Act
    state = load_state(cwd=tmp_path, package_dir=custom_pkg)

    # Assert
    assert state.guide_map == {"test": {"**/*.rs": ["rust"]}}
    assert ("test", "rust") in state.discovered
    assert ("test", "python") not in state.discovered
