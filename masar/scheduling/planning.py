"""Choose sections and enrollments jointly with room and student feasibility."""
import copy
import math
import time
from collections import defaultdict

from ortools.sat.python import cp_model

from masar.sections import planned_data, section_pool
from .checker import inspect_solution
from masar.validation import need, prepare
from .staffing import add_teacher_constraints
from .memory import DEFAULT_MEMORY_MB, memory_mb as _memory_mb, solve_with_memory_limit as _solve_with_memory_limit  # noqa: F401  (re-exported for slot planning and archived scripts)


def _split_demand_groups(data):
    """An estimated batch is not a requirement to keep its students together.

    Each anonymous member keeps the complete course bundle. Independent counts
    per course would lose that guarantee. Explicit intact groups stay intact.
    Expansion is delayed until after resource infeasibility checks.
    """
    groups = []
    used = {g['id'] for g in data['groups']}
    for group in data['groups']:
        if not group.get('splittable') or group['students'] == 1:
            groups.append(copy.deepcopy(group))
            continue
        for member in range(group['students']):
            gid = f"{group['id']}@member{member+1}"
            while gid in used:
                gid += '_'
            used.add(gid)
            groups.append(dict(copy.deepcopy(group), id=gid, students=1,
                               source_group_id=group['id'], split_member=member))
    return dict(data, groups=groups)


def _merge_allocated_groups(groups, originals):
    """Compact identical student schedules into reportable subgroups."""
    routes = defaultdict(list)
    for group in groups:
        source = group['id'] if group['id'] in originals else group['source_group_id']
        routes[source].append(group)
    merged = []
    used = set(originals)
    for source_id, members in routes.items():
        bundles = defaultdict(int)
        for member in members:
            bundles[tuple(sorted(member['section_ids']))] += member['students']
        for index, (section_ids, count) in enumerate(sorted(bundles.items()), 1):
            original = originals[source_id]
            group = {k: copy.deepcopy(v) for k, v in original.items() if k != 'event_ids'}
            gid = source_id
            if len(bundles) > 1:
                gid = f'{source_id}@part{index}'
                while gid in used:
                    gid += '_'
                used.add(gid)
            group.update(id=gid, students=count, section_ids=list(section_ids))
            if gid != source_id:
                group['source_group_id'] = source_id
            merged.append(group)
    return merged


def _candidates(ctx):
    """List the possible sections and rooms that could serve each course's demand."""
    pools = defaultdict(list)
    for section_id in ctx['section_event']:
        section = ctx['sections'][section_id]
        pools[section_pool(section, ctx['patterns'])].append(section)
    next_number = defaultdict(int)
    for section in ctx['sections'].values():
        code = section['course_code']
        next_number[code] = max(next_number[code], section['section_number'])
    candidates = {}
    demands = {}
    pool_ids = {}
    room_options = {}
    group_counts = defaultdict(int)
    for group in ctx['groups'].values():
        for key in {section_pool(ctx['sections'][sid], ctx['patterns']) for sid in group['section_ids']}:
            group_counts[key] += 1
    for key, originals in pools.items():
        demand = sum(s['students'] for s in originals)
        demands[key] = demand
        allowed = [room_id for room_id, room in ctx['rooms'].items()
                   if room['type'] in ctx['data']['compatibility'][key[2]]]
        caps = [ctx['rooms'][room_id]['capacity'] for room_id in allowed]
        # Enough candidates to use smaller rooms when larger rooms are unavailable.
        required_candidates = math.ceil(demand / min(caps)) if caps and key[1] != 'online' else 1
        # Different groups may require different times even when they would fit
        # together in a room (or when the course is online).
        required_candidates = max(required_candidates, group_counts[key])
        templates = [copy.deepcopy(s) for s in originals]
        teacher_ids = sorted({tid for s in originals for tid in s.get('teacher_ids', [])})
        for source in originals:
            for pattern_id in ctx['data'].get('section_pattern_options', {}).get(source['id'], []):
                if pattern_id == source['pattern_id']:
                    continue
                need(pattern_id in ctx['patterns'], f'Unknown pattern option: {pattern_id}')
                pattern = ctx['patterns'][pattern_id]
                need(len(pattern['days']) * pattern['duration'] == key[3], 'Pattern option changes weekly teaching hours.')
                next_number[key[0]] += 1
                variant = copy.deepcopy(source)
                variant.update(id=f"{key[0]}_planned_{next_number[key[0]]}",
                               section_number=next_number[key[0]], pattern_id=pattern_id)
                templates.append(variant)
        by_pattern = defaultdict(list)
        for section in templates:
            if ctx['data']['teachers_enabled']:
                section['teacher_ids'] = teacher_ids
            by_pattern[section['pattern_id']].append(section)
        # Each permitted pattern must remain usable even if the other patterns
        # cannot fit the room calendar or the student groups.
        for same_pattern in by_pattern.values():
            pattern = ctx['patterns'][same_pattern[0]['pattern_id']]
            # No two physical sections can occupy the same room/start; online
            # sections at an identical time can merge without a capacity limit.
            positions = len(pattern['starts']) * (len(allowed) if key[1] != 'online' else 1)
            count = min(required_candidates, positions)
            for index in range(max(0, count - len(same_pattern))):
                template = copy.deepcopy(same_pattern[index % len(same_pattern)])
                next_number[key[0]] += 1
                template['section_number'] = next_number[key[0]]
                template['id'] = f"{key[0]}_planned_{next_number[key[0]]}"
                while template['id'] in ctx['sections'] or template['id'] in candidates:
                    template['id'] += '_new'
                templates.append(template)
        pool_ids[key] = []
        for section in templates:
            sid = section['id']
            candidates[sid] = section
            pool_ids[key].append(sid)
            room_options[sid] = allowed
    return candidates, demands, pool_ids, room_options


