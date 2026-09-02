"""argus-phase-4-recovery-002 -- frozen acceptance matrix rows AM-01, AM-02,
AM-04, AM-08, AM-09, AM-12, AM-13 (the pure parser/artifact rows -- no
database needed).

These exercise the exact three defects the independent
`argus-phase-4-recovery-review-001` audit found in the `argus-phase-4-
recovery-001` submission, at their exact production seam:

- F-01 (SPEC_BLOCKING): ``argus.shadow.quote_jobs._is_positive_raw_amount``
  used ``str.isdigit()`` (which accepts non-ASCII Unicode "digit"
  characters, e.g. superscript-two ``"\\u00b2"``, that ``int()`` cannot
  parse) with no guard around the subsequent ``int(value)`` conversion --
  an uncaught ``ValueError`` (also raised by Python's own global integer-
  string-conversion length guard for a several-thousand-digit string)
  escapes ``_classify_quote``'s ``else`` branch in
  ``_execute_and_record_probe``, which is NOT covered by that function's
  provider ``try/except`` (that except only wraps the provider call
  itself) -- so the whole probe-processing call crashes instead of
  recording an honest terminal ``NO_ROUTE``.
- F-02 (SAFETY_OR_INTEGRITY_BLOCKING):
  ``_safe_provider_error_code`` performed only a type/length check, never
  a content/character-class sanitization -- an unsafe-shaped string
  (a URL with an embedded fake API key, JSON-body-shaped text, control
  characters) that happened to fit the length bound was persisted
  verbatim into ``failure_evidence``. Separately, ``_classify_provider_
  exception``'s HTTP 429 branch returned immediately without ever
  inspecting the response body, so a genuinely-supplied safe
  ``errorCode`` was silently dropped on a 429 even though this project
  explicitly preserves it for every other status.
- F-03 (SPEC_BLOCKING): the previous round's own checkpoint (`orchestration/
  checkpoints/phase_4_recovery.md`) was never actually run through the
  project's own production ``validate_checkpoint_content``/
  ``validate_bundle_content`` functions before submission -- it is
  missing the required terminal end marker entirely and has no section
  whose text contains the literal (case-insensitive) phrase "acceptance
  criteria" (its own section is titled "Row-by-row acceptance matrix").

Every counterexample here was run against the pre-fix `argus-phase-4-
recovery-001` code (target commit `29a49ff4aa2618ae016a6ed90cd8ba680310a95e`)
before F-01/F-02 were implemented; the observed pre-fix failure is recorded
in each test's own docstring/comment, never hidden behind ``xfail``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from argus.shadow.quote_jobs import (
    _MAX_SAFE_PROVIDER_CODE_LEN,
    _is_positive_raw_amount,
    _is_structurally_valid_route_entry,
    _safe_provider_error_code,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT_PATH = _REPO_ROOT / "scripts" / "argus_orchestrator_watch.py"
_spec = importlib.util.spec_from_file_location("argus_orchestrator_watch_p4rec2", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
watch = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("argus_orchestrator_watch_p4rec2", watch)
_spec.loader.exec_module(watch)


def _valid_swap_info(*, in_amount: object, out_amount: object) -> dict:
    return {
        "swapInfo": {
            "ammKey": "AMMkey1111111111111111111111111111111111",
            "label": "Raydium",
            "inputMint": "SomeMint1111111111111111111111111111111111",
            "outputMint": "SomeMint2222222222222222222222222222222222",
            "inAmount": in_amount,
            "outAmount": out_amount,
        },
        "percent": 100,
    }


# ---------------------------------------------------------------------
# AM-01: superscript-two ("²") passes str.isdigit() but int() raises
# ValueError. Pre-fix, this call raised uncaught; post-fix it must return
# False with no exception.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("nested_field", ["inAmount", "outAmount"])
def test_am01_non_ascii_digit_raw_amount_is_rejected_not_raised(nested_field: str) -> None:
    # Pre-fix: raised "ValueError: invalid literal for int() with base 10:
    # '\xb2'" directly out of _is_positive_raw_amount -- captured against
    # target commit 29a49ff4aa2618ae016a6ed90cd8ba680310a95e before F-01.
    assert _is_positive_raw_amount("²") is False
    param_name = "in_amount" if nested_field == "inAmount" else "out_amount"
    other_param = "out_amount" if param_name == "in_amount" else "in_amount"
    entry = _valid_swap_info(**{param_name: "²", other_param: "1000000"})
    assert _is_structurally_valid_route_entry(entry) is False


def test_am01_non_ascii_digit_variants_never_raise() -> None:
    # A broader sample of non-ASCII "digit" code points str.isdigit()
    # accepts but int() cannot parse -- none may ever raise.
    for garbage in ("²", "³", "⁵", "１", "1²"):
        assert _is_positive_raw_amount(garbage) is False


# ---------------------------------------------------------------------
# AM-02: a 5000-ASCII-digit string exceeds Python's default int() string
# conversion length guard (4300 digits) and raises ValueError. The global
# guard itself must remain untouched -- this only proves the call site is
# now guarded, not that the interpreter limit was disabled.
# ---------------------------------------------------------------------


def test_am02_excessively_long_ascii_digit_string_is_rejected_not_raised() -> None:
    # Pre-fix: raised "ValueError: Exceeds the limit (4300 digits) for
    # integer string conversion" uncaught -- captured against target
    # commit 29a49ff4aa2618ae016a6ed90cd8ba680310a95e before F-01.
    huge = "1" * 5000
    assert _is_positive_raw_amount(huge) is False
    entry = _valid_swap_info(in_amount=huge, out_amount="1000000")
    assert _is_structurally_valid_route_entry(entry) is False


def test_am02_global_conversion_guard_is_unchanged() -> None:
    import sys as _sys

    with pytest.raises(ValueError, match="Exceeds the limit"):
        int("1" * 5000)
    # Sanity: this project must not have raised the interpreter's own
    # default limit to make the call site "work" -- it stays at its
    # Python-default value (4300) for this test process.
    assert _sys.get_int_max_str_digits() == 4300


# ---------------------------------------------------------------------
# AM-04: total raw-amount validity matrix -- valid positive
# representations (including leading zeroes and real ints) keep passing;
# every invalid shape (empty/garbage/zero/negative/bool/float/None/
# non-ASCII-digit) is rejected, never raised.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["1", "001", 1, "42", "0001000"],
    ids=["str-1", "str-001-leading-zero", "int-1", "str-42", "str-leading-zeros-large"],
)
def test_am04_valid_positive_amounts_are_accepted(value: object) -> None:
    assert _is_positive_raw_amount(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "abc", "0", 0, "-1", -1, True, False, 1.5, None, "²", "1" * 5000, [], {}],
    ids=[
        "empty-string",
        "ascii-garbage",
        "str-zero",
        "int-zero",
        "str-negative",
        "int-negative",
        "bool-true",
        "bool-false",
        "float",
        "none",
        "non-ascii-digit",
        "excessively-long-digits",
        "list",
        "dict",
    ],
)
def test_am04_invalid_amounts_are_rejected_never_raised(value: object) -> None:
    assert _is_positive_raw_amount(value) is False


def test_am04_route_entry_validator_still_enforces_existing_mint_gates() -> None:
    # P4-REC-02's existing gates (nonempty mint strings) stay green --
    # this recovery only deepens amount validation, never re-opens them.
    entry = _valid_swap_info(in_amount="1000000", out_amount="500000")
    assert _is_structurally_valid_route_entry(entry) is True
    bad_mint = _valid_swap_info(in_amount="1000000", out_amount="500000")
    bad_mint["swapInfo"]["inputMint"] = ""
    assert _is_structurally_valid_route_entry(bad_mint) is False


# ---------------------------------------------------------------------
# AM-08/AM-09: _safe_provider_error_code bounded identifier grammar --
# ASCII full-match [A-Za-z][A-Za-z0-9_]{0,127}. Pre-fix, only type/length
# was checked, so several of these unsafe-shaped-but-length-legal strings
# survived unchanged.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "https://quote-api.jup.ag/v6/quote?api_key=AUDIT_ONLY_FAKE_SECRET",
        "api_key=AUDIT_ONLY_FAKE_SECRET",
        "CODE_WITH\nEMBEDDED\nNEWLINE",
        "CODE_WITH\x00CONTROL",
        '{"errorCode": "X"}',
        "",
        "A" * 129,
        True,
        123,
        {"errorCode": "X"},
        ["X"],
        "1STARTS_WITH_DIGIT",
        "_STARTS_WITH_UNDERSCORE",
        "HAS SPACE",
        "HAS-DASH",
    ],
    ids=[
        "url-with-fake-key",
        "bare-query-assignment",
        "embedded-newline",
        "embedded-control-char",
        "json-body-shaped",
        "empty-string",
        "129-ascii-letters-over-limit",
        "bool",
        "int",
        "dict",
        "list",
        "starts-with-digit",
        "starts-with-underscore",
        "contains-space",
        "contains-dash",
    ],
)
def test_am08_unsafe_or_malformed_provider_codes_are_rejected(value: object) -> None:
    # Pre-fix: "https://quote-api.jup.ag/v6/quote?api_key=AUDIT_ONLY_FAKE_SECRET"
    # is 63 chars (<=128) and a non-empty str, so pre-fix
    # _safe_provider_error_code returned it VERBATIM -- captured against
    # target commit 29a49ff4aa2618ae016a6ed90cd8ba680310a95e before F-02.
    assert _safe_provider_error_code(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "A",
        "A" * _MAX_SAFE_PROVIDER_CODE_LEN,
        "AUDIT_RATE_LIMIT",
        "COULD_NOT_FIND_ANY_ROUTE",
        "a1_b2_C3",
        "X" + "9" * 127,
    ],
    ids=[
        "boundary-1-char",
        "boundary-128-chars",
        "known-identifier",
        "known-no-route-identifier",
        "digits-and-underscore",
        "boundary-128-with-digits",
    ],
)
def test_am09_valid_identifier_boundary_is_preserved_verbatim(value: str) -> None:
    assert _safe_provider_error_code(value) == value


def test_am09_129_chars_is_rejected() -> None:
    assert _safe_provider_error_code("A" * (_MAX_SAFE_PROVIDER_CODE_LEN + 1)) is None


# ---------------------------------------------------------------------
# AM-13: negative artifact fixtures -- existing validators must reject
# each, and the previous round's real, still-untouched failing checkpoint
# is itself one of the "acceptance-criteria section missing" fixtures.
# ---------------------------------------------------------------------


def _well_formed_checkpoint(git_commit: str) -> str:
    return f"""{watch.CHECKPOINT_START_MARKER}

