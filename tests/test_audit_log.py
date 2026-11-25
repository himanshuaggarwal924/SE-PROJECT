import json

import audit_log
import config


def test_events_are_appended_as_json_lines():
    audit_log.log_event("run-1", "a", x=1)
    audit_log.log_event("run-2", "b")
    lines = config.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["a", "b"]


def test_read_events_filters_by_run():
    audit_log.log_event("run-1", "a")
    audit_log.log_event("run-2", "b")
    assert [e["event"] for e in audit_log.read_events("run-2")] == ["b"]
    assert len(audit_log.read_events()) == 2


def test_run_ids_are_unique():
    assert audit_log.new_run_id() != audit_log.new_run_id()
