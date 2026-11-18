"""Infer bounded co-enrollment scenarios from degree-plan prerequisite graphs.

These scenarios protect plausible course combinations. They are not registrations
or a reconstruction of actual students, majors, semesters, or passed courses.
"""
import copy
import math
from collections import Counter, defaultdict

from ortools.sat.python import cp_model

from .planning import _pool
from .validation import need, prepare


DEFAULT_POLICY = {
    'enabled': True,
    'source': 'course_requirements/five_majors_degree_plans.json',
    'method': 'prerequisite_layers_v1',
    'max_group_credits': 18,
    'max_group_courses': 6,
    'max_program_elective_credits': 9,
    'max_university_elective_credits': 9,
    'max_university_basket_credits': 3,
}


def prerequisite_levels(records, max_credits=18):
    """Weighted depth: strict prerequisites add a level, permitted concurrency does not."""
    index = {}
    for record in records:
        code = record['course_code']
        need(code not in index, f'Duplicate degree-plan course: {code}')
        index[code] = record
    levels = {code: math.ceil((r.get('minimum_completed_hours') or 0) / max_credits)
              for code, r in index.items()}
    for record in records:
        for req in record['requirements']:
            need(req['course_code'] in index, f"Missing prerequisite {req['course_code']} in plan.")
    for _ in range(len(index) + 1):
        changed = False
        for code, record in sorted(index.items()):
            for req in record['requirements']:
                value = levels[req['course_code']] + (0 if req['concurrent_allowed'] else 1)
                if value > levels[code]:
                    levels[code] = value
                    changed = True
        if not changed:
            return levels
    need(False, 'Degree-plan prerequisites contain an inconsistent cycle.')


def _assumed_completed(codes, index):
    seen = set(codes)
    completed = set()
    pending = list(codes)
    while pending:
        for requirement in index[pending.pop()]['requirements']:
            code = requirement['course_code']
            if code in seen:
                continue
            seen.add(code)
            completed.add(code)
            pending.append(code)
    return sorted(completed)


def _calendar_check(section_ids, sections, patterns, cache):
    """Reject a proposed group that cannot fit its own allowed weekly patterns."""
    keys = tuple(sorted(_pool(sections[sid], patterns) for sid in section_ids))
    if keys in cache:
        return cache[keys]
    model = cp_model.CpModel()
    daily = defaultdict(list)
    for index, key in enumerate(keys):
        pattern_ids = sorted({s['pattern_id'] for s in sections.values()
                              if s['status'] == 'scheduled' and _pool(s, patterns) == key})
        alternatives = []
        for pattern_id in pattern_ids:
            pattern = patterns[pattern_id]
            if not pattern['starts']:
                continue
            chosen = model.new_bool_var(f'pattern@{index}@{pattern_id}')
            alternatives.append(chosen)
            start = model.new_int_var_from_domain(cp_model.Domain.from_values(pattern['starts']),
                                                   f'start@{index}@{pattern_id}')
            for day in pattern['days']:
                daily[day].append(model.new_optional_fixed_size_interval_var(
                    start, pattern['duration'], chosen, f'lesson@{index}@{pattern_id}@{day}'))
        model.add_exactly_one(alternatives)
    for intervals in daily.values():
        model.add_no_overlap(intervals)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    cache[keys] = solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return cache[keys]