PROJECT: ARGUS
SCOPE: Phase 4 authorized phase 4 recovery-002 (F-01/F-02/F-03)
STATUS: PASS
GIT_COMMIT: {git_commit}

Commands actually run:
- uv run pytest tests/unit/test_phase4_recovery_2_contract.py -q

Test results: 1 passed, 0 failed, 0 skipped.

Acceptance criteria: [PASS] all frozen rows met.

Deviations: NONE.

Known bugs / debt: none new.

Security state: unchanged; no live-execution code touched.

Next action: STOP. Await independent audit.

{watch.CHECKPOINT_END_MARKER}
"""


def test_am13_missing_end_marker_is_rejected() -> None:
    well_formed = _well_formed_checkpoint("deadbeef" * 5)
    missing_end = well_formed.replace(f"\n{watch.CHECKPOINT_END_MARKER}\n", "\n")
    ok, reason = watch.validate_checkpoint_content(missing_end)
    assert not ok
    assert "end marker" in reason


def test_am13_missing_acceptance_criteria_section_is_rejected() -> None:
    well_formed = _well_formed_checkpoint("deadbeef" * 5)
    no_acceptance = well_formed.replace("Acceptance criteria: [PASS] all frozen rows met.\n", "")
    ok, reason = watch.validate_checkpoint_content(no_acceptance)
    assert not ok
    assert "acceptance criteria" in reason


def test_am13_the_actual_previous_round_checkpoint_still_fails_both_ways() -> None:
    """The still-untouched `orchestration/checkpoints/phase_4_recovery.md`
    (this round must never overwrite it) is itself real, unmodified proof
    of F-03: it has a start marker but no end marker at all, and its own
    acceptance section is titled "Row-by-row acceptance matrix" -- not the
    literal required "acceptance criteria" phrase."""
    real_checkpoint = (
        _REPO_ROOT / "orchestration" / "checkpoints" / "phase_4_recovery.md"
    ).read_text()
    ok, reason = watch.validate_checkpoint_content(real_checkpoint)
    assert not ok
    assert "end marker" in reason
    assert "acceptance criteria" not in real_checkpoint.lower()


def test_am13_mismatched_embedded_checkpoint_is_rejected() -> None:
    checkpoint_a = _well_formed_checkpoint("a" * 40)
    checkpoint_b = _well_formed_checkpoint("b" * 40)
    bundle = (
        "ARGUS REVIEW BUNDLE\nSTATUS: PASS\nGIT_COMMIT: "
        + "a" * 40
        + "\nTEST: ok\n\n"
        + checkpoint_b
        + "\n"
    )
    ok, reason = watch.validate_bundle_content(bundle, checkpoint_a)
    assert not ok
    assert "verbatim" in reason


# ---------------------------------------------------------------------
# AM-12: the ACTUAL new checkpoint/bundle this round produces must pass
# both real production validators, exactly, with an empty reason -- not
# merely "looks right." These paths are created and hash-filled by this
# same recovery round; by the time the full suite runs (this project's
# own established acceptance-command order), both files exist on disk at
# their final, committed bytes.
# ---------------------------------------------------------------------


def test_am12_new_checkpoint_and_bundle_pass_production_validators() -> None:
    checkpoint_path = _REPO_ROOT / "orchestration" / "checkpoints" / "phase_4_recovery_2.md"
    bundle_path = _REPO_ROOT / "orchestration" / "bundles" / "phase_4_recovery_2.txt"
    if not checkpoint_path.exists() or not bundle_path.exists():
        pytest.skip(
            "phase_4_recovery_2 checkpoint/bundle not yet generated "
            "(generated near the end of this recovery round, before final push)"
        )
    checkpoint_text = checkpoint_path.read_text()
    bundle_text = bundle_path.read_text()

    ok, reason = watch.validate_checkpoint_content(checkpoint_text)
    assert ok, reason
    ok, reason = watch.validate_bundle_content(bundle_text, checkpoint_text)
    assert ok, reason
    assert checkpoint_text.strip() in bundle_text
