from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import ROOT

client = TestClient(app)


def h(user):
    return {"X-Dev-User": user}


def test_unauthenticated_rejected():
    assert client.get("/cases").status_code == 401


def test_case_flow_and_scoping():
    r = client.post("/cases", json={"client_ref": "CRM-9", "team": "north"}, headers=h("alice"))
    assert r.status_code == 200, r.text
    case_id = r.json()["id"]
    data = (ROOT / "samples" / "pension_statement.txt").read_bytes()
    r = client.post(f"/cases/{case_id}/documents", files={"file": ("s.txt", data, "text/plain")},
                    headers=h("alice"))
    assert r.status_code == 200 and r.json()["doc_type"] == "pension_statement"
    record = client.get(f"/cases/{case_id}/record", headers=h("alice")).json()
    fact = record["facts"][0]
    span_id = fact["sources"][0]["span_id"]
    assert client.get(f"/spans/{span_id}", headers=h("alice")).json()["span"]["page"] == 1
    assert client.get(f"/cases/{case_id}/record", headers=h("sam")).status_code == 403
    assert client.post(f"/cases/{case_id}/reports", headers=h("alice")).status_code in (200, 409)


def test_audit_verification_requires_auditor():
    assert client.get("/audit/verify", headers=h("alice")).status_code == 403
    r = client.get("/audit/verify", headers=h("erin"))
    assert r.status_code == 200 and r.json()["ok"] is True


def test_demo_mode_uses_labelled_scripted_drafter(monkeypatch):
    from app.main import build_service

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_DEMO", "1")
    assert build_service().drafter.name == "scripted-demo-drafter"
    monkeypatch.delenv("APP_DEMO")
    assert build_service().drafter.name == "fact-listing-fallback"
