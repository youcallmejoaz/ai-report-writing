import pytest

from app.domain.schemas import Role, User
from app.templates_mgmt.pack import PackValidationError, validate_pack
from app.templates_mgmt.registry import RegistryError, TemplateRegistry, VersionStatus


def test_author_cannot_approve_even_with_compliance_role(pack):
    both = User(id="zoe", name="Zoe", roles={Role.TEMPLATE_ADMIN, Role.COMPLIANCE})
    reg = TemplateRegistry()
    reg.save_draft(pack, both)
    reg.submit_for_review(pack.id, pack.version, both)
    with pytest.raises(RegistryError, match="author"):
        reg.approve(pack.id, pack.version, both)


def test_published_version_is_immutable(registry, pack, users):
    with pytest.raises(RegistryError, match="new version"):
        registry.save_draft(pack, users["dan"])


def test_tampering_with_published_content_is_detected(registry, pack):
    tv = registry.published(pack.id)
    tv.pack.clauses["risk_warnings"].text = "Investments always go up."
    with pytest.raises(RegistryError, match="integrity"):
        registry.published(pack.id)


def test_publishing_new_version_retires_old(registry, pack, users):
    v2 = pack.model_copy(update={"version": "1.1.0"}, deep=True)
    registry.save_draft(v2, users["dan"])
    registry.submit_for_review(v2.id, v2.version, users["dan"])
    registry.approve(v2.id, v2.version, users["carol"])
    registry.publish(v2.id, v2.version, users["carol"])
    assert registry.published(pack.id).pack.version == "1.1.0"
    assert registry.get(pack.id, "1.0.0").status is VersionStatus.RETIRED


def test_validation_rejects_unknown_references(pack, catalogue):
    broken = pack.model_copy(deep=True)
    broken.sections[0].blocks[0].clause = "does_not_exist"
    with pytest.raises(PackValidationError, match="unknown clause"):
        validate_pack(broken, catalogue)
    broken = pack.model_copy(deep=True)
    broken.clauses["intro_purpose"].text = "Dear {{ client.nickname }}"
    with pytest.raises(PackValidationError, match="unknown placeholder"):
        validate_pack(broken, catalogue)
