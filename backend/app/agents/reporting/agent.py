from ...contracts import CaseInput, InterviewPlan, InterviewResult, Assessment, Report
from ...context import AgentContext
from uuid import uuid4
from ...errors import AppError

async def build_report(case: CaseInput, plan: InterviewPlan, interview: InterviewResult, assessment: Assessment, ctx: AgentContext) -> Report:
    """Build an evidence-preserving report without another provider call.

    The assessment owns judgments; reporting never upgrades them or invents scores.
    Persistence and approval remain the repository/workflow's responsibility.
    """
    if not (case.case_id == plan.case_id == interview.case_id == assessment.case_id) or assessment.plan_version != plan.plan_version:
        raise AppError("REPORT_CONTEXT_MISMATCH", "Report inputs must belong to the same case and plan", 409)
    if not interview.consent_confirmed or interview.status not in {"completed", "incomplete"} or not interview.turns:
        raise AppError("INCOMPLETE_INTERVIEW", "A finished, consented interview with transcript evidence is required for a report", 409)
    turns = {turn.turn_id: turn for turn in interview.turns}
    evidence = []
    seen = set()
    for skill in assessment.skills:
        for ref in skill.evidence:
            # An excerpt is evidence only when it is an exact candidate utterance.
            turn = turns.get(ref.source_id)
            if ref.source_type != "transcript" or not turn or turn.speaker != "candidate" or not ref.excerpt.strip() or ref.excerpt not in turn.text:
                raise AppError("INVALID_REPORT_EVIDENCE", "Assessment evidence must reference an exact candidate transcript excerpt", 409)
            key = (ref.source_id, ref.locator, ref.excerpt)
            if key not in seen:
                seen.add(key)
                evidence.append(ref)
    strengths = [f"{s.skill}: {s.rationale}" for s in assessment.skills if s.status == "demonstrated"]
    gaps = [f"{s.skill} ({s.status.replace('_', ' ')}): {s.rationale}" for s in assessment.skills if s.status != "demonstrated"]
    gaps.extend(assessment.limitations)
    if interview.status == "incomplete":
        gaps.append("Interview coverage is incomplete. Missing answers are not evidence of failure.")
    next_steps = []
    for skill in assessment.skills:
        if case.mode == "mock" and skill.status != "demonstrated":
            next_steps.append(f"Practise {skill.skill}: describe a specific example, explain your decisions and the outcome, then address this feedback: {skill.rationale}")
        elif skill.needs_verification or skill.status != "demonstrated":
            next_steps.append(f"Verify {skill.skill}: ask for a concrete example and supporting detail addressing: {skill.rationale}")
    summary = f"{case.role} — {round(assessment.coverage * 100)}% assessment coverage. {assessment.recommendation.replace('_', ' ')}. Review the supporting evidence and limitations before making decisions."
    return Report(case_id=case.case_id, report_version=str(uuid4()), mode=case.mode,
                  summary=summary, strengths=strengths, gaps=gaps, evidence=evidence,
                  suggested_next_steps=next_steps, learning_resources=[],
                  draft_email=(f"Subject: {case.role} interview review\n\n{summary}\n\nStrengths:\n" + "\n".join(strengths or ["No demonstrated strengths recorded."]) + "\n\nGaps and limitations:\n" + "\n".join(gaps or ["None recorded."]) + "\n\nVerification questions:\n" + "\n".join(next_steps or ["Review the evidence before submission."])) if case.mode == "recruitment" else None,
                  approval_status="draft" if case.mode == "recruitment" else "not_applicable")
