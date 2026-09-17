"""The deployment as shipped, not as described.

Every claim the guide makes about these files is only true while the files say
so. These tests are what keeps the two from drifting apart.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from reim.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = REPO_ROOT / "deploy" / "docker-compose.prod.yml"
CADDYFILE = REPO_ROOT / "deploy" / "Caddyfile"
ENV_EXAMPLE = REPO_ROOT / "deploy" / ".env.prod.example"

#: ``${REIM_X:-value}`` — a variable an operator may set, with a fallback.
DEFAULTED = re.compile(r"^\$\{(REIM_[A-Z0-9_]+):-(.*)\}$")
#: ``${REIM_X:?message}`` — a variable an operator *must* set; compose refuses
#: to render the file at all when it is missing, so there is no default to pin.
REQUIRED = re.compile(r"^\$\{(REIM_[A-Z0-9_]+):\?(.*)\}$")
#: The shortest exclusion or pinning reason a reader could act on. Crude, and
#: deliberately so: no test can judge prose, but ``"TODO"`` is not a decision.
MIN_REASON = 40
#: ``REIM_X=`` at the start of a line in ``.env.prod.example``, commented or not.
ENV_EXAMPLE_ASSIGNMENT = re.compile(r"^#?\s*(REIM_[A-Z0-9_]+)=", re.MULTILINE)

#: Fields of ``Settings`` given no path through ``docker-compose.prod.yml`` at
#: all, each with the reason it is not an operator's to set.
#:
#: This mapping is half of a partition, not a note: every field of ``Settings``
#: is either reachable from the api service's environment block or named here,
#: and ``test_every_setting_is_wired_or_deliberately_excluded`` fails on any
#: field that is neither. That is what stops the gap this file already caught
#: three times — the rate limits, then the alert settings, then
#: ``max_export_rows``, each shipped unreachable and each found only because
#: somebody happened to look — from happening a fourth time when the next field
#: is added to ``reim/core/config.py``.
#:
#: Adding a field means deciding, here, whether an operator of a public
#: deployment would reach for it. Wire it, or write down why not.
EXCLUDED_FROM_COMPOSE: dict[str, str] = {
    "database_echo": (
        "Logs every SQL statement. A development affordance: in production it "
        "floods the log and can put query parameters into it."
    ),
    "http_user_agent": (
        "Identifies the software to the data providers we fetch from, not the "
        "deployment, and already carries a project URL so they can attribute "
        "our traffic. Letting each deployment rewrite it defeats the field."
    ),
    "catalog_path": (
        "A path to a file baked into the image (sources/catalog.yml). Set from "
        ".env it would name a path that does not exist in the container, since "
        "this compose file mounts no volume there — a trap, not a knob."
    ),
    "quality_rules_path": "Same as catalog_path, for sources/quality_rules.yml.",
    "api_title": ("Cosmetic OpenAPI title with no operational consequence either way."),
    "api_root_path": (
        "Only meaningful when the API is served under a path prefix, and the "
        "shipped Caddyfile serves it at the domain root. Setting it alone makes "
        "FastAPI generate /prefix/openapi.json and /prefix/docs URLs that Caddy "
        "does not serve, so the operator gets broken docs rather than a no-op."
    ),
    "cors_allow_credentials": (
        "REIM authenticates on the X-API-Key header (apps/api/middleware.py), "
        'never a cookie, and allow_headers=["*"] already covers that header, '
        "so credentialed CORS buys nothing — while true alongside a loose "
        "origin list is a real exposure."
    ),
}

#: Variables that *are* in the api service's environment block but fixed there,
#: so an operator cannot change them from ``deploy/.env``, each with the reason.
#:
#: ``test_the_pinned_settings_are_not_reachable_from_env`` checks both
#: directions: that each of these really is fixed, and that nothing else in the
#: block is fixed without a reason recorded here.
PINNED_IN_COMPOSE: dict[str, str] = {
    "REIM_DATABASE_URL": (
        "Composed from POSTGRES_USER/PASSWORD/DB and pointed at the postgres "
        "service on this compose network. An override would aim the API at a "
        "database this stack does not create, migrate or back up, while the "
        "same command: still runs alembic upgrade head and db seed against it."
    ),
    "REIM_ENVIRONMENT": (
        "Pinned to production. Settings.is_production gates the debug "
        "affordances, so a settable value lets an operator turn them back on "
        "in a public deployment by accident."
    ),
    "REIM_LOG_JSON": (
        "Pinned true. Structured logs are the point of shipping this in a "
        "container; the human renderer is the local-development mode."
    ),
    "REIM_TRUSTED_PROXY_HOPS": (
        "Pinned to 1, matching the one caddy in front. This is the single "
        "setting that decides whether the rate limiter can be bypassed, and "
        ".env is the operator-editable file, so it does not belong there. "
        "Putting another proxy (a CDN, a load balancer) in front of caddy "
        "means editing this compose file and re-measuring."
    ),
}

#: Variables the compose file *requires* an operator to supply — the
#: ``${VAR:?message}`` form, which makes compose refuse to render the file at
#: all rather than fall back to anything — each with the reason it is demanded
#: rather than defaulted.
#:
#: These have no default to pin, so ``test_each_compose_default_is_the_application_default``
#: cannot see them and ``OPERATOR_SETTABLE`` does not cover them. That is the
#: gap this mapping closes: a setting wired this way is the most deliberate
#: kind there is, and would otherwise reach no file an operator reads while
#: passing every other test here.
REQUIRED_IN_COMPOSE: dict[str, str] = {
    "REIM_CORS_ALLOW_ORIGINS": (
        "The origins allowed to call this API from a browser. Every default "
        "worth having is either a wildcard, which undoes the reason this "
        "deployment exists, or a guess at somebody's domain. Refusing to start "
        "is the correct behaviour: there is no safe value we can pick for them."
    ),
}

#: Variables that are operator-settable in fact but deliberately absent from
#: ``OPERATOR_SETTABLE``, each with the reason — so that the difference is a
#: named decision rather than an off-by-one in an arithmetic guard.
OPERATOR_SETTABLE_BUT_UNDOCUMENTED: dict[str, str] = {
    "REIM_LOG_LEVEL": (
        "Reachable from .env as ${REIM_LOG_LEVEL:-INFO}, but documenting it in "
        "deploy/.env.prod.example is Task 4 Step 3's work in the deployment "
        "corrections increment, and asserting it here would either fail or do "
        "their job for them. When it is documented, move it into "
        "OPERATOR_SETTABLE and delete this entry — the two are checked as one "
        "set, so moving it across changes nothing else."
    ),
}

#: The variables an operator is meant to be able to tune from ``deploy/.env``
#: *and* find documented in ``deploy/.env.prod.example``. Kept explicit rather
#: than derived, so that a variable silently dropped from the compose file
#: fails by name.
OPERATOR_SETTABLE = (
    "REIM_RATE_LIMIT_ENABLED",
    "REIM_RATE_LIMIT_ANONYMOUS",
    "REIM_RATE_LIMIT_KEYED",
    "REIM_RATE_LIMIT_WINDOW_SECONDS",
    "REIM_ALERT_WEBHOOK_URL",
    "REIM_ALERT_SEVERITY_FLOOR",
    "REIM_ALERT_REPEAT_HOURS",
    "REIM_ALERT_STUCK_RUN_HOURS",
    "REIM_DEFAULT_PAGE_SIZE",
    "REIM_MAX_PAGE_SIZE",
    "REIM_MAX_EXPORT_ROWS",
    "REIM_METRICS_ENABLED",
    "REIM_DATABASE_POOL_SIZE",
    "REIM_DATABASE_MAX_OVERFLOW",
    "REIM_HTTP_TIMEOUT_SECONDS",
    "REIM_HTTP_MAX_RETRIES",
    "REIM_HTTP_RETRY_BACKOFF_SECONDS",
)


@pytest.fixture
def production() -> dict:
    return yaml.safe_load(PRODUCTION.read_text(encoding="utf-8"))


def test_only_caddy_publishes_ports(production: dict) -> None:
    """Every other service is reachable only from the compose network.

    Asserted over every service rather than naming postgres and api, so a
    service added later cannot quietly open a port nobody tested for. An
    earlier draft of this plan used a compose *overlay* declaring ``ports: []``
    and a test that read that overlay; both passed while the merged deployment
    still published 5432, because Compose concatenates ports when merging. The
    lesson kept here is that the assertion belongs on the whole resolved file.
    """
    publishing = {
        name: service.get("ports")
        for name, service in production["services"].items()
        if service.get("ports")
    }

    assert set(publishing) == {"caddy"}, (
        f"only caddy may publish ports; these also do: {sorted(set(publishing) - {'caddy'})}"
    )


def test_exactly_one_trusted_proxy_hop(production: dict) -> None:
    """One proxy is in front, and it is ours.

    Higher than the number of proxies actually run hands the choice of identity
    back to the client and the rate limiter stops limiting.
    """
    environment = production["services"]["api"]["environment"]

    assert str(environment["REIM_TRUSTED_PROXY_HOPS"]) == "1"


def test_the_proxy_image_is_pinned_to_an_exact_version(production: dict) -> None:
    """The header behaviour REIM_TRUSTED_PROXY_HOPS=1 rests on was measured
    against one Caddy build.

    Caddy overwrites X-Forwarded-For rather than appending, which is what makes
    one hop the right number. A floating tag lets a future release replace the
    binary that was measured, with nothing to notice the change.
    """
    image = production["services"]["caddy"]["image"]

    tag = image.rsplit(":", 1)[-1]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-\w+)?", tag), (
        f"caddy image tag {tag!r} is not an exact version; the measured "
        "X-Forwarded-For behaviour is not pinned to anything"
    )


def test_the_settings_an_operator_tunes_reach_the_container(production: dict) -> None:
    """An operator's tuning must not require editing the file we shipped them.

    Each of these must be referenced in the api service's environment block so
    that setting it in .env actually reaches the container. Their absence there
    is exactly what let ``REIM_RATE_LIMIT_ANONYMOUS`` through unconfigurable
    until this test existed. Alerting had the identical gap, one subsystem
    over, and then ``REIM_MAX_EXPORT_ROWS`` had it a third time while
    ``docs/deployment.md`` named it as the export budget to tune — three
    instances found one at a time, each because somebody happened to look.

    So this list is no longer the subsystem somebody last noticed. It is the
    result of enumerating every field of ``reim.core.config.Settings`` against
    this block and keeping the ones an operator of a public deployment would
    plausibly set. The other two classes — fixed in the compose file, and given
    no path at all — are ``PINNED_IN_COMPOSE`` and ``EXCLUDED_FROM_COMPOSE``
    above, each entry with its reason, and
    ``test_every_setting_is_wired_or_deliberately_excluded`` is what makes a new
    field belong to one of the three rather than to nobody. This tuple stays
    explicit so a variable dropped from the compose file fails by name.
    """
    environment = production["services"]["api"]["environment"]

    for variable in OPERATOR_SETTABLE:
        assert variable in environment, f"{variable} has no path through docker-compose.prod.yml"


def test_every_wired_variable_names_a_real_setting(production: dict) -> None:
    """The other half of the same gap: a key here that no ``Settings`` field reads.

    ``SettingsConfigDict(extra="ignore")`` means a misspelled or renamed
    ``REIM_*`` key is not an error — it is simply never read, which looks
    exactly like the setting being wired. The test above cannot see that:
    ``REIM_MAX_EXPORT_ROW`` would satisfy nothing and fail loudly, but
    ``REIM_MAX_EXPORT_ROWS`` surviving a later rename of the field itself would
    leave a line here that reaches nothing and a test that still passes.
    """
    environment = production["services"]["api"]["environment"]
    known = {f"REIM_{name.upper()}" for name in Settings.model_fields}

    unknown = sorted(key for key in environment if key.startswith("REIM_") and key not in known)

    assert not unknown, (
        f"these keys are set on the api service but no field of Settings reads them, "
        f"so they are silently ignored: {unknown}"
    )


def assert_reasons_are_usable(reasons: dict[str, str], name: str) -> None:
    """A reason is the artifact that makes these mappings worth having.

    ``if not reason`` catches only the empty string, so ``"TODO"``, ``"n/a"``
    and ``"see the report"`` all passed — which reintroduces, through the door
    this file built, exactly the undecided setting it exists to catch. No test
    can judge prose, so this is a length floor and nothing more: every reason
    actually written here runs from 52 to 311 characters, and a placeholder
    written in a hurry does not reach forty.
    """
    too_short = sorted(key for key, reason in reasons.items() if len(reason.strip()) < MIN_REASON)
    assert not too_short, (
        f"{name} entries for {too_short} have no reason a reader could act on. This is a "
        f"crude length check ({MIN_REASON} characters) standing in for one nobody can "
        f"write: say what the setting does and why it is in this class, the way the "
        f"entries beside it do."
    )


def _wired_fields(production: dict) -> set[str]:
    """``Settings`` fields the api service's environment block mentions at all."""
    environment = production["services"]["api"]["environment"]
    return {name for name in Settings.model_fields if f"REIM_{name.upper()}" in environment}


