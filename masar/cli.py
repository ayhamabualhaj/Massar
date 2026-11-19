"""Command-line options and the prepare, solve, export workflow."""
import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import ortools

from .demand.scenario import ScenarioOptionError, prepare_scenario
from .reports.output import PublishError, new_run_dir, prune_runs, publish_run, recover_interrupted_publish, write_outputs
from .scheduling.solver import solve


EXIT_OK = 0
EXIT_NO_TIMETABLE = 2


def main(argv=None):
    """Read the run options, prepare course demand, find a timetable, and save the result.

    Every run is recorded in the companion extra information folder. Only a run with an
    independently validated timetable replaces the active output. Returns the process
    exit status: 0 when a validated timetable was published, 2 otherwise.
    """
    root = Path(__file__).resolve().parent.parent
    parser = _argument_parser()
    # args holds the options for this run, including defaults for any you left out.
    args = parser.parse_args(argv)
    if not 0 < args.seconds <= 285:
        parser.error('--seconds must be greater than zero and at most 285 seconds (under five minutes).')
    if args.requests and args.fixed_sections:
        parser.error('--requests creates course demand; use section planning rather than --fixed-sections.')
    try:
        scenario = prepare_scenario(
            root, args.input, args.requests, fixed_sections=args.fixed_sections,
            save_projection=args.input is None and args.output is None,
        )
    except ScenarioOptionError as exc:
        parser.error(str(exc))

    data = scenario.data
    forecast = data.get('enrollment_generation', {})
    data['solver_memory_limit_mb'] = args.memory_mb
    data['solver_workers'] = args.workers or data.get('solver_workers', forecast.get('solver_workers', 4))
    data['solver_route_limit'] = args.routes or data.get('solver_route_limit', forecast.get('solver_route_limit', 3))
    print(f"Solver budget: {args.seconds:g} seconds; {data['solver_workers']} search workers; memory guard {args.memory_mb} MB.", flush=True)
    out = (args.output or root / 'masar_v2_output').resolve()
    state = out.parent / 'extra information' / out.name
    # A fingerprint lets us recognize the exact input used for an earlier timetable.
    input_sha256 = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    recover_interrupted_publish(state)
    hint = None if args.fixed_sections else _previous_solution(state, input_sha256)
    result = solve(data, optimize=not args.no_optimize, seconds=args.seconds,
                   plan_sections=not args.fixed_sections, hints=hint)
    result['run_metadata'] = dict(
        generated_at=datetime.now(timezone.utc).isoformat(), python_version=platform.python_version(),
        ortools_version=ortools.__version__, time_budget_seconds=args.seconds,
        input_sha256=input_sha256,
        demand_source=scenario.demand_source,
        constraints=dict(rooms=True, student_groups=True, teachers=data['teachers_enabled']))
    print(result["status"], result["diagnostics"])
    if result.get("section_plan"):
        plan = result["section_plan"]
        print(f"Opened sections: {plan['opened_sections']}; minimum proven: {plan['minimum_proven']}")
    if result['validation']:
        print(f"Validation: {result['validation']['hard_rule_violations']} hard constraint violations.")
    run_dir = new_run_dir(state)
    write_outputs(scenario, result, run_dir)
    print(f"Run saved in {run_dir}", flush=True)
    if not result.get('publishable'):
        print(f"NOT PUBLISHED: no validated timetable ({result['status']}). "
              f"The active timetable in {out} was left unchanged.", flush=True)
        prune_runs(state)
        return EXIT_NO_TIMETABLE
    reports = state.parent if out == root / 'masar_v2_output' else state / 'reports'
    try:
        publish_run(run_dir, state, reports, timetable=out / 'timetable.csv')
    except PublishError as error:
        print(f"NOT PUBLISHED: {error} The active timetable in {out} was left unchanged.", flush=True)
        return EXIT_NO_TIMETABLE
    prune_runs(state)
    print(f"Published timetable: {out / 'timetable.csv'}", flush=True)
    return EXIT_OK

def _argument_parser():
    """Define the options you can pass when starting Massar and their default values."""
    parser = argparse.ArgumentParser(description='Estimate course demand and plan a timetable.')
    parser.add_argument('--input', type=Path, help='Scheduling JSON (default: data/masar_data_v2.json).')
    parser.add_argument('--requests', type=Path, help='JSON list of explicit student course-request bundles.')
    parser.add_argument('--output', type=Path, help='Directory for timetable.csv. Run details go in the adjacent extra information folder.')
    parser.add_argument('--seconds', type=float, default=240,
                        help='Scheduling time budget in seconds (default: 240 = 4 minutes; maximum: 285).')
    parser.add_argument('--workers', type=int, choices=[1, 2, 4, 8], help='Parallel section-search workers (default: input setting, otherwise 4).')
    parser.add_argument('--routes', type=int, choices=range(1, 9), help='Maximum timetable routes per estimated group in compact search (default: input setting, otherwise 3).')
    parser.add_argument('--memory-mb', type=int, default=16384, help='Observed solver process memory budget (default: 16384 MB = 16 GB); sampled stop guard.')
    parser.add_argument('--fixed-sections', action='store_true', help='Keep the supplied section list; do not minimize its count.')
    parser.add_argument('--no-optimize', action='store_true', help='Skip second-stage timetable preferences.')
    return parser


def _previous_solution(out, input_sha256):
    """Load a saved timetable as a starting point if its input matches this run."""
    path = out / 'result.json'
    if path.exists():
        candidate = json.loads(path.read_text(encoding='utf-8'))
        if candidate.get('has_solution') and candidate.get('run_metadata', {}).get('input_sha256') == input_sha256:
            print(f"Starting from {len(candidate.get('planned_sections', []))} validated sections.", flush=True)
            return candidate
    return None
