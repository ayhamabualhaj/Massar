"""Build scheduling demand directly from registration/request bundles.

    A row represents one student (students=1), or an estimated batch with the
    same requested courses. Course codes remain strings, including leading zeros.
"""
import copy
from collections import defaultdict

from .planning import _pool
from .room_free import allocate_room_free_activity
from .validation import index_records, need, prepare, whole


def with_course_requests(reference, requests):
    output = copy.deepcopy(reference)
    for key in ('group_inference', 'enrollment_projection'):
        output.pop(key, None)
    output['groups'] = []
    prepare(output)
    indexed = index_records(requests, 'course requests')
    need(bool(indexed), 'No course requests supplied.')
    sources = {s['id']: s for s in reference['sections'] if s['status'] == 'scheduled'}
    activities = {s['course_code']: s for s in reference['sections'] if s.get('room_free_activity')}
    activity_demand = defaultdict(int)
    pools = defaultdict(list)
    for section in sources.values():
        pools[_pool(section, reference['patterns'])].append(section)
    demand = defaultdict(int)
    bundles = {}
    for rid, request in indexed.items():
        need(whole(request.get('students'), 1, 100000), f'{rid}: invalid student count.')
        codes = request.get('course_codes')
        need(isinstance(codes, list) and codes and all(isinstance(c, str) for c in codes)
             and len(set(codes)) == len(codes), f'{rid}: course_codes must be unique strings.')
        mapping = request.get('pool_source_ids', {})
        need(isinstance(mapping, dict) and set(mapping) <= set(codes), f'{rid}: invalid pool mapping.')
        selected = []
        for code in codes:
            if code in activities:
                need(code not in mapping, f'{rid}: room-free activity {code} has no teaching pool.')
                activity_demand[code] += request['students']
                continue
            options = [key for key in pools if key[0] == code]
            if code in mapping:
                sid = mapping[code]
                need(isinstance(sid, str) and sid in sources and sources[sid]['course_code'] == code,
                     f'{rid}: invalid source pool for {code}.')
                options = [_pool(sources[sid], reference['patterns'])]
            need(len(options) == 1, f'{rid}: {code} has no unique teaching pool; supply pool_source_ids or correct the course code.')
            selected.append(options[0])
            demand[options[0]] += request['students']
        bundles[rid] = selected
    seeds = {}
    options = {}
    for i, (key, count) in enumerate(sorted(demand.items()), 1):
        templates = pools[key]
        seed = copy.deepcopy(templates[0])
        seed.update(id=f'{key[0]}_request_{i}', students=count, unmodeled_student_count=0,
                    enrollment_status='supplied_course_requests',
                    assumptions=['Enrollment from supplied course-request bundles; room and time assumptions remain those of the reference.'])
        if reference['teachers_enabled']:
            seed['teacher_ids'] = sorted({tid for s in templates for tid in s['teacher_ids']})
        seeds[key] = seed
        options[seed['id']] = sorted({pid for s in templates
            for pid in [s['pattern_id']] + reference.get('section_pattern_options', {}).get(s['id'], [])})
    need(bool(seeds), 'Course requests must include at least one course with meeting times; room-free-only scheduling is not supported.')
    room_free = []
    for code, count in sorted(activity_demand.items()):
        for section in allocate_room_free_activity(activities[code], count):
            section['enrollment_status'] = 'supplied_course_requests'
            room_free.append(section)
    output.update(sections=list(seeds.values()) + room_free, section_pattern_options=options,
        groups=[dict(id=rid, students=indexed[rid]['students'], course_codes=indexed[rid]['course_codes'],
                     section_ids=[seeds[key]['id'] for key in keys], splittable=True,
                     status='supplied_course_requests') for rid, keys in bundles.items() if keys],
        enrollment_generation={'enabled': False}, group_generation={'enabled': False},
        request_provenance={'source': 'supplied_course_requests', 'request_bundles': len(indexed),
                            'students': sum(r['students'] for r in indexed.values()),
                            'course_registrations': sum(demand.values()) + sum(activity_demand.values()),
                            'timed_course_registrations': sum(demand.values()),
                            'room_free_course_registrations': sum(activity_demand.values()),
                            'room_free_only_students': sum(indexed[rid]['students'] for rid, keys in bundles.items() if not keys)})
    requested_codes = {code for request in indexed.values() for code in request['course_codes']}
    if 'estimated_meeting_patterns' in output:
        output['estimated_meeting_patterns'] = [row for row in output['estimated_meeting_patterns']
                                               if row['course_code'] in requested_codes]
    if 'room_free_course_codes' in output:
        output['room_free_course_codes'] = sorted(activity_demand)
    prepare(output)
    return output
