"""End-to-end walk-through on synthetic data, fully offline.

    python scripts/demo.py            (from backend/)

Shows: extraction with span citations; conflict and gap detection; prompt-injection text staying inert;
drafting blocked until conflicts are resolved; the verifier catching an unsupported figure and prohibited
wording; maker-checker refusal; approval; finalisation; audit chain verification.
Outputs Word files to backend/outputs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.audit import verify_chain  # noqa: E402
from app.auth import DEV_USERS  # noqa: E402
from app.domain.catalogue import default_catalogue  # noqa: E402
from app.pipeline.draft import DraftingBlocked, ScriptedDraftingModel  # noqa: E402
from app.pipeline.extract import LabelMatchingExtractor  # noqa: E402
from app.pipeline.ingest import AllowAllScanner  # noqa: E402
from app.service import ReportService  # noqa: E402
from app.templates_mgmt.pack import load_pack  # noqa: E402
from app.templates_mgmt.registry import TemplateRegistry  # noqa: E402
from app.workflow import WorkflowError  # noqa: E402

# What a drafting model might return for each slot, as (text, [fact keys cited]).
# In production these come from LLMDraftingModel (Azure OpenAI, structured outputs).
DEMO_DRAFTS = {
    "circumstances_summary": [
        ("You are currently employed full time as a senior project manager.", ["client.employment_status"]),
        ("You have not told us about any circumstances that might make you vulnerable.",
         ["client.vulnerability_flag"]),
    ],
    "objectives_summary": [
        ("You told us that you would like to consolidate your old workplace pension into a plan you can "
         "manage online, and to reduce the charges you pay.", ["client.objectives"]),
        ("You intend to retire at 63.", ["client.retirement_age_target"]),
    ],
    "risk_summary": [
        ("Your attitude to risk is recorded as Balanced (4 out of 7).", ["client.attitude_to_risk"]),
        ("You told us that a fall in the value of this pension would not affect your standard of living, "
         "so your capacity for loss is recorded as high.", ["client.capacity_for_loss"]),
    ],
    "recommendation_explanation": [
        ("We recommend that you transfer your Northbridge Life pension, currently valued at £125,400.00, "
         "to the recommended personal pension.", ["adviser.recommendation", "pension.fund_value"]),
        ("This reduces your total annual charge from 1.15% to 0.55%, which supports your objective of "
         "reducing the charges you pay.",
         ["pension.annual_charge_pct", "adviser.recommended_charge_pct", "client.objectives"]),
        ("The plan can be managed online and offers a range of funds matched to a balanced attitude to "
         "risk.", ["adviser.reasons"]),
    ],
}


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 70 - len(text)))


def main() -> None:
    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    u = DEV_USERS
    catalogue = default_catalogue()

    banner("Template pack lifecycle (template admin authors, compliance approves)")
    registry = TemplateRegistry()
    pack = load_pack(ROOT / "template_packs" / "suitability_v1", catalogue)
    registry.save_draft(pack, u["dan"])
    registry.submit_for_review(pack.id, pack.version, u["dan"])
    try:
        registry.approve(pack.id, pack.version, u["dan"])
    except PermissionError as exc:
        print("Dan (author, template admin) tries to approve ->", exc)
    registry.approve(pack.id, pack.version, u["carol"])
    tv = registry.publish(pack.id, pack.version, u["carol"])
    print(f"Published {tv.pack.id}@{tv.pack.version} sha256={tv.content_hash[:16]}…")

    svc = ReportService(catalogue=catalogue, registry=registry, extractor=LabelMatchingExtractor(),
                        drafter=ScriptedDraftingModel(DEMO_DRAFTS), scanner=AllowAllScanner(),
                        allow_text_uploads=True)

    banner("Case creation and upload")
    case = svc.create_case(u["alice"], client_ref="CRM-000123", team="north", template_pack_id=pack.id)
    for name in ("fact_find.txt", "pension_statement.txt"):
        result = svc.upload_document(u["alice"], case.id, name, (ROOT / "samples" / name).read_bytes())
        print(f"{name}: type={result.doc_type} fields={len(result.fields)} issues={len(result.issues)} "
              f"not_found={result.not_found}")
    try:
        svc.case_record(u["sam"], case.id)
    except PermissionError as exc:
        print("Sam (south team) tries to open the case ->", exc)

    record = svc.case_record(u["alice"], case.id)
    banner("Case record")
    for f in record.facts:
        spans = [svc.store.spans[s.span_id] for s in f.sources if s.span_id]
        cites = "; ".join(f"{svc.store.documents[s.document_id].filename} p{s.page}" for s in spans)
        print(f"  {f.key:34} {f.display:55.55} [{cites}]")
    for c in record.conflicts:
        vals = [record.fact(fid).display for fid in c.candidate_fact_ids]
        print(f"  CONFLICT {c.key}: {vals}")
    for g in record.gaps:
        print(f"  GAP {g.key} (needed by {g.required_by})")
    print("  Note: the injected 'ignore all previous instructions' line in the fact-find is not a field;"
          " it never reaches the drafting model.")

    banner("Drafting before conflicts are resolved")
    try:
        svc.generate_report(u["alice"], case.id)
    except DraftingBlocked as exc:
        print("Blocked ->", exc)

    banner("Human resolution of evidence")
    conflict = record.conflicts[0]
    statement_value = next(fid for fid in conflict.candidate_fact_ids if record.fact(fid).display == "£125,400.00")
    svc.resolve_conflict(u["alice"], case.id, conflict.id, statement_value,
                         "Provider statement dated 31 March 2026 is more recent than the client's estimate")
    svc.adviser_input(u["alice"], case.id, "client.capacity_for_loss",
                      "High: a fall in value would not affect standard of living",
                      note="Discussed at meeting 02/09/2026")
    try:
        svc.adviser_input(u["alice"], case.id, "adviser.recommendation", "Transfer")
    except PermissionError as exc:
        print("Alice (preparer) tries to record the recommendation ->", exc)
    svc.adviser_input(u["aaron"], case.id, "adviser.recommendation",
                      "Transfer the Northbridge Life personal pension to the recommended personal pension")
    svc.adviser_input(u["aaron"], case.id, "adviser.reasons",
                      "Lower total charges; online access; fund range suitable for a balanced investor")
    svc.adviser_input(u["aaron"], case.id, "adviser.recommended_charge_pct", "0.55%")
    for f in list(record.facts):
        if f.status == "extracted":
            svc.verify_fact(u["alice"], case.id, f.id)
    print(f"All facts verified. Open gaps: {[g.key for g in record.gaps if g.status == 'open']}")

    banner("Draft + verification")
    report = svc.generate_report(u["alice"], case.id)
    print(f"Report {report.id}: {len(report.statements)} statements, "
          f"{len(report.open_blocking_findings)} blocking findings")

    banner("Preparer edit introduces an unsupported figure and prohibited wording")
    target = next(s for s in report.statements if s.slot_id == "recommendation_explanation")
    original = (target.text, list(target.fact_ids))
    svc.edit_statement(u["alice"], report.id, target.id,
                       "We recommend a transfer; your pension of £130,000 is guaranteed to grow.",
                       target.fact_ids)
    for f in report.open_blocking_findings:
        print(f"  BLOCKING {f.code}: {f.message}")
    svc.edit_statement(u["alice"], report.id, target.id, *original)
    print(f"Reverted. Blocking findings now: {len(report.open_blocking_findings)}")
    for f in report.findings:
        print(f"  {f.severity.upper()} {f.code}: {f.message}")

    (out_dir / "demo_report_review.docx").write_bytes(svc.render(u["alice"], report.id, "review"))

    banner("Review and approval")
    svc.submit(u["alice"], report.id)
    try:
        svc.approve(u["bob"], report.id)
    except WorkflowError as exc:
        print("Bob approves before reviewing each AI section ->", exc)
    for slot in sorted(report.ai_slots):
        svc.mark_reviewed(u["bob"], report.id, slot)
    try:
        svc.approve(u["alice"], report.id)
    except WorkflowError as exc:
        print("Alice tries to approve her own report ->", exc)
    svc.approve(u["bob"], report.id, "Checked against source documents")
    svc.finalise(u["bob"], report.id)
    print(f"Final: status={report.status} sha256={report.final_sha256[:16]}…")

    for variant in ("client", "review", "evidence"):
        path = out_dir / f"demo_report_{variant}.docx"
        path.write_bytes(svc.render(u["bob"], report.id, variant))
        print(f"Wrote {path.relative_to(ROOT)}")

    banner("Audit")
    ok, bad = verify_chain(svc.audit.events)
    print(f"{len(svc.audit.events)} events, hash chain valid: {ok}")
    for e in svc.audit.events[-6:]:
        print(f"  #{e.seq} {e.actor:7} {e.action:24} {e.object_type}:{e.object_id}")
    tampered = list(svc.audit.events)
    tampered[5] = tampered[5].model_copy(update={"actor": "mallory"})
    print("After altering event #6:", verify_chain(tampered))


if __name__ == "__main__":
    main()
