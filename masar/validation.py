from collections import defaultdict


OBJECTIVE_KEYS = {
    "group_idle_minutes",
    "late_meeting_minutes",
    "source_shift_minutes",
    "parallel_same_start",
}


class InputError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise InputError(message)


def whole(value, minimum=0, maximum=1440):
    return type(value) is int and minimum <= value <= maximum


def index_records(records, label):
    need(isinstance(records, list), f"{label} must be a list.")
    indexed = {}
    for record in records:
        need(isinstance(record, dict), f"{label}: each record must be an object.")
        record_id = record.get("id")
        need(
            isinstance(record_id, str) and record_id and record_id not in indexed,
            f"{label}: missing or duplicate string id: {record_id}.",
        )
        indexed[record_id] = record
    return indexed


def _validate_rooms(rooms):
    for room_id, room in rooms.items():
        need(isinstance(room.get("type"), str), f"{room_id}: missing room type.")
        need(whole(room.get("capacity"), 1, 100000), f"{room_id}: invalid capacity.")
        need(
            isinstance(room.get("blackouts", []), list),
            f"{room_id}: blackouts must be a list.",
        )
        for blackout in room.get("blackouts", []):
            need(
                isinstance(blackout, dict)
                and whole(blackout.get("day"), 1, 7)
                and whole(blackout.get("start"))
                and whole(blackout.get("end"))
                and blackout["start"] < blackout["end"],
                f"{room_id}: invalid blackout.",
            )


def _merge_blackouts(rooms):
    """Merge overlapping closures so they do not clash with each other."""
    normalized_rooms = {}
    for room_id, room in rooms.items():
        daily_closures = defaultdict(list)
        for blackout in room.get("blackouts", []):
            daily_closures[blackout["day"]].append(
                (blackout["start"], blackout["end"])
            )

        merged = []
        for day, periods in daily_closures.items():
            for start, end in sorted(periods):
                if merged and merged[-1]["day"] == day and start <= merged[-1]["end"]:
                    merged[-1]["end"] = max(merged[-1]["end"], end)
                else:
                    merged.append({"day": day, "start": start, "end": end})
        normalized_rooms[room_id] = dict(room, blackouts=merged)

    return normalized_rooms


def _validate_patterns(patterns):
    for pattern_id, pattern in patterns.items():
        need(isinstance(pattern, dict), f"{pattern_id}: pattern must be an object.")
        days = pattern.get("days")
        starts = pattern.get("starts")
        duration = pattern.get("duration")
        need(
            isinstance(days, list) and days and all(whole(day, 1, 7) for day in days),
            f"{pattern_id}: invalid days.",
        )
        need(len(days) == len(set(days)), f"{pattern_id}: duplicate days.")
        need(whole(duration, 1), f"{pattern_id}: invalid duration.")
        need(
            isinstance(starts, list)
            and all(whole(start) and start + duration <= 1440 for start in starts),
            f"{pattern_id}: invalid starts.",
        )
        need(len(starts) == len(set(starts)), f"{pattern_id}: duplicate starts.")


def _active_sections(sections, patterns, compatibility):
    active = {}
    for section_id, section in sections.items():
        need(
            isinstance(section.get("course_code"), str)
            and isinstance(section.get("name_ar"), str),
            f"{section_id}: missing course identity.",
        )
        need(
            section.get("status") in ("scheduled", "no_meeting_days"),
            f"{section_id}: unknown status.",
        )
        if section["status"] == "no_meeting_days":
            continue

        pattern_id = section.get("pattern_id")
        requirement = section.get("room_requirement")
        need(
            isinstance(pattern_id, str) and pattern_id in patterns,
            f"{section_id}: unknown pattern.",
        )
        need(
            isinstance(requirement, str) and requirement in compatibility,
            f"{section_id}: unknown room requirement.",
        )
        need(
            section.get("delivery") in ("online", "in_person"),
            f"{section_id}: invalid delivery.",
        )
        need(
            whole(section.get("students"), 1, 100000),
            f"{section_id}: invalid students.",
        )
        need(
            whole(section.get("source_start"), 0, 1439),
            f"{section_id}: invalid source time.",
        )
        active[section_id] = section

    need(bool(active), "No sections with meeting days.")
    return active


