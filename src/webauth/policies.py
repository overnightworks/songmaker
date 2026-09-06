"""What the host application decides about its own requests.

The library owns the mechanism — one budget class per request, one CSRF
verdict, one body limit, one set of response headers — and knows nothing
about which paths a particular deployment serves. Each policy below carries
those answers as data: the application builds it at startup and hands it to
the middleware that reads it, so no middleware reaches for a settings
singleton or an application module of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class PathShape:
    """A path recognised by how it begins and how it ends."""

    starts_with: str
    ends_with: str

    def matches(self, path: str) -> bool:
        return path.startswith(self.starts_with) and path.endswith(self.ends_with)


@dataclass(frozen=True)
class PathRules:
    """The paths a rule selects, named exactly or by shape."""

    exact: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()
    shapes: tuple[PathShape, ...] = ()
    patterns: tuple[re.Pattern[str], ...] = ()

    def matches(self, path: str) -> bool:
        return (
            path in self.exact
            or path.startswith(self.prefixes)
            or any(shape.matches(path) for shape in self.shapes)
            or any(pattern.match(path) for pattern in self.patterns)
        )


class RateLimitClass(Enum):
    """The budget a request spends from, decided once per request."""

    API = auto()
    MEDIA = auto()
    STREAM = auto()


@dataclass(frozen=True)
class RateLimitBudget:
    """How many requests one class grants an address within its window."""

    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitPolicy:
    """Which paths belong to which budget class, and how large each budget is.

    Separate classes exist so one traffic pattern cannot starve another
    arriving from the same address: range-served media and stream openings
    are ordinary use at rates that would look like abuse on an API budget.
    """

    budgets: Mapping[RateLimitClass, RateLimitBudget]
    exempt: PathRules = PathRules()
    media: PathRules = PathRules()
    stream: PathRules = PathRules()

    def __post_init__(self) -> None:
        unbudgeted = [
            rate_limit_class.name
            for rate_limit_class in RateLimitClass
            if rate_limit_class not in self.budgets
        ]
        if unbudgeted:
            raise ValueError(
                "Every rate-limit class needs a budget, or a request classified "
                f"into one would go unlimited; missing: {', '.join(unbudgeted)}.",
            )

    def is_exempt(self, path: str) -> bool:
        return self.exempt.matches(path)

    def classify(self, path: str) -> RateLimitClass:
        """The one class ``path`` spends from.

        A path no rule claims spends from the API budget — fail closed, so an
        unrecognised route cannot slip through unlimited.
        """
        if self.media.matches(path):
            return RateLimitClass.MEDIA
        if self.stream.matches(path):
            return RateLimitClass.STREAM
        return RateLimitClass.API

    def budget(self, rate_limit_class: RateLimitClass) -> RateLimitBudget:
        return self.budgets[rate_limit_class]


@dataclass(frozen=True)
class CsrfPolicy:
    """Which requests must prove they were made from this site.

    A path may be exempt from the token check and still owe a same-origin
    check: a login carries no session yet, so it has no token to submit, but
    a foreign page must not be able to submit it either.
    """

    protected: PathRules = PathRules()
    token_exempt: PathRules = PathRules()

    def requires_same_origin(self, path: str) -> bool:
        return self.protected.matches(path)

    def requires_token(self, path: str) -> bool:
        return self.protected.matches(path) and not self.token_exempt.matches(path)


@dataclass(frozen=True)
class BodySizeRule:
    """Routes whose request body may be larger than the default, and by how much."""

    paths: PathRules
    max_bytes: int
    methods: frozenset[str] | None = None
    """The methods the larger budget applies to; ``None`` means every method."""

    def applies_to(self, path: str, method: str) -> bool:
        if self.methods is not None and method.upper() not in self.methods:
            return False
        return self.paths.matches(path)


@dataclass(frozen=True)
class BodySizePolicy:
    """How large a request body may be, by default and on the routes that differ."""

    default_max_bytes: int
    rules: tuple[BodySizeRule, ...] = ()

    def max_bytes(self, path: str, method: str) -> int:
        """The budget for this request; the first matching rule wins."""
        for rule in self.rules:
            if rule.applies_to(path, method):
                return rule.max_bytes
        return self.default_max_bytes


@dataclass(frozen=True)
class CacheControlRule:
    """The ``Cache-Control`` value the paths it names are answered with."""

    paths: PathRules
    value: str


@dataclass(frozen=True)
class SecurityHeadersPolicy:
    """The policy headers every response carries out of this deployment."""

    content_security_policy: str
    cache_control_rules: tuple[CacheControlRule, ...] = ()

    def cache_control(self, path: str) -> str | None:
        """What this path may be cached as; the first matching rule wins."""
        for rule in self.cache_control_rules:
            if rule.paths.matches(path):
                return rule.value
        return None


def default_content_security_policy(script_hashes: Sequence[str]) -> str:
    """Nothing loads unless this origin serves it, and no page may frame it.

    Inline scripts a build emits into its own document are admitted by hash,
    so the policy needs no ``unsafe-inline`` for them.
    """
    script_src = "'self'"
    for script_hash in script_hashes:
        script_src += f" '{script_hash}'"
    return (
        "default-src 'none'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "connect-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "manifest-src 'self'; "
        "worker-src 'self'; "
        "frame-ancestors 'none'"
    )
