"""Compact placement search for large, splittable student-demand scenarios.

A route represents any number of students following the same complete course
schedule. Each route chooses course meeting times; seats at that time can be
distributed between compatible rooms after search without changing attendance.
The bounded route count is a search restriction, never an infeasibility proof.
"""
import copy
import math
import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .checker import inspect_solution
from masar.sections import planned_data, section_pool
from .planning import _check_enrollments, _solve_with_memory_limit
from .resources import room_requirements
from masar.validation import prepare, need


def _build(ctx, route_limit):
    """Model possible room and time assignments and the routes students can take through them."""
    data = ctx['data']
    model = cp_model.CpModel()
    pools = defaultdict(list)
    for sid in ctx['section_event']:
        section = ctx['sections'][sid]
        pools[section_pool(section, ctx['patterns'])].append(section)
    options, opened, loads, sources = {}, {}, {}, {}
    daily, supply = defaultdict(list), defaultdict(list)
    for key, sections in pools.items():
        demand = sum(s['students'] for s in sections)
        patterns = {pid for section in sections
                    for pid in [section['pattern_id']] + data.get('section_pattern_options', {}).get(section['id'], [])}
        options[key] = []
        pool_opened = []
        for pid in sorted(patterns):
            pattern = ctx['patterns'][pid]
            for start in pattern['starts']:
                option = (key, pid, start)
                options[key].append(option)
                rooms = [None] if key[1] == 'online' else [
                    rid for rid, room in ctx['rooms'].items()
                    if room['type'] in data['compatibility'][key[2]]
                    and not any(b['day'] in pattern['days']
                                and max(start, b['start']) < min(start + pattern['duration'], b['end'])
                                for b in room['blackouts'])]
                for rid in rooms:
                    tag = (option, rid)
                    chosen = model.new_bool_var(f'open@{tag}')
                    capacity = demand if rid is None else ctx['rooms'][rid]['capacity']
                    students = model.new_int_var(0, min(demand, capacity), f'load@{tag}')
                    model.add(students >= chosen)
                    model.add(students <= capacity * chosen)
                    opened[tag], loads[tag], sources[tag] = chosen, students, sections[0]
                    pool_opened.append(chosen)
                    supply[option].append(students)
                    if rid is not None:
                        for day in pattern['days']:
                            daily[rid, day].append(model.new_optional_fixed_size_interval_var(
                                start, pattern['duration'], chosen, f'room@{tag}@{day}'))
        model.add(sum(load for (option, _), load in loads.items() if option[0] == key) == demand)
        # Expose the proven per-course capacity bound to search directly.
        maximum = demand if key[1] == 'online' else max((room['capacity'] for room in ctx['rooms'].values()
            if room['type'] in data['compatibility'][key[2]]), default=0)
        if maximum:
            minimum = math.ceil(demand / maximum)
            model.add(sum(pool_opened) >= minimum)
            if key[1] != 'online':
                # At the capacity minimum, some courses must use the scarce
                # larger rooms. Expose those integer covers directly; extra
                # sections remain allowed when a larger room is unavailable.
                capacities = sorted({room['capacity'] for room in ctx['rooms'].values()
                    if room['type'] in data['compatibility'][key[2]]})
                tight = None
                for threshold in capacities[:-1]:
                    large_required = math.ceil(max(0, demand - threshold * minimum) / (maximum - threshold))
                    if not large_required:
                        continue
                    if tight is None:
                        tight = model.new_bool_var(f'minimum_count@{key}')
                        model.add(sum(pool_opened) == minimum).only_enforce_if(tight)
                        model.add(sum(pool_opened) >= minimum + 1).only_enforce_if(tight.Not())
                    large = [var for (option, rid), var in opened.items() if option[0] == key
                             and ctx['rooms'][rid]['capacity'] > threshold]
                    model.add(sum(large) >= large_required).only_enforce_if(tight)
    for intervals in daily.values():
        model.add_no_overlap(intervals)

    routes, demand_by_time = [], defaultdict(list)
    for gid, group in ctx['groups'].items():
        keys = sorted({section_pool(ctx['sections'][sid], ctx['patterns']) for sid in group['section_ids']})
        sizes = []
        for index in range(min(route_limit, group['students'])):
            name = f'{gid}@route{index}'
            size = model.new_int_var(0, group['students'], f'size@{name}')
            active = model.new_bool_var(f'active@{name}')
            model.add(size >= active)
            model.add(size <= group['students'] * active)
            sizes.append(size)
            flags, daily = {}, defaultdict(list)
            for key in keys:
                flags[key] = {}
                for option in options[key]:
                    _, pid, start = option
                    pattern = ctx['patterns'][pid]
                    selected = model.new_bool_var(f'attend@{name}@{option}')
                    count = model.new_int_var(0, group['students'], f'count@{name}@{option}')
                    model.add(count == size).only_enforce_if(selected)
                    model.add(count == 0).only_enforce_if(selected.Not())
                    demand_by_time[option].append(count)
                    flags[key][option] = selected
                    if not supply[option]:
                        model.add(selected == 0)
                    for day in pattern['days']:
                        daily[day].append(model.new_optional_fixed_size_interval_var(
                            start, pattern['duration'], selected, f'attend@{name}@{option}@{day}'))
                model.add(sum(flags[key].values()) == active)
            for intervals in daily.values():
                model.add_no_overlap(intervals)
            routes.append((group, size, flags))
        model.add(sum(sizes) == group['students'])
        for first, second in zip(sizes, sizes[1:]):
            model.add(first >= second)
    for course_options in options.values():
        for option in course_options:
            model.add(sum(demand_by_time[option]) <= sum(supply[option]))
    model.minimize(sum(opened.values()))
    return model, opened, loads, sources, routes


