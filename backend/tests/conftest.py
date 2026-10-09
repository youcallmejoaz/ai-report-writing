from __future__ import annotations

from pathlib import Path

import pytest

from app.auth import DEV_USERS
from app.domain.catalogue import default_catalogue
from app.pipeline.draft import ScriptedDraftingModel
from app.pipeline.extract import LabelMatchingExtractor
from app.pipeline.ingest import AllowAllScanner
from app.service import ReportService
from app.templates_mgmt.pack import load_pack
from app.templates_mgmt.registry import TemplateRegistry

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "template_packs" / "suitability_v1"

GOOD_DRAFTS = {
    "circumstances_summary": [("You are employed full time as a senior project manager.",
                               ["client.employment_status"])],
    "objectives_summary": [("You want to consolidate your pension and reduce charges.", ["client.objectives"]),
                           ("You intend to retire at 63.", ["client.retirement_age_target"])],
    "risk_summary": [("Your attitude to risk is recorded as Balanced (4 out of 7).", ["client.attitude_to_risk"]),
                     ("Your capacity for loss is recorded as high.", ["client.capacity_for_loss"])],
    "recommendation_explanation": [
        ("We recommend transferring your pension, valued at £125,400.00.",
         ["adviser.recommendation", "pension.fund_value"]),
        ("The charge falls from 1.15% to 0.55%.", ["pension.annual_charge_pct", "adviser.recommended_charge_pct"]),
    ],
}


@pytest.fixture
def users():
    return DEV_USERS


@pytest.fixture
def catalogue():
    return default_catalogue()


@pytest.fixture
def pack(catalogue):
    return load_pack(PACK_DIR, catalogue)


@pytest.fixture
def registry(pack, users):
    reg = TemplateRegistry()
    reg.save_draft(pack, users["dan"])
    reg.submit_for_review(pack.id, pack.version, users["dan"])
    reg.approve(pack.id, pack.version, users["carol"])
    reg.publish(pack.id, pack.version, users["carol"])
    return reg


def make_service(catalogue, registry, drafts=None):
    return ReportService(catalogue=catalogue, registry=registry, extractor=LabelMatchingExtractor(),
                         drafter=ScriptedDraftingModel(drafts or GOOD_DRAFTS), scanner=AllowAllScanner(),
                         allow_text_uploads=True)


@pytest.fixture
def service(catalogue, registry):
    return make_service(catalogue, registry)


def upload_samples(svc, user, case_id):
    for name in ("fact_find.txt", "pension_statement.txt"):
        svc.upload_document(user, case_id, name, (ROOT / "samples" / name).read_bytes())


def prepare_ready_case(svc, users, pack_id):
    """Case with samples uploaded, conflict resolved, gaps filled and every fact verified."""
    case = svc.create_case(users["alice"], client_ref="CRM-1", team="north", template_pack_id=pack_id)
    upload_samples(svc, users["alice"], case.id)
    record = svc.store.records[case.id]
    conflict = record.conflicts[0]
    chosen = next(i for i in conflict.candidate_fact_ids if record.fact(i).display == "£125,400.00")
    svc.resolve_conflict(users["alice"], case.id, conflict.id, chosen, "statement is more recent")
    svc.adviser_input(users["alice"], case.id, "client.capacity_for_loss", "High")
    svc.adviser_input(users["aaron"], case.id, "adviser.recommendation", "Transfer to the recommended plan")
    svc.adviser_input(users["aaron"], case.id, "adviser.reasons", "Lower charges and online access")
    svc.adviser_input(users["aaron"], case.id, "adviser.recommended_charge_pct", "0.55%")
    for f in list(record.facts):
        if f.status == "extracted":
            svc.verify_fact(users["alice"], case.id, f.id)
    return case
