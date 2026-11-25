"""Phase 5: templates, the adaptive interview loop (rules first, model only
for borderline answers), transcripts, imports, and interviews as pipeline input."""

import pytest

import audit_log
import config
import llm_service
from checks.quality import quantities
from interview import engine, store
from interview.importer import import_transcript, parse_turns
from interview.templates import kb_hints, role_templates, topics
from pipeline import run_pipeline
from tests.mock_llm import make_requirement


@pytest.fixture(autouse=True)
def interviews_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INTERVIEWS_DIR", tmp_path / "interviews")


# ---------------------------------------------------------------- templates --
def test_all_nine_roles_and_thirteen_topics():
    assert len(topics()) == 13
    assert set(role_templates()) == {
        "customer", "business_analyst", "product_owner", "architect", "information_security",
        "compliance_legal", "risk_management", "operations", "auditor_regulator"}
    covered = {t for r in role_templates().values() for t in r["topics"]}
    assert covered == set(topics())          # every topic is asked by at least one role


def test_kb_hints_are_context_aware():
    hints = kb_hints("data_collection_retention")
    assert hints and any("retain" in h["text"].lower() or "retention" in h["text"].lower() for h in hints)
    assert kb_hints("schedule_budget") == []


@pytest.mark.parametrize("text, expected", [
    ("The limit is ₹5 lakh per loan", {"₹5 lakh"}),
    ("Rs. 10,00,000 needs approval", {"₹10 lakh"}),
    ("above 2 crore", {"₹2 crore"}),
    ("INR 50,000 daily", {"₹50,000"}),
    ("₹500,000 and ₹5 lakh are the same", {"₹5 lakh"}),
])
def test_rupee_amounts_are_normalised(text, expected):
    assert quantities(text)["INR"] == expected


def test_plain_numbers_are_not_money():
    assert "INR" not in quantities("We have 5 teams and 3 offices")


# ------------------------------------------------------------ the adaptive loop --
def start(role="compliance_legal"):
    return engine.start_session(role, "Personal loan approval", "Priya", user="alice")


def go_to(session, topic):
    while session["current_topic"] != topic:
        engine.skip_topic(session)


def last(session):
    return session["turns"][-1]


def last_answer(session):
    return [t for t in session["turns"] if t["speaker"] == "stakeholder"][-1]


def test_new_topic_question_is_template_starter_plus_kb_pointer():
    session = start()
    topic = session["current_topic"]
    starter = role_templates()["compliance_legal"]["topics"][topic]
    assert last(session)["text"].startswith(starter)
    assert "knowledge base covers this" in last(session)["text"]


def test_long_answer_with_numbers_is_complete_without_model(mock_llm):
    session = start()
    go_to(session, "data_collection_retention")
    engine.submit_answer(session, "We keep application records for 8 years and identity documents "
                                  "for 5 years after the account closes, then delete them.")
    assert last_answer(session)["assessment"]["verdict"] == "complete"
    assert last_answer(session)["assessment"]["source"] == "rules"
    assert session["coverage"]["data_collection_retention"] == "covered"
    assert mock_llm.calls == []                                   # instant: no model call


def test_vague_answer_gets_one_rule_follow_up_and_never_loops(mock_llm):
    session = start()
    topic = session["current_topic"]
    engine.submit_answer(session, "It should be fast and secure")
    assert last_answer(session)["assessment"]["verdict"] == "vague"
    assert last(session)["kind"] == "follow_up" and "fast" in last(session)["text"]
    engine.submit_answer(session, "It should be fast and secure, really")
    assert session["coverage"][topic] == "partial"                # max one follow-up
    assert session["current_topic"] != topic and last(session)["kind"] == "question"
    assert mock_llm.calls == []


def test_one_word_answer_gets_follow_up_without_model(mock_llm):
    session = start()
    engine.submit_answer(session, "Yes")
    assert last_answer(session)["assessment"]["verdict"] == "too_short"
    assert last(session)["kind"] == "follow_up"
    assert mock_llm.calls == []


def test_missing_number_on_a_number_topic(mock_llm):
    session = start()
    go_to(session, "transaction_limits")
    engine.submit_answer(session, "Large loans need extra checks by the compliance team before approval.")
    assert last_answer(session)["assessment"]["verdict"] == "missing_number"
    assert last(session)["kind"] == "follow_up"
    assert mock_llm.calls == []