def _apply_hint(ctx, model, opened, loads, routes, hint):
    """Seed an unchanged or expanded search from a fully checked timetable.

    Check both allowed meeting options and complete student bundles before
    using an incumbent as an upper bound. Incompatible hints are ignored.
    """
    if not isinstance(hint, dict) or not hint.get('has_solution'):
        return False
    try:
        planned = prepare(planned_data(ctx['data'], hint))
        _check_enrollments(ctx, planned)
        if not inspect_solution(planned, hint['assignments'])['valid']:
            return False
        sections = planned['sections']
        assignments = {a['event_id']: a for a in hint['assignments']}
        previous = {}
        for sid in planned['section_event']:
            section = sections[sid]
            assignment = assignments[sid]
            option = (section_pool(section, ctx['patterns']), section['pattern_id'], assignment['start'])
            tag = (option, assignment['room_id'])
            if tag not in opened or tag in previous:
                return False
            previous[tag] = section['students']
        bundles = defaultdict(lambda: defaultdict(int))
        for group in planned['groups'].values():
            source = group['id'] if group['id'] in ctx['groups'] else group['source_group_id']
            bundle = tuple(sorted((section_pool(sections[sid], ctx['patterns']), sections[sid]['pattern_id'],
                                   assignments[sid]['start']) for sid in group['section_ids']))
            bundles[source][bundle] += group['students']
        available = defaultdict(list)
        for group, size, flags in routes:
            available[group['id']].append((size, flags))
        values = []
        for gid, candidates in available.items():
            choices = sorted(bundles[gid].items(), key=lambda pair: (-pair[1], pair[0]))
            if len(choices) > len(candidates):
                return False
            for index, (size, flags) in enumerate(candidates):
                bundle, count = choices[index] if index < len(choices) else ((), 0)
                selected = {option[0]: option for option in bundle}
                if count and (set(selected) != set(flags) or any(selected[key] not in flags[key] for key in flags)):
                    return False
                values.append((size, count))
                for key, alternatives in flags.items():
                    values.extend((flag, int(option == selected.get(key))) for option, flag in alternatives.items())
        values.extend((var, int(tag in previous)) for tag, var in opened.items())
        values.extend((var, previous.get(tag, 0)) for tag, var in loads.items())
    except (KeyError, TypeError, ValueError):
        return False
    for variable, value in values:
        model.add_hint(variable, value)
    model.add(sum(opened.values()) <= len(previous))
    return True


