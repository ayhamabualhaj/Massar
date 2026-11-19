import csv
import json
import tempfile
import unittest
from pathlib import Path

from masar.demand.enrollment import read_intakes
from masar.settings import (read_settings, read_course_switches, read_major_totals,
                            apply_room_capacities, apply_student_counts, apply_major_totals)
from masar.validation import InputError


ROOT = Path(__file__).resolve().parents[1]


class SettingsTests(unittest.TestCase):
    def test_course_switches_cover_current_timetable_and_allow_disabling(self):
        catalog = json.loads((ROOT/'course_requirements/five_majors_degree_plans.json').read_text())
        codes = {record['course_code'] for record in catalog['records']}
        switches = read_course_switches(ROOT/'settings/courses', codes)
        with (ROOT/'masar_v2_output/timetable.csv').open(encoding='utf-8-sig', newline='') as stream:
            timetable_codes = {row['رقم المادة'] for row in csv.DictReader(stream)}
        self.assertEqual(set(switches), {record['course_code'] for record in catalog['records']
                                         if record['category'] in ('كلية إجباري', 'تخصص إجباري', 'تخصص اختياري')})
        snapshot = json.loads((ROOT/'extra information/masar_v2_output/input_snapshot.json').read_text())
        self.assertTrue(timetable_codes <= set(snapshot['enrollment_generation']['enabled_course_codes']))
        self.assertFalse(switches['0202100'])
        with (ROOT/'extra information/university_schedule/real_university_schedule.tsv').open(
                encoding='utf-8-sig', newline='') as stream:
            real_codes = {row['رقم المادة'] for row in csv.DictReader(stream, delimiter='\t')}
        with (ROOT/'settings/courses/All Courses/courses.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(all(not switches[row['course_code']] for row in rows
            if 'تخصص اختياري' in row['catalog_types'] and row['course_code'] not in real_codes))
        self.assertTrue(switches['0612112'])
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for path in (ROOT/'settings/courses').glob('*/courses.csv'):
                target = base/path.parent.name/'courses.csv'
                target.parent.mkdir(parents=True)
                target.write_bytes(path.read_bytes())
            target = base/'All Courses'/'courses.csv'
            with target.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            row = next(row for row in rows if row['course_code'] == '0612112')
            row['enabled'] = '0'
            with target.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            self.assertFalse(read_course_switches(base, codes)['0612112'])

    def test_current_settings_preserve_source_counts_and_capacities(self):
        rooms, students = read_settings(ROOT/'settings')
        data = json.loads((ROOT/'data/masar_section_templates.json').read_text())
        adjusted = apply_room_capacities(data, rooms)
        self.assertEqual({r['id']: r['capacity'] for r in adjusted['rooms']}, rooms)
        self.assertEqual(data, adjusted)
        source = read_intakes(ROOT/'extra information/student_numbers/student_expected_number_for_each_semester.csv')
        names = {'SE':'هندسة البرمجيات', 'CS':'علم الحاسوب',
                 'AI':'علم البيانات والذكاء الاصطناعي', 'CYBER':'الأمن السيبراني',
                 'CIS':'نظم المعلومات الحاسوبية'}
        self.assertEqual(apply_student_counts(source, students, names), source)

    def test_edits_change_inputs_without_mutating_sources(self):
        rooms, students = read_settings(ROOT/'settings')
        data = json.loads((ROOT/'data/masar_section_templates.json').read_text())
        source = read_intakes(ROOT/'extra information/student_numbers/student_expected_number_for_each_semester.csv')
        names = {'SE':'هندسة البرمجيات', 'CS':'علم الحاسوب',
                 'AI':'علم البيانات والذكاء الاصطناعي', 'CYBER':'الأمن السيبراني',
                 'CIS':'نظم المعلومات الحاسوبية'}
        rooms['T101'] = 80
        students['2026', '1', 'SE'] = 170
        changed = apply_room_capacities(data, rooms)
        intakes = apply_student_counts(source, students, names)
        self.assertEqual(next(r['capacity'] for r in changed['rooms'] if r['id']=='T101'), 80)
        self.assertEqual(next(r['capacity'] for r in data['rooms'] if r['id']=='T101'), 73)
        self.assertEqual(next(r['عدد الطلبة الجدد'] for r in intakes
            if r['السنة المرجعية']=='2026' and r['الفصل']=='الأول' and r['نوع الصف']=='إجمالي الفصل'), '401')
        self.assertEqual(next(r['عدد الطلبة الجدد'] for r in source
            if r['السنة المرجعية']=='2026' and r['الفصل']=='الأول' and r['نوع الصف']=='إجمالي الفصل'), '400')

    def test_major_totals_change_intake_counts_used_for_demand(self):
        _, cohort_weights = read_settings(ROOT/'settings')
        names = {'SE':'هندسة البرمجيات', 'CS':'علم الحاسوب',
                 'AI':'علم البيانات والذكاء الاصطناعي', 'CYBER':'الأمن السيبراني',
                 'CIS':'نظم المعلومات الحاسوبية'}
        totals = read_major_totals(ROOT/'settings', names)
        self.assertEqual(totals, {'SE':190, 'CS':188, 'AI':171, 'CYBER':150, 'CIS':192})
        adjusted = apply_major_totals(cohort_weights, totals)
        for major, expected in totals.items():
            self.assertEqual(sum(value for (year, semester, code), value in adjusted.items()
                                 if code == major and value is not None), expected)
        self.assertEqual(adjusted['2023','1','SE'], 48)
        self.assertIsNone(adjusted['2023','2','SE'])
        source = read_intakes(ROOT/'extra information/student_numbers/student_expected_number_for_each_semester.csv')
        intakes = apply_student_counts(source, adjusted, names)
        self.assertEqual(sum(int(row['عدد الطلبة الجدد']) for row in intakes
                             if row['نوع الصف']=='تخصص مستقل' and row['عدد الطلبة الجدد']!='غير محدد'), 891)
        changed = apply_major_totals(cohort_weights, dict(totals, SE=191))
        self.assertEqual(sum(value for (year, semester, code), value in changed.items()
                             if code == 'SE' and value is not None), 191)
        self.assertEqual(cohort_weights['2023','1','SE'], 169)

    def test_invalid_room_capacity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with (path/'rooms.csv').open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['room_id','room_name','room_type','capacity'])
                writer.writerow(['T101','101','classroom','zero'])
            (path/'student').mkdir()
            (path/'student'/'students.csv').write_text('year,semester,major,students\n2026,1,SE,169\n')
            with self.assertRaisesRegex(InputError, 'capacity must be a positive integer'):
                read_settings(path)
