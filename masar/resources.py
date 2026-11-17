"""Conservative workload lower bounds: never relax room or time constraints."""
import math
from collections import defaultdict

from .planning import _pool


def _union(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged


def room_requirements(ctx):
    pools=defaultdict(list)
    for sid in ctx['section_event']:
        section=ctx['sections'][sid]
        pools[_pool(section,ctx['patterns'])].append(section)
    requirements=[]
    windows=defaultdict(list)
    for pool,sections in sorted(pools.items()):
        demand=sum(s['students'] for s in sections)
        online=pool[1]=='online'
        allowed=[] if online else [rid for rid,room in ctx['rooms'].items()
                                   if room['type'] in ctx['data']['compatibility'][pool[2]]]
        maximum=None if online else max((ctx['rooms'][rid]['capacity'] for rid in allowed),default=0)
        lower=1 if online else math.ceil(demand/maximum) if maximum else None
        requirements.append(dict(course_code=pool[0],delivery=pool[1],room_requirement=pool[2],
                                 weekly_minutes=pool[3],students=demand,maximum_room_capacity=maximum,
                                 minimum_sections=lower,eligible_room_ids=allowed))
        patterns={s['pattern_id'] for s in sections}
        for s in sections:
            patterns.update(ctx['data'].get('section_pattern_options',{}).get(s['id'],[]))
        for rid in allowed:
            for pid in patterns:
                pattern=ctx['patterns'][pid]
                for day in pattern['days']:
                    for start in pattern['starts']:
                        windows[rid,day].append((start,start+pattern['duration']))
    available=defaultdict(int)
    for (rid,day),intervals in windows.items():
        spans=_union(intervals)
        blackouts=_union([(b['start'],b['end']) for b in ctx['rooms'][rid]['blackouts'] if b['day']==day])
        minutes=sum(end-start for start,end in spans)
        blocked=sum(max(0,min(end,bend)-max(start,bstart)) for start,end in spans for bstart,bend in blackouts)
        available[rid]+=minutes-blocked
    diagnostics=[]
    physical=[r for r in requirements if r['delivery']!='online']
    for row in physical:
        if not row['eligible_room_ids']:
            diagnostics.append(dict(reason='no_compatible_room',course_code=row['course_code'],
                                    message=f"{row['course_code']}: no compatible physical room."))
    subsets={tuple(sorted(r['eligible_room_ids'])) for r in physical if r['eligible_room_ids']}
    if ctx['rooms']:subsets.add(tuple(sorted(ctx['rooms'])))
    for subset in sorted(subsets):
        forced=[r for r in physical if r['minimum_sections'] is not None
                and set(r['eligible_room_ids'])<=set(subset)]
        needed=sum(r['minimum_sections']*r['weekly_minutes'] for r in forced)
        capacity=sum(available[rid] for rid in subset)
        seat_needed=sum(r['students']*r['weekly_minutes'] for r in forced)
        seat_available=sum(available[rid]*ctx['rooms'][rid]['capacity'] for rid in subset)
        if seat_needed>seat_available:
            diagnostics.append(dict(reason='weekly_student_seat_capacity_exceeded',room_ids=list(subset),
                minimum_student_minutes=seat_needed,available_student_minutes=seat_available,
                shortfall_student_minutes=seat_needed-seat_available,
                message=f"Rooms {', '.join(subset)} must provide {seat_needed/60:g} student-hours per week, "
                        f"but their allowed times and seat capacities provide at most {seat_available/60:g} "
                        f"(shortfall {(seat_needed-seat_available)/60:g} student-hours)."))
        if needed>capacity:
            diagnostics.append(dict(reason='weekly_room_workload_exceeded',room_ids=list(subset),
                minimum_weekly_minutes=needed,available_weekly_minutes=capacity,shortfall_minutes=needed-capacity,
                message=f"Rooms {', '.join(subset)} need at least {needed/60:g} weekly teaching hours, "
                        f"but their allowed time windows provide at most {capacity/60:g}."))
    return requirements,diagnostics