def _extract(ctx, solver, opened, loads, sources, routes):
    """Turn the solver's choices into sections, student groups, and timetable assignments."""
    sections, assignments, groups = [], [], []
    seats, serial = defaultdict(list), defaultdict(int)
    for tag, chosen in opened.items():
        if not solver.boolean_value(chosen):
            continue
        option, rid = tag
        key, pid, start = option
        serial[key[0]] += 1
        sid = f'{key[0]}_slot_{serial[key[0]]}'
        section = copy.deepcopy(sources[tag])
        section.update(id=sid, section_number=serial[key[0]], students=solver.value(loads[tag]), pattern_id=pid)
        section['assumptions'] = [a for a in section.get('assumptions', [])
                                  if not a.startswith('Enrollment is synthetic:')]
        section['assumptions'].append('Enrollment assigned by compact section planning; source instructor is not an assigned instructor.')
        sections.append(section)
        seats[option].append([sid, section['students']])
        pattern = ctx['patterns'][pid]
        assignments.append(dict(event_id=sid, source_ids=[sid], start=start, room_id=rid,
            meetings=[dict(day=day, start=start, end=start + pattern['duration']) for day in pattern['days']]))

    serial = defaultdict(int)
    used_ids = set(ctx['groups'])
    for source, size, flags in routes:
        remaining = solver.value(size)
        if not remaining:
            continue
        options = [next(option for option, selected in alternatives.items()
                        if solver.boolean_value(selected)) for alternatives in flags.values()]
        while remaining:
            selected_seats = [next(seat for seat in seats[option] if seat[1] > 0) for option in options]
            count = min([remaining] + [seat[1] for seat in selected_seats])
            serial[source['id']] += 1
            gid = f"{source['id']}@part{serial[source['id']]}"
            while gid in used_ids:
                gid += '_'
            used_ids.add(gid)
            group = {k: copy.deepcopy(v) for k, v in source.items() if k != 'event_ids'}
            group.update(id=gid, source_group_id=source['id'], students=count,
                         section_ids=[seat[0] for seat in selected_seats])
            groups.append(group)
            for seat in selected_seats:
                seat[1] -= count
            remaining -= count
    enrolled = defaultdict(int)
    for group in groups:
        for sid in group['section_ids']:
            enrolled[sid] += group['students']
    for section in sections:
        section['unmodeled_student_count'] = section['students'] - enrolled[section['id']]
    return dict(ctx['data'], sections=sections, groups=groups, section_pattern_options={}), assignments