def _build_model(ctx, candidates, demands, pools, room_options):
    """Describe which sections can open and how rooms, times, and students fit together."""
    model = cp_model.CpModel()
    opened, loads, starts, choices = {}, {}, {}, {}
    room_intervals = defaultdict(list)
    for sid, section in candidates.items():
        key = section_pool(section, ctx['patterns'])
        pattern = ctx['patterns'][section['pattern_id']]
        opened[sid] = model.new_bool_var(f'open@{sid}')
        maximum = demands[key] if section['delivery'] == 'online' else max(
            (ctx['rooms'][rid]['capacity'] for rid in room_options[sid]), default=0)
        loads[sid] = model.new_int_var(0, min(maximum, demands[key]), f'students@{sid}')
        model.add(loads[sid] >= opened[sid])
        model.add(loads[sid] <= demands[key] * opened[sid])
        starts[sid] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(pattern['starts'] or [0]), f'start@{sid}')
        if not pattern['starts']:
            model.add(opened[sid] == 0)
        choices[sid] = {}
        if section['delivery'] != 'online':
            for rid in room_options[sid]:
                chosen = model.new_bool_var(f'{sid}@{rid}')
                choices[sid][rid] = chosen
                model.add(loads[sid] <= ctx['rooms'][rid]['capacity']).only_enforce_if(chosen)
                for day in pattern['days']:
                    room_intervals[rid, day].append(model.new_optional_fixed_size_interval_var(
                        starts[sid], pattern['duration'], chosen, f'{sid}@{rid}@{day}'))
            model.add(sum(choices[sid].values()) == opened[sid])
    for rid, room in ctx['rooms'].items():
        for index, blackout in enumerate(room['blackouts']):
            room_intervals[rid, blackout['day']].append(model.new_fixed_size_interval_var(
                blackout['start'], blackout['end'] - blackout['start'], f'closed@{rid}@{index}'))
    for intervals in room_intervals.values():
        model.add_no_overlap(intervals)
    # Attach choices to the model wrapper without changing the public tuple
    # returned by this helper (also used by analysis scripts).
    model.teacher_choices = add_teacher_constraints(model, ctx, starts, candidates, opened)

    for key, ids in pools.items():
        model.add(sum(loads[sid] for sid in ids) == demands[key])
        maximum = demands[key] if key[1] == 'online' else max(
            (ctx['rooms'][rid]['capacity'] for rid in room_options[ids[0]]), default=0)
        if maximum:
            model.add(sum(opened[sid] for sid in ids) >= math.ceil(demands[key] / maximum))
        # Sections using the same pattern are interchangeable during count planning.
        by_pattern = defaultdict(list)
        for sid in ids:
            by_pattern[candidates[sid]['pattern_id']].append(sid)
        for same_pattern in by_pattern.values():
            for first, second in zip(same_pattern, same_pattern[1:]):
                model.add(opened[first] >= opened[second])
                model.add(starts[first] <= starts[second]).only_enforce_if(opened[second])

    allocations = {}
    assigned_students = defaultdict(list)
    member_orders = defaultdict(list)
    for gid, group in ctx['groups'].items():
        group_pools = {section_pool(ctx['sections'][sid], ctx['patterns']) for sid in group['section_ids']}
        daily = defaultdict(list)
        for key in sorted(group_pools):
            alternatives = {}
            for sid in pools[key]:
                selected = model.new_bool_var(f'group@{gid}@{sid}')
                alternatives[sid] = selected
                model.add(selected <= opened[sid])
                assigned_students[sid].append(group['students'] * selected)
                pattern = ctx['patterns'][candidates[sid]['pattern_id']]
                for day in pattern['days']:
                    daily[day].append(model.new_optional_fixed_size_interval_var(
                        starts[sid], pattern['duration'], selected, f'group@{gid}@{sid}@{day}'))
            model.add_exactly_one(list(alternatives.values()))
            allocations[gid, key] = alternatives
            if 'split_member' in group and key == min(group_pools):
                order = sum(i * var for i, var in enumerate(alternatives.values()))
                member_orders[group['source_group_id']].append((group['split_member'], order))
        for intervals in daily.values():
            model.add_no_overlap(intervals)
    for sid, totals in assigned_students.items():
        model.add(loads[sid] >= sum(totals))
    for orders in member_orders.values():
        ordered = sorted(orders, key=lambda item: item[0])
        for first, second in zip(ordered, ordered[1:]):
            model.add(first[1] <= second[1])
    model.minimize(sum(opened.values()))
    return model, opened, loads, starts, choices, allocations


