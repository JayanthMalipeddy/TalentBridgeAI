"""A report composed solely from the versioned LLM assessment and verified quotes."""
from ..contracts import Report, EvidenceRef
from .common import digest


def build(case,assessment,config):
    rows=assessment['criteria']
    score=assessment['score']
    summary=(f"{case['role']}: {score:.2f}% against a {assessment['threshold']}% threshold. "
             if score is not None else f"{case['role']}: insufficient evidence. ")
    summary+=assessment['recommendation'].replace('_',' ')+'. HR confirmation is required.'
    evidence=[];seen=set()
    for row in rows:
        for ref in row['evidence']:
            key=(ref['turn_id'],ref['excerpt'])
            if key not in seen:
                seen.add(key)
                evidence.append(EvidenceRef(source_type='transcript',source_id=ref['turn_id'],locator=ref['turn_id'],excerpt=ref['excerpt']))
    return Report(case_id=case['case_id'],report_version='hr-'+digest({'assessment':assessment['version'],'config':config['version']})[:20],
        mode='recruitment',summary=summary,
        strengths=[r['criterion']['title']+': '+r['rationale'] for r in rows if r['score'] is not None and r['score']>=3],
        gaps=[r['criterion']['title']+': '+r['rationale'] for r in rows if r['score'] is None or r['score']<3],
        evidence=evidence,suggested_next_steps=['Review criterion evidence, recipients and the CV, then confirm shortlist, rejection or hold.'],
        learning_resources=[],draft_email=config['data'].get('approved_summary') or '\n\n'.join(r['criterion']['title']+': '+r['rationale'] for r in rows),approval_status='draft')
