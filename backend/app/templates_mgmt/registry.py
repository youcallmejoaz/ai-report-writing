"""Template registry: lifecycle, maker-checker approval and immutability of published versions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.domain.schemas import Role, User, utcnow
from app.templates_mgmt.pack import TemplatePack


class VersionStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    RETIRED = "retired"


class RegistryError(PermissionError):
    pass


class TemplateVersion(BaseModel):
    pack: TemplatePack
    status: VersionStatus
    author: str
    content_hash: str
    approver: str | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.pack.id, self.pack.version


class TemplateRegistry:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], TemplateVersion] = {}

    def _get(self, pack_id: str, version: str) -> TemplateVersion:
        try:
            return self._versions[(pack_id, version)]
        except KeyError as exc:
            raise RegistryError(f"no template {pack_id}@{version}") from exc

    def save_draft(self, pack: TemplatePack, author: User) -> TemplateVersion:
        if not author.has(Role.TEMPLATE_ADMIN):
            raise RegistryError("only Template Administrators can edit templates")
        existing = self._versions.get((pack.id, pack.version))
        if existing and existing.status is not VersionStatus.DRAFT:
            raise RegistryError(
                f"{pack.id}@{pack.version} is {existing.status}; create a new version instead"
            )
        # Store a private copy so later edits to the caller's object cannot alter the registered version.
        pack = pack.model_copy(deep=True)
        tv = TemplateVersion(pack=pack, status=VersionStatus.DRAFT, author=author.id,
                             content_hash=pack.content_hash)
        self._versions[tv.key] = tv
        return tv

    def submit_for_review(self, pack_id: str, version: str, user: User) -> TemplateVersion:
        tv = self._get(pack_id, version)
        if tv.status is not VersionStatus.DRAFT:
            raise RegistryError("only drafts can be submitted")
        tv.status = VersionStatus.IN_REVIEW
        return tv

    def return_to_draft(self, pack_id: str, version: str, user: User) -> TemplateVersion:
        tv = self._get(pack_id, version)
        if tv.status is not VersionStatus.IN_REVIEW:
            raise RegistryError("only versions in review can be returned")
        tv.status = VersionStatus.DRAFT
        return tv

    def approve(self, pack_id: str, version: str, approver: User) -> TemplateVersion:
        tv = self._get(pack_id, version)
        if not approver.has(Role.COMPLIANCE):
            raise RegistryError("only Compliance can approve template versions")
        if approver.id == tv.author:
            raise RegistryError("the author of a template version cannot approve it")
        if tv.status is not VersionStatus.IN_REVIEW:
            raise RegistryError("only versions in review can be approved")
        if tv.pack.content_hash != tv.content_hash:
            raise RegistryError("content changed after submission")
        tv.status, tv.approver, tv.approved_at = VersionStatus.APPROVED, approver.id, utcnow()
        return tv

    def publish(self, pack_id: str, version: str, user: User) -> TemplateVersion:
        tv = self._get(pack_id, version)
        if not (user.has(Role.TEMPLATE_ADMIN) or user.has(Role.COMPLIANCE)):
            raise RegistryError("not permitted to publish")
        if tv.status is not VersionStatus.APPROVED:
            raise RegistryError("only approved versions can be published")
        for other in self._versions.values():
            if other.pack.id == pack_id and other.status is VersionStatus.PUBLISHED:
                other.status = VersionStatus.RETIRED
        tv.status, tv.published_at = VersionStatus.PUBLISHED, utcnow()
        return tv

    def published(self, pack_id: str) -> TemplateVersion:
        for tv in self._versions.values():
            if tv.pack.id == pack_id and tv.status is VersionStatus.PUBLISHED:
                if tv.pack.content_hash != tv.content_hash:
                    raise RegistryError(f"integrity failure: {pack_id}@{tv.pack.version} content changed")
                return tv
        raise RegistryError(f"no published version of {pack_id}")

    def get(self, pack_id: str, version: str) -> TemplateVersion:
        return self._get(pack_id, version)

    def all(self) -> list[TemplateVersion]:
        return list(self._versions.values())
