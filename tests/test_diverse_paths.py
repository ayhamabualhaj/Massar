import copy
import csv
import json
import tempfile
import unittest
from collections import Counter,defaultdict
from pathlib import Path
from unittest.mock import patch

from masar.enrollment import with_intake_enrollments,read_intakes,_check_study_plan
from masar.estimated_meetings import with_estimated_meetings
from masar.enrollment_reporting import write_enrollment_reports
from masar.solver import solve

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=json.loads((ROOT/'masar_v2_output/archive/before_positive_course_demand/data/masar_data_v2.json').read_text())
CURRICULUM=json.loads((ROOT/'course_requirements/five_majors_degree_plans.json').read_text())
POLICY=SNAPSHOT['enrollment_generation']
_reference=with_estimated_meetings(json.loads((ROOT/POLICY['reference_source']).read_text()),CURRICULUM,POLICY['estimated_meeting_courses'])
SNAPSHOT=with_intake_enrollments(_reference,CURRICULUM,read_intakes((ROOT/'masar_v2_output/archive/before_student_capacity_fit')/POLICY['intake_source']),policy=POLICY,cached_projection=SNAPSHOT['enrollment_projection'])


class DiverseStudyPathTests(unittest.TestCase):
    def rebuild(self):
        reference=json.loads((ROOT/POLICY['reference_source']).read_text())
        reference=with_estimated_meetings(reference,CURRICULUM,POLICY['estimated_meeting_courses'])
        return with_intake_enrollments(reference,CURRICULUM,read_intakes((ROOT/'masar_v2_output/archive/before_student_capacity_fit')/POLICY['intake_source']),
            policy=POLICY,cached_projection=SNAPSHOT['enrollment_projection'])

    def test_each_major_year_has_different_current_course_bundles_and_exact_population(self):
        data=self.rebuild();profiles=data['enrollment_projection']['cohorts']
        self.assertEqual(len(profiles),60)
        cohorts=defaultdict(list)
        for profile in profiles:cohorts[profile['parent_cohort_id']].append(profile)
        self.assertEqual(len(cohorts),20)
        counts={'SE':244,'CS':73,'AI':73,'CYBER':73,'CIS':112}
        for rows in cohorts.values():
            self.assertEqual(len(rows),3)
            self.assertEqual(sum(r['students'] for r in rows),counts[rows[0]['program_id']])
            self.assertEqual(len({tuple(r['planned_courses']) for r in rows}),3)
        self.assertEqual(sum(g['students'] for g in data['groups']),2300)
        self.assertEqual(data['enrollment_projection']['represented_students'],2300)

    def test_every_profile_has_prerequisites_and_no_repeated_completed_course(self):
        data=self.rebuild()
        index={(r['program_id'],r['course_code']):r for r in CURRICULUM['records']}
        for profile in data['enrollment_projection']['cohorts']:
            current=set(profile['planned_courses']);completed=set(profile['assumed_completed_course_codes'])
            self.assertFalse(current&completed)
            for code in current:
                row=index[profile['program_id'],code]
                for req in row['requirements']:
                    prerequisite=index.get((profile['program_id'],req['course_code']))
                    if not prerequisite or prerequisite['credit_hours']==0:continue
                    self.assertTrue(req['course_code'] in completed or
                        (req['concurrent_allowed'] and req['course_code'] in current))
                self.assertGreaterEqual(sum(index[profile['program_id'],c]['credit_hours'] for c in completed),
                                        row.get('minimum_completed_hours') or 0)

    def test_paths_keep_full_degree_credits_and_nine_major_elective_credits(self):
        data=self.rebuild()
        for program,paths in data['enrollment_projection']['study_paths'].items():
            rows=[r for r in CURRICULUM['records'] if r['program_id']==program]
            index={r['course_code']:r for r in rows}
            self.assertEqual(len(paths),3)
            for path in paths:
                _check_study_plan(rows,path['semesters'],POLICY)
                self.assertEqual(sum(index[c]['credit_hours'] for c in path['semesters']),132)
                self.assertEqual(sum(index[c]['credit_hours'] for c in path['semesters']
                    if index[c]['category']=='تخصص اختياري'),9)

    def test_course_demand_is_sum_of_profile_counts_not_whole_cohort_for_each_option(self):
        data=self.rebuild();expected=Counter();actual=Counter()
        for profile in data['enrollment_projection']['cohorts']:
            self.assertFalse(profile['unavailable_courses'])
            for code in profile['planned_courses']:expected[code]+=profile['students']
        for s in data['sections']:
            if s['status']=='scheduled':actual[s['course_code']]+=s['students']
        self.assertEqual(actual,expected)
        self.assertNotIn('0614100',actual)

    def test_cached_rebuild_does_not_randomly_reassign_students_or_change_plan(self):
        with patch('masar.enrollment._study_plan',side_effect=AssertionError('Unexpected plan regeneration')):
            first=self.rebuild();second=self.rebuild()
        self.assertEqual(first,second)
        self.assertEqual(first,SNAPSHOT)

    def test_reports_identify_paths_and_nine_credit_limit_per_path(self):
        data=self.rebuild();result=solve(data,seconds=1)
        with tempfile.TemporaryDirectory() as directory:
            write_enrollment_reports(data,result,CURRICULUM,directory)
            with (Path(directory)/'student_learning_profiles.csv').open(encoding='utf-8-sig') as f:profiles=list(csv.DictReader(f))
            self.assertEqual(len(profiles),60)
            self.assertEqual(sum(int(r['عدد الطلبة']) for r in profiles),2300)
            with (Path(directory)/'major_elective_selections.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            credits=Counter()
            for r in rows:credits[r['التخصص'],r['المسار']]+=int(r['الساعات المعتمدة'])
            self.assertEqual(len(credits),15)
            self.assertEqual(set(credits.values()),{9})


if __name__=='__main__':unittest.main()
