"""auth module — verifies identity-provider tokens and gates roles (ADR-011, ADR-013).

Layout: ``provider`` (port) + ``firebase``/``fake`` (implementations), ``service``
(domain logic), ``dependencies`` (FastAPI authn/role gates), ``router``, ``schemas``,
``domain`` (Role, AuthenticatedUser), ``errors``. No repository yet — the module owns no
tables until registration lands (M0.3 Part 3). Nothing outside this module may import
Firebase types (docs/SYSTEM_ARCHITECTURE.md isolation rules).
"""
