"""patients module — patient registration, Health ID issuance (ADR-012), profile.

Layout: ``router`` → ``service`` (registration/idempotency/Health-ID draw loop) →
``repository`` (persistence only), plus ``models``, ``schemas``, ``errors``, and
``health_id`` (pure generation/validation). Identities are provisioned through auth's
``UserAccountService`` — this module never touches the users table or Firebase
(docs/SYSTEM_ARCHITECTURE.md isolation rules).
"""