def test_every_setting_is_wired_or_deliberately_excluded(production: dict) -> None:
    """A new ``Settings`` field must be classified before the suite goes green.

    This is the test the three previous instances of this gap needed and did not
    have. Both of the tests above mutate in the wrong direction: they catch a
    variable removed from the compose file, and a compose key that names no
    field. Neither notices the case that actually happened three times — a field
    added to ``reim/core/config.py`` that nobody wired — because a hardcoded
    list of what to check cannot grow by itself.

    Partitioning does grow by itself. Every field is wired, or it is in
    ``EXCLUDED_FROM_COMPOSE`` with a reason; a field in neither fails here,
    naming itself. The reason lives in this file rather than in a design
    document because this file is what runs.
    """
    wired = _wired_fields(production)
    excluded = set(EXCLUDED_FROM_COMPOSE)

    unclassified = sorted(set(Settings.model_fields) - wired - excluded)
    assert not unclassified, (
        f"these Settings fields are neither wired into the api service's environment "
        f"block nor listed in EXCLUDED_FROM_COMPOSE: {unclassified}. Decide whether an "
        f"operator of a public deployment would set them from deploy/.env: wire the "
        f"ones that they would, and record the others in EXCLUDED_FROM_COMPOSE with "
        f"the reason they are not theirs to set."
    )

    both = sorted(excluded & wired)
    assert not both, (
        f"these fields are wired into the compose file *and* listed as excluded from "
        f"it, so the recorded reason no longer describes what ships: {both}"
    )

    stale = sorted(excluded - set(Settings.model_fields))
    assert not stale, (
        f"EXCLUDED_FROM_COMPOSE names fields that Settings no longer has, so their "
        f"reasons are about settings that do not exist: {stale}"
    )

    assert_reasons_are_usable(EXCLUDED_FROM_COMPOSE, "EXCLUDED_FROM_COMPOSE")


