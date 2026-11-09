"""Exact weighted scoring; omitted evidence never silently shrinks the denominator."""
from decimal import Decimal
from .contracts import Findings

def calculate(rubric, findings: Findings, interview, threshold):
    turns={t['turn_id']:t for t in interview['turns']}
    rows=[]
    for criterion in rubric['criteria']:
        matches=[f for f in findings.findings if f.criterion_id==criterion['criterion_id']]
        f=matches[0].model_dump() if len(matches)==1 else None
        valid=bool(f and f['score'] is not None and f['evidence'])
        if valid:
            valid=all(e['turn_id'] in turns and turns[e['turn_id']]['speaker']=='candidate' and e['excerpt'].strip() and e['excerpt'] in turns[e['turn_id']]['text'] and turns[e['turn_id']].get('question_id') in (None,criterion['question_id']) for e in f['evidence'])
        rows.append(dict(criterion=criterion,score=f['score'] if valid else None,
                         rationale=f['rationale'] if valid else 'Insufficient evidence: missing, ambiguous or invalid transcript citation.',
                         evidence=f['evidence'] if valid else [],uncertainty=f['uncertainty'] if f else 'Missing finding'))
    sufficient=interview['status']=='completed' and findings.transcript_quality_sufficient and all(r['score'] is not None and not r['uncertainty'].strip() for r in rows)
    exact=None
    if sufficient:
        numerator=sum(Decimal(str(r['criterion']['weight']))*Decimal(r['score']) for r in rows)
        denominator=sum(Decimal(str(r['criterion']['weight']))*4 for r in rows)
        exact=100*numerator/denominator
    recommendation='insufficient_evidence' if exact is None else 'recommend_shortlist' if exact>=Decimal(str(threshold)) else 'below_threshold'
    return {'criteria':rows,'score':float(exact) if exact is not None else None,'unrounded_score':str(exact) if exact is not None else None,'threshold':threshold,'recommendation':recommendation,
            'explanation':'Insufficient evidence — HR review required.' if exact is None else 'Performance against the reviewed rubric, not a probability of job success.'}
