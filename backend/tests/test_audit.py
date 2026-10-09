from app.audit import AuditLog, verify_chain


def _log():
    log = AuditLog()
    for i in range(5):
        log.record("alice", "fact.verify", "fact", f"f{i}", case_id="c1")
    return log


def test_chain_valid():
    assert verify_chain(_log().events) == (True, None)


def test_modification_detected():
    events = list(_log().events)
    events[2] = events[2].model_copy(update={"actor": "mallory"})
    assert verify_chain(events) == (False, 3)


def test_deletion_and_reordering_detected():
    events = list(_log().events)
    assert verify_chain(events[:2] + events[3:])[0] is False
    assert verify_chain([events[1], events[0], *events[2:]])[0] is False