def _extract(ctx, solver, candidates, opened, loads, starts, choices, allocations):
    """Turn the solver's choices into sections, student groups, and timetable assignments."""
    selected = {sid for sid in candidates if solver.boolean_value(opened[sid])}
    sections = []
    assignments = []
    for sid, source in candidates.items():
        if sid not in selected:
            continue
        section = copy.deepcopy(source)
        section['students'] = solver.value(loads[sid])
        section['assumptions'] = [a for a in section.get('assumptions', [])
                                  if not a.startswith('Enrollment is synthetic:')]
        section['assumptions'].append('Enrollment allocated from summed input course counts.')
        sections.append(section)
        start = solver.value(starts[sid])
        pattern = ctx['patterns'][section['pattern_id']]
        room = next((rid for rid, variable in choices[sid].items()
                     if solver.boolean_value(variable)), None)
        assignments.append(dict(event_id=sid, source_ids=[sid], start=start, room_id=room,
                                meetings=[dict(day=day, start=start, end=start + pattern['duration'])
                                          for day in pattern['days']]))
    groups = []
    for gid, source in ctx['groups'].items():
        group = {k: copy.deepcopy(v) for k, v in source.items() if k != 'event_ids'}
        group['section_ids'] = [sid for (group_id, _), alternatives in allocations.items()
                                if group_id == gid for sid, variable in alternatives.items()
                                if solver.boolean_value(variable)]
        groups.append(group)
    enrolled = defaultdict(int)
    for group in groups:
        for sid in group['section_ids']:
            enrolled[sid] += group['students']
    for section in sections:
        section['unmodeled_student_count'] = section['students'] - enrolled[section['id']]
    return dict(ctx['data'], sections=sections, groups=groups, shared_classes=[], section_pattern_options={}), assignments


def _check_enrollments(original, planned):
    """Check enrollment conservation and group course membership independently."""
    def totals(ctx):
        """Count students across sections with the same teaching requirements."""
        result = defaultdict(int)
        for sid in ctx['section_event']:
            section = ctx['sections'][sid]
            result[section_pool(section, ctx['patterns'])] += section['students']
        return result
    need(totals(original) == totals(planned), 'Section planning changed course enrollment totals.')
    members = defaultdict(list)
    for gid, group in planned['groups'].items():
        source = gid if gid in original['groups'] else group.get('source_group_id')
        need(source in original['groups'], 'Section planning invented a student group.')
        members[source].append(group)
    need(original['groups'].keys() == members.keys(), 'Section planning lost student groups.')
    for gid, group in original['groups'].items():
        need(sum(g['students'] for g in members[gid]) == group['students'],
             f'{gid}: section planning changed student population.')
        need(group.get('splittable') or len(members[gid]) == 1, f'{gid}: intact group was split.')
        before = {section_pool(original['sections'][sid], original['patterns']) for sid in group['section_ids']}
        for new in members[gid]:
            after = [section_pool(planned['sections'][sid], planned['patterns']) for sid in new['section_ids']]
            need(len(after) == len(set(after)) and set(after) == before,
                 f'{gid}: section planning changed group enrollment.')


