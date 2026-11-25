"""Phase 12: stakeholder satisfaction form."""

import pytest
from streamlit.testing.v1 import AppTest

import audit_log
from storage import db, feedback


def test_submit_and_summary():
    feedback.submit("ana", 4, "Clear and traceable.", "run-1")
    feedback.submit("bob", 2, "")
    assert feedback.summary() == {"responses": 2, "mean": 3.0, "distribution": {1: 0, 2: 1, 3: 0, 4: 1, 5: 0}}
    assert feedback.entries()[-1]["comment"] == "Clear and traceable."
    stored = db.query("SELECT comment FROM satisfaction WHERE run_id = 'run-1'")[0]["comment"]
    assert stored.startswith("enc:v1:")                                   # comments encrypted at rest
    assert [e["event"] for e in audit_log.read_events("run-1")] == ["satisfaction_submitted"]


@pytest.mark.parametrize("score", [0, 6])
def test_score_must_be_1_to_5(score):
    with pytest.raises(ValueError):
        feedback.submit("ana", score)


def _page():
    from ui.page_evaluation import render_evaluation_page
    render_evaluation_page()


def test_form_on_the_evaluation_page():
    app = AppTest.from_function(_page)
    app.session_state["username"] = "ana"
    app.run(timeout=120)
    assert not app.exception, app.exception
    app.radio[0].set_value(5)
    app.text_area[0].set_value("Great")
    next(b for b in app.button if b.label == "Submit rating").click().run(timeout=120)
    assert not app.exception, app.exception
    assert feedback.summary()["responses"] == 1 and feedback.entries()[0]["comment"] == "Great"