def test_the_pinned_settings_are_not_reachable_from_env(production: dict) -> None:
    """Some settings are in the block precisely so an operator cannot change them.

    ``REIM_TRUSTED_PROXY_HOPS`` is the one that matters: it decides whether the
    rate limiter can be bypassed, and ``deploy/.env`` is the file the guide
    invites operators to edit. A literal value with no ``${...}`` around it is
    what makes it unreachable — the ``environment:`` block is the only channel
    by which any variable reaches this container, since the service declares no
    ``env_file:``, and ``--env-file deploy/.env`` feeds compose's own
    interpolation rather than the container's environment.

    Checked in both directions, so that neither a pin that quietly becomes
    settable nor a new pin nobody justified passes silently.
    """
    environment = production["services"]["api"]["environment"]
    assert "env_file" not in production["services"]["api"], (
        "the api service now declares env_file:, which is a second channel into the "
        "container's environment that this test cannot see; the pins below are only "
        "unreachable while the environment: block is the only one"
    )

    assert_reasons_are_usable(PINNED_IN_COMPOSE, "PINNED_IN_COMPOSE")
    for key in PINNED_IN_COMPOSE:
        assert key in environment, f"{key} is recorded as pinned but is not in the block"
        assert f"${{{key}" not in str(environment[key]), (
            f"{key} is recorded as pinned, with a reason it must not be settable from "
            f".env, but its value now interpolates {key}: {environment[key]!r}"
        )

    unrecorded = sorted(
        key
        for key, value in environment.items()
        if key.startswith("REIM_")
        and f"${{{key}" not in str(value)
        and key not in PINNED_IN_COMPOSE
    )
    assert not unrecorded, (
        f"these variables are fixed in the compose file, so no .env can change them, "
        f"but no reason for that is recorded in PINNED_IN_COMPOSE: {unrecorded}"
    )


