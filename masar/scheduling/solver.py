"""Run section planning or schedule a fixed list of sections."""
import math

from ortools.sat.python import cp_model

from .checker import inspect_solution
from .constraints import add_group_constraints, add_objective, add_room_constraints
from masar.validation import need, prepare
from .staffing import add_teacher_constraints
from .memory import DEFAULT_MEMORY_MB, solve_with_memory_limit


def _find_input_problems(ctx):
    """Flag events with missing scheduling options before starting the search."""
    diagnostics = []
    for event_id, event in ctx["events"].items():
        pattern = ctx["patterns"][event["pattern_id"]]
        if not pattern["starts"]:
            diagnostics.append(f"{event_id}: no allowed start times.")
        if event["delivery"] != "online" and not ctx["eligible"][event_id]:
            diagnostics.append(f"{event_id}: no room fits capacity and compatibility.")
    return diagnostics


def _read_assignments(ctx, solver, starts, room_choices, teacher_choices=None):
    """Translate the solver's room and time choices into meeting records."""
    assignments = []
    for event_id, event in ctx["events"].items():
        start = solver.value(starts[event_id])
        pattern = ctx["patterns"][event["pattern_id"]]
        room_id = next(
            (
                room_id
                for room_id, selected in room_choices.get(event_id, {}).items()
                if solver.boolean_value(selected)
            ),
            None,
        )
        assignments.append({
            "event_id": event_id,
            "source_ids": event["source_ids"],
            "start": start,
            "room_id": room_id,
            "meetings": [
                {"day": day, "start": start, "end": start + pattern["duration"]}
                for day in pattern["days"]
            ],
        })
        if ctx['data']['teachers_enabled']:
            assignments[-1]['teacher_id'] = next(tid for tid, var in teacher_choices[event_id].items()
                                                  if solver.boolean_value(var))
    return assignments


def _group_coverage(ctx):
    """Summarize which teaching events are represented in student groups."""
    covered_events = {
        event_id
        for group in ctx["groups"].values()
        for event_id in group["event_ids"]
    }
    return {
        "events": len(ctx["events"]),
        "events_in_student_groups": len(covered_events),
        "unprotected_event_ids": sorted(set(ctx["events"]) - covered_events),
    }


def _solve_fixed(data, optimize=True, seconds=30, hints=None, workers=1):
    """Build and solve a timetable without changing input data or writing files."""
    need(type(optimize) is bool, "optimize must be Boolean.")
    need(
        type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
        "seconds must be finite and positive.",
    )
    ctx = prepare(data)
    result = {
        "status": None,
        "has_solution": False,
        "assignments": [],
        "validation": None,
        "diagnostics": _find_input_problems(ctx),
        "mode": "weighted_optimization" if optimize else "feasibility",
        "objective_bound": None,
    }
    if result["diagnostics"]:
        result["status"] = "INFEASIBLE"
        return result

    model = cp_model.CpModel()
    starts = {
        event_id: model.new_int_var_from_domain(
            cp_model.Domain.from_values(ctx["patterns"][event["pattern_id"]]["starts"]),
            f"start@{event_id}",
        )
        for event_id, event in ctx["events"].items()
    }
    room_choices = add_room_constraints(model, ctx, starts)
    teacher_choices = add_teacher_constraints(model, ctx, starts)
    idle_minutes = add_group_constraints(model, ctx, starts)
    if optimize:
        add_objective(model, ctx, starts, idle_minutes)

    for assignment in hints or []:
        event_id = assignment["event_id"]
        model.add_hint(starts[event_id], assignment["start"])
        for room_id, selected in room_choices.get(event_id, {}).items():
            model.add_hint(selected, int(room_id == assignment["room_id"]))
        for tid, selected in teacher_choices.get(event_id, {}).items():
            model.add_hint(selected, int(tid == assignment.get('teacher_id')))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(seconds)
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 0

    memory_limit = data.get('solver_memory_limit_mb', DEFAULT_MEMORY_MB)
    need(type(memory_limit) is int and memory_limit >= 256, 'Memory limit must be an integer of at least 256 MB.')
    status, memory_stopped, peak_memory = solve_with_memory_limit(solver, model, memory_limit)
    result["status"] = solver.status_name(status)
    # The guard may stop before the search starts, in which case there is no wall time.
    result["solver_seconds"] = solver.wall_time if not (memory_stopped and status == cp_model.UNKNOWN) else 0.0
    result["search_statistics"] = dict(memory_limit_mb=memory_limit, observed_peak_rss_mb=peak_memory,
                                       stopped_for_memory=memory_stopped)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if memory_stopped:
            result["diagnostics"] = [f"Search stopped at the {memory_limit} MB process memory budget; "
                                     "feasibility remains unknown."]
            return result
        messages = {
            "INFEASIBLE": "Hard constraints cannot all be satisfied.",
            "UNKNOWN": "No solution or infeasibility proof before search stopped.",
            "MODEL_INVALID": model.validate(),
        }
        result["diagnostics"] = [
            messages.get(result["status"], "No usable solution.")
        ]
        return result

    assignments = _read_assignments(ctx, solver, starts, room_choices, teacher_choices)
    validation = inspect_solution(ctx, assignments)
    result["validation"] = validation
    if not validation["valid"]:
        result["status"] = "VALIDATION_FAILED"
        result["diagnostics"] = validation["errors"]
        return result

    if optimize:
        need(
            round(solver.objective_value) == validation["weighted_score"],
            "Internal objective/checker mismatch.",
        )
        result["objective_bound"] = solver.best_objective_bound

    result["has_solution"] = True
    result["assignments"] = assignments
    result["coverage"] = _group_coverage(ctx)
    return result


def solve(data, optimize=True, seconds=30, plan_sections=True, hints=None):
    """Minimize required sections, then improve their timetable preferences.

    Set plan_sections=False to schedule an explicitly fixed section list.
    """
    need(type(plan_sections) is bool, "plan_sections must be Boolean.")
    if not plan_sections:
        return _solve_fixed(data, optimize=optimize, seconds=seconds)
    from .planning import solve_sections

    result = solve_sections(data, optimize=optimize, seconds=seconds, hints=hints)
    import copy
    for key in ("group_inference", "enrollment_projection"):
        if data.get(key):
            result[key] = copy.deepcopy(data[key])
    return result
