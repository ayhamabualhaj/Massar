"""Check imported source placements without inventing enrollment or student groups."""
import copy
import csv
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .checker import inspect_solution
from .validation import prepare


def audit_historical_schedule(reference):
    data = copy.deepcopy(reference)
    data['sections'] = [s for s in data['sections'] if s['status']=='scheduled'
                        and s.get('meeting_pattern_status') != 'estimated_user_approved']
    if not data['sections']:
        return dict(status='no_source_meetings', issues=[], overlapping_pairs=[], timed_sections=0)
    # Source enrollments and group memberships are synthetic. Do not use them
    # to certify or reject the university's actual student seating/conflicts.
    data.update(groups=[], shared_classes=[], teachers_enabled=False, section_pattern_options={})
    for s in data['sections']:
        s.update(students=1, unmodeled_student_count=1)
    ctx = prepare(data)
    assignments, daily = [], defaultdict(list)
    for eid, event in ctx['events'].items():
        pattern = ctx['patterns'][event['pattern_id']]
        start = event['source_start']
        room = event.get('source_room')
        meetings = [dict(day=day, start=start, end=start+pattern['duration']) for day in pattern['days']]
        assignments.append(dict(event_id=eid, start=start, room_id=room, meetings=meetings))
        if room is not None:
            for meeting in meetings:
                daily[room, meeting['day']].append((eid, meeting['start'], meeting['end']))
    pairs = {}
    for (room, day), meetings in daily.items():
        for first, second in combinations(meetings, 2):
            if max(first[1],second[1]) >= min(first[2],second[2]):
                continue
            ids = tuple(sorted((first[0],second[0])))
            pair = pairs.setdefault((room,*ids), dict(room_id=room, first_section=ids[0],
                second_section=ids[1], days=[], overlap_minutes_per_day=min(first[2],second[2])-max(first[1],second[1])))
            pair['days'].append(day)
    validation = inspect_solution(ctx, assignments)
    return dict(status='source_conflicts_found' if not validation['valid'] else 'source_placement_checks_passed',
        timed_sections=len(data['sections']), course_codes=len({s['course_code'] for s in data['sections']}),
        issues=validation['errors'], overlapping_pairs=list(pairs.values()),
        scope='Imported source room/time placements and configured equipment compatibility only. Enrollment, room capacity, teachers and student conflicts are not certified. Overlaps may reflect source errors or unrecorded shared classes; no automatic merging or course-code aliases.')


def write_historical_audit(reference, directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    report=audit_historical_schedule(reference)
    (directory/'historical_schedule_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sections={s['id']:s for s in reference['sections']}
    with (directory/'historical_room_overlaps.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['room_id','first_section','first_course_name','second_section','second_course_name','days','overlap_minutes_per_day','first_source','second_source'])
        for pair in report['overlapping_pairs']:
            first,second=sections[pair['first_section']],sections[pair['second_section']]
            writer.writerow([pair['room_id'],first['id'],first['name_ar'],second['id'],second['name_ar'],
                ','.join(map(str,sorted(pair['days']))),pair['overlap_minutes_per_day'],
                json.dumps(first.get('sources',[]),ensure_ascii=False),json.dumps(second.get('sources',[]),ensure_ascii=False)])
    return report