# Share of the time budget spent choosing sections when preferences are optimized afterwards.
PLANNING_SHARE = 0.75
# Above this many students (all in splittable groups, no teachers) the compact
# room-time-slot search is used; the member-level model becomes too large.
COMPACT_SEARCH_MIN_STUDENTS = 200


def improve_preferences(result, effective, seconds, workers=1):
    """Re-time the chosen sections to reduce student gaps, late meetings and shifts.

    Section choice and student membership stay fixed; only times and rooms may move.
    The improved timetable is kept only if it validates and does not score worse;
    otherwise (timeout, memory stop, or error) the first validated timetable is kept.
    """
    from .solver import _solve_fixed
    from masar.validation import InputError

    result['preference_status'] = 'NOT_RUN'
    if seconds < 1 or not result.get('has_solution'):
        return result
    before = result['validation']
    try:
        improved = _solve_fixed(effective, optimize=True, seconds=seconds,
                                hints=result['assignments'], workers=workers)
    except InputError as error:
        result['preference_status'] = 'ERROR'
        result['preference_search'] = dict(error=str(error), kept='first_timetable')
        return result
    result['preference_status'] = improved['status']
    accepted = bool(improved['has_solution']
                    and improved['validation']['weighted_score'] <= before['weighted_score'])
    if accepted:
        result.update(assignments=improved['assignments'], validation=improved['validation'],
                      objective_bound=improved['objective_bound'])
    result['preference_search'] = dict(
        improved.get('search_statistics', {}), accepted=accepted,
        kept='improved_timetable' if accepted else 'first_timetable',
        diagnostics=[] if improved['has_solution'] else improved['diagnostics'])
    result['preference_score_before'] = before['weighted_score']
    result['preference_score_after'] = result['validation']['weighted_score']
    result['preference_metrics_before'] = before['metrics']
    peak = improved.get('search_statistics', {}).get('observed_peak_rss_mb')
    statistics = result.get('search_statistics')
    if statistics is not None and peak is not None:
        statistics['observed_peak_rss_mb'] = max(statistics.get('observed_peak_rss_mb') or 0, peak)
    result['mode'] = result['mode'] + '_then_weighted_optimization'
    return result


