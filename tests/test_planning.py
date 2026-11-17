import copy
import csv
import io
import json
import unittest
from pathlib import Path

from masar.checker import inspect_solution
from masar.planning import planned_data
from masar.reporting import table_rows
from masar.solver import solve
from masar.validation import prepare


def fixture(counts=(15, 15), capacity=40):
    return {
        'schema_version': '2.0', 'teachers_enabled': False,
        'rooms': [dict(id='R', name_ar='قاعة', type='classroom', capacity=capacity, blackouts=[])],
        'patterns': {'P': dict(days=[7, 2], duration=60, starts=[510, 570, 630])},
        'compatibility': {'lecture': ['classroom'], 'computers': ['computer_lab'], 'online': []},
        'sections': [dict(id=f'C_{i}', course_code='C', name_ar='مادة', section_number=i,
                          status='scheduled', pattern_id='P', delivery='in_person',
                          room_requirement='lecture', students=n, source_start=510)
                     for i, n in enumerate(counts, 1)],
        'groups': [], 'shared_classes': [],
        'objective_weights': dict(group_idle_minutes=100, late_meeting_minutes=2,
                                  source_shift_minutes=1, parallel_same_start=30),
        'late_after': 870,
    }


class SectionPlanningTests(unittest.TestCase):
    def check_plan(self, data, expected):
        before = copy.deepcopy(data)
        result = solve(data, seconds=5)
        self.assertTrue(result['has_solution'], result['diagnostics'])
        self.assertTrue(result['section_plan']['minimum_proven'])
        self.assertEqual(result['section_plan']['opened_sections'], expected)
        effective = planned_data(data, result)
        ctx = prepare(effective)
        self.assertTrue(inspect_solution(ctx, result['assignments'])['valid'])
        self.assertEqual(data, before)
        original_totals = {}
        for section in data['sections']:
            if section['status'] == 'scheduled':
                code = section['course_code']
                original_totals[code] = original_totals.get(code, 0) + section['students']
        new_totals = {}
        for section in effective['sections']:
            code = section['course_code']
            new_totals[code] = new_totals.get(code, 0) + section['students']
        self.assertEqual(new_totals, original_totals)
        return result

    def test_merge_and_csv_enrollment(self):
        data = fixture()
        result = self.check_plan(data, 1)
        rows = table_rows(data, result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['عدد الطلبة'], 30)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        stream.seek(0)
        self.assertEqual(next(csv.DictReader(stream))['عدد الطلبة'], '30')

    def test_capacity_requires_two_sections(self):
        result = self.check_plan(fixture((35, 35)), 2)
        self.assertTrue(all(s['students'] <= 40 for s in result['planned_sections']))

    def test_larger_input_can_open_required_additional_section(self):
        self.check_plan(fixture((30, 31), capacity=30), 3)

    def test_closed_large_room_uses_two_smaller_sections(self):
        data = fixture((20, 20), capacity=25)
        data['rooms'].append(dict(id='BIG', name_ar='كبيرة', type='classroom', capacity=40,
                                  blackouts=[dict(day=7, start=0, end=1440)]))
        result = self.check_plan(data, 2)
        self.assertTrue(all(a['room_id'] == 'R' for a in result['assignments']))

    def test_online_has_no_physical_capacity_limit(self):
        data = fixture((15, 15, 15))
        data['rooms'] = []
        for section in data['sections']:
            section.update(delivery='online', room_requirement='online')
        result = self.check_plan(data, 1)
        self.assertEqual(result['planned_sections'][0]['students'], 45)
        self.assertIsNone(result['assignments'][0]['room_id'])

    def test_room_requirements_remain_separate(self):
        data = fixture((15, 12))
        data['sections'][1]['room_requirement'] = 'computers'
        data['rooms'].append(dict(id='LAB', name_ar='مختبر', type='computer_lab', capacity=30, blackouts=[]))
        self.check_plan(data, 2)

    def test_different_weekly_teaching_hours_remain_separate(self):
        data = fixture()
        data['patterns']['Q'] = dict(days=[7], duration=60, starts=[510, 570])
        data['sections'][1]['pattern_id'] = 'Q'
        self.check_plan(data, 2)

    def test_student_groups_reassigned_without_clashes_or_loss(self):
        data = fixture((10, 10))
        other = dict(data['sections'][0], id='D_1', course_code='D', students=20)
        data['sections'].append(other)
        data['groups'] = [dict(id='G1', students=10, section_ids=['C_1', 'D_1']),
                          dict(id='G2', students=10, section_ids=['C_2', 'D_1'])]
        result = self.check_plan(data, 2)
        groups = result['planned_groups']
        self.assertEqual(groups[0]['section_ids'], groups[1]['section_ids'])
        self.assertTrue(all(s['unmodeled_student_count'] == 0 for s in result['planned_sections']))

    def test_alternative_days_can_be_selected(self):
        data = fixture()
        data['patterns']['Q'] = dict(days=[1, 3], duration=60, starts=[510])
        data['sections'][1]['pattern_id'] = 'Q'
        data['rooms'][0]['blackouts'] = [dict(day=7, start=0, end=1440)]
        result = self.check_plan(data, 1)
        self.assertEqual(result['planned_sections'][0]['pattern_id'], 'Q')

    def test_available_pattern_can_supply_multiple_required_sections(self):
        data = fixture((30, 30), capacity=30)
        data['patterns']['Q'] = dict(days=[1, 3], duration=60, starts=[510, 570])
        data['sections'][1]['pattern_id'] = 'Q'
        data['rooms'][0]['blackouts'] = [dict(day=7, start=0, end=1440)]
        result = self.check_plan(data, 2)
        self.assertTrue(all(s['pattern_id'] == 'Q' for s in result['planned_sections']))

    def test_no_capacity_is_infeasible_and_not_exported(self):
        data = fixture()
        data['rooms'] = []
        result = solve(data, seconds=1)
        self.assertEqual(result['status'], 'INFEASIBLE')
        self.assertEqual(table_rows(data, result), [])

    def test_groups_can_require_additional_sections_despite_spare_capacity(self):
        for online in (False, True):
            with self.subTest(online=online):
                data = fixture((20,))
                data['patterns']['P']['starts'] = [510, 570]
                data['patterns']['D'] = dict(days=[7, 2], duration=60, starts=[510])
                data['patterns']['E'] = dict(days=[7, 2], duration=60, starts=[570])
                for code in ('D', 'E'):
                    data['sections'].append(dict(data['sections'][0], id=code,
                                                 course_code=code, pattern_id=code, students=10))
                data['groups'] = [dict(id='G1', students=10, section_ids=['C_1', 'D']),
                                  dict(id='G2', students=10, section_ids=['C_1', 'E'])]
                data['rooms'].append(dict(data['rooms'][0], id='R2'))
                if online:
                    data['rooms'] = []
                    for section in data['sections']:
                        section.update(delivery='online', room_requirement='online')
                self.check_plan(data, 4)

    def test_unknown_no_meeting_enrollment_is_not_invented(self):
        data = fixture()
        data['sections'].append(dict(id='UNKNOWN', course_code='UNKNOWN', name_ar='غير محدد',
                                     section_number=1, status='no_meeting_days', students=None))
        result = self.check_plan(data, 1)
        self.assertEqual(result['section_plan']['unplanned_section_ids'], ['UNKNOWN'])
        self.assertEqual(len(table_rows(data, result)), 1)

    def test_real_dataset_conserves_every_course_total(self):
        data = json.loads((Path(__file__).resolve().parents[1] / 'data/masar_section_templates.json').read_text())
        result = solve(data, optimize=False, seconds=15)
        self.assertTrue(result['has_solution'], result['diagnostics'])
        self.assertTrue(result['section_plan']['minimum_proven'])
        self.assertLess(result['section_plan']['opened_sections'], sum(s['status'] == 'scheduled' for s in data['sections']))
        self.assertEqual(len(table_rows(data, result)), result['section_plan']['opened_sections'])
        self.assertEqual(len(result['section_plan']['unplanned_section_ids']), 46)
        ctx = prepare(planned_data(data, result))
        self.assertTrue(inspect_solution(ctx, result['assignments'])['valid'])
        for course in result['section_plan']['courses']:
            self.assertEqual(sum(s['students'] for s in result['planned_sections']
                                 if s['course_code'] == course['course_code']), course['students'])


if __name__ == '__main__':
    unittest.main()