def test_contradicting_amounts_are_noticed(mock_llm):
    session = start()
    go_to(session, "transaction_limits")
    engine.submit_answer(session, "Any loan above ₹5 lakh must be approved by a senior credit officer "
                                  "before the money is released to the customer.")
    assert session["current_topic"] != "transaction_limits"        # complete, moved on
    engine.submit_answer(session, "Loans above ₹10 lakh need senior approval before the money is "
                                  "released, otherwise the system decides automatically.")
    assessment = last_answer(session)["assessment"]
    assert assessment["verdict"] == "inconsistent"
    assert "₹5 lakh" in assessment["reason"] and "₹10 lakh" in assessment["reason"]
    assert last(session)["kind"] == "follow_up" and "Which value is correct" in last(session)["text"]


def test_borderline_answer_goes_to_model_once(mock_llm):
    session = start()
    topic = session["current_topic"]
    engine.submit_answer(session, "Our internal credit policy and the customer due diligence standard "
                                  "both apply to every loan we approve.")
    assert len(mock_llm.calls) == 1
    assert last_answer(session)["assessment"]["source"] == "model"
    assert session["coverage"][topic] == "covered"                # mock says complete


def test_borderline_vague_answer_uses_model_follow_up(mock_llm):
    session = start()
    engine.submit_answer(session, "I am not sure, probably the usual banking rules apply to these loans.")
    assert last_answer(session)["assessment"]["verdict"] == "vague"
    assert last(session)["text"] == "MOCK FOLLOW-UP?"


