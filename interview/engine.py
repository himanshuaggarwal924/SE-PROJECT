"""
interview/engine.py - The adaptive interview loop.

After each answer, deterministic checks decide first (instant):
  * contradicts an earlier answer (same unit, different value - e.g. a
    ₹5 lakh limit, later ₹10 lakh)              -> follow-up asking which is right
  * very short (< INTERVIEW_MIN_WORDS words)      -> follow-up
  * vague words ("fast", "secure"...) and no number -> follow-up
  * topic needs a number (limits, retention...) and none given -> follow-up
  * long (>= INTERVIEW_CLEAR_WORDS words) and contains a number -> complete
Only a BORDERLINE answer (none of the above) goes to the model, in ONE call
(prompts/interview_agent.yaml): complete or vague, plus a follow-up question.

A topic gets at most INTERVIEW_MAX_FOLLOWUPS follow-ups, then the interview
moves on, so it can never loop. Questions for new topics are the role
template's starter question, plus a pointer to the most similar knowledge-base
section (MiniLM, pre-computed per topic; shown only above
INTERVIEW_KB_HINT_MIN_SIMILARITY) added by plain string formatting. If the model is
unavailable, a borderline answer is accepted - the interview never gets stuck.

A session is a plain dict (JSON-serialisable), so it can live in Streamlit's
session_state and be saved as-is.
"""

import re
import uuid
from datetime import datetime

import audit_log
import config
import llm_service
from agents.prompt_builder import build_messages
from agents.registry import INTERVIEW_AGENT
from agents.schemas import InterviewTurnDraft, strict_json_schema
from checks.grounding import extract_numbers
from checks.quality import content_words, find_vague_words, jaccard, quantities
from interview.templates import ensure_topic_hints, role_templates, topic_pointer, topics
from output_parser import parse_agent_output
from security.injection import scan, wrap_data


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _add_turn(session: dict, speaker: str, text: str, kind: str, assessment: dict | None = None) -> dict:
    turn = {"n": len(session["turns"]) + 1, "speaker": speaker,
            "role": session["role_label"] if speaker == "stakeholder" else "Interviewer",
            "text": text, "topic": session["current_topic"], "kind": kind,
            "timestamp": _now(), "assessment": assessment, "edited": False}
    session["turns"].append(turn)
    return turn


def topic_question(session: dict, topic: str) -> str:
    """The template's starter question, plus a pointer to matching KB text."""
    question = role_templates()[session["role"]]["topics"][topic]
    hint = topic_pointer(topic)       # MiniLM match, pre-computed (None below the threshold)
    if hint:
        question += f" (For reference, our knowledge base covers this in “{hint['title']} – {hint['section']}”.)"
    return question


def start_session(role: str, scenario: str, stakeholder_name: str = "", user: str | None = None) -> dict:
    template = role_templates()[role]
    first = next(iter(template["topics"]))
    ensure_topic_hints()      # one-time MiniLM matching when the KB or topics changed
    session = {
        "id": "iv-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
        "source": "interview", "created_by": user, "created_at": _now(),
        "role": role, "role_label": template["display_name"],
        "stakeholder_name": stakeholder_name.strip(), "scenario": scenario.strip(),
        "turns": [], "coverage": {t: "pending" for t in template["topics"]},
        "followups": {t: 0 for t in template["topics"]},
        "current_topic": first, "current_question": "", "status": "active",
    }
    session["current_question"] = topic_question(session, first)
    _add_turn(session, "interviewer", session["current_question"], "question")
    audit_log.log_event(session["id"], "interview_started", user=user, role=role,
                        stakeholder=session["stakeholder_name"], scenario=session["scenario"])
    return session


def next_pending_topic(session: dict) -> str | None:
    return next((t for t, status in session["coverage"].items() if status == "pending"), None)


