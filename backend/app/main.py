"""HTTP API. Thin layer over ``ReportService``: authentication, request/response shapes, error mapping.

Run locally:  APP_ENV=local uvicorn app.main:app --reload   (use header X-Dev-User: alice|bob|...)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.audit import verify_chain
from app.auth import DEV_USERS, current_user, require_role
from app.demo_content import DEMO_DRAFTS
from app.domain.catalogue import default_catalogue
from app.domain.schemas import Role, User
from app.pipeline.draft import DraftingBlocked, FactListingDraftingModel, LLMDraftingModel, ScriptedDraftingModel
from app.pipeline.extract import LabelMatchingExtractor
from app.pipeline.ingest import AllowAllScanner
from app.service import NotFound, ReportService
from app.templates_mgmt.pack import load_pack
from app.templates_mgmt.registry import RegistryError, TemplateRegistry
from app.workflow import WorkflowError

PACKS_DIR = Path(__file__).resolve().parents[1] / "template_packs"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build_service() -> ReportService:
    catalogue = default_catalogue()
    registry = TemplateRegistry()
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from app.llm.client import AzureOpenAIClient

        drafter = LLMDraftingModel(AzureOpenAIClient.from_env())
    elif os.environ.get("APP_DEMO") == "1" and os.environ.get("APP_ENV", "local") == "local":
        # Portfolio/demo recordings: pre-written, evidence-faithful drafts, labelled as such in the UI.
        drafter = ScriptedDraftingModel(DEMO_DRAFTS, name="scripted-demo-drafter")
    else:
        drafter = FactListingDraftingModel()
    service = ReportService(
        catalogue=catalogue,
        registry=registry,
        extractor=LabelMatchingExtractor(),
        drafter=drafter,
        scanner=AllowAllScanner(),
        allow_text_uploads=os.environ.get("APP_ENV", "local") == "local",
    )
    if os.environ.get("APP_ENV", "local") == "local":
        # Seed the example pack through the full lifecycle (author != approver).
        pack = load_pack(PACKS_DIR / "suitability_v1", catalogue)
        registry.save_draft(pack, DEV_USERS["dan"])
        registry.submit_for_review(pack.id, pack.version, DEV_USERS["dan"])
        registry.approve(pack.id, pack.version, DEV_USERS["carol"])
        registry.publish(pack.id, pack.version, DEV_USERS["carol"])
    return service


app = FastAPI(title="AI Report Writing (reference implementation)", version="0.1.0")
service = build_service()


@app.exception_handler(PermissionError)
async def _forbidden(_: Request, exc: PermissionError):
    status = 409 if isinstance(exc, WorkflowError | RegistryError) else 403
    return JSONResponse({"detail": str(exc)}, status_code=status)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse({"detail": f"not found: {exc.args[0]}"}, status_code=404)


@app.exception_handler(ValueError)
async def _invalid(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(DraftingBlocked)
async def _blocked(_: Request, exc: DraftingBlocked):
    return JSONResponse({"detail": str(exc)}, status_code=409)


# ----------------------------------------------------------------------------- request bodies


class CaseIn(BaseModel):
    client_ref: str
    team: str
    template_pack_id: str = "pension_consolidation_suitability"
    restricted: bool = False


class CorrectIn(BaseModel):
    value: str
    reason: str


class ResolveIn(BaseModel):
    chosen_fact_id: str | None
    reason: str


class AdviserInputIn(BaseModel):
    key: str
    value: str
    note: str | None = None


class EditIn(BaseModel):
    text: str
    fact_ids: list[str]


class CommentIn(BaseModel):
    comment: str | None = None


class DismissIn(BaseModel):
    reason: str


# ----------------------------------------------------------------------------- routes


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user


@app.post("/cases")
def create_case(body: CaseIn, user: User = Depends(current_user)):
    return service.create_case(user, **body.model_dump())


@app.get("/cases")
def list_cases(user: User = Depends(current_user)):
    return service.list_cases(user)


@app.post("/cases/{case_id}/documents")
async def upload(case_id: str, file: UploadFile = File(...), doc_type: str | None = None,
                 user: User = Depends(current_user)):
    data = await file.read()
    return service.upload_document(user, case_id, file.filename or "upload", data, doc_type)


@app.get("/cases/{case_id}/record")
def record(case_id: str, user: User = Depends(current_user)):
    return service.case_record(user, case_id)


@app.get("/spans/{span_id}")
def span(span_id: str, user: User = Depends(current_user)):
    s, doc = service.source_span(user, span_id)
    return {"span": s, "document": {"id": doc.id, "filename": doc.filename, "sha256": doc.sha256}}


@app.post("/cases/{case_id}/facts/{fact_id}/verify")
def verify_fact(case_id: str, fact_id: str, user: User = Depends(current_user)):
    return service.verify_fact(user, case_id, fact_id)


@app.post("/cases/{case_id}/facts/{fact_id}/correct")
def correct_fact(case_id: str, fact_id: str, body: CorrectIn, user: User = Depends(current_user)):
    return service.correct_fact(user, case_id, fact_id, body.value, body.reason)


@app.post("/cases/{case_id}/conflicts/{conflict_id}/resolve")
def resolve(case_id: str, conflict_id: str, body: ResolveIn, user: User = Depends(current_user)):
    return service.resolve_conflict(user, case_id, conflict_id, body.chosen_fact_id, body.reason)


@app.post("/cases/{case_id}/adviser-inputs")
def adviser_input(case_id: str, body: AdviserInputIn, user: User = Depends(current_user)):
    return service.adviser_input(user, case_id, body.key, body.value, body.note)


@app.post("/cases/{case_id}/reports")
def generate(case_id: str, user: User = Depends(current_user)):
    return service.generate_report(user, case_id)


@app.get("/cases/{case_id}/reports")
def list_reports(case_id: str, user: User = Depends(current_user)):
    return [
        {"id": r.id, "status": r.status, "revision": r.revision, "prepared_by": r.prepared_by,
         "template": f"{r.template_pack_id}@{r.template_version}"}
        for r in service.list_reports(user, case_id)
    ]


@app.get("/reports/{report_id}")
def get_report(report_id: str, user: User = Depends(current_user)):
    return service.get_report(user, report_id)


@app.patch("/reports/{report_id}/statements/{statement_id}")
def edit(report_id: str, statement_id: str, body: EditIn, user: User = Depends(current_user)):
    return service.edit_statement(user, report_id, statement_id, body.text, body.fact_ids)


@app.post("/reports/{report_id}/submit")
def submit(report_id: str, user: User = Depends(current_user)):
    return service.submit(user, report_id)


@app.post("/reports/{report_id}/slots/{slot_id}/reviewed")
def reviewed(report_id: str, slot_id: str, user: User = Depends(current_user)):
    return service.mark_reviewed(user, report_id, slot_id)


@app.post("/reports/{report_id}/findings/{finding_id}/dismiss")
def dismiss(report_id: str, finding_id: str, body: DismissIn, user: User = Depends(current_user)):
    return service.dismiss_warning(user, report_id, finding_id, body.reason)


@app.post("/reports/{report_id}/request-changes")
def request_changes(report_id: str, body: CommentIn, user: User = Depends(current_user)):
    return service.request_changes(user, report_id, body.comment or "")


@app.post("/reports/{report_id}/approve")
def approve(report_id: str, body: CommentIn, user: User = Depends(current_user)):
    return service.approve(user, report_id, body.comment)


@app.post("/reports/{report_id}/finalise")
def finalise(report_id: str, user: User = Depends(current_user)):
    return service.finalise(user, report_id)


@app.get("/reports/{report_id}/download")
def download(report_id: str, variant: Literal["review", "client", "evidence"] = "review",
             user: User = Depends(current_user)):
    data = service.render(user, report_id, variant)
    return Response(data, media_type=DOCX_MEDIA,
                    headers={"Content-Disposition": f'attachment; filename="{report_id}-{variant}.docx"'})


@app.get("/templates")
def templates(user: User = Depends(current_user)):
    require_role(user, Role.TEMPLATE_ADMIN, Role.COMPLIANCE)
    return [
        {"id": tv.pack.id, "version": tv.pack.version, "name": tv.pack.name, "status": tv.status,
         "author": tv.author, "approver": tv.approver, "content_hash": tv.content_hash}
        for tv in service.registry.all()
    ]


@app.get("/audit/verify")
def audit_verify(user: User = Depends(current_user)):
    require_role(user, Role.AUDITOR, Role.COMPLIANCE)
    ok, bad = verify_chain(service.audit.events)
    if not ok:
        raise HTTPException(500, f"audit chain broken at event {bad}")
    return {"ok": True, "events": len(service.audit.events)}
