"""Only validated, complete runs replace the active timetable, and every active file comes from one run."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from masar.reports import output
from masar.reports.output import (PublishError, is_publishable, prune_runs, publish_run,
                                  recover_interrupted_publish)
from masar.reports.timetable import major_views
from masar.scheduling.planning import improve_preferences, solve_sections
from masar.scheduling.solver import solve
from masar.validation import InputError

from test_engine import fixture as engine_fixture
from test_planning import fixture as planning_fixture


def _run(base, name, valid, marker, majors=('CS',), reports=('model_audit/summary.json',)):
    run = base / 'runs' / name
    (run / 'by_major').mkdir(parents=True)
    snapshot = dict(marker=marker)
    result = dict(has_solution=valid, validation=dict(valid=valid) if valid else None, marker=marker,
                  run_metadata=dict(input_sha256=output._fingerprint(snapshot)))
    (run / 'result.json').write_text(json.dumps(result))
    (run / 'timetable.csv').write_text(marker)
    (run / 'input_snapshot.json').write_text(json.dumps(snapshot))
    for major in majors:
        (run / 'by_major' / f'{major}.csv').write_text(marker)
    for report in reports:
        (run / 'reports' / report).parent.mkdir(parents=True, exist_ok=True)
        (run / 'reports' / report).write_text(marker)
    return run


def _active(base, reports):
    """Every active file's content, so a test can check that they all come from one run."""
    files = [base / 'timetable.csv', base / 'input_snapshot.json', *sorted((base / 'by_major').glob('*.csv')),
             *sorted(p for p in reports.rglob('*') if p.is_file())]
    contents = {str(p.relative_to(base.parent)): p.read_text() for p in files}
    contents['input_snapshot.json'] = json.loads(contents.pop('out/input_snapshot.json'))['marker']
    contents['result'] = json.loads((base / 'result.json').read_text())['marker']
    contents['run'] = (base / 'PUBLISHED_RUN.txt').read_text().strip()
    return contents


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base, self.reports = Path(self.tmp.name) / 'out', Path(self.tmp.name) / 'info'

    def tearDown(self):
        self.tmp.cleanup()

    def test_publishable_requires_independent_validation(self):
        self.assertTrue(is_publishable(dict(has_solution=True, validation=dict(valid=True))))
        self.assertFalse(is_publishable(dict(has_solution=True, validation=dict(valid=False))))
        self.assertFalse(is_publishable(dict(has_solution=False, validation=None)))

    def test_publish_replaces_master_majors_and_reports_together(self):
        publish_run(_run(self.base, 'a', True, 'first', majors=('CS', 'SE')), self.base, self.reports)
        publish_run(_run(self.base, 'b', True, 'second'), self.base, self.reports)
        active = _active(self.base, self.reports)
        self.assertEqual(set(active.values()), {'second', 'b'})
        self.assertFalse((self.base / 'by_major' / 'SE.csv').exists())

    def test_failed_run_cannot_be_published(self):
        publish_run(_run(self.base, 'a', True, 'good'), self.base, self.reports)
        with self.assertRaises(PublishError):
            publish_run(_run(self.base, 'b', False, 'bad'), self.base, self.reports)
        self.assertEqual(set(_active(self.base, self.reports).values()), {'good', 'a'})

    def test_incomplete_run_changes_nothing(self):
        publish_run(_run(self.base, 'a', True, 'good'), self.base, self.reports)
        broken = _run(self.base, 'b', True, 'new')
        (broken / 'input_snapshot.json').unlink()
        with self.assertRaises(PublishError):
            publish_run(broken, self.base, self.reports)
        self.assertEqual(set(_active(self.base, self.reports).values()), {'good', 'a'})

    def test_snapshot_must_match_the_result_fingerprint(self):
        publish_run(_run(self.base, 'a', True, 'good'), self.base, self.reports)
        mismatched = _run(self.base, 'b', True, 'new')
        (mismatched / 'input_snapshot.json').write_text(json.dumps(dict(marker='other input')))
        with self.assertRaises(PublishError):
            publish_run(mismatched, self.base, self.reports)
        self.assertEqual(set(_active(self.base, self.reports).values()), {'good', 'a'})

    def _fail_after(self, calls):
        real, count = os.replace, [0]

        def flaky(source, destination):
            count[0] += 1
            if count[0] > calls:
                raise OSError('disk failure during publish')
            return real(source, destination)
        return flaky

    def test_failure_midway_through_the_swap_rolls_back_every_file(self):
        publish_run(_run(self.base, 'a', True, 'good', majors=('CS', 'SE')), self.base, self.reports)
        before = _active(self.base, self.reports)
        new = _run(self.base, 'b', True, 'new', majors=('CS', 'AI'))
        for calls in range(1, 12):
            with self.subTest(calls=calls), patch('masar.reports.output.os.replace', self._fail_after(calls)):
                try:
                    publish_run(new, self.base, self.reports)
                except OSError:
                    pass
                else:
                    break
            # The in-process rollback may itself hit the failing disk; the journal
            # then lets the next run restore the previous files.
            recover_interrupted_publish(self.base)
            self.assertEqual(_active(self.base, self.reports), before)
            self.assertFalse((self.base / output.JOURNAL).exists())

    def test_crash_midway_is_recovered_on_the_next_run(self):
        publish_run(_run(self.base, 'a', True, 'good', majors=('CS', 'SE')), self.base, self.reports)
        before = _active(self.base, self.reports)
        new = _run(self.base, 'b', True, 'new', majors=('CS', 'AI'))
        # Simulate the process dying: no in-process rollback runs.
        with patch('masar.reports.output.os.replace', self._fail_after(5)), \
                patch('masar.reports.output._rollback'), \
                patch('masar.reports.output.Path.unlink'):
            with self.assertRaises(OSError):
                publish_run(new, self.base, self.reports)
        self.assertTrue((self.base / output.JOURNAL).exists())
        self.assertNotEqual(_active(self.base, self.reports), before)
        self.assertTrue(recover_interrupted_publish(self.base))
        self.assertEqual(_active(self.base, self.reports), before)
        leftovers = [p for p in Path(self.tmp.name).rglob('*')
                     if p.name.endswith((output.STAGED, output.PREVIOUS)) and 'runs' not in p.parts]
        self.assertEqual(leftovers, [])

    def test_stale_generated_reports_are_removed_but_hand_kept_files_stay(self):
        (self.reports / 'student_numbers').mkdir(parents=True)
        (self.reports / 'student_numbers' / 'README.md').write_text('kept by hand')
        publish_run(_run(self.base, 'a', True, 'intake', reports=(
            'model_audit/summary.json', 'student_numbers/projection.csv')), self.base, self.reports)
        publish_run(_run(self.base, 'b', True, 'requests'), self.base, self.reports)
        self.assertFalse((self.reports / 'student_numbers' / 'projection.csv').exists())
        self.assertEqual((self.reports / 'student_numbers' / 'README.md').read_text(), 'kept by hand')
        self.assertEqual((self.reports / 'model_audit' / 'summary.json').read_text(), 'requests')

    def test_prune_keeps_newest_and_published_runs(self):
        publish_run(_run(self.base, '1', True, 'x'), self.base, self.reports)
        for name in '2345':
            _run(self.base, name, False, 'y')
        prune_runs(self.base, keep=2)
        self.assertEqual(sorted(p.name for p in (self.base / 'runs').iterdir()), ['1', '4', '5'])


