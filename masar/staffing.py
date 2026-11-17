"""Optional instructor assignment, availability, and weekly teaching limits."""
from collections import defaultdict


def add_teacher_constraints(model, ctx, starts, sections=None, opened=None):
    choices = {}
    if not ctx['data']['teachers_enabled']:
        return choices
    daily = defaultdict(list)
    workload = defaultdict(list)
    for sid, section in (sections if sections is not None else ctx['events']).items():
        pattern = ctx['patterns'][section['pattern_id']]
        choices[sid] = {}
        for tid in section['teacher_ids']:
            selected = model.new_bool_var(f'teacher@{sid}@{tid}')
            choices[sid][tid] = selected
            workload[tid].append(len(pattern['days']) * pattern['duration'] * selected)
            for day in pattern['days']:
                daily[tid, day].append(model.new_optional_fixed_size_interval_var(
                    starts[sid], pattern['duration'], selected, f'teacher@{sid}@{tid}@{day}'))
        model.add(sum(choices[sid].values()) == (opened[sid] if opened is not None else 1))
    for tid, teacher in ctx['teachers'].items():
        for i, closure in enumerate(teacher['blackouts']):
            daily[tid, closure['day']].append(model.new_fixed_size_interval_var(
                closure['start'], closure['end']-closure['start'], f'teacher_closed@{tid}@{i}'))
        if teacher.get('max_weekly_minutes') is not None:
            model.add(sum(workload[tid]) <= teacher['max_weekly_minutes'])
    for intervals in daily.values():
        model.add_no_overlap(intervals)
    return choices


def check_teachers(ctx, scheduled, errors):
    """Independent validation; do not trust the solver's teacher choices."""
    if not ctx['data']['teachers_enabled']:
        return
    daily = defaultdict(list)
    workload = defaultdict(int)
    for eid, assignment in scheduled.items():
        event = ctx['events'][eid]
        tid = assignment.get('teacher_id')
        if tid not in event['teacher_ids']:
            errors.append(f'{eid}: unknown or unqualified teacher.')
            continue
        start = assignment.get('start')
        if type(start) is not int:
            continue
        pattern = ctx['patterns'][event['pattern_id']]
        workload[tid] += len(pattern['days'])*pattern['duration']
        for day in pattern['days']:
            daily[tid, day].append((start, start+pattern['duration'], eid))
    for tid, teacher in ctx['teachers'].items():
        maximum = teacher.get('max_weekly_minutes')
        if maximum is not None and workload[tid] > maximum:
            errors.append(f'{tid}: weekly teaching limit exceeded.')
        for closure in teacher['blackouts']:
            daily[tid, closure['day']].append((closure['start'], closure['end'], 'BLACKOUT'))
    for (tid, day), meetings in daily.items():
        for i, first in enumerate(meetings):
            for second in meetings[i+1:]:
                if max(first[0], second[0]) < min(first[1], second[1]):
                    errors.append(f'Teacher clash {tid}, day {day}: {first[2]}, {second[2]}.')