def _resolve_events(sections, active, shared_classes):
    section_events = {section_id: section_id for section_id in active}
    used_sections = set()

    for event_id, shared_class in shared_classes.items():
        section_ids = shared_class.get("section_ids")
        need(
            event_id not in sections,
            f"{event_id}: shared event ID collides with a source section ID.",
        )
        need(
            isinstance(section_ids, list)
            and len(section_ids) >= 2
            and all(
                isinstance(section_id, str) and section_id in active
                for section_id in section_ids
            ),
            f"{event_id}: invalid shared-class members.",
        )
        need(
            len(section_ids) == len(set(section_ids))
            and not used_sections.intersection(section_ids),
            f"{event_id}: duplicate shared members.",
        )
        need(
            whole(shared_class.get("students"), 1, 100000),
            f"{event_id}: explicit total enrollment required.",
        )
        for field in ("pattern_id", "delivery", "room_requirement"):
            need(
                len({active[section_id][field] for section_id in section_ids}) == 1,
                f"{event_id}: inconsistent {field}.",
            )
        for section_id in section_ids:
            section_events[section_id] = event_id
        used_sections.update(section_ids)

    event_members = defaultdict(list)
    for section_id, event_id in section_events.items():
        event_members[event_id].append(section_id)

    events = {}
    for event_id, section_ids in event_members.items():
        first_section = active[section_ids[0]]
        enrollment = (
            shared_classes[event_id]["students"]
            if event_id in shared_classes
            else first_section["students"]
        )
        events[event_id] = dict(
            first_section, id=event_id, source_ids=section_ids, students=enrollment
        )

    return events, section_events


def _resolve_groups(groups, active, events, section_events):
    enrollment_totals = defaultdict(int)
    resolved = {}
    for group_id, group in groups.items():
        section_ids = group.get("section_ids")
        need(
            isinstance(section_ids, list)
            and section_ids
            and all(
                isinstance(section_id, str) and section_id in active
                for section_id in section_ids
            ),
            f"{group_id}: unknown or unscheduled section in group.",
        )
        need(
            len(section_ids) == len(set(section_ids)),
            f"{group_id}: repeated section.",
        )
        need(whole(group.get("students"), 1, 100000), f"{group_id}: invalid students.")
        event_ids = sorted({section_events[section_id] for section_id in section_ids})
        resolved[group_id] = dict(group, event_ids=event_ids)
        for event_id in event_ids:
            enrollment_totals[event_id] += group["students"]

    need(
        all(
            enrollment_totals[event_id] <= events[event_id]["students"]
            for event_id in enrollment_totals
        ),
        "Mock groups are disjoint: their enrollment totals cannot exceed "
        "section/event enrollment.",
    )
    return resolved


def _validate_objective(data):
    weights = data.get("objective_weights")
    need(
        isinstance(weights, dict) and set(weights) == OBJECTIVE_KEYS,
        "Unsupported objective keys.",
    )
    need(
        all(whole(weight, 0, 1000000) for weight in weights.values()),
        "Objective weights must be nonnegative integers.",
    )
    need(
        whole(data.get("late_after")),
        "late_after must be minutes after midnight.",
    )


def _eligible_rooms(events, rooms, compatibility):
    return {
        event_id: [
            room_id
            for room_id, room in rooms.items()
            if room["type"] in compatibility[event["room_requirement"]]
            and room["capacity"] >= event["students"]
        ]
        for event_id, event in events.items()
        if event["delivery"] != "online"
    }


def prepare(data):
    """Validate configuration and prepare events, groups, and eligible rooms."""
    need(
        isinstance(data, dict) and data.get("schema_version") == "2.0",
        "Expected schema_version 2.0.",
    )
    need(data.get("teachers_enabled") is False, "Teacher scheduling is not implemented.")
    rooms = index_records(data.get("rooms"), "rooms")
    sections = index_records(data.get("sections"), "sections")
    groups = index_records(data.get("groups"), "groups")
    shared_classes = index_records(data.get("shared_classes"), "shared_classes")
    patterns = data.get("patterns")
    compatibility = data.get("compatibility")
    need(
        isinstance(patterns, dict) and patterns,
        "patterns must be a nonempty object.",
    )
    need(isinstance(compatibility, dict), "compatibility must be an object.")

    _validate_rooms(rooms)
    rooms = _merge_blackouts(rooms)
    for requirement, room_types in compatibility.items():
        need(
            isinstance(room_types, list)
            and all(isinstance(room_type, str) for room_type in room_types),
            f"{requirement}: invalid room type list.",
        )
    _validate_patterns(patterns)
    active = _active_sections(sections, patterns, compatibility)
    events, section_events = _resolve_events(sections, active, shared_classes)
    resolved_groups = _resolve_groups(groups, active, events, section_events)
    _validate_objective(data)

    return {
        "data": data,
        "rooms": rooms,
        "sections": sections,
        "patterns": patterns,
        "events": events,
        "groups": resolved_groups,
        "section_event": section_events,
        "eligible": _eligible_rooms(events, rooms, compatibility),
    }
