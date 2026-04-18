"""Tests for sdlc.guides — config loading, merging, discovery, and resolution."""

import json

import pytest

from sdlc.guides import (
    discover_guides,
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
        It should return a dict with kebab-case 'guide-map' covering test and style.
    """
    # Act
    result = load_package_default()

    # Assert
    assert "guide-map" in result
    assert result["guide-map"]["test"]["**/*.py"] == ["python"]
    assert result["guide-map"]["style"]["**/*.md"] == ["markdown"]


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
