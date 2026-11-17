"""Run this file in PyCharm to generate the timetable."""
import json
import os
import sys
import argparse
import hashlib
import platform
from datetime import datetime, timezone
from pathlib import Path


def _use_project_interpreter():
    """Use the local virtual environment even with stale IDE interpreter settings."""
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    interpreter = environment / "bin" / "python"
    if interpreter.is_file() and Path(sys.prefix).resolve() != environment.resolve():
        arguments = [str(interpreter)]
        if sys.dont_write_bytecode:
            arguments.append("-B")
        os.execv(str(interpreter), arguments + [str(root / "main.py"), *sys.argv[1:]])


if __name__ == "__main__":
    _use_project_interpreter()

import pandas as pd

from masar.solver import solve
from masar.reporting import table_rows, TABLE_COLUMNS
from masar.student_groups import with_plan_groups
from masar.group_reporting import write_group_reports
from masar.enrollment import with_intake_enrollments, read_intakes
from masar.enrollment_reporting import write_enrollment_reports
from masar.requests import with_course_requests
from masar.audit import write_audit_reports
from masar.historical_audit import write_historical_audit
from masar.estimated_meetings import with_estimated_meetings
from masar.external_courses import with_external_courses, write_external_reports
from masar.room_free import with_room_free_activities
from masar.settings import (read_settings, read_course_switches, read_major_totals,
                            apply_room_capacities, apply_student_counts, apply_major_totals)


def _teaching_reference(root, data, room_capacities=None):
    forecast = data.get('enrollment_generation', {})
    if not forecast.get('enabled'):
        return data, None
    reference = json.loads((root / forecast['reference_source']).read_text(encoding='utf-8'))
    if room_capacities is not None:
        reference = apply_room_capacities(reference, room_capacities)
    curriculum = json.loads((root / forecast['curriculum_source']).read_text(encoding='utf-8'))
    enabled = set(forecast.get('enabled_course_codes',
        [row['course_code'] for row in curriculum['records']]))
    if forecast.get('estimated_meeting_courses'):
        reference = with_estimated_meetings(reference, curriculum,
            [code for code in forecast['estimated_meeting_courses'] if code in enabled])
    if forecast.get('room_free_course_codes'):
        reference = with_room_free_activities(reference, curriculum,
            [code for code in forecast['room_free_course_codes'] if code in enabled])
    if forecast.get('external_courses', {}).get('enabled'):
        reference = with_external_courses(reference, forecast['external_courses'])
    reference['sections'] = [section for section in reference['sections']
                             if section['course_code'] in enabled]
    reference['course_catalog_scope'] = dict(records=[record for record in curriculum['records']
        if record['category'] in ('كلية إجباري', 'تخصص إجباري', 'تخصص اختياري')])
    return reference, curriculum


