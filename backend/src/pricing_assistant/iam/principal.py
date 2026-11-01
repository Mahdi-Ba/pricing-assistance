"""The authenticated caller."""

import uuid
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    EXPERT = "expert"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    username: str
    tenant_id: uuid.UUID
    roles: frozenset[Role]

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_any_role(self, *roles: Role) -> bool:
        return not self.roles.isdisjoint(roles)