def test_each_compose_default_is_the_application_default(
    production: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule the environment block states about itself, actually checked.

    The block's comment promises ``the default here is Settings' own default,
    so leaving one unset in .env changes nothing``. Nothing enforced it. Change
    ``default_page_size`` in ``reim/core/config.py`` and every deployment would
    keep running the compose file's stale copy while the code documented the new
    one — and both of the tests above would stay green, because the key is still
    present and still names a real field.

    Each default is fed through the environment, not the constructor, because
    the environment source is the path a ``deploy/.env`` value actually takes
    and it parses differently (``tests/unit/test_config.py`` exists because of
    exactly that difference).
    """
    for name in [key for key in os.environ if key.startswith("REIM_")]:
        monkeypatch.delenv(name)
    defaults = Settings(_env_file=None)

    environment = production["services"]["api"]["environment"]
    # Derived from the file rather than counted by hand: everything in the block
    # that is neither pinned to a literal nor demanded of the operator has a
    # default, and every one of those must be checked here. An earlier version
    # asserted a hardcoded total and blamed the regex when it did not match,
    # which sent the reader to the wrong file for the two likeliest causes — a
    # variable added to the block, or one reclassified.
    should_check = {
        key
        for key, raw in environment.items()
        if key.startswith("REIM_")
        and key not in PINNED_IN_COMPOSE
        and key not in REQUIRED_IN_COMPOSE
    }
    checked = set()
    for key, raw in environment.items():
        match = DEFAULTED.match(str(raw))
        if match is None or match.group(1) != key:
            continue
        field = key.removeprefix("REIM_").lower()
        if field not in Settings.model_fields:
            continue

        monkeypatch.setenv(key, match.group(2))
        actual = getattr(Settings(_env_file=None), field)
        monkeypatch.delenv(key)
        expected = getattr(defaults, field)

        # ``${REIM_ALERT_WEBHOOK_URL:-}`` is the one entry whose compose default
        # is the empty string against an application default of ``None``. That
        # is deliberate and not drift: ``reim/services/alerting.py`` gates on
        # ``not url``, so unset and empty are the same "not configured".
        if expected is None and actual == "":
            actual = None

        assert actual == expected, (
            f"{key}'s default in docker-compose.prod.yml is {match.group(2)!r}, which "
            f"parses to {actual!r}, but Settings.{field} defaults to {expected!r}. A "
            f"fresh deployment would silently run the compose file's value."
        )
        checked.add(key)

    unchecked = sorted(should_check - checked)
    assert not unchecked, (
        f"{unchecked} are in the api service's environment block but this test never "
        f"compared their defaults. Either they were added without a default (use the "
        f"${{VAR:-value}} form, or record them in PINNED_IN_COMPOSE or "
        f"REQUIRED_IN_COMPOSE with the reason), or the ${{VAR:-value}} form itself has "
        f"changed and this test now silently checks less than it claims."
    )


def test_the_compose_block_is_a_partition_too(production: dict) -> None:
    """Closure over the file, not only over ``Settings``.

    ``test_every_setting_is_wired_or_deliberately_excluded`` partitions the
    application's fields, which closes the gap where a setting is unreachable.
    It cannot close the mirror image: a variable that reaches the container but
    reaches no file an operator reads.

    The ``${VAR:?message}`` form is where that hides. It has no default, so the
    defaults test has nothing to compare; it is not a literal, so the pins test
    ignores it; and ``OPERATOR_SETTABLE`` is hand-kept, so nothing forced it to
    be listed. A setting wired that way refuses to let the stack start — loudly,
    not silently — but it refuses over a variable no shipped document names,
    which is a worse first experience than the gap this file already fixed. So
    every key in the block belongs to exactly one of the four classes, and
    ``REQUIRED_IN_COMPOSE``'s members must be documented like the rest.
    """
    environment = production["services"]["api"]["environment"]
    assert_reasons_are_usable(REQUIRED_IN_COMPOSE, "REQUIRED_IN_COMPOSE")
    assert_reasons_are_usable(
        OPERATOR_SETTABLE_BUT_UNDOCUMENTED, "OPERATOR_SETTABLE_BUT_UNDOCUMENTED"
    )

    classes = {
        "OPERATOR_SETTABLE": set(OPERATOR_SETTABLE),
        "OPERATOR_SETTABLE_BUT_UNDOCUMENTED": set(OPERATOR_SETTABLE_BUT_UNDOCUMENTED),
        "PINNED_IN_COMPOSE": set(PINNED_IN_COMPOSE),
        "REQUIRED_IN_COMPOSE": set(REQUIRED_IN_COMPOSE),
    }
    classified: set[str] = set()
    for name, members in classes.items():
        overlap = sorted(classified & members)
        assert not overlap, f"{overlap} are in {name} and in an earlier class as well"
        classified |= members

    keys = {key for key in environment if key.startswith("REIM_")}

    unclassified = sorted(keys - classified)
    assert not unclassified, (
        f"{unclassified} reach the api container but belong to none of the four classes "
        f"in this file, so nothing says whether an operator may set them, must set them, "
        f"or cannot. Put each in OPERATOR_SETTABLE (and document it in "
        f"deploy/.env.prod.example), OPERATOR_SETTABLE_BUT_UNDOCUMENTED, PINNED_IN_COMPOSE "
        f"or REQUIRED_IN_COMPOSE, with the reason."
    )

    phantom = sorted(classified - keys)
    assert not phantom, (
        f"{phantom} are classified in this file but are not in the api service's "
        f"environment block at all, so the recorded reasoning is about variables that "
        f"no longer reach the container"
    )

    not_required = sorted(
        key for key in REQUIRED_IN_COMPOSE if not REQUIRED.match(str(environment[key]))
    )
    assert not not_required, (
        f"{not_required} are recorded as demanded of the operator, with a reason no "
        f"default is safe to pick, but no longer use the ${{VAR:?message}} form: "
        f"{[str(environment[key]) for key in not_required]}"
    )


def test_the_env_example_documents_what_the_compose_file_reads(production: dict) -> None:
    """The file operators copy and edit, checked against the one that reads it.

    ``.env.prod.example`` is the file a stranger edits, and a misspelled name in
    it is inert by the same ``extra="ignore"`` mechanism as everywhere else in
    this file — except that here nothing would ever raise, in any deployment
    made from it. The compose keys are written once under review; these are
    copied by everyone.
    """
    documented = set(ENV_EXAMPLE_ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    reachable = {
        key
        for service in production["services"].values()
        for key in (service.get("environment") or {})
        if key.startswith("REIM_")
    }

    unreachable = sorted(documented - reachable)
    assert not unreachable, (
        f"deploy/.env.prod.example documents these variables, but no service in "
        f"docker-compose.prod.yml reads them, so setting one would do nothing: "
        f"{unreachable}"
    )

    # ``REQUIRED_IN_COMPOSE`` is included because a variable the stack refuses to
    # start without is the one an operator most needs to find written down.
    undocumented = sorted((set(OPERATOR_SETTABLE) | set(REQUIRED_IN_COMPOSE)) - documented)
    assert not undocumented, (
        f"these must be set, or may be tuned, from deploy/.env, but the example an "
        f"operator copies never mentions them: {undocumented}"
    )


def test_the_rate_limiter_is_on_unless_an_operator_turns_it_off(production: dict) -> None:
    """``REIM_RATE_LIMIT_ENABLED`` is newly settable, and ``false`` is a real footgun.

    Wiring it was right — the guide's own scaling note tells an operator running
    several workers to move limiting into their gateway, and this is the switch
    that lets them. But ``apps/api/main.py`` adds no limiter middleware at all
    when it is false, so what ships must be on, and that is worth a test rather
    than a comment.
    """
    environment = production["services"]["api"]["environment"]

    assert Settings.model_fields["rate_limit_enabled"].default is True
    assert str(environment["REIM_RATE_LIMIT_ENABLED"]) == "${REIM_RATE_LIMIT_ENABLED:-true}"


def test_compose_file_declares_no_cors_wildcard_default(production: dict) -> None:
    """The compose file declares no wildcard default and requires the operator to supply origins.

    PyYAML does not resolve ${VAR}, so this checks the file's declared default, not the
    operator's runtime value — which is the right check for the regression that motivated it.
    """
    environment = production["services"]["api"]["environment"]
    value = str(environment.get("REIM_CORS_ALLOW_ORIGINS", ""))

    assert "*" not in value, "the production compose must not default CORS to a wildcard"


def test_caddy_proxies_to_the_api_service_by_name(production: dict) -> None:
    """Over the compose network, never over a published port."""
    text = CADDYFILE.read_text(encoding="utf-8")

    assert "api:8000" in text
    assert "localhost:8000" not in text


def test_metrics_is_not_reachable_from_outside() -> None:
    """The metrics design put authentication out of scope on the grounds that a
    scrape endpoint is restricted at the network. This is that restriction."""
    text = CADDYFILE.read_text(encoding="utf-8")

    # Structural check: the /metrics handler block must respond, not proxy.
    # Extract the handler block content and verify it responds rather than proxies.
    # This is not satisfied by having "respond 404" anywhere in the file — it must
    # be inside the /metrics handler block specifically.
    match = re.search(r"handle\s+/metrics\s*\{([^}]+)\}", text)
    assert match, "handle /metrics block not found in Caddyfile"

    handler_body = match.group(1)
    assert "respond" in handler_body, (
        "/metrics handler must respond, but found no 'respond' directive in its body"
    )
    assert "reverse_proxy" not in handler_body, (
        "/metrics handler must not reverse_proxy; found 'reverse_proxy' in its body"
    )


def _api_command_argv(production: dict) -> list[str]:
    """Return the argv the container's entrypoint would actually receive.

    An ``entrypoint:`` on the service can replace ``command:``'s role entirely
    — a script that ignores or rewrites its arguments would leave ``command:``
    (and anything asserted about its text) untouched while running whatever it
    likes. Nothing here can see inside such a script, so its presence is
    refused outright rather than silently trusted.

    Compose tokenizes a plain ``command:`` string the same way a shell would —
    quotes preserved, nothing else interpreted — before handing it to the
    entrypoint; ``shlex.split`` in POSIX mode does the same job. A list-form
    ``command:`` is already tokenized.
    """
    service = production["services"]["api"]
    assert "entrypoint" not in service, (
        "the api service now has an entrypoint:, which can replace or rewrite "
        "command: before it runs; this test cannot see inside an entrypoint "
        "script and must be taught how to check it before this is safe to ignore"
    )

    command = service["command"]
    if isinstance(command, list):
        return [str(part) for part in command]
    return shlex.split(str(command))


def _uvicorn_argv_from_actually_running_the_command(argv: list[str], tmp_path: Path) -> list[str]:
    """Run the command for real, with stand-ins for alembic/python/uvicorn on PATH.

    This is what "structural, not a substring check" means in practice: a `#`
    partway through the string, a flag living in the ``alembic`` segment
    instead of the ``uvicorn`` one, or ``--proxy-headers`` appended after
    ``--no-proxy-headers`` are all shell-level facts. Re-deriving shell
    comment and quoting rules in Python would just be a second, competing
    guess at what ``sh`` does; asking the real ``sh`` to run the command and
    recording what its ``uvicorn`` stand-in actually received removes the
    guessing entirely — the one thing this test cannot be fooled about is
    what argv its own fake ``uvicorn`` was called with.
    """
    record = tmp_path / "uvicorn_argv.txt"
    bindir = tmp_path / "bin"
    bindir.mkdir()

    # alembic and python must succeed and do nothing, so `&&` keeps going.
    for name in ("alembic", "python", "python3"):
        stub = bindir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    uvicorn_stub = bindir / "uvicorn"
    uvicorn_stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\nexit 0\n')
    uvicorn_stub.chmod(0o755)

    result = subprocess.run(
        argv,
        env={"PATH": f"{bindir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        "the api service's command exited "
        f"{result.returncode} running with stand-ins for alembic/python/uvicorn "
        f"on PATH (stderr: {result.stderr!r})"
    )
    assert record.exists(), "uvicorn was never invoked when the api service's command actually ran"

    return record.read_text().splitlines()


def test_the_production_command_keeps_uvicorn_out_of_the_identity_decision(
    production: dict, tmp_path: Path
) -> None:
    """``--no-proxy-headers`` must survive every edit to this command.

    uvicorn's own proxy-header handling is enabled by default and trusts
    127.0.0.1, so without this flag it rewrites the client address from a
    caller-supplied ``X-Forwarded-For`` before REIM's limiter runs whenever
    uvicorn's immediate TCP peer is itself trusted — the ``Dockerfile``'s
    ``CMD`` carries the same flag and an explanation, but this ``command:``
    overrides that ``CMD`` entirely, so the Dockerfile's copy protects nothing
    here.

    A substring check on the YAML text is satisfied by ``--proxy-headers``
    appended after this flag (click keeps whichever is given last), by a
    trailing shell comment, or by the flag sitting in a different ``&&``
    segment than the ``uvicorn`` call — none of which reach uvicorn. So this
    asserts on the argv uvicorn actually receives when the command runs for
    real, not on where the substring sits in the YAML scalar.
    """
    argv = _api_command_argv(production)
    uvicorn_args = _uvicorn_argv_from_actually_running_the_command(argv, tmp_path)

    no_proxy_positions = [i for i, arg in enumerate(uvicorn_args) if arg == "--no-proxy-headers"]
    proxy_positions = [i for i, arg in enumerate(uvicorn_args) if arg == "--proxy-headers"]

    assert no_proxy_positions, (
        "uvicorn's actual argv, once the api service's command really runs, carries no "
        f"--no-proxy-headers: {uvicorn_args!r}"
    )
    if proxy_positions:
        assert max(no_proxy_positions) > max(proxy_positions), (
            "click resolves this pair of flags to whichever is given last, and "
            f"--proxy-headers comes after --no-proxy-headers in {uvicorn_args!r}, so "
            "uvicorn would actually run with proxy headers enabled"
        )
