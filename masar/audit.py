"""Keep mathematical feasibility separate from input-data completeness."""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from .planning import _pool


def data_quality(data):
    projection = data.get('enrollment_projection', {})
    issues = []

    def issue(code, count, message):
        if count:
            issues.append(dict(code=code, count=count, message=message))

    issue('unverified_room_capacities', sum(r.get('capacity_status') != 'verified' for r in data['rooms']),
          'Room capacities are assumed or unverified; capacity conclusions are scenario estimates.')
    issue('unverified_external_room_inventory',sum(r.get('location')=='outside_it' for r in data['rooms']),
          'External rooms are estimated placeholders; actual outside-room inventory and fixed meeting times have not been supplied.')
    issue('teachers_not_modeled', int(not data['teachers_enabled']),
          'Instructor assignments and availability are not protected in this scenario.')
    issue('inferred_room_requirements', sum(any('Room requirement inferred' in a for a in s.get('assumptions', []))
                                           for s in data['sections'] if s['status']=='scheduled' and s.get('room_requirement_status') != 'user_confirmed'),
          'Equipment requirements inferred from historical room placement need verification; a past lab placement does not prove a mandatory lab requirement.')
    issue('estimated_meeting_patterns', len(data.get('estimated_meeting_patterns', [])),
          'Weekly contact patterns are approved estimates, not verified university teaching hours.')
    issue('estimated_course_demand', int(bool(projection)),
          'Admissions and an inferred study plan are not actual course registrations.')
    issue('unknown_course_demand', sum(r['students'] is None for r in projection.get('course_coverage', [])),
          'Reference course codes without an exact curriculum match have unknown demand.')
    issue('missing_planned_course_registrations', sum(c['students']*len(c['unavailable_courses']) for c in projection.get('cohorts', [])),
          'These planned student-course registrations have no offered teaching template and are not scheduled.')
    issue('students_without_offered_courses', projection.get('estimated_students', 0)-projection.get('represented_students', 0),
          'These students remain in the population forecast but have no modeled offered courses this term.')
    issue('unknown_second_semester_intakes', len(projection.get('excluded_unknown_second_semester_intakes', [])),
          'Second-semester admissions are unknown and excluded from the estimate.')
    return dict(operational_readiness='not_certified', issues=issues,
                user_confirmed_computer_courses=len({s['course_code'] for s in data['sections']
                    if s.get('room_requirement')=='computers' and s.get('room_requirement_status')=='user_confirmed'}),
                note='A valid solver result certifies modeled hard constraints only; this audit does not certify a university timetable.')


def write_audit_reports(data, reference, result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    def write(name, headers, rows):
        with (directory/name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)

    audit = data_quality(data)
    write('data_quality_issues.csv', ['issue', 'count', 'explanation'],
          [[i['code'], i['count'], i['message']] for i in audit['issues']])
    write('room_capacity_inventory.csv', ['room_id', 'room_name', 'type', 'capacity', 'capacity_status'],
          [[r['id'], r['name_ar'], r['type'], r['capacity'], r.get('capacity_status', 'unverified')] for r in data['rooms']])
    write('course_room_requirements.csv', ['course_code', 'course_name', 'room_requirement', 'evidence_status', 'evidence'],
          [[s['course_code'], s['name_ar'], s['room_requirement'], s.get('room_requirement_status', 'unverified'),
            s.get('room_requirement_evidence', '; '.join(s.get('assumptions', [])))]
           for s in data['sections'] if s['status']=='scheduled'])
    real = defaultdict(list)
    demand = defaultdict(int)
    for s in reference['sections']:
        if s['status'] == 'scheduled' and s.get('meeting_pattern_status') != 'estimated_user_approved':
            real[_pool(s, reference['patterns'])].append(s)
    for s in data['sections']:
        if s['status'] == 'scheduled':
            demand[_pool(s, data['patterns'])] += s['students']
    known = {r['course_code']: r['students'] for r in data.get('enrollment_projection', {}).get('course_coverage', [])}
    rows = []
    for key in sorted(real.keys() | demand.keys()):
        count = len(real[key])
        caps = [r['capacity'] for r in data['rooms'] if r['type'] in data['compatibility'][key[2]]]
        maximum = None if key[1] == 'online' else max(caps, default=0)
        students = demand.get(key, 0) if key in demand or known.get(key[0]) is not None else None
        lower = (math.ceil(students/maximum) if maximum else 1 if maximum is None else None) if students else 0 if students == 0 else None
        rows.append([*key, count, students if students is not None else 'unknown',
                     maximum if maximum is not None else 'unlimited',
                     count*maximum if maximum is not None else 'unlimited',
                     lower if lower is not None else 'unknown',
                     max(0, lower-count) if lower is not None else 'unknown',
                     'scenario estimate; reference section counts do not establish actual enrollment'])
    write('real_section_comparison.csv', ['course_code', 'delivery', 'room_requirement', 'weekly_minutes',
          'real_teaching_sections', 'projected_students', 'maximum_compatible_room_capacity',
          'reference_seat_upper_bound', 'capacity_section_lower_bound', 'additional_sections_lower_bound', 'basis'], rows)
    missing = [[c['id'], c['program_id'], c['students'], code] for c in data.get('enrollment_projection', {}).get('cohorts', [])
               for code in c['unavailable_courses']]
    write('missing_planned_courses.csv', ['cohort_id', 'program_id', 'estimated_students', 'course_code'], missing)
    audit.update(solver_status=result['status'], has_valid_modeled_timetable=result['has_solution'],
                 required_sections_lower_bound=result.get('required_sections_lower_bound'))
    (directory/'audit_summary.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return audit
