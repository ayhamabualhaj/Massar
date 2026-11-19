"""Describe room rules, student group conflicts, and timetable preferences."""
from collections import defaultdict
from itertools import combinations


MINUTES_PER_DAY = 1440


def add_room_constraints(model, ctx, starts):
    """Choose one room per event and prevent overlapping room use."""
    room_intervals = defaultdict(list)
    room_choices = {}

    for event_id, eligible_rooms in ctx["eligible"].items():
        event = ctx["events"][event_id]
        pattern = ctx["patterns"][event["pattern_id"]]
        room_choices[event_id] = {
            room_id: model.new_bool_var(f"{event_id}@{room_id}")
            for room_id in eligible_rooms
        }
        model.add_exactly_one(list(room_choices[event_id].values()))

        for room_id, selected in room_choices[event_id].items():
            for day in pattern["days"]:
                interval = model.new_optional_fixed_size_interval_var(
                    starts[event_id],
                    pattern["duration"],
                    selected,
                    f"{event_id}@{room_id}@{day}",
                )
                room_intervals[room_id, day].append(interval)

    for room_id, room in ctx["rooms"].items():
        for index, blackout in enumerate(room.get("blackouts", [])):
            interval = model.new_fixed_size_interval_var(
                blackout["start"],
                blackout["end"] - blackout["start"],
                f"closed@{room_id}@{index}",
            )
            room_intervals[room_id, blackout["day"]].append(interval)

    for intervals in room_intervals.values():
        model.add_no_overlap(intervals)

    return room_choices


def add_group_constraints(model, ctx, starts):
    """Prevent student-group clashes; return weekly idle minutes per group and per student."""
    idle_minutes = []
    student_idle_minutes = []

    for group_id, group in ctx["groups"].items():
        daily_lessons = defaultdict(list)
        for event_id in group["event_ids"]:
            event = ctx["events"][event_id]
            pattern = ctx["patterns"][event["pattern_id"]]
            for day in pattern["days"]:
                daily_lessons[day].append((event_id, pattern["duration"]))

        for day, lessons in daily_lessons.items():
            intervals = [
                model.new_fixed_size_interval_var(
                    starts[event_id], duration, f"{group_id}@{day}@{event_id}"
                )
                for event_id, duration in lessons
            ]
            model.add_no_overlap(intervals)

            first_start = model.new_int_var(
                0, MINUTES_PER_DAY, f"first@{group_id}@{day}"
            )
            last_end = model.new_int_var(
                0, MINUTES_PER_DAY, f"last@{group_id}@{day}"
            )
            model.add_min_equality(
                first_start, [starts[event_id] for event_id, _ in lessons]
            )
            model.add_max_equality(
                last_end,
                [starts[event_id] + duration for event_id, duration in lessons],
            )

            gap = model.new_int_var(
                0, MINUTES_PER_DAY, f"idle@{group_id}@{day}"
            )
            teaching_minutes = sum(duration for _, duration in lessons)
            model.add(gap == last_end - first_start - teaching_minutes)
            idle_minutes.append(gap)
            student_idle_minutes.append(group["students"] * gap)

    return sum(idle_minutes), sum(student_idle_minutes)


def parallel_pairs(ctx):
    """Find distinct events of the same course with the same meeting days."""
    course_events = defaultdict(set)
    for section_id, event_id in ctx["section_event"].items():
        section = ctx["sections"][section_id]
        pattern = ctx["patterns"][section["pattern_id"]]
        key = (section["course_code"], tuple(sorted(pattern["days"])))
        course_events[key].add(event_id)

    pairs = {
        tuple(sorted(pair))
        for event_ids in course_events.values()
        for pair in combinations(event_ids, 2)
    }
    return sorted(pairs)


def add_objective(model, ctx, starts, idle):
    """Tell the solver how to score timetables using the preference weights.

    ``idle`` is the (group idle minutes, student-weighted idle minutes) pair
    returned by :func:`add_group_constraints`.
    """
    idle, student_idle = idle
    late_minutes = []
    source_shifts = []
    parallel_starts = []

    for event_id, event in ctx["events"].items():
        pattern = ctx["patterns"][event["pattern_id"]]
        excess = model.new_int_var(0, MINUTES_PER_DAY, f"late@{event_id}")
        model.add_max_equality(
            excess,
            [0, starts[event_id] + pattern["duration"] - ctx["data"]["late_after"]],
        )
        late_minutes.append(len(pattern["days"]) * excess)

    for section_id, event_id in ctx["section_event"].items():
        shift = model.new_int_var(0, MINUTES_PER_DAY, f"shift@{section_id}")
        source_start = ctx["sections"][section_id]["source_start"]
        model.add_abs_equality(shift, starts[event_id] - source_start)
        source_shifts.append(shift)

    for first_id, second_id in parallel_pairs(ctx):
        same_start = model.new_bool_var(f"same_start@{first_id}@{second_id}")
        model.add(starts[first_id] == starts[second_id]).only_enforce_if(same_start)
        model.add(starts[first_id] != starts[second_id]).only_enforce_if(
            same_start.Not()
        )
        parallel_starts.append(same_start)

    terms = {
        "group_idle_minutes": idle,
        "student_idle_minutes": student_idle,
        "late_meeting_minutes": sum(late_minutes),
        "source_shift_minutes": sum(source_shifts),
        "parallel_same_start": sum(parallel_starts),
    }
    weights = ctx["data"]["objective_weights"]
    model.minimize(
        sum(weights.get(name, 0) * expression for name, expression in terms.items()
            if weights.get(name, 0))
    )
