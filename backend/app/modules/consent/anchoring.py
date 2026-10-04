"""The audit-anchor port and its local development adapter (ADR-004, ADR-026).

PostgreSQL is the authoritative audit store and the only read path; an anchor exists to
make a stored digest *tamper-evident*, never to hold data. What crosses this boundary is
therefore a 64-character hex digest and nothing else — no identifiers, no timestamps drawn
from the event, no action name, no patient, no record. The narrowness is the design: a port
that cannot be handed a clinical payload cannot leak one, whatever an adapter behind it
later does with what it receives (docs/BLOCKCHAIN_ARCHITECTURE.md §What Goes On-Chain).

``LocalChainAuditAnchor`` is the ``DbAuditAnchor`` role that document reserves for
development and tests. **It is a simulation and provides no independent immutability**: its
reference is a pure function of the digest, so anyone able to rewrite the anchor row can
recompute a matching reference. It exists to make the seam, the lifecycle and the
verification plumbing real and testable without a network. The property a real chain adds —
a reference that a third party can check and no database owner can forge — arrives with
``PolygonAuditAnchor`` at M6, behind this same port and with no change above it.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from app.shared.time import utc_now

#: Network identifier stored on every anchor written by the development adapter. Persisted
#: rather than assumed, so a row anchored locally can never be mistaken for a Polygon one
#: after the real adapter lands.
LOCAL_DEV_NETWORK: Final = "local-dev"

#: Domain separator for the local reference derivation. Versioned: changing how a reference
#: is computed changes this string, so anchors written under an older rule verify under the
#: rule they were written with rather than silently failing.
_LOCAL_REFERENCE_DOMAIN: Final = "pulseos:audit-anchor:local-dev:v1"

#: A digest is the hex output of the event hasher (ADR-019: SHA-256 today, keccak256 at M6).
DIGEST_LENGTH: Final = 64


class InvalidDigestError(ValueError):
    """The value offered for anchoring is not a bare hex digest.

    Raised at the port rather than inside an adapter, so *every* implementation inherits the
    same refusal. This is the check that makes "no PHI on chain" a property of the type
    system rather than of an adapter's good behaviour: a filename, a Health ID, a JSON
    document or a name cannot satisfy it.
    """


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    """What an anchor submission returns: where it went, and how to find it again.

    Deliberately free of anything about the *event*. The receipt is paired with an audit
    event by the row that stores it (``AuditAnchorEntry``), never by content carried here.
    """

    network: str
    #: Transaction-like identifier, ``0x`` + 64 hex on every adapter written so far.
    reference: str
    anchored_at: datetime


class AuditAnchor(Protocol):
    """Publish an audit digest so its existence can later be proven, and check one.

    Two methods and one argument type, which is the whole point (ADR-004: hashes only). The
    signature is what a Polygon implementation needs and no more, so M6 is an adapter rather
    than a change to anything above this line.
    """

    @property
    def network(self) -> str:
        """Identifier stored alongside every anchor this adapter produces."""
        ...

    async def submit(self, digest: str) -> AnchorReceipt:
        """Anchor one digest. Raises ``InvalidDigestError`` for anything that is not one."""
        ...

    async def verify(self, digest: str, receipt: AnchorReceipt) -> bool:
        """Whether ``receipt`` really is this network's anchor of ``digest``."""
        ...


def require_digest(value: str) -> str:
    """The gate every adapter's input passes. Lowercase hex, exactly ``DIGEST_LENGTH``.

    Rejecting rather than coercing: a caller that offers something else has made a mistake
    worth surfacing, and silently hashing it would be exactly the accident this guard
    exists to prevent — turning arbitrary content into something that looks anchorable.
    """
    if len(value) != DIGEST_LENGTH:
        raise InvalidDigestError(f"a digest is {DIGEST_LENGTH} hex characters")
    if any(character not in "0123456789abcdef" for character in value):
        raise InvalidDigestError("a digest is lowercase hexadecimal")
    return value


class LocalChainAuditAnchor:
    """Deterministic, network-free ``AuditAnchor`` for development and tests.

    The reference is ``0x`` + SHA-256 of a domain-separated digest, so submitting the same
    digest twice yields the same reference and a test can assert an exact value without
    stubbing a clock or a network. The domain separator keeps that reference from colliding
    with any other SHA-256 the system computes over the same bytes — notably the event
    digest itself, which is what a reference must never be confusable with.

    ``anchored_at`` is the only non-deterministic part, and it is the honest one: it records
    when this process submitted, not when any chain accepted. A real adapter replaces it
    with block time.
    """

    def __init__(self, *, network: str = LOCAL_DEV_NETWORK, clock: object = utc_now) -> None:
        self._network = network
        # Typed loosely then narrowed, so a test clock is injectable without importing
        # Callable machinery into the port's module surface.
        assert callable(clock)
        self._now = clock

    @property
    def network(self) -> str:
        return self._network

    async def submit(self, digest: str) -> AnchorReceipt:
        now = self._now()
        assert isinstance(now, datetime)
        return AnchorReceipt(
            network=self._network,
            reference=self._reference(require_digest(digest)),
            anchored_at=now,
        )

    async def verify(self, digest: str, receipt: AnchorReceipt) -> bool:
        """Recompute the reference and compare.

        Also checks the network: a receipt from another network is not evidence about this
        one, and answering ``True`` for it would let a local anchor stand in for a chain
        anchor after the real adapter lands.
        """
        if receipt.network != self._network:
            return False
        try:
            expected = self._reference(require_digest(digest))
        except InvalidDigestError:
            return False
        return receipt.reference == expected

    def _reference(self, digest: str) -> str:
        payload = f"{_LOCAL_REFERENCE_DOMAIN}:{digest}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()
