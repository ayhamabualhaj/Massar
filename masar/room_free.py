"""Field training and graduation projects retain enrollment but reserve no room."""
import copy

from .validation import need, prepare


def with_room_free_activities(reference,curriculum,codes):
    output=copy.deepcopy(reference)
    catalog={r['course_code']:r for r in curriculum['records']}
    need(isinstance(codes,list) and len(codes)==len(set(codes)),'Invalid room-free course list.')
    for code in codes:
        need(code in catalog and any(word in catalog[code]['course_name']
             for word in ('مشروع تخرج','التدريب الميداني')),
             f'{code}: room-free activity must be a project or field-training course.')
    output['sections']=[s for s in output['sections'] if s['course_code'] not in codes]
    for code in sorted(codes):
        row=catalog[code]
        output['sections'].append(dict(id=f'{code}_room_free',course_code=code,
            name_ar=row['course_name'],section_number=1,status='no_meeting_days',students=None,
            room_free_activity=True,room_requirement='none',teaching_location='لا يتطلب قاعة',
            assumptions=['User-requested room-free project/field training: enrollment and degree credits are retained; no fixed weekly room/time reservations are inferred.']))
    if output.get('estimated_meeting_patterns'):
        output['estimated_meeting_patterns']=[row for row in output['estimated_meeting_patterns']
                                              if row['course_code'] not in codes]
    output['room_free_course_codes']=list(codes)
    prepare(output)
    return output