def solve_slot_sections(data, seconds=120, route_limit=3, progress=None, hints=None):
    """Find and check a complete timetable; restricted failure means UNKNOWN.

    This backend supports splittable groups without teacher/shared-class inputs.
    Any size of group can be seated across rooms at the same meeting time.
    """
    need(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0, 'Invalid search time.')
    need(type(route_limit) is int and route_limit > 0, 'Invalid route limit.')
    beginning = time.monotonic()
    ctx = prepare(data)
    need(not data['teachers_enabled'] and not data['shared_classes'], 'Compact search requires separate courses without teachers.')
    need(all(g.get('splittable') for g in data['groups']), 'Compact search requires splittable groups.')
    requirements, proofs = room_requirements(ctx)
    lower = sum(r['minimum_sections'] or 0 for r in requirements)
    result = dict(status='UNKNOWN', has_solution=False, assignments=[], validation=None, diagnostics=[],
        mode='minimum_sections_compact', objective_bound=None, section_requirements=requirements,
        required_sections_lower_bound=lower)
    if proofs:
        return dict(result, status='INFEASIBLE', resource_diagnostics=proofs,
                    diagnostics=[p['message'] for p in proofs], solver_seconds=time.monotonic()-beginning)
    model, opened, loads, sources, routes = _build(ctx, route_limit)
    hint_applied = _apply_hint(ctx, model, opened, loads, routes, hints)
    build_seconds = time.monotonic()-beginning
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(.001, seconds-build_seconds)
    workers=data.get('solver_workers',4)
    need(type(workers) is int and workers in (1,2,4,8),'Invalid worker count.')
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 0
    if progress:
        solver.parameters.log_search_progress = True
        solver.parameters.log_to_stdout = False
        last = [-10.]

        def log(line):
            """Forward occasional progress updates when the solver has a timetable to report."""
            now = time.monotonic()-beginning
            if line.startswith('#') and 'best:' in line and 'best:inf' not in line and not line.startswith('#Bound') and now-last[0] >= 5:
                progress(line.strip())
                last[0] = now
        solver.log_callback = log
    memory_limit = data.get('solver_memory_limit_mb', 16384)
    need(type(memory_limit) is int and memory_limit >= 256,'Invalid memory limit.')
    status, memory_stopped, peak = _solve_with_memory_limit(solver, model, memory_limit)
    result['restricted_search_status'] = solver.status_name(status)
    result['search_statistics'] = dict(build_seconds=build_seconds,
        search_seconds=time.monotonic()-beginning-build_seconds, student_units=len(routes),
        candidate_sections=len(opened), variables=len(model.proto.variables),
        workers=solver.parameters.num_search_workers, observed_peak_rss_mb=peak,
        memory_limit_mb=memory_limit, stopped_for_memory=memory_stopped,
        backend='room_time_slots', route_limit=route_limit, incumbent_hint_applied=hint_applied)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        if hint_applied and status == cp_model.UNKNOWN:
            retained = copy.deepcopy(hints)
            retained.update(status='OPTIMAL' if len(hints['planned_sections']) == lower else 'FEASIBLE',
                validation=inspect_solution(prepare(dict(data, sections=hints['planned_sections'],
                    groups=hints['planned_groups'], shared_classes=[], section_pattern_options={})), hints['assignments']),
                restricted_search_status=result['restricted_search_status'],
                search_statistics=dict(result['search_statistics'], incumbent_retained=True),
                solver_seconds=time.monotonic()-beginning,
                diagnostics=['Search stopped without a new incumbent; the independently validated starting timetable was retained.'])
            return retained
        if status == cp_model.MODEL_INVALID:
            result.update(status='MODEL_INVALID', diagnostics=[model.validate()])
        else:
            result['diagnostics'] = ([f'Search stopped at the {memory_limit} MB process memory budget; feasibility remains unknown.']
                if memory_stopped else ['No timetable found in the bounded-route search; full feasibility remains unknown.'])
        result['solver_seconds'] = time.monotonic()-beginning
        return result
    effective, assignments = _extract(ctx, solver, opened, loads, sources, routes)
    planned = prepare(effective)
    _check_enrollments(ctx, planned)
    validation = inspect_solution(planned, assignments)
    need(validation['valid'], 'Compact timetable failed independent validation: '+str(validation['errors']))
    # A restricted search optimum is not a proof of the unrestricted minimum.
    # Equality to the independent room-capacity bound IS a global proof.
    count = len(effective['sections'])
    minimum_proven = count == lower
    courses = defaultdict(lambda: dict(students=0, input_sections=0, opened_sections=0))
    for sid in ctx['section_event']:
        source = ctx['sections'][sid]
        courses[source['course_code']]['students'] += source['students']
        courses[source['course_code']]['input_sections'] += 1
    for section in effective['sections']:
        courses[section['course_code']]['opened_sections'] += 1
    from .solver import _group_coverage
    result.update(status='OPTIMAL' if minimum_proven else 'FEASIBLE', has_solution=True,
        assignments=assignments, validation=validation, coverage=_group_coverage(planned),
        planned_sections=effective['sections'], planned_groups=effective['groups'],
        planning_status='OPTIMAL' if minimum_proven else 'FEASIBLE', preference_status='NOT_RUN',
        section_plan=dict(minimum_proven=minimum_proven, opened_sections=count, section_count_bound=lower,
            restricted_search_bound=solver.best_objective_bound,
            courses=[dict(course_code=code, **counts) for code, counts in sorted(courses.items())],
            unplanned_section_ids=[s['id'] for s in data['sections'] if s['status']=='no_meeting_days'],
            planning_seconds=solver.wall_time), solver_seconds=time.monotonic()-beginning)
    if not minimum_proven:
        result['diagnostics'].append('Complete timetable validated; global minimum section count is not proven.')
    return result