class MajorViewTests(unittest.TestCase):
    def test_shared_courses_appear_in_each_eligible_major(self):
        data = dict(course_catalog_scope=dict(records=[
            dict(course_code='A', program_id='CS'), dict(course_code='A', program_id='SE'),
            dict(course_code='B', program_id='CS')]))
        rows = [{'رقم المادة': 'A'}, {'رقم المادة': 'B'}, {'رقم المادة': 'Z'}]
        views = major_views(data, rows)
        self.assertEqual(views['CS'], rows[:2])
        self.assertEqual(views['SE'], rows[:1])
        self.assertEqual(views['AI'], [])
        self.assertNotIn(rows[2], [r for v in views.values() for r in v])


class PreferencePhaseTests(unittest.TestCase):
    def _first_timetable(self):
        """A valid timetable with a two-hour gap between the group's two classes."""
        data = engine_fixture()
        first = solve(copy.deepcopy(data), optimize=False, seconds=2, plan_sections=False)
        for assignment in first['assignments']:
            start = 510 if assignment['event_id'] == 'S1' else 810
            assignment['start'] = start
            assignment['meetings'] = [dict(m, start=start, end=start + 60) for m in assignment['meetings']]
        from masar.scheduling.checker import inspect_solution
        from masar.validation import prepare
        first['validation'] = inspect_solution(prepare(data), first['assignments'])
        self.assertTrue(first['validation']['valid'])
        self.assertGreater(first['validation']['metrics']['group_idle_minutes'], 0)
        first['mode'] = 'test'
        return data, first

    def test_improvement_is_accepted_and_scores_are_reported(self):
        data, result = self._first_timetable()
        improve_preferences(result, data, seconds=5)
        self.assertTrue(result['preference_search']['accepted'])
        self.assertLess(result['preference_score_after'], result['preference_score_before'])
        self.assertEqual(result['validation']['metrics']['group_idle_minutes'], 0)
        self.assertGreater(result['preference_metrics_before']['group_idle_minutes'], 0)

    def test_first_timetable_is_kept_when_preference_search_finds_nothing(self):
        data, result = self._first_timetable()
        original = copy.deepcopy(result['assignments'])
        stopped = dict(status='UNKNOWN', has_solution=False, diagnostics=['stopped'],
                       search_statistics=dict(stopped_for_memory=True, observed_peak_rss_mb=1))
        with patch('masar.scheduling.solver._solve_fixed', return_value=stopped):
            improve_preferences(result, data, seconds=5)
        self.assertEqual(result['assignments'], original)
        self.assertEqual(result['preference_search']['kept'], 'first_timetable')

    def test_first_timetable_is_kept_when_preference_search_errors(self):
        data, result = self._first_timetable()
        original = copy.deepcopy(result['assignments'])
        with patch('masar.scheduling.solver._solve_fixed', side_effect=InputError('mismatch')):
            improve_preferences(result, data, seconds=5)
        self.assertEqual(result['assignments'], original)
        self.assertEqual(result['preference_status'], 'ERROR')

    def test_fixed_solver_respects_the_memory_guard(self):
        data = engine_fixture()
        data['solver_memory_limit_mb'] = 256
        with patch('masar.scheduling.memory.memory_mb', return_value=10 ** 6):
            result = solve(data, seconds=2, plan_sections=False)
        self.assertFalse(result['has_solution'])
        self.assertTrue(result['search_statistics']['stopped_for_memory'])

    def test_no_optimize_skips_preferences_on_the_compact_planner(self):
        data = planning_fixture((240,), capacity=100)
        data['groups'] = [dict(id=f'G{i}', students=60, section_ids=['C_1'], splittable=True) for i in range(4)]
        data['solver_workers'] = 1
        with patch('masar.scheduling.planning.improve_preferences') as improve:
            result = solve_sections(copy.deepcopy(data), optimize=False, seconds=5)
            self.assertTrue(result['has_solution'])
            improve.assert_not_called()
            self.assertEqual(result['preference_status'], 'NOT_RUN')
            solve_sections(copy.deepcopy(data), optimize=True, seconds=5)
            improve.assert_called_once()

    def test_student_weighted_idle_counts_every_waiting_student(self):
        data, result = self._first_timetable()
        group = data['groups'][0]
        metrics = result['validation']['metrics']
        self.assertEqual(metrics['student_idle_minutes'], metrics['group_idle_minutes'] * group['students'])


if __name__ == '__main__':
    unittest.main()