def test_model_failure_accepts_borderline_answer(monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError("Ollama is not running")
    monkeypatch.setattr(llm_service, "chat", down)
    session = start()
    topic = session["current_topic"]
    engine.submit_answer(session, "Our internal credit policy and the due diligence standard apply here.")
    assert last_answer(session)["assessment"]["source"] == "rules (model unavailable)"
    assert session["coverage"][topic] == "covered"


def test_skip_edit_end_and_audit(mock_llm):
    session = start()
    engine.submit_answer(session, "Our credit policy and the due diligence standard apply to every loan.")
    answer = last_answer(session)
    engine.edit_answer(session, answer["n"], "Corrected answer text.")
    assert answer["text"] == "Corrected answer text." and answer["edited"]
    with pytest.raises(ValueError):
        engine.edit_answer(session, 1, "questions can't be edited")
    while session["status"] == "active":
        engine.skip_topic(session)
    assert session["status"] == "ended"
    events = [e["event"] for e in audit_log.read_events(session["id"])]
    assert events[0] == "interview_started"
    assert {"interview_answer", "interview_edited", "interview_skipped", "interview_ended"} <= set(events)


def test_every_turn_has_role_and_timestamp(mock_llm):
    session = start()
    engine.submit_answer(session, "We follow the internal credit policy for all personal loans.")
    for turn in session["turns"]:
        assert turn["timestamp"] and turn["role"] and turn["speaker"] in ("interviewer", "stakeholder")


# ---------------------------------------------------------------- the store --
def test_store_isolates_users_and_keeps_unfinished_interviews():
    mine = start()
    other = engine.start_session("operations", "x", user="bob")
    store.save(mine)
    store.save(other)
    found = store.list_sessions("alice")
    assert [s["id"] for s in found] == [mine["id"]]
    assert found[0]["status"] == "active"                          # can be resumed after a refresh
    assert store.load(mine["id"])["stakeholder_name"] == "Priya"


# ---------------------------------------------------------------- importer --
def test_parse_questionnaire():
    turns = parse_turns("Q: What limits apply?\nA: Loans above 50,000 need approval.\n"
                        "Q: Retention?\nA: Seven years.", "Compliance / legal")
    assert [t["speaker"] for t in turns] == ["interviewer", "stakeholder"] * 2
    assert turns[1] == {"speaker": "stakeholder", "role": "Compliance / legal",
                        "text": "Loans above 50,000 need approval."}


def test_parse_meeting_notes_with_continuation_lines():
    turns = parse_turns("Ravi (Operations): Batch runs at night\nand must finish by 6am.\n"
                        "Meena (Risk): Limits are reviewed quarterly.", "Business analyst")
    assert turns[0] == {"speaker": "stakeholder", "role": "Ravi (Operations)",
                        "text": "Batch runs at night and must finish by 6am."}
    assert turns[1]["role"] == "Meena (Risk)"


def test_parse_email_ignores_headers():
    turns = parse_turns("From: Priya (Compliance)\nTo: team\nSubject: KYC\n\n"
                        "KYC must be complete before the account opens.\nRegards", "Customer / end user")
    assert len(turns) == 1
    assert turns[0]["role"] == "Priya (Compliance)"
    assert turns[0]["text"].startswith("KYC must be complete")


def test_parse_plain_paragraphs():
    turns = parse_turns("First point about loans.\nStill the first point.\n\nSecond point.", "Operations")
    assert [t["text"] for t in turns] == ["First point about loans. Still the first point.", "Second point."]


def test_import_transcript_shape():
    session = import_transcript("Q: Limits?\nA: 50,000 per day.", "risk_management", "notes.txt", "alice")
    assert session["status"] == "ended" and session["created_by"] == "alice"
    assert session["turns"][1]["role"] == "Risk management"
    assert session["source"] == "imported: notes.txt"


# --------------------------------------------------- interviews -> pipeline --
def test_interview_answers_become_citable_excerpts(mock_llm):
    session = start()
    engine.submit_answer(session, "Loans above 50,000 must be approved by a senior underwriter.")
    segments = engine.transcript_segments([session])
    assert len(segments) == 1
    assert segments[0]["text"].startswith("Q: ") and "50,000" in segments[0]["text"]

    mock_llm.responses["RequirementsBatch"] = lambda s, u: {"scenario_summary": "x", "requirements": [
        make_requirement("FR-01", statement="The system shall route loans above 50,000 to a senior underwriter.",
                         sources=["C1"], source_stakeholder="someone the model guessed")]}
    result = run_pipeline("Loans", segments=segments, source_name="interviews",
                          options={"num_functional": 1, "num_non_functional": 1})
    assert result.context_info["method"] == "transcript"
    chunk = result.chunk_map["C1"]
    assert chunk["origin"] == "transcript" and chunk["interview_id"] == session["id"]
    assert chunk["turn"] == segments[0]["turn"]
    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert fr1.source_stakeholder == "Priya (Compliance / legal)"     # from the transcript, not the model
    assert not [f for f in fr1.flags if f.type == "possible_hallucination"]
    prompt = mock_llm.calls_for("RequirementsBatch")[0].user_prompt
    # Phase 9: the interviewee's name is masked in prompts (kept locally for the requirement).
    assert f"[C1] (Interview {session['id']}, <NAME_1>, Compliance / legal, answer" in prompt
    assert "Priya" not in prompt


def test_large_transcript_uses_answer_level_retrieval(mock_llm, fake_retrieval):
    segments = [{"text": f"Q: Topic {i}?\nA: " + "Detailed answer about loan rules. " * 20,
                 "speaker_role": "Operations", "stakeholder": "", "interview_id": "iv-x",
                 "turn": i, "timestamp": "2026-01-01T10:00:00", "topic": ""} for i in range(1, 30)]
    result = run_pipeline("Loans", segments=segments, source_name="interviews",
                          options={"num_functional": 1, "num_non_functional": 1})
    assert result.context_info["method"] == "transcript_retrieval"
    job = next(j for j in fake_retrieval if j.get("document"))
    assert job["document"]["segments"] == [s["text"] for s in segments]   # one chunk per answer
    turns = [c["turn"] for c in result.chunk_map.values() if c.get("origin") == "transcript"]
    assert turns and all(1 <= t <= 29 for t in turns)


# ------------------------------------------ embedding-based KB pointers (5.1) --
def test_topic_hints_are_computed_once_and_cached(fake_retrieval):
    from interview.templates import ensure_topic_hints
    first = ensure_topic_hints()
    assert set(first) == set(topics())
    jobs = len([j for j in fake_retrieval if j.get("topic_texts")])
    ensure_topic_hints()
    assert len([j for j in fake_retrieval if j.get("topic_texts")]) == jobs      # cache reused


def test_topic_hints_recomputed_when_kb_allowlist_changes(fake_retrieval, monkeypatch):
    from interview.templates import ensure_topic_hints
    ensure_topic_hints()
    monkeypatch.setattr(config, "KB_ALLOWED_SOURCES", config.KB_ALLOWED_SOURCES[:-1])
    ensure_topic_hints()
    assert len([j for j in fake_retrieval if j.get("topic_texts")]) == 2


def test_no_pointer_below_threshold(monkeypatch):
    monkeypatch.setattr(config, "INTERVIEW_KB_HINT_MIN_SIMILARITY", 0.99)
    session = start()
    assert "knowledge base covers this" not in last(session)["text"]


def test_no_pointer_when_embeddings_unavailable(monkeypatch):
    import context_loader

    def broken(job):
        raise RuntimeError("no torch")
    monkeypatch.setattr(context_loader, "_run_retrieval_worker", broken)
    session = start()
    starter = role_templates()["compliance_legal"]["topics"][session["current_topic"]]
    assert last(session)["text"] == starter
