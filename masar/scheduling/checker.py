"""Check a finished timetable for conflicts and measure its preferences."""
from collections import defaultdict
from itertools import combinations

from .constraints import parallel_pairs
from .staffing import check_teachers


def _check_assignments(ctx, assignments, errors, metrics):
    """Check assigned times and rooms, and collect meetings for the conflict checks."""
    scheduled = {}
    room_meetings = defaultdict(list)

    for assignment in assignments:
        event_id = assignment.get("event_id")
        if event_id not in ctx["events"] or event_id in scheduled:
            errors.append(f"Unknown or repeated event: {event_id}")
            continue

        scheduled[event_id] = assignment
        event = ctx["events"][event_id]
        pattern = ctx["patterns"][event["pattern_id"]]
        start = assignment.get("start")
        room_id = assignment.get("room_id")
        if type(start) is not int or start not in pattern["starts"]:
            errors.append(f"{event_id}: invalid start time.")
            continue

        if event["delivery"] == "online":
            if room_id is not None:
                errors.append(f"{event_id}: online event has a physical room.")
        elif room_id not in ctx["rooms"]:
            errors.append(f"{event_id}: unknown room.")
        else:
            room = ctx["rooms"][room_id]
            if room["capacity"] < event["students"]:
                errors.append(f"{event_id}: capacity exceeded.")
            allowed_types = ctx["data"]["compatibility"][event["room_requirement"]]
            if room["type"] not in allowed_types:
                errors.append(f"{event_id}: incompatible room.")

        expected_meetings = [
            {"day": day, "start": start, "end": start + pattern["duration"]}
            for day in pattern["days"]
        ]
        if assignment.get("meetings") != expected_meetings:
            errors.append(f"{event_id}: recurring meetings were changed.")

        for meeting in expected_meetings:
            if room_id is not None:
                room_meetings[room_id, meeting["day"]].append(
                    (meeting["start"], meeting["end"], event_id)
                )

        late_minutes = max(
            0, start + pattern["duration"] - ctx["data"]["late_after"]
        )
        metrics["late_meeting_minutes"] += len(pattern["days"]) * late_minutes

    if set(scheduled) != set(ctx["events"]):
        errors.append("Not every event was scheduled exactly once.")

    return scheduled, room_meetings


def _check_room_clashes(ctx, room_meetings, errors):
    """Find meetings that overlap in a room or fall during a room closure."""
    for room_id, room in ctx["rooms"].items():
        for blackout in room.get("blackouts", []):
            room_meetings[room_id, blackout["day"]].append(
                (blackout["start"], blackout["end"], "BLACKOUT")
            )

    for (room_id, day), meetings in room_meetings.items():
        for first, second in combinations(meetings, 2):
            if _overlap(first, second):
                errors.append(
                    f"Room clash {room_id}, day {day}: {first[2]}, {second[2]}."
                )


def _overlap(first, second):
    """Return whether two time intervals share any time, allowing back-to-back meetings."""
    return max(first[0], second[0]) < min(first[1], second[1])


def _check_group_clashes(ctx, scheduled, errors, metrics):
    """Find overlapping classes and gaps in each student group's day."""
    group_report = []
    for group_id, group in ctx["groups"].items():
        daily_meetings = defaultdict(list)
        for event_id in group["event_ids"]:
            if event_id not in scheduled:
                continue
            start = scheduled[event_id].get("start")
            if type(start) is not int:
                continue

            event = ctx["events"][event_id]
            pattern = ctx["patterns"][event["pattern_id"]]
            for day in pattern["days"]:
                daily_meetings[day].append(
                    (start, start + pattern["duration"], event_id)
                )

        for day, meetings in daily_meetings.items():
            for first, second in combinations(meetings, 2):
                if _overlap(first, second):
                    errors.append(
                        f"Student clash {group_id}, day {day}: "
                        f"{first[2]}, {second[2]}."
                    )

            first_start = min(start for start, _, _ in meetings)
            last_end = max(end for _, end, _ in meetings)
            teaching_minutes = sum(end - start for start, end, _ in meetings)
            gap = last_end - first_start - teaching_minutes
            metrics["group_idle_minutes"] += gap
            metrics["student_idle_minutes"] += gap * group["students"]
            group_report.append({
                "group_id": group_id,
                "day": day,
                "students": group["students"],
                "idle_minutes": gap,
            })

    return group_report


def _measure_preferences(ctx, scheduled, metrics):
    """Measure how well the timetable meets the configured scheduling preferences."""
    for section_id, event_id in ctx["section_event"].items():
        if event_id in scheduled and type(scheduled[event_id].get("start")) is int:
            original_start = ctx["sections"][section_id]["source_start"]
            metrics["source_shift_minutes"] += abs(
                scheduled[event_id]["start"] - original_start
            )

    for first_id, second_id in parallel_pairs(ctx):
        if first_id in scheduled and second_id in scheduled:
            metrics["parallel_same_start"] += int(
                scheduled[first_id]["start"] == scheduled[second_id]["start"]
            )


def inspect_solution(ctx, assignments):
    """Check assignments independently of the solver and calculate their score."""
    errors = []
    metrics = defaultdict(int)
    scheduled, room_meetings = _check_assignments(ctx, assignments, errors, metrics)
    _check_room_clashes(ctx, room_meetings, errors)
    check_teachers(ctx, scheduled, errors)
    group_report = _check_group_clashes(ctx, scheduled, errors, metrics)
    _measure_preferences(ctx, scheduled, metrics)

    weights = ctx["data"]["objective_weights"]
    score = sum(weight * metrics[name] for name, weight in weights.items())
    return {
        "valid": not errors,
        "hard_rule_violations": len(errors),
        "errors": errors,
        "metrics": dict(metrics),
        "weighted_score": score,
        "group_day_gaps": group_report,
    }
