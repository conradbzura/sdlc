# Python Test Guide

Key words MUST, MUST NOT, SHOULD, and SHOULD NOT are interpreted as described in RFC 2119. This guide covers Python testing conventions using pytest, pytest-mock, and Hypothesis.

The guide is organised in three parts: **Core Principles** (apply to all tests), **Unit Testing** (unit-test specifics), and **Integration Testing** (integration-test specifics). See [Appendix A](#appendix-a-async-unit-testing) and [Appendix B](#appendix-b-async-integration-testing) for async-specific additions.

## Core Principles

### 1. Philosophy

Test behavior, not implementation.

### 2. Test Independence

- Tests MUST be independent. Each test sets up its own preconditions.
- When a foundation behavior breaks, many tests fail. The blast radius IS the information — it tells you which behaviors depend on the broken one.
- MUST use `pytest -x` (stop on first failure), `--maxfail=N`, or `-lf` (last failed) to manage noise.
- Dependency markers (`@pytest.mark.dependency`) MUST NOT be used in new tests.

### 3. Test Naming

Test methods mirror the qualified name of their subject:

```
test_<method_name>_<brief_scenario>
```

The scenario portion is derived from the Given and When — it describes the condition and action, not the expected outcome:

```
test_dispatch_with_stopping_service
test_to_protobuf_with_unpicklable_callable
test___init___outside_task_context
```

Rules:
- `<method_name>` MUST match the method's `__name__` exactly, including dunder prefixes (e.g., `test___init___...`).
- `<brief_scenario>` SHOULD be 2-5 words in snake_case.
- Do NOT encode the expected outcome in the name — that belongs in the `Then` section of the docstring.

### 4. Docstrings (Given-When-Then)

Scope: test functions and methods only — NOT fixtures or helpers.

**Standard test:**

```python
"""Test <summary of what is being tested>.

Given:
    <preconditions>
When:
    <action under test>
Then:
    It should <expected outcome>
"""
```

**Property-based test:**

Same format. The `Given` describes the generated input space, not a specific value:

```python
"""Test <property being verified>.

Given:
    <description of generated input domain>
When:
    <action under test>
Then:
    <invariant that must hold>
"""
```

Rules:
- First line MUST start with `Test` and describe what is being tested.
- Blank line after the first line.
- `Given:`, `When:`, `Then:` each on their own line, followed by a colon.
- Content under each section indented 4 spaces.
- Each section's content starts with a capital letter.
- `Then` content typically starts with "It should...".
- One `Given`/`When`/`Then` block per docstring (no bullet lists within).

### 5. Test Body (AAA)

Every test MUST use Arrange-Act-Assert phase comments. One behavior per test.

**Full 3-phase (default):**

```python
def test_<method>_<scenario>(self, ...):
    """..."""
    # Arrange
    <set up preconditions>

    # Act
    <call the method under test>

    # Assert
    <verify the outcome>
```

**Combined phases:**

When phases are inseparable, combine the comments:

*No arrangement needed:*

```python
# Act
result = SomeClass()

# Assert
assert result.field == expected
```

*Action and assertion are the same expression:*

```python
# Arrange
<set up preconditions>

# Act & assert
with pytest.raises(SomeError, match="expected message"):
    unit.method()
```

*Trivial one-liner:*

```python
# Arrange, act, & assert
with SomePool(size=3) as pool:
    assert pool is not None
```

The combined forms are acceptable but the full 3-phase form is preferred. When in doubt, use the full form.

### 6. Fixtures

- MUST use fixtures for shared setup that multiple tests need.
- Fixtures MUST NOT have Given-When-Then docstrings. Plain reST docstrings are fine.
- SHOULD prefer narrowest scope: function > class > module > session.

### 7. Property-Based Testing (Hypothesis)

Property-based testing is a peer of example-based testing, not an afterthought. Property tests live in the same class as example tests, grouped by the method they exercise.

MUST be used for:
- Invariants.
- Roundtrip/serialization.
- Edge-case discovery.
- Any function with a wide input domain.

Rules:
- MUST use `@given` with appropriate strategies.
- MUST use `@settings` to control `max_examples` and suppress health checks when justified.
- MUST have Given-When-Then docstrings on property tests (the `Given` describes the generated domain, not a specific value).

```python
@given(st.binary())
def test_roundtrip_with_arbitrary_payload(self, payload):
    """Test serialization roundtrip with arbitrary payloads.

    Given:
        Any binary payload.
    When:
        The payload is serialized and deserialized.
    Then:
        It should equal the original payload.
    """
    # Act
    result = deserialize(serialize(payload))

    # Assert
    assert result == payload
```

## Unit Testing

### 8. Coverage Scope

- MUST achieve 100% test coverage of all public APIs.
- MUST test ONLY public functions, methods, and classes (no underscore prefix).
- MUST NOT manipulate or validate any private/internal state.
- MUST NOT reference private functions/methods/variables in tests.
- Private functions SHOULD achieve coverage naturally through public API usage.

### 9. File and Class Organization

- MUST name test files `test_<module_name>.py` — mirroring the module under test.
- MUST name test classes `class Test<ClassName>:` where `<ClassName>` is the exact `__name__` of the class under test.
- MUST place tests for class methods in the corresponding test class.
- MUST place tests for module-level functions as module-level test functions.
- Tests MUST be grouped by the behavior they exercise, not by implementation detail. For example, property-based tests for a method live alongside example-based tests for the same method in the same class — do NOT create separate classes by test technique.
- MUST order tests from foundational to derived within a test class or module: test `__init__` before methods that require a constructed instance, and test simple methods before methods that compose them. This ensures `pytest -x` stops at the most fundamental failure first.

### 10. Idiomatic Testing

MUST test dunder methods idiomatically, MUST NOT call them directly:

- `__init__`/`__post_init__`: Test via class instantiation.
- `__enter__`/`__exit__`: Test via `with` statements.
- `__call__`: Test by calling the object as a function.
- Other dunder methods: Use their natural Python idiom.

### 11. Mocking

- MUST use the `mocker` fixture (pytest-mock), not `unittest.mock` directly.
- MUST mock at system boundaries only: external services, I/O, network.
- MUST NOT mock internal/private methods.
- MUST NOT mock the unit under test.
- SHOULD prefer `mocker.patch.object(module, "attr")` over `mocker.patch("dotted.string.path")`. Object-style patches let IDE AST indexing resolve mock targets, making references findable and rename-safe.

```python
# Preferred — IDE can resolve the target
import requests
from mypackage import some_module

mocker.patch.object(some_module, "SomeClass", return_value=mock)
mocker.patch.object(requests, "get", return_value=mock)

# Discouraged — opaque string, invisible to AST tooling
mocker.patch("mypackage.some_module.SomeClass", return_value=mock)
```

### 12. Verification Commands

```
pytest <path> -x
pytest <path> --maxfail=3
pytest <path> -lf
```

If your project uses a runner wrapper (e.g., `uv run`, `poetry run`), prefix accordingly — see project instructions.

## Integration Testing

Integration tests exercise real cross-boundary interactions — real subprocesses, real network I/O, real serialization — and MUST NOT mock the system under test. They complement unit tests by validating that assembled subsystems work together correctly.

### Marker

All integration tests MUST be marked with a dedicated marker (e.g., `@pytest.mark.integration`) to enable selective execution:

```sh
# Run only integration tests
pytest -m integration -x

# Run everything except integration tests
pytest -m "not integration" -x
```

The marker MUST be registered in `pyproject.toml` under `[tool.pytest.ini_options]`.

### Test Style

Integration tests follow the same conventions as unit tests: Given-When-Then docstrings on test functions and methods (not fixtures or helpers), and AAA phase comments.

### File Layout

Integration tests MUST live in a dedicated `tests/integration/` package:

```
tests/integration/
    __init__.py         (empty)
    conftest.py         (scenario model, enums, filter, builder, fixtures)
    routines.py         (functions exercised by integration tests)
    test_scenario.py    (unit tests for the Scenario model itself)
    test_composition.py (builder tests — one per major system mode)
    test_integration.py (pairwise parametrized + Hypothesis exploration)
```

### Routine Module

Test routines — functions exercised by integration tests — MUST live in a non-test module (e.g., `routines.py`, no `test_` prefix) so pytest does not collect them. This module defines all the callable targets that integration tests invoke through the real runtime. Organize routines by the dimensions they exercise (e.g., input format, output target, module function vs instance method vs classmethod vs staticmethod).

### Dimensions and Enums

Each orthogonal axis identified by the test skill (see `agents/skills/test.md` section 6) becomes a separate `Enum`:

```python
class InputFormat(Enum):
    JSON = auto()
    CSV = auto()
    # ...

class ProcessingMode(Enum):
    BATCH = auto()
    STREAMING = auto()
    # ...
```

### Composable Scenario Model

MUST model each scenario as a frozen dataclass with one field per dimension, all defaulting to `None`. MUST implement `__or__` for algebraic merge (right side wins on `None` fields, raises `ValueError` on conflicting non-`None` values), `is_complete` to check all fields are set, and `__str__` returning dash-separated enum member names for pytest IDs:

```python
@dataclass(frozen=True)
class Scenario:
    input_format: InputFormat | None = None
    processing_mode: ProcessingMode | None = None
    # ...

    def __or__(self, other: Scenario) -> Scenario:
        """Merge two partial scenarios; raise on conflicts."""

    @property
    def is_complete(self) -> bool:
        """True when all dimensions are set."""
```

MUST write unit tests for the Scenario model itself (`__or__` with disjoint fields, conflicting fields, identical values, empty merge, completeness checks). These are fast, synchronous tests that validate the test infrastructure before trusting it for real integration tests.

### Filter Function

A `filter_func` encodes cross-dimension constraints — combinations that are structurally invalid and MUST be excluded from generation:

- **Structural constraints** — e.g., a streaming mode requires a persistent connection; batch mode does not.
- **Permanent exclusions** — combinations that are documented limitations (not bugs). These MUST be excluded in the filter with a comment referencing the issue or documentation.

Bugs expected to be fixed MUST NOT be filtered — use `xfail` instead (see below).

### Builder

MUST implement a builder — typically a context manager — that takes a complete `Scenario` and resolves each dimension to its concrete runtime value:

```python
@contextmanager
def build_from_scenario(scenario, shared_fixtures):
    """Resolve all dimensions and yield the running system."""
    assert scenario.is_complete
    # Resolve each dimension to concrete values...
    with system:
        yield system
```

Some modes may require special handling. For example, a mode that only connects to an already-running external process needs a helper that starts that process and registers it before creating the system under test.

MUST implement a separate `invoke` function that maps the scenario's callable shape and binding to the correct invocation protocol (call, iterate) and asserts the expected result.

MUST write builder tests — one per major mode — that construct a complete scenario, build the system, invoke a simple call, and assert the result. These validate that each mode works in isolation before combining them in the pairwise suite.

### Pairwise Covering Arrays

MUST use `allpairspy.AllPairs` with the `filter_func` to generate a deterministic covering array that exercises all pairwise dimension combinations:

```python
from allpairspy import AllPairs

PAIRWISE_SCENARIOS = [
    Scenario(input_format=row[0], processing_mode=row[1], ...)
    for row in AllPairs(
        [list(InputFormat), list(ProcessingMode), ...],
        filter_func=my_filter,
    )
]
```

MUST parametrize with `@pytest.mark.parametrize("scenario", PAIRWISE_SCENARIOS, ids=str)`.

### Hypothesis Exploration

MUST use `@st.composite` strategies that draw from per-dimension `st.sampled_from(Enum)` with conditional filtering matching the `filter_func` logic. MUST apply the same permanent exclusions as the filter. MUST decorate tests with:

```python
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
    ],
)
@example(scenario=Scenario(...))  # Smoke test with known-good config
@given(scenario=scenarios_strategy())
```

`deadline=None` prevents false positives from subprocess startup latency or slow I/O. `HealthCheck.too_slow` suppresses the health check that fires when data generation is slow.

### xfail for Known Bugs

Scenarios that hit known bugs MUST be registered in a `_KnownBug` data structure and handled by an `xfail_known_bugs` fixture (not `skip`, not filtered out). Each entry defines a `match` predicate, a `raises` tuple constraining the expected failure mode, a `reason` referencing the issue, and optional `retries` with a `retryable` predicate for transient errors:

```python
@dataclass(frozen=True)
class _KnownBug:
    match: Callable[[Scenario], bool]
    raises: tuple[type[BaseException], ...]
    reason: str
    retries: int = 0
    backoff: float = 0.5
    retryable: Callable[[BaseException], bool] = lambda _: False

_KNOWN_BUGS: list[_KnownBug] = [
    _KnownBug(
        match=lambda s: s.processing_mode == ProcessingMode.STREAMING,
        raises=(ConnectionError, TimeoutError),
        reason="streaming mode connection instability under load (#123)",
        retries=3,
        retryable=lambda e: isinstance(e, ConnectionError),
    ),
]
```

The fixture wraps the test body, catches matching exceptions, retries transient ones with exponential backoff, and calls `pytest.xfail()` when retries are exhausted or the error is non-retryable. Unmatched exceptions propagate as real failures. MUST use the fixture as a callable in tests:

```python
def test_dispatch(scenario, xfail_known_bugs):
    def body():
        ...
    xfail_known_bugs(scenario, body)
```

The distinction from permanent filter exclusions: filtered combinations are documented limitations that will not be fixed. `xfail` combinations are bugs with open issues that will eventually pass.

### Cleanup

Autouse fixtures MUST clear shared state between tests — connection pools, context variables, cached singletons, temporary files. These fixtures MUST live in the integration `conftest.py` and MUST mirror any equivalent cleanup fixtures from the unit test suite to prevent cross-test contamination.

### Three Test Layers

Integration test files SHOULD follow this progression:

1. **Scenario model unit tests** — fast, synchronous tests for `__or__`, `is_complete`, `__str__`. Validate the test infrastructure itself.
2. **Builder/composition tests** — one test per major system mode. Validate that each mode works in isolation before combining.
3. **Pairwise + Hypothesis** — combinatorial tests covering all pairwise dimension interactions and random exploration. These are the main integration tests.

---

## Appendix A: Async Unit Testing

MUST use `pytest-asyncio` with `@pytest.mark.asyncio` for async test functions. MUST use async mocks via `mocker.AsyncMock()`.

```python
@pytest.mark.asyncio
async def test_fetch_data_with_valid_endpoint(self, mocker):
    """..."""
    # Arrange
    mock_response = mocker.AsyncMock(return_value={"key": "value"})
    mocker.patch.object(http_client, "get", mock_response)

    # Act
    result = await unit.fetch_data("/endpoint")

    # Assert
    assert result == {"key": "value"}
```

## Appendix B: Async Integration Testing

Apply these additions on top of the Integration Testing section when integration tests exercise async code.

### Test Style

MUST add `@pytest.mark.asyncio` to async integration test functions.

### Dimensions

Async routines introduce additional shape dimensions. MUST add enum members for each async callable form your system supports:

```python
class RoutineShape(Enum):
    FUNCTION = auto()     # plain callable
    COROUTINE = auto()    # async def
    ASYNC_GEN = auto()    # async def generator
    # ...
```

### Builder

MUST replace the `@contextmanager` builder from the Integration Testing section with an async context manager:

```python
@asynccontextmanager
async def build_from_scenario(scenario, shared_fixtures):
    """Resolve all dimensions and yield the running system."""
    assert scenario.is_complete
    # Resolve each dimension to concrete values...
    async with system:
        yield system
```

### Invoke

MUST map the scenario's callable shape to the correct async invocation protocol:

- `await fn()` for coroutines
- `async for item in fn()` for async generators
- `.asend()`, `.athrow()`, `.aclose()` for async generator protocol control

### Hypothesis Suppressions

MUST add `HealthCheck.function_scoped_fixture` to `suppress_health_check` when using function-scoped async fixtures alongside Hypothesis — they don't compose cleanly and this health check fires spuriously:

```python
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
```

### xfail for Async Known Bugs

The `xfail_known_bugs` fixture MUST be async, and tests MUST use it with `await`:

```python
_KNOWN_BUGS: list[_KnownBug] = [
    _KnownBug(
        match=lambda s: s.shape in _NESTED_SHAPES,
        raises=(grpc.RpcError, TimeoutError),
        reason="grpcio race condition (#41483)",
        retries=3,
        retryable=lambda e: (
            isinstance(e, grpc.RpcError)
            and e.code() == grpc.StatusCode.INTERNAL
        ),
    ),
]

async def test_dispatch(scenario, xfail_known_bugs):
    async def body():
        ...
    await xfail_known_bugs(scenario, body)
```

### Cleanup

Autouse cleanup fixtures that tear down async resources MUST be async:

```python
@pytest.fixture(autouse=True)
async def cleanup_async_resources():
    yield
    await pool.aclose()
```