def main(argv=None):
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='Estimate course demand and plan a timetable.')
    parser.add_argument('--input', type=Path, help='Scheduling JSON (default: data/masar_data_v2.json).')
    parser.add_argument('--requests', type=Path, help='JSON list of explicit student course-request bundles.')
    parser.add_argument('--output', type=Path, help='Separate directory for a scenario run and its reports.')
    parser.add_argument('--seconds', type=float, default=1800, help='Scheduling time budget in seconds (default: 1800 = 30 minutes).')
    parser.add_argument('--workers', type=int, choices=[1,2,4,8], help='Parallel section-search workers (default: input setting, otherwise 4).')
    parser.add_argument('--routes', type=int, choices=range(1,9), help='Maximum timetable routes per estimated group in compact search (default: input setting, otherwise 3).')
    parser.add_argument('--memory-mb', type=int, default=16384, help='Observed solver process memory budget (default: 16384 MB = 16 GB); sampled stop guard.')
    parser.add_argument('--fixed-sections', action='store_true', help='Keep the supplied section list; do not minimize its count.')
    parser.add_argument('--no-optimize', action='store_true', help='Skip second-stage timetable preferences.')
    args = parser.parse_args(argv)
    if args.requests and args.fixed_sections:
        parser.error('--requests creates course demand; use section planning rather than --fixed-sections.')
    data = json.loads((args.input or root / 'data/masar_data_v2.json').read_text(encoding='utf-8'))
    room_capacities, student_counts = read_settings(root / 'settings')
    data = apply_room_capacities(data, room_capacities)
    forecast = data.get("enrollment_generation", {})
    if forecast.get('enabled'):
        catalog = json.loads((root / forecast['curriculum_source']).read_text(encoding='utf-8'))
        switches = read_course_switches(root / 'settings/courses',
            {row['course_code'] for row in catalog['records']})
        forecast = dict(forecast, enabled_course_codes=sorted(code for code, enabled in switches.items() if enabled))
        data['enrollment_generation'] = forecast
    historical_reference = (json.loads((root / forecast['reference_source']).read_text(encoding='utf-8'))
                            if forecast.get('enabled') else data)
    reference = data
    if args.requests:
        reference, _ = _teaching_reference(root, data, room_capacities)
        data = with_course_requests(reference, json.loads(args.requests.read_text(encoding='utf-8')))
        forecast = data['enrollment_generation']
        print('Demand source: supplied course requests.')
    if args.fixed_sections and forecast.get('enabled'):
        parser.error('--fixed-sections requires a fixed section input, not an intake-demand snapshot.')
    curriculum = None
    if forecast.get("enabled"):
        reference, curriculum = _teaching_reference(root, data, room_capacities)
        major_totals = read_major_totals(root / 'settings', forecast['program_names'])
        effective_counts = apply_major_totals(student_counts, major_totals)
        intakes = apply_student_counts(read_intakes(root / forecast["intake_source"]), effective_counts,
                                       forecast['program_names'])
        forecast = dict(forecast, major_student_totals=major_totals,
                        major_student_totals_source='settings/student/major_students.csv')
        data['enrollment_generation'] = forecast
        data = with_intake_enrollments(reference, curriculum, intakes,
                                       policy=forecast, cached_projection=data.get("enrollment_projection"))
        if forecast.get('estimate_missing_profile_meetings'):
            missing=sorted({code for c in data['enrollment_projection']['cohorts'] for code in c['unavailable_courses']})
            if missing:
                forecast=dict(data['enrollment_generation'])
                forecast['estimated_meeting_courses']=sorted(set(forecast.get('estimated_meeting_courses',[]))|set(missing))
                reference=with_estimated_meetings(reference,curriculum,forecast['estimated_meeting_courses'])
                if forecast.get('room_free_course_codes'):
                    reference=with_room_free_activities(reference,curriculum,forecast['room_free_course_codes'])
                if forecast.get('external_courses',{}).get('enabled'):
                    reference=with_external_courses(reference,forecast['external_courses'])
                data=with_intake_enrollments(reference,curriculum,intakes,
                    policy=forecast,cached_projection=data['enrollment_projection'])
        print(f"Estimated students: {data['enrollment_projection']['estimated_students']}; "
              f"cohort groups: {len(data['groups'])}")
        if args.input is None and args.output is None:
            (root / "data/masar_data_v2.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    demand_run = bool(forecast.get("enabled") or args.requests)
    policy = data.get("group_generation", {})
    if not forecast.get("enabled") and policy.get("enabled"):
        curriculum = json.loads((root / policy["source"]).read_text(encoding="utf-8"))
        data = with_plan_groups(data, curriculum)
        report = data["group_inference"]
        print(f"Plan-derived groups: {report['group_count']}; "
              f"modeled course enrollments: {report['modeled_course_enrollments']}/"
              f"{report['total_course_enrollments']}")
    elif not forecast.get("enabled"):
        data.pop("group_inference", None)
    data['solver_memory_limit_mb'] = args.memory_mb
    data['solver_workers'] = args.workers or data.get('solver_workers', forecast.get('solver_workers', 4))
    data['solver_route_limit'] = args.routes or data.get('solver_route_limit', forecast.get('solver_route_limit', 3))
    print(f"Solver budget: {args.seconds:g} seconds; {data['solver_workers']} search workers; memory guard {args.memory_mb} MB.", flush=True)
    out = args.output or root / 'masar_v2_output'
    input_sha256 = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    previous_hint = None
    if (out / 'result.json').exists() and not args.fixed_sections:
        candidate = json.loads((out / 'result.json').read_text(encoding='utf-8'))
        if candidate.get('has_solution') and candidate.get('run_metadata', {}).get('input_sha256') == input_sha256:
            previous_hint = candidate
            print(f"Starting from {len(candidate.get('planned_sections', []))} validated sections.", flush=True)
    result = solve(data, optimize=not args.no_optimize, seconds=args.seconds, plan_sections=not args.fixed_sections, hints=previous_hint)
    import ortools
    result['run_metadata'] = dict(
        generated_at=datetime.now(timezone.utc).isoformat(), python_version=platform.python_version(),
        ortools_version=ortools.__version__, time_budget_seconds=args.seconds,
        input_sha256=input_sha256,
        demand_source='supplied_course_requests' if args.requests else 'intake_forecast' if forecast.get('enabled') else 'section_counts',
        constraints=dict(rooms=True, student_groups=True, teachers=data['teachers_enabled']))
    print(result["status"], result["diagnostics"])
    if result.get("section_plan"):
        plan = result["section_plan"]
        print(f"Opened sections: {plan['opened_sections']}; minimum proven: {plan['minimum_proven']}")
    if result['validation']:
        print(f"Validation: {result['validation']['hard_rule_violations']} hard constraint violations.")
    out = args.output or root / 'masar_v2_output'
    out.mkdir(parents=True, exist_ok=True)
    (out / "input_snapshot.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    information = out / 'reports' if args.output else root / 'extra information'
    result['data_quality'] = write_audit_reports(data, reference, result, information/'model_audit')
    historical_audit = write_historical_audit(historical_reference, information/'model_audit')
    result['historical_schedule_audit'] = historical_audit
    if historical_audit['issues']:
        print(f"Historical source audit: {len(historical_audit['overlapping_pairs'])} overlapping section pairs; see model_audit/historical_schedule_audit.json.")
    for issue in result['data_quality']['issues']:
        print(f"Data: {issue['code']} = {issue['count']}. {issue['message']}")
    if forecast.get("enabled") and (out / "result.json").exists():
        previous = json.loads((out / "result.json").read_text(encoding="utf-8"))
        if previous.get("has_solution"):
            import shutil
            archive = out / "archive"
            archive.mkdir(exist_ok=True)
            for name in ("result.json", "timetable.csv"):
                if (out / name).exists() and not (archive / ("before_intake_projection_" + name)).exists():
                    shutil.copyfile(out / name, archive / ("before_intake_projection_" + name))
    rows = table_rows(data, result) if result["has_solution"] or demand_run else []
    if demand_run:
        result["timetable_export"] = {
            "kind": "scheduled" if result["has_solution"] else "unscheduled_capacity_proposals",
            "row_count": len(rows),
            "room_free_activity_rows": sum(bool(section.get('room_free_activity')) for section in data['sections']),
            "has_assigned_times_and_rooms": bool(result["has_solution"]),
            "has_group_section_assignments": bool(result["has_solution"]),
        }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(rows, columns=TABLE_COLUMNS).to_csv(
        out / 'timetable.csv', index=False, encoding='utf-8-sig')
    if result["has_solution"] or demand_run:
        if data.get("group_inference"):
            write_group_reports(data, result, information / 'student_groups',
                                allow_unscheduled=demand_run)
    else:
        print('No feasible timetable. timetable.csv contains headers only; see result.json for diagnostics.')
    if forecast.get("enabled"):
        write_enrollment_reports(data, result, curriculum, information / 'student_numbers')
        if data.get('external_course_allocation'):
            write_external_reports(data,result,information/'external_courses')
    if demand_run:
        print(f"Capacity-only section lower bound: {result.get('required_sections_lower_bound')}")
        if data.get('room_free_course_codes'):
            print(f"Room-free project/training courses retained: {len(data['room_free_course_codes'])}; no fixed room/time reservations.")
        if not result["has_solution"]:
            if result['status'] == 'UNKNOWN':
                print('Search stopped before finding a schedule: feasibility is still unknown. timetable.csv contains unscheduled capacity proposals; no times or rooms have been assigned.')
            elif result['status'] == 'INFEASIBLE':
                print('This scenario is proven infeasible under the configured constraints. timetable.csv contains unscheduled capacity proposals; see result.json for the proof or diagnostics.')
            else:
                print('No validated timetable was produced; see result.json for diagnostics.')


if __name__ == "__main__":
    main()
