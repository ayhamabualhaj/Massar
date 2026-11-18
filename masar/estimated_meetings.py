"""Explicitly approved contact-time estimates for missing degree-plan courses."""
import copy

from .validation import need, prepare


def with_estimated_meetings(reference, curriculum, course_codes):
    output = copy.deepcopy(reference)
    records = curriculum['records']
    index = {}
    for row in records:
        if row['category'] in ('كلية إجباري', 'تخصص إجباري', 'تخصص اختياري'):
            index[row['course_code']] = row
    need(isinstance(course_codes, list) and len(course_codes)==len(set(course_codes)),
         'Estimated meeting codes must be a unique list.')
    approved = set(course_codes)
    need(approved <= index.keys(), 'Estimated meetings require exact IT degree-plan codes.')
    existing = {s['course_code'] for s in reference['sections'] if s['status']=='scheduled'}
    estimates = [copy.deepcopy(r) for r in reference.get('estimated_meeting_patterns',[])
                 if r['course_code'] in approved]
    # A course previously listed without meeting days now receives approved
    # estimated meetings. Its old nonmeeting placeholders must not duplicate it.
    output['sections'] = [s for s in output['sections']
                          if not (s['course_code'] in approved-existing and s['status']=='no_meeting_days')]
    for code in sorted(approved-existing):
        row = index[code]
        credits = row['credit_hours']
        lab = 'مختبر' in row['course_name']
        need(credits in (1,2,3), f'{code}: no approved estimate for {credits} credits.')
        need(not lab or credits==1, f'{code}: only the one-credit lab estimate was approved.')
        if credits==3:
            patterns = ['UTT60', 'MW90']
        elif credits==2:
            patterns = ['UT60']
        else:
            patterns=[]
            for day in (7,1,2,3,4):
                pid=f'ESTIMATED_SINGLE60_D{day}'
                output['patterns'][pid]=dict(days=[day], duration=60,
                                             starts=list(output['patterns']['TH60']['starts']))
                patterns.append(pid)
        requirement = 'computers' if lab else 'lecture'
        for number, pid in enumerate(patterns,1):
            output['sections'].append(dict(id=f'{code}_estimated_template_{number}',
                course_code=code,name_ar=row['course_name'],section_number=number,
                status='scheduled',pattern_id=pid,delivery='in_person',
                room_requirement=requirement,students=1,source_start=output['patterns'][pid]['starts'][0],
                unmodeled_student_count=1,meeting_pattern_status='estimated_user_approved',
                assumptions=['User-approved estimated contact pattern: 3-credit lecture 3x60 or 2x90; 2-credit lecture 2x60; 1-credit lab one 60-minute meeting. Not an official meeting assignment.',
                             'Template enrollment is a placeholder; intake-derived demand replaces it, never adds to it.'],
                sources=[dict(file='course_requirements/five_majors_degree_plans.json',course_code=code,
                              source_image=row.get('source_image',''))]))
        estimates.append(dict(course_code=code,course_name=row['course_name'],credits=credits,
                              room_requirement=requirement,pattern_ids=patterns,
                              status='estimated_user_approved'))
    output['estimated_meeting_patterns']=sorted(estimates,key=lambda row:row['course_code'])
    output['groups']=[]
    prepare(output)
    return output