# ----------------------------------------------------- deterministic checks --
def _contradiction(session: dict, answer: str, topic: str) -> str | None:
    """An earlier answer giving a different value for the same unit, on the
    same topic or a clearly overlapping subject. Returns a description."""
    mine = quantities(answer)
    if not mine:
        return None
    words = content_words(answer)
    for turn in session["turns"]:
        if turn["speaker"] != "stakeholder":
            continue
        same_subject = turn.get("topic") == topic or jaccard(words, content_words(turn["text"])) >= 0.2
        if not same_subject:
            continue
        theirs = quantities(turn["text"])
        for unit in mine.keys() & theirs.keys():
            if not (mine[unit] & theirs[unit]):
                return (f"Earlier you said {', '.join(sorted(theirs[unit]))}, now "
                        f"{', '.join(sorted(mine[unit]))}")
    return None


def classify(session: dict, answer: str) -> dict:
    """Instant verdict from the rules: {"verdict", "reason", "question"}.
    verdict: inconsistent | too_short | vague | missing_number | complete | borderline."""
    topic = session["current_topic"]
    info = topics()[topic]
    label = info["label"].lower()
    numbers = extract_numbers(answer)
    words = len(answer.split())

    contradiction = _contradiction(session, answer, topic)
    if contradiction:
        return {"verdict": "inconsistent", "reason": contradiction + ".",
                "question": f"{contradiction}. Which value is correct, and does it apply in every case?"}
    if words < config.INTERVIEW_MIN_WORDS:
        return {"verdict": "too_short", "reason": "The answer is very short.",
                "question": f"Could you tell me more about {label}? For example: {info['description']}."}
    vague = find_vague_words(answer)
    if vague and not numbers:
        return {"verdict": "vague", "reason": f"Vague term(s) without a measurable value: {', '.join(vague)}.",
                "question": f"You said “{vague[0]}”. What would that mean in measurable terms - "
                            f"for example a time, amount, percentage or named control?"}
    if info.get("needs_number") and not numbers:
        return {"verdict": "missing_number", "reason": "No concrete number was given.",
                "question": f"Could you give the specific values for {label} (amounts, times or periods)?"}
    if numbers and words >= config.INTERVIEW_CLEAR_WORDS:
        return {"verdict": "complete", "reason": "Detailed answer with concrete values.", "question": ""}
    return {"verdict": "borderline", "reason": "", "question": ""}


# ------------------------------------------------------------- model check --
def _earlier_answers(session: dict, limit: int = 6) -> str:
    answers = [t for t in session["turns"] if t["speaker"] == "stakeholder"][-limit:]
    return "\n".join(f"- ({topics()[t['topic']]['label']}) {t['text'][:300]}"
                     for t in answers if t.get("topic") in topics()) or "None yet."


def _assess_with_model(session: dict, answer: str, model_name: str) -> InterviewTurnDraft | None:
    """ONE call: complete/vague/inconsistent + a follow-up question. None if unavailable."""
    topic = topics()[session["current_topic"]]
    variables = {
        "scenario": session["scenario"] or "the planned finance system",
        "stakeholder_role": session["role_label"], "topic_label": topic["label"],
        "topic_description": topic["description"], "question": session["current_question"],
        # The stakeholder's words are data, never instructions.
        "answer": wrap_data(answer, "answer", inline=True),
        "earlier_answers": wrap_data(_earlier_answers(session), "earlier answers"),
    }
    system_prompt, user_prompt = build_messages(INTERVIEW_AGENT, variables, {})
    try:
        response = llm_service.chat(system_prompt, user_prompt, model_name,
                                    json_schema=strict_json_schema(InterviewTurnDraft))
    except Exception as error:          # Ollama down, timeout...
        audit_log.log_event(session["id"], "agent_call", agent=INTERVIEW_AGENT.display_name,
                            parse_error=f"Model unavailable: {error}")
        return None
    parsed, error = parse_agent_output(response.text, InterviewTurnDraft)
    audit_log.log_event(session["id"], "agent_call", agent=INTERVIEW_AGENT.display_name,
                        seconds=response.seconds, input={"user_prompt": user_prompt},
                        output=response.text, parse_error=error)
    return parsed


