"""
interview/importer.py - Turns questionnaires, emails or meeting notes into a
transcript (the same structure as a live interview), so they can be sent to
the analysis pipeline and cited answer by answer.

Recognised (deterministically, no LLM):
  "Q: ..." / "A: ..."                 questionnaire
  "Priya (Compliance): ..."           speaker lines in meeting notes
  "From: ..." + body                  emails (Subject/To/Cc/Date are ignored)
  anything else                       one answer per paragraph
"""

import re
import uuid
from datetime import datetime

from interview.templates import role_templates

SPEAKER_LINE = re.compile(r"^\s*([A-Za-z][\w .()/&'-]{0,48}?)\s*:\s+(.+)$")
QUESTION_SPEAKERS = {"q", "question", "interviewer", "analyst", "ba"}
ANSWER_SPEAKERS = {"a", "answer", "response"}
IGNORED_HEADERS = {"subject", "to", "cc", "bcc", "date", "sent"}


def _speaker(line: str) -> tuple[str, str] | None:
    """(speaker key as written, content) for a 'Name: text' line, else None."""
    match = SPEAKER_LINE.match(line)
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def parse_turns(text: str, default_role: str) -> list[dict]:
    """[{speaker: interviewer|stakeholder, role, text}] from free text."""
    lines = text.replace("\r\n", "\n").split("\n")
    has_speakers = any((s := _speaker(line)) and s[0].lower() not in IGNORED_HEADERS for line in lines)
    if not has_speakers:
        # Plain notes: every paragraph is one answer from the chosen role.
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
        return [{"speaker": "stakeholder", "role": default_role, "text": p} for p in paragraphs]

    turns: list[dict] = []
    for line in lines:
        speaker = _speaker(line)
        if speaker:
            name, content = speaker
            key = name.lower()
            if key in IGNORED_HEADERS:
                continue
            if key == "from":            # email: the body that follows is this sender's
                turns.append({"speaker": "stakeholder", "role": content, "text": ""})
            elif key in QUESTION_SPEAKERS:
                turns.append({"speaker": "interviewer", "role": "Interviewer", "text": content})
            elif key in ANSWER_SPEAKERS:
                turns.append({"speaker": "stakeholder", "role": default_role, "text": content})
            else:
                turns.append({"speaker": "stakeholder", "role": name, "text": content})
        elif line.strip() and turns:     # continuation of the previous speaker
            turns[-1]["text"] = f"{turns[-1]['text']} {line.strip()}".strip()
    return [t for t in turns if t["text"]]


def import_transcript(text: str, role: str, source_name: str, user: str | None,
                      scenario: str = "") -> dict:
    """A saved-transcript dict (same shape as an interview session)."""
    role_label = role_templates()[role]["display_name"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    session = {
        "id": "imp-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
        "source": f"imported: {source_name}", "created_by": user, "created_at": now,
        "role": role, "role_label": role_label, "stakeholder_name": "", "scenario": scenario,
        "turns": [], "coverage": {}, "followups": {}, "current_topic": "", "current_question": "",
        "status": "ended", "ended_at": now,
    }
    for number, turn in enumerate(parse_turns(text, role_label), start=1):
        session["turns"].append({
            "n": number, "speaker": turn["speaker"], "role": turn["role"], "text": turn["text"],
            "topic": "", "kind": "question" if turn["speaker"] == "interviewer" else "answer",
            "timestamp": now, "assessment": None, "edited": False})
    return session
