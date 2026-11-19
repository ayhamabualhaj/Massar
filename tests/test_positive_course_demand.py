import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from masar.demand.enrollment import _check_study_plan
from masar.demand.scenario import prepare_scenario

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'data/masar_data_v2.json').read_text())
CURRICULUM=json.loads((ROOT/'course_requirements/five_majors_degree_plans.json').read_text())
POLICY=DATA['enrollment_generation']


class PositiveCourseDemandTests(unittest.TestCase):
    def test_every_catalog_course_has_positive_profile_derived_enrollment(self):
        catalog={r['course_code'] for r in DATA['course_catalog_scope']['records']}
        actual=Counter();expected=Counter()
        for s in DATA['sections']:
            if s.get('students'):actual[s['course_code']]+=s['students']
        for profile in DATA['enrollment_projection']['cohorts']:
            self.assertFalse(profile['unavailable_courses'])
            for code in profile['planned_courses']:expected[code]+=profile['students']
        degree_courses = {r['course_code'] for r in CURRICULUM['records']
                          if r['category'] in ('كلية إجباري', 'تخصص إجباري', 'تخصص اختياري')}
        enabled_courses = degree_courses.intersection(POLICY['enabled_course_codes'])
        self.assertEqual(catalog, enabled_courses)
        self.assertEqual(set(actual), enabled_courses)
        self.assertTrue(all(n>0 for n in actual.values()))
        self.assertEqual(actual,expected)

    def test_population_degree_and_elective_totals_are_preserved(self):
        projection=DATA['enrollment_projection']
        expected_by_major = POLICY['major_student_totals']
        projected_by_major = Counter()
        for cohort in projection['cohorts']:
            projected_by_major[cohort['program_id']] += cohort['students']
        self.assertEqual(projected_by_major, expected_by_major)
        self.assertEqual(sum(g['students'] for g in DATA['groups']), sum(expected_by_major.values()))
        for program,paths in projection['study_paths'].items():
            rows=[r for r in CURRICULUM['records'] if r['program_id']==program]
            index={r['course_code']:r for r in rows}
            for path in paths:
                _check_study_plan(rows,path['semesters'],POLICY)
                self.assertEqual(sum(index[c]['credit_hours'] for c in path['semesters']),132)
                self.assertEqual(sum(index[c]['credit_hours'] for c in path['semesters']
                    if index[c]['category']=='تخصص اختياري'),9)

    def test_calendar_parity_does_not_exclude_valid_academic_stages(self):
        profiles=DATA['enrollment_projection']['cohorts']
        self.assertTrue(any(p['study_semester']%2==0 for p in profiles))
        self.assertTrue(any(p['study_semester']%2==1 for p in profiles))
        index={(r['program_id'],r['course_code']):r for r in CURRICULUM['records']}
        for profile in profiles:
            self.assertEqual(profile['study_semester'],profile['calendar_study_semester']+profile['progression_offset'])
            completed=set(profile['assumed_completed_course_codes']);current=set(profile['planned_courses'])
            self.assertFalse(current&completed)
            for code in current:
                for req in index[profile['program_id'],code]['requirements']:
                    prerequisite=index.get((profile['program_id'],req['course_code']))
                    if not prerequisite or prerequisite['credit_hours']==0:continue
                    self.assertTrue(req['course_code'] in completed or
                        (req['concurrent_allowed'] and req['course_code'] in current))

    def test_cached_positive_enrollments_are_stable(self):
        current = prepare_scenario(ROOT).data
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'input.json'
            snapshot.write_text(json.dumps(current), encoding='utf-8')
            with patch('masar.demand.enrollment._study_plan',
                       side_effect=AssertionError('Unexpected path regeneration')):
                rebuilt = prepare_scenario(ROOT, input_path=snapshot).data
        self.assertEqual(rebuilt['enrollment_projection'], current['enrollment_projection'])
        self.assertEqual(rebuilt['groups'], current['groups'])
        self.assertEqual(rebuilt['sections'], current['sections'])
        self.assertNotIn('0202100', {s['course_code'] for s in rebuilt['sections']})

    def test_export_major_labels_match_degree_plan_eligibility_including_electives(self):
        from collections import defaultdict
        expected=defaultdict(set)
        for record in CURRICULUM['records']:
            if record['category'] in ('كلية إجباري','تخصص إجباري','تخصص اختياري'):
                expected[record['course_code']].add(record['program_name'])
        from masar.reports.timetable import table_rows
        result=json.loads((ROOT/'extra information/masar_v2_output/result.json').read_text())
        rows=table_rows(DATA,result)
        all_majors={record['program_name'] for record in CURRICULUM['records']}
        for row in rows:
            self.assertNotIn('الحالة',row)
            if expected[row['رقم المادة']]==all_majors:
                self.assertEqual(row['الفئة'],'all')
            else:
                self.assertEqual(set(row['الفئة'].split('، ')),expected[row['رقم المادة']])
            self.assertNotIn('لجميع الطلبة',row['الفئة'])
        by_code={row['رقم المادة']:row for row in rows}
        self.assertEqual(by_code['0615490']['الفئة'],'علم البيانات والذكاء الاصطناعي')
        self.assertEqual(by_code['0612331']['الفئة'],'all')
        self.assertEqual(by_code['0612112']['الفئة'],'all')

    def test_csv_contains_all_courses_and_no_university_courses(self):
        with (ROOT/'masar_v2_output/timetable.csv').open(encoding='utf-8-sig') as stream:
            rows=list(csv.DictReader(stream))
        catalog={r['course_code'] for r in DATA['course_catalog_scope']['records']}
        self.assertEqual({r['رقم المادة'] for r in rows},catalog)
        self.assertTrue(all(int(r['عدد الطلبة'])>0 for r in rows))
        self.assertNotIn('0614100',catalog)
        self.assertNotIn('0612098',catalog)


if __name__=='__main__':unittest.main()
