import csv
import json
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from masar.enrollment import with_intake_enrollments,read_intakes,_check_study_plan
from masar.estimated_meetings import with_estimated_meetings
from masar.external_courses import with_external_courses
from masar.room_free import with_room_free_activities

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'data/masar_data_v2.json').read_text())
CURRICULUM=json.loads((ROOT/'course_requirements/course_requirements.json').read_text())
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
        self.assertEqual(len(catalog),111)
        self.assertEqual(set(actual),catalog)
        self.assertTrue(all(n>0 for n in actual.values()))
        self.assertEqual(actual,expected)
        for code in ['0511233','0511234','0612117','0612413','0615345']:
            self.assertGreater(actual[code],0)

    def test_population_degree_and_elective_totals_are_preserved(self):
        projection=DATA['enrollment_projection']
        intakes=read_intakes(ROOT/POLICY['intake_source'])
        expected=sum(int(r['عدد الطلبة الجدد']) for r in intakes if r['نوع الصف']=='تخصص مستقل' and r['عدد الطلبة الجدد'].isdigit())
        self.assertEqual(sum(c['students'] for c in projection['cohorts']),expected)
        self.assertEqual(sum(g['students'] for g in DATA['groups']),expected)
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
        reference=with_estimated_meetings(json.loads((ROOT/POLICY['reference_source']).read_text()),
            CURRICULUM,POLICY['estimated_meeting_courses'])
        if POLICY.get('room_free_course_codes'):
            reference=with_room_free_activities(reference,CURRICULUM,POLICY['room_free_course_codes'])
        if POLICY.get('external_courses',{}).get('enabled'):
            reference=with_external_courses(reference,POLICY['external_courses'])
        with patch('masar.enrollment._study_plan',side_effect=AssertionError('Unexpected path regeneration')):
            result=with_intake_enrollments(reference,CURRICULUM,read_intakes(ROOT/POLICY['intake_source']),
                policy=POLICY,cached_projection=DATA['enrollment_projection'])
        self.assertEqual(result,DATA)

    def test_export_major_labels_match_degree_plan_eligibility_including_electives(self):
        from collections import defaultdict
        expected=defaultdict(set)
        for record in CURRICULUM['records']:
            if record['category'] in ('كلية إجباري','تخصص إجباري','تخصص اختياري'):
                expected[record['course_code']].add(record['program_name'])
        from masar.reporting import table_rows
        result=json.loads((ROOT/'masar_v2_output/result.json').read_text())
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
