import copy
import json
import unittest
from pathlib import Path
from collections import Counter

from masar.demand.estimated_meetings import with_estimated_meetings
from masar.demand.enrollment import with_intake_enrollments, read_intakes
from masar.scheduling.solver import solve
from masar.reports.timetable import table_rows
from masar.validation import InputError

ROOT=Path(__file__).resolve().parents[1]


class ApprovedMeetingTests(unittest.TestCase):
    def setUp(self):
        self.reference=json.loads((ROOT/'data/masar_section_templates.json').read_text())
        self.curriculum=json.loads((ROOT/'course_requirements/five_majors_degree_plans.json').read_text())
        self.snapshot=json.loads((ROOT/'extra information/masar_v2_output/archive/before_diverse_student_paths/data/masar_data_v2.json').read_text())
        self.policy=self.snapshot['enrollment_generation']
        self.codes=self.policy['estimated_meeting_courses']

    def rebuild(self):
        reference=with_estimated_meetings(self.reference,self.curriculum,self.codes)
        return with_intake_enrollments(reference,self.curriculum,read_intakes((ROOT/'extra information/masar_v2_output/archive/before_student_capacity_fit')/self.policy['intake_source']),
            policy=self.policy,cached_projection=self.snapshot['enrollment_projection'])

    def test_approved_patterns_preserve_credits_and_do_not_change_reference_or_hours(self):
        original=copy.deepcopy(self.reference)
        result=with_estimated_meetings(self.reference,self.curriculum,self.codes)
        self.assertEqual(self.reference,original)
        self.assertEqual(len(result['estimated_meeting_patterns']),34)
        for item in result['estimated_meeting_patterns']:
            for pid in item['pattern_ids']:
                pattern=result['patterns'][pid]
                self.assertEqual(len(pattern['days'])*pattern['duration'],item['credits']*60)
                self.assertLessEqual(max(pattern['starts'])+pattern['duration'],960)
            if 'مختبر' in item['course_name']:
                self.assertEqual(item['room_requirement'],'computers')
        active_codes={s['course_code'] for s in result['sections'] if s['status']=='scheduled'}
        for s in result['sections']:
            if s['course_code'] in self.codes:self.assertEqual(s['status'],'scheduled')
        self.assertTrue(set(self.codes)<=active_codes)

    def test_all_56_needed_courses_and_all_students_are_represented(self):
        result=self.rebuild()
        projection=result['enrollment_projection']
        self.assertEqual(projection['estimated_students'],2300)
        self.assertEqual(projection['represented_students'],2300)
        self.assertTrue(all(not c['unavailable_courses'] for c in projection['cohorts']))
        expected=Counter()
        for c in projection['cohorts']:
            for code in c['planned_courses']:expected[code]+=c['students']
        actual=Counter()
        for s in result['sections']:
            if s['status']=='scheduled':actual[s['course_code']]+=s['students']
        self.assertEqual(len(actual),56)
        self.assertEqual(actual,expected)
        self.assertNotIn('0614100',actual)
        self.assertNotIn('0612098',actual)
        self.assertEqual(sum(g['students'] for g in result['groups']),2300)

    def test_full_demand_shortage_is_reported_without_fabricating_times(self):
        # The shortage is a property of the archived demand and room inventory.
        data=self.snapshot
        result=solve(data,seconds=2)
        self.assertEqual(result['status'],'INFEASIBLE')
        proof=next(p for p in result['resource_diagnostics'] if p['reason']=='weekly_student_seat_capacity_exceeded')
        self.assertEqual(proof['shortfall_student_minutes'],3100*60)
        rows=table_rows(data,result)
        self.assertEqual(len({r['رقم المادة'] for r in rows}),56)
        self.assertTrue(all(r['من']=='—' and r['القاعة']=='—' for r in rows))

    def test_university_course_cannot_receive_estimated_IT_meetings(self):
        with self.assertRaises(InputError):
            with_estimated_meetings(self.reference,self.curriculum,['0614100'])


if __name__=='__main__':unittest.main()