def with_plan_groups(data, curriculum, policy=None):
    """Return a copy with inferred groups and a transparent enrollment-coverage report."""
    config = dict(DEFAULT_POLICY, **(policy or data.get('group_generation', {})))
    need(config['method'] == DEFAULT_POLICY['method'], 'Unsupported group generation method.')
    for name in ('max_group_credits', 'max_group_courses', 'max_program_elective_credits',
                 'max_university_elective_credits', 'max_university_basket_credits'):
        need(type(config[name]) is int and config[name] > 0, f'Invalid group policy: {name}')
    output = copy.deepcopy(data)
    # Validate the scheduling inputs independently of the obsolete group list.
    output['groups'] = []
    ctx = prepare(output)
    need(not data.get('shared_classes'), 'Plan-derived groups require separate courses, not shared_classes.')
    records = curriculum['records'] if isinstance(curriculum, dict) else curriculum
    programs = defaultdict(list)
    for row in records:
        programs[row['program_id']].append(row)
    indexes = {p: {r['course_code']: r for r in rows} for p, rows in programs.items()}
    levels = {p: prerequisite_levels(rows, config['max_group_credits']) for p, rows in programs.items()}
    by_course = defaultdict(list)
    for section in ctx['sections'].values():
        if section['status'] == 'scheduled':
            by_course[section['course_code']].append(section)
    demand = {code: sum(s['students'] for s in ss) for code, ss in by_course.items()}
    remaining = {s['id']: s['students'] for ss in by_course.values() for s in ss}
    quotas = defaultdict(dict)
    allocation = {}
    reasons = {}
    for code, ss in sorted(by_course.items()):
        matches = [p for p, index in indexes.items() if code in index]
        if not matches:
            reasons[code] = 'no_exact_plan_code_match'
            continue
        if any(indexes[p][code]['credit_hours'] == 0 for p in matches):
            reasons[code] = 'zero_credit_or_remedial_track_not_inferred'
            continue
        required = [p for p in matches if indexes[p][code]['category'] != 'تخصص اختياري'
                    and indexes[p][code]['category'] != 'جامعة اختياري']
        eligible = sorted(required or matches)
        base, extra = divmod(demand[code], len(eligible))
        allocation[code] = {p: base + int(i < extra) for i, p in enumerate(eligible)}
        for p, count in allocation[code].items():
            if count:
                quotas[p][code] = count

    groups = []
    calendar_cache = {}
    for program, counts in sorted(quotas.items()):
        index = indexes[program]
        program_name = programs[program][0]['program_name']
        for level in sorted({levels[program][code] for code in counts}):
            frontier = {code for code in counts if levels[program][code] == level and counts[code] > 0}
            sequence = 0
            while len(frontier) >= 2:
                # Compulsory classes first, then lab/lecture neighbors, then electives.
                order = sorted(frontier, key=lambda code: (
                    'اختياري' in index[code]['category'],
                    next((r['course_code'] for r in index[code]['requirements']
                          if r['concurrent_allowed'] and r['course_code'] in frontier), code), code))
                selected, selected_ids = [], []
                credits, elective, uni_elective = 0, 0, 0
                baskets = Counter()
                for code in order:
                    candidates = [s for s in by_course[code] if remaining[s['id']] > 0]
                    if not candidates:
                        continue
                    section = min(candidates, key=lambda s: (-remaining[s['id']], s['id']))
                    row = index[code]
                    hours = row['credit_hours']
                    university = row['category'] == 'جامعة اختياري'
                    optional = row['category'] == 'تخصص اختياري'
                    if len(selected) >= config['max_group_courses'] or credits + hours > config['max_group_credits']:
                        continue
                    if optional and elective + hours > config['max_program_elective_credits']:
                        continue
                    if university and (uni_elective + hours > config['max_university_elective_credits']
                                       or baskets[row['elective_basket']] + hours > config['max_university_basket_credits']):
                        continue
                    proposed = selected_ids + [section['id']]
                    if not _calendar_check(proposed, ctx['sections'], ctx['patterns'], calendar_cache):
                        continue
                    selected.append(code)
                    selected_ids = proposed
                    credits += hours
                    elective += hours if optional else 0
                    uni_elective += hours if university else 0
                    baskets[row['elective_basket']] += hours if university else 0
                if len(selected) < 2:
                    break
                students = min(min(counts[code] for code in selected), min(remaining[sid] for sid in selected_ids))
                need(students > 0, 'Inferred group must have students.')
                sequence += 1
                groups.append(dict(
                    id=f'PLAN_{program}_L{level+1:02d}_{sequence:02d}', students=students,
                    section_ids=selected_ids, status='inferred_from_degree_plan',
                    program_id=program, program_name=program_name, prerequisite_level=level+1,
                    course_codes=selected, credit_hours=credits,
                    course_evidence=[dict(course_code=code, course_name=index[code]['course_name'],
                                          credit_hours=index[code]['credit_hours'],
                                          category=index[code]['category'],
                                          prerequisites=copy.deepcopy(index[code]['requirements']),
                                          source_image=index[code].get('source_image', ''),
                                          notes=index[code].get('notes', '')) for code in selected],
                    assumed_completed_course_codes=_assumed_completed(selected, index),
                    basis='Exact plan codes, prerequisite depth, permitted concurrency, bounded elective choices and available patterns; inferred co-enrollment, not registrations.',
                    requirements_source=config['source']))
                for code, sid in zip(selected, selected_ids):
                    counts[code] -= students
                    remaining[sid] -= students
                frontier = {code for code in frontier if counts[code] > 0}
    output['groups'] = groups
    output['group_generation'] = config
    modeled = Counter()
    for group in groups:
        for code in group['course_codes']:
            modeled[code] += group['students']
    for section in output['sections']:
        if section['status'] == 'scheduled':
            section['unmodeled_student_count'] = remaining[section['id']]
    coverage = []
    for code in sorted(demand):
        missing = demand[code] - modeled[code]
        need(missing >= 0, f'{code}: groups exceed course enrollment.')
        coverage.append(dict(course_code=code, course_name=by_course[code][0]['name_ar'],
                             students=demand[code], modeled_students=modeled[code], unmodeled_students=missing,
                             program_allocation=allocation.get(code, {}),
                             reason=reasons.get(code, 'fully_modeled' if missing == 0 else
                                                'unpaired_remainder_or_group_limits')))
    report = dict(
        method=config['method'], inferred=True, actual_registrations=False, policy=config,
        assumptions=[
            'Prerequisite levels are graph depths, not official semesters or student progress.',
            'External prerequisites are assumed completed for each inferred scenario; no transcripts are available.',
            'Course demand is divided equally among compulsory matching programs; if none, elective matching programs. Actual major shares are unknown.',
            'Student counts are residual enrollment allocations, not measured cohort headcounts.',
            'Only exact course codes are matched. No legacy-code or similar-name substitutions.',
            'Zero-credit/remedial courses are not assigned to regular inferred cohorts.',
            'Only groups of at least two available courses create conflict protection; leftover enrollment remains explicitly unmodeled.',
            'Groups cannot exceed configured credits/elective limits or their own available time patterns.'
        ],
        group_count=len(groups), inferred_group_students=sum(g['students'] for g in groups),
        scheduled_courses=len(demand), exact_plan_matched_courses=len(demand.keys() & {r['course_code'] for r in records}),
        grouped_courses=len(modeled), modeled_course_enrollments=sum(modeled.values()),
        total_course_enrollments=sum(demand.values()),
        unmodeled_course_enrollments=sum(demand.values())-sum(modeled.values()),
        course_coverage=coverage)
    output['group_inference'] = report
    provenance = output.setdefault('provenance', {})
    provenance['plans'] = 'Nine 2026 degree-plan photos transcribed in course_requirements/five_majors_degree_plans.json; used for inferred co-enrollment scenarios, not actual registrations.'
    provenance['group_basis'] = 'Generated from program-specific prerequisite levels and concurrency; enrollment-bounded, exact code matching, and documented assumptions in group_inference.'
    prepare(output)
    return output