# ------------------------------------------------------------------ the loop --
def submit_answer(session: dict, answer: str, model_name: str = config.MODEL_NAME) -> dict:
    """Record an answer, assess it (rules first, model only if borderline),
    then follow up or ask the next topic's question (or end)."""
    answer = answer.strip()
    if not answer or session["status"] != "active":
        return session
    topic = session["current_topic"]

    rule = classify(session, answer)
    assessment = {"verdict": rule["verdict"], "source": "rules", "reason": rule["reason"]}
    suspicious = scan(answer)
    if suspicious:
        assessment["injection_patterns"] = suspicious
    follow_up = rule["question"]
    if rule["verdict"] == "borderline":
        draft = _assess_with_model(session, answer, model_name)
        if draft is None:
            assessment.update(verdict="complete", source="rules (model unavailable)",
                              reason="Accepted: no problem found by the automatic checks.")
        else:
            assessment.update(verdict=draft.assessment, source="model", reason=draft.reason)
            follow_up = draft.follow_up_question.strip() or \
                f"Could you be more specific about {topics()[topic]['label'].lower()}?"
    weak = assessment["verdict"] != "complete"
    assessment["weak"] = weak
    _add_turn(session, "stakeholder", answer, "answer", assessment)

    if weak and session["followups"][topic] < config.INTERVIEW_MAX_FOLLOWUPS:
        session["followups"][topic] += 1
        session["current_question"] = follow_up
        _add_turn(session, "interviewer", follow_up, "follow_up")
        decision = "follow_up"
    else:
        session["coverage"][topic] = "partial" if weak else "covered"
        decision = _move_on(session)

    audit_log.log_event(session["id"], "interview_answer", topic=topic, assessment=assessment,
                        decision=decision)
    return session


def _move_on(session: dict) -> str:
    """Go to the next pending topic, or end the interview if none is left."""
    topic = next_pending_topic(session)
    if topic is None:
        end_session(session)
        return "ended"
    session["current_topic"] = topic
    session["current_question"] = topic_question(session, topic)
    _add_turn(session, "interviewer", session["current_question"], "question")
    return f"next_topic:{topic}"


def skip_topic(session: dict) -> dict:
    if session["status"] == "active":
        session["coverage"][session["current_topic"]] = "skipped"
        audit_log.log_event(session["id"], "interview_skipped", topic=session["current_topic"])
        _move_on(session)
    return session


def edit_answer(session: dict, turn_number: int, new_text: str) -> dict:
    turn = next(t for t in session["turns"] if t["n"] == turn_number)
    if turn["speaker"] != "stakeholder":
        raise ValueError("Only stakeholder answers can be edited.")
    audit_log.log_event(session["id"], "interview_edited", turn=turn_number,
                        before=turn["text"], after=new_text.strip())
    turn.update(text=new_text.strip(), edited=True, edited_at=_now())
    return session


def end_session(session: dict) -> dict:
    if session["status"] != "ended":
        session["status"] = "ended"
        session["ended_at"] = _now()
        audit_log.log_event(session["id"], "interview_ended", coverage=session["coverage"])
    return session


def coverage_ratio(session: dict) -> float:
    done = sum(status in ("covered", "partial") for status in session["coverage"].values())
    return done / len(session["coverage"]) if session["coverage"] else 0.0


# ------------------------------------------------------- to the pipeline --
def transcript_segments(sessions: list[dict]) -> list[dict]:
    """One segment per stakeholder answer (with the question it answered),
    so a requirement can cite - and link back to - the exact answer."""
    segments = []
    for session in sessions:
        question = ""
        for turn in session["turns"]:
            if turn["speaker"] == "interviewer":
                question = turn["text"]
                continue
            segments.append({
                "text": (f"Q: {question}\nA: {turn['text']}" if question else turn["text"]),
                "speaker_role": turn.get("role") or session["role_label"],
                "stakeholder": session.get("stakeholder_name") or "",
                "interview_id": session["id"], "turn": turn["n"],
                "timestamp": turn["timestamp"], "topic": turn.get("topic") or "",
            })
    return segments


def segment_label(segment: dict) -> str:
    # Prompts show the masked name (<NAME_n>) when the pipeline masked it.
    name = segment.get("stakeholder_masked") or segment.get("stakeholder")
    who = f"{name}, " if name else ""
    topic = topics().get(segment.get("topic") or "", {}).get("label", "")
    return (f"Interview {segment['interview_id']}, {who}{segment['speaker_role']}, answer {segment['turn']}"
            + (f", topic: {topic}" if topic else ""))


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:80]
