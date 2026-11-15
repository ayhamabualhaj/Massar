import math

from ortools.sat.python import cp_model

from .checker import inspect_solution
from .constraints import add_group_constraints, add_objective, add_room_constraints
from .validation import need, prepare


def _find_input_problems(ctx):
    diagnostics = []
    for event_id, event in ctx["events"].items():
        pattern = ctx["patterns"][event["pattern_id"]]
        if not pattern["starts"]:
            diagnostics.append(f"{event_id}: no allowed start times.")
        if event["delivery"] != "online" and not ctx["eligible"][event_id]:
            diagnostics.append(f"{event_id}: no room fits capacity and compatibility.")
    return diagnostics


def _read_assignments(ctx, solver, starts, room_choices):
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
    return assignments


def _group_coverage(ctx):
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


def solve(data, optimize=True, seconds=30):
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
    idle_minutes = add_group_constraints(model, ctx, starts)
    if optimize:
        add_objective(model, ctx, starts, idle_minutes)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0

    status = solver.solve(model)
    result["status"] = solver.status_name(status)
    result["solver_seconds"] = solver.wall_time
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = {
            "INFEASIBLE": "Hard constraints cannot all be satisfied.",
            "UNKNOWN": "No solution or infeasibility proof before search stopped.",
            "MODEL_INVALID": model.validate(),
        }
        result["diagnostics"] = [
            messages.get(result["status"], "No usable solution.")
        ]
        return result

    assignments = _read_assignments(ctx, solver, starts, room_choices)
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
