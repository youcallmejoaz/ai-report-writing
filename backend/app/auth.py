"""Authentication (Entra ID) and authorisation (roles + case scope).

Production: every request carries an Entra ID access token for this API. App roles arrive in the
``roles`` claim; team membership is derived from group object ids via TEAM_GROUP_MAP. Local
development: the ``X-Dev-User`` header selects one of the fixture users below (disabled unless
APP_ENV=local).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from fastapi import Header, HTTPException, status

from app.domain.schemas import Case, Role, User

APP_ENV = os.environ.get("APP_ENV", "local")

DEV_USERS = {
    "alice": User(id="alice", name="Alice Preparer", roles={Role.PREPARER}, teams={"north"}),
    "aaron": User(id="aaron", name="Aaron Adviser", roles={Role.ADVISER}, teams={"north"}),
    "bob": User(id="bob", name="Bob Reviewer", roles={Role.REVIEWER, Role.PREPARER}, teams={"north"}),
    "carol": User(id="carol", name="Carol Compliance", roles={Role.COMPLIANCE}, teams=set()),
    "dan": User(id="dan", name="Dan Template Admin", roles={Role.TEMPLATE_ADMIN}, teams=set()),
    "erin": User(id="erin", name="Erin Auditor", roles={Role.AUDITOR}, teams=set()),
    "pat": User(id="pat", name="Pat Platform Admin", roles={Role.PLATFORM_ADMIN}, teams=set()),
    "sam": User(id="sam", name="Sam South Preparer", roles={Role.PREPARER}, teams={"south"}),
}


@lru_cache(maxsize=1)
def _jwks_client():
    import jwt

    tenant = os.environ["ENTRA_TENANT_ID"]
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys")


def _user_from_token(token: str) -> User:
    import jwt

    tenant = os.environ["ENTRA_TENANT_ID"]
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=os.environ["ENTRA_API_AUDIENCE"],
        issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
    )
    roles = {Role(r) for r in claims.get("roles", []) if r in Role._value2member_map_}
    group_map: dict[str, str] = json.loads(os.environ.get("TEAM_GROUP_MAP", "{}"))
    teams = {group_map[g] for g in claims.get("groups", []) if g in group_map}
    return User(id=claims["oid"], name=claims.get("name", claims["oid"]), roles=roles, teams=teams)


def current_user(
    authorization: str | None = Header(default=None),
    x_dev_user: str | None = Header(default=None),
) -> User:
    if APP_ENV == "local" and x_dev_user:
        user = DEV_USERS.get(x_dev_user)
        if user:
            return user
    if authorization and authorization.lower().startswith("bearer "):
        try:
            return _user_from_token(authorization.split(" ", 1)[1])
        except Exception as exc:  # noqa: BLE001 - any token failure is a 401
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")


def can_access_case(user: User, case: Case) -> bool:
    """Case-level scoping on top of roles. Platform admins have no default access to client content."""
    if user.has(Role.COMPLIANCE):
        return True
    if not (user.has(Role.PREPARER) or user.has(Role.ADVISER) or user.has(Role.REVIEWER)):
        return False
    if case.restricted:
        return user.id in case.assigned_to
    return case.team in user.teams or user.id in case.assigned_to


def require_role(user: User, *roles: Role) -> None:
    if not any(user.has(r) for r in roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires one of: {', '.join(roles)}")