def solve_sections(data, optimize=True, seconds=30, hints=None):
    """Search for a feasible timetable using as few sections as possible."""
    from .solver import _group_coverage, _solve_fixed

    need(type(optimize) is bool, 'optimize must be Boolean.')
    need(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
         'seconds must be finite and positive.')
    beginning = time.monotonic()
    ctx = prepare(data)
    original_ctx = ctx
    need(not data['shared_classes'],
         'Section planning requires separate courses; use plan_sections=False for explicit shared classes.')
    from .resources import room_requirements
    requirements, resource_diagnostics = room_requirements(ctx)
    if resource_diagnostics:
        return dict(status='INFEASIBLE', has_solution=False, assignments=[], validation=None,
                    diagnostics=[item['message'] for item in resource_diagnostics], mode='minimum_sections',
                    objective_bound=None, section_requirements=requirements,
                    resource_diagnostics=resource_diagnostics,
                    required_sections_lower_bound=sum(r['minimum_sections'] or 0 for r in requirements),
                    solver_seconds=time.monotonic()-beginning)
    workers = data.get('solver_workers', 4 if sum(g['students'] for g in data['groups']) > 200 else 1)
    need(type(workers) is int and workers in (1, 2, 4, 8), 'workers must be 1, 2, 4, or 8.')
    if (sum(g['students'] for g in data['groups']) > COMPACT_SEARCH_MIN_STUDENTS
            and not data['teachers_enabled']
            and all(g.get('splittable') for g in data['groups'])):
        from .slot_planning import solve_slot_sections
        remaining = seconds - (time.monotonic() - beginning)
        result = solve_slot_sections(data, seconds=max(.001, remaining * (PLANNING_SHARE if optimize else 1.0)),
                                     route_limit=data.get('solver_route_limit', 3), hints=hints)
        if optimize and result.get('has_solution'):
            improve_preferences(result, planned_data(data, result),
                                seconds - (time.monotonic() - beginning), workers)
        return result
    ctx = prepare(_split_demand_groups(data))
    candidates, demands, pools, options = _candidates(ctx)
    model, opened, loads, starts, choices, allocations = _build_model(ctx, candidates, demands, pools, options)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, (seconds - (time.monotonic()-beginning)) * (PLANNING_SHARE if optimize else 1.0))
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 0
    build_seconds = time.monotonic()-beginning
    # Large inputs need the available budget to find the first timetable.
    if len(ctx['groups']) > 200:
        solver.parameters.max_time_in_seconds = max(0.001, seconds-build_seconds)
    memory_limit = data.get('solver_memory_limit_mb', DEFAULT_MEMORY_MB)
    need(type(memory_limit) is int and memory_limit >= 256, 'Memory limit must be an integer of at least 256 MB.')
    search_started = time.monotonic()
    status, memory_stopped, peak_memory = _solve_with_memory_limit(solver, model, memory_limit)
    search_elapsed = time.monotonic()-search_started
    result = dict(status=solver.status_name(status), has_solution=False, assignments=[],
                  validation=None, diagnostics=[], mode='minimum_sections', objective_bound=None,
                  section_requirements=requirements,
                  required_sections_lower_bound=sum(r['minimum_sections'] or 0 for r in requirements),
                  search_statistics=dict(build_seconds=build_seconds, search_seconds=search_elapsed,
                      student_units=len(ctx['groups']), candidate_sections=len(candidates),
                      variables=len(model.proto.variables), workers=solver.parameters.num_search_workers,
                      memory_limit_mb=memory_limit, observed_peak_rss_mb=peak_memory,
                      stopped_for_memory=memory_stopped))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result['diagnostics'] = [model.validate() if status == cp_model.MODEL_INVALID else
                                 ('No feasible section plan before the time limit.' if status == cp_model.UNKNOWN
                                  else 'Course enrollment cannot fit the rooms, patterns, and student-group constraints.')]
        if memory_stopped:
            result['diagnostics'] = [f'Search stopped at the {memory_limit} MB process memory budget; feasibility remains unknown.']
        result['solver_seconds'] = time.monotonic()-beginning
        return result
    effective, assignments = _extract(ctx, solver, candidates, opened, loads, starts, choices, allocations)
    if data['teachers_enabled']:
        for assignment in assignments:
            assignment['teacher_id'] = next(tid for tid, var in model.teacher_choices[assignment['event_id']].items()
                                            if solver.boolean_value(var))
    effective['groups'] = _merge_allocated_groups(effective['groups'], original_ctx['groups'])
    planned = prepare(effective)
    _check_enrollments(original_ctx, planned)
    validation = inspect_solution(planned, assignments)
    result.update(has_solution=validation['valid'], assignments=assignments,
                  validation=validation, coverage=_group_coverage(planned))
    result['planning_status'] = solver.status_name(status)
    result['preference_status'] = 'NOT_RUN'
    if not validation['valid']:
        result.update(status='VALIDATION_FAILED', diagnostics=validation['errors'])
        return result
    # Re-time the chosen sections for student preferences, whether or not the
    # section count was proven minimal. Optimality here applies to the chosen
    # sections and memberships, not to all possible minimum-section plans.
    if optimize:
        improve_preferences(result, effective, seconds - (time.monotonic() - beginning), workers)
    courses = defaultdict(lambda: dict(students=0, input_sections=0, opened_sections=0))
    for sid in ctx['section_event']:
        section = ctx['sections'][sid]
        entry = courses[section['course_code']]
        entry['students'] += section['students']
        entry['input_sections'] += 1
    for section in effective['sections']:
        courses[section['course_code']]['opened_sections'] += 1
    result['section_plan'] = dict(
        minimum_proven=status == cp_model.OPTIMAL,
        opened_sections=len(effective['sections']),
        section_count_bound=solver.best_objective_bound,
        courses=[dict(course_code=code, **counts) for code, counts in sorted(courses.items())],
        unplanned_section_ids=[sid for sid, section in ctx['sections'].items()
                               if section['status'] == 'no_meeting_days'],
        planning_seconds=solver.wall_time)
    if status != cp_model.OPTIMAL:
        result['diagnostics'].append('A feasible section plan was found, but minimum section count is not proven.')
    result['planned_sections'] = effective['sections']
    result['planned_groups'] = effective['groups']
    result['solver_seconds'] = time.monotonic() - beginning
    return result
