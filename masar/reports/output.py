"""Write the artifacts for one timetable run and publish validated runs."""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .audit import write_audit_reports
from .enrollment import write_enrollment_reports
from .external_courses import write_external_reports
from .groups import write_group_reports
from .historical_audit import write_historical_audit
from .timetable import TABLE_COLUMNS, major_views, table_rows

RUN_HISTORY = 20


def is_publishable(result):
    """A run may replace the active timetable only when it was independently validated."""
    validation = result.get('validation') or {}
    return bool(result.get('has_solution')) and validation.get('valid') is True


def new_run_dir(base):
    """Create a fresh, uniquely named folder for one run under ``base/runs``."""
    runs = Path(base) / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path, suffix = runs / stamp, 1
    while path.exists():
        suffix += 1
        path = runs / f'{stamp}_{suffix}'
    path.mkdir()
    return path


def _write_csv(rows, path):
    pd.DataFrame(rows, columns=TABLE_COLUMNS).to_csv(path, index=False, encoding='utf-8-sig')


def write_outputs(scenario, result, run_dir):
    """Save the input, timetable, per-major views, result, and reports into one run folder.

    Nothing outside ``run_dir`` is touched; use :func:`publish_run` to promote it.
    """
    data = scenario.data
    run_dir = Path(run_dir)
    information = run_dir / 'reports'
    intake_run = scenario.demand_source == 'intake_forecast'
    demand_run = scenario.demand_source != 'section_counts'
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'input_snapshot.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result['data_quality'] = write_audit_reports(data, scenario.reference, result, information / 'model_audit')
    historical_audit = write_historical_audit(scenario.historical_reference, information / 'model_audit')
    result['historical_schedule_audit'] = historical_audit
    if historical_audit['issues']:
        print(f"Historical source audit: {len(historical_audit['overlapping_pairs'])} overlapping section pairs; "
              "see model_audit/historical_schedule_audit.json.")
    for issue in result['data_quality']['issues']:
        print(f"Data: {issue['code']} = {issue['count']}. {issue['message']}")
    rows = table_rows(data, result) if result['has_solution'] or demand_run else []
    if demand_run:
        result['timetable_export'] = {
            'kind': 'scheduled' if result['has_solution'] else 'unscheduled_capacity_proposals',
            'row_count': len(rows),
            'room_free_activity_rows': sum(bool(section.get('room_free_activity')) for section in data['sections']),
            'has_assigned_times_and_rooms': bool(result['has_solution']),
            'has_group_section_assignments': bool(result['has_solution']),
        }
    result['publishable'] = is_publishable(result)
    (run_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    _write_csv(rows, run_dir / 'timetable.csv')
    by_major = run_dir / 'by_major'
    by_major.mkdir(exist_ok=True)
    for program, program_rows in major_views(data, rows).items():
        _write_csv(program_rows, by_major / f'{program}.csv')
    if result['has_solution'] or demand_run:
        if data.get('group_inference'):
            write_group_reports(data, result, information / 'student_groups', allow_unscheduled=demand_run)
    else:
        print('No feasible timetable. timetable.csv contains headers only; see result.json for diagnostics.')
    if intake_run:
        write_enrollment_reports(data, result, scenario.curriculum, information / 'student_numbers')
        if data.get('external_course_allocation'):
            write_external_reports(data, result, information / 'external_courses')
    if demand_run:
        print(f"Capacity-only section lower bound: {result.get('required_sections_lower_bound')}")
        if data.get('room_free_course_codes'):
            print(f"Room-free project/training courses retained: {len(data['room_free_course_codes'])}; "
                  'no fixed room/time reservations.')
        if not result['has_solution']:
            if result['status'] == 'UNKNOWN':
                print('Search stopped before finding a schedule: feasibility is still unknown. '
                      'The run folder contains unscheduled capacity proposals only.')
            elif result['status'] == 'INFEASIBLE':
                print('This scenario is proven infeasible under the configured constraints; see result.json.')
            else:
                print('No validated timetable was produced; see result.json for diagnostics.')
    return result


JOURNAL = '.publish_journal.json'
MANIFEST = '.published_files.json'
STAGED = '.publish-staged'
PREVIOUS = '.publish-previous'


class PublishError(RuntimeError):
    """A run could not be published; the active timetable was left unchanged."""


def _fingerprint(data):
    import hashlib
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _verify_run(run_dir):
    """Check that a run is complete and self-consistent before anything active is touched."""
    result_path = run_dir / 'result.json'
    if not result_path.is_file():
        raise PublishError(f'{run_dir}: result.json is missing.')
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if not is_publishable(result):
        raise PublishError(f'{run_dir} has no validated timetable and cannot be published.')
    for name in ('timetable.csv', 'input_snapshot.json'):
        if not (run_dir / name).is_file():
            raise PublishError(f'{run_dir}: {name} is missing.')
    if not (run_dir / 'by_major').is_dir() or not any((run_dir / 'by_major').glob('*.csv')):
        raise PublishError(f'{run_dir}: by_major views are missing.')
    expected = result.get('run_metadata', {}).get('input_sha256')
    if expected:
        snapshot = json.loads((run_dir / 'input_snapshot.json').read_text(encoding='utf-8'))
        if _fingerprint(snapshot) != expected:
            raise PublishError(f'{run_dir}: input_snapshot.json does not match the input fingerprint in result.json.')


def _publish_plan(run_dir, out, reports_destination, timetable):
    """List every (source, destination) pair; result.json goes last."""
    pairs = [(run_dir / 'timetable.csv', timetable),
             (run_dir / 'input_snapshot.json', out / 'input_snapshot.json')]
    pairs += [(path, out / 'by_major' / path.name) for path in sorted((run_dir / 'by_major').glob('*.csv'))]
    reports = run_dir / 'reports'
    if reports.is_dir():
        pairs += [(path, reports_destination / path.relative_to(reports))
                  for path in sorted(reports.rglob('*')) if path.is_file()]
    pairs.append((run_dir / 'result.json', out / 'result.json'))
    return pairs


def _sibling(path, suffix):
    return path.with_name(path.name + suffix)


def _write_json(path, value):
    temporary = _sibling(path, STAGED)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def _rollback(journal):
    """Put back every file the interrupted publish replaced or removed."""
    for entry in reversed(journal['files']):
        destination = Path(entry['destination'])
        backup = _sibling(destination, PREVIOUS)
        if entry['had_previous']:
            if backup.exists():
                os.replace(backup, destination)
        elif entry['new'] and destination.exists():
            destination.unlink()
        staged = _sibling(destination, STAGED)
        if staged.exists():
            staged.unlink()
    for name in ('PUBLISHED_RUN.txt', MANIFEST):
        path = Path(journal['out']) / name
        backup = _sibling(path, PREVIOUS)
        if backup.exists():
            os.replace(backup, path)
        elif not journal['markers_existed'][name]:
            path.unlink(missing_ok=True)
        _sibling(path, STAGED).unlink(missing_ok=True)


def recover_interrupted_publish(out):
    """If an earlier publish was interrupted, restore the previously active files."""
    path = Path(out) / JOURNAL
    if not path.exists():
        return False
    _rollback(json.loads(path.read_text(encoding='utf-8')))
    path.unlink()
    print(f'Recovered from an interrupted publish in {out}; the previous timetable is active again.', flush=True)
    return True


def publish_run(run_dir, out, reports_destination, *, timetable=None):
    """Promote a validated run so that every active file comes from that one run.

    Nothing active changes until the run is verified and all copies are staged. The
    swap is journaled: if it fails, or the process dies mid-swap, the previous files
    are restored (immediately, or by :func:`recover_interrupted_publish` on the next
    run). Generated files from the previous publish that this run did not produce
    are removed; files never generated by Masar (such as READMEs and inputs) are kept.
    """
    run_dir, out, reports_destination = Path(run_dir), Path(out), Path(reports_destination)
    out.mkdir(parents=True, exist_ok=True)
    recover_interrupted_publish(out)
    _verify_run(run_dir)
    pairs = _publish_plan(run_dir, out, reports_destination, timetable or out / 'timetable.csv')
    destinations = {str(destination) for _, destination in pairs}
    manifest_path = out / MANIFEST
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    stale = [Path(p) for p in previous.get('files', []) if p not in destinations and Path(p).exists()]
    staged = []
    try:
        for source, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            target = _sibling(destination, STAGED)
            shutil.copyfile(source, target)
            staged.append(target)
    except BaseException:
        for target in staged:
            target.unlink(missing_ok=True)
        raise
    journal = dict(out=str(out), run=run_dir.name,
                   markers_existed={name: (out / name).exists() for name in ('PUBLISHED_RUN.txt', MANIFEST)},
                   files=(
        [dict(destination=str(d), had_previous=d.exists(), new=True) for _, d in pairs]
        + [dict(destination=str(d), had_previous=True, new=False) for d in stale]))
    _write_json(out / JOURNAL, journal)
    try:
        for entry in journal['files']:
            destination = Path(entry['destination'])
            if entry['had_previous']:
                os.replace(destination, _sibling(destination, PREVIOUS))
            if entry['new']:
                os.replace(_sibling(destination, STAGED), destination)
        for name in ('PUBLISHED_RUN.txt', MANIFEST):
            if (out / name).exists():
                shutil.copyfile(out / name, _sibling(out / name, PREVIOUS))
        (out / 'PUBLISHED_RUN.txt').write_text(f'{run_dir.name}\n', encoding='utf-8')
        _write_json(manifest_path, dict(run=run_dir.name, files=sorted(destinations)))
    except BaseException:
        _rollback(journal)
        (out / JOURNAL).unlink(missing_ok=True)
        raise
    (out / JOURNAL).unlink()  # Commit point: the new run is now the active one.
    for entry in journal['files']:
        _sibling(Path(entry['destination']), PREVIOUS).unlink(missing_ok=True)
    for name in ('PUBLISHED_RUN.txt', MANIFEST):
        _sibling(out / name, PREVIOUS).unlink(missing_ok=True)


def prune_runs(base, keep=RUN_HISTORY):
    """Delete the oldest run folders, keeping the newest ``keep`` and the published one."""
    runs = Path(base) / 'runs'
    if not runs.is_dir():
        return
    marker = Path(base) / 'PUBLISHED_RUN.txt'
    published = marker.read_text(encoding='utf-8').strip() if marker.exists() else None
    folders = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name)
    for folder in folders[:-keep] if keep else folders:
        if folder.name != published:
            shutil.rmtree(folder)
