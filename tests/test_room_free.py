import copy
import csv
import json
import unittest
from pathlib import Path
from collections import Counter

from masar.room_free import with_room_free_activities
from masar.validation import prepare,InputError

ROOT=Path(__file__).resolve().parents[1]


class RoomFreeActivityTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'data/masar_data_v2.json').read_text())
        self.result=json.loads((ROOT/'masar_v2_output/result.json').read_text())
        self.codes=set(self.data['enrollment_generation']['room_free_course_codes'])

    def test_projects_and_training_have_no_events_or_room_workload(self):
        self.assertEqual(len(self.codes),10)
        ctx=prepare(self.data)
        activities=[s for s in self.data['sections'] if s['course_code'] in self.codes]
        self.assertEqual(len(activities),10)
        for activity in activities:
            self.assertEqual(activity['status'],'no_meeting_days')
            self.assertTrue(activity['room_free_activity'])
            self.assertGreater(activity['students'],0)
            self.assertNotIn(activity['id'],ctx['section_event'])
        self.assertFalse(any(r['course_code'] in self.codes for r in self.result['section_requirements']))
        self.assertFalse(any(sid in {s['id'] for s in activities} for g in self.data['groups'] for sid in g['section_ids']))

    def test_all_student_course_enrollments_are_preserved(self):
        before=json.loads((ROOT/'masar_v2_output/archive/before_room_free_activities/data/masar_data_v2.json').read_text())
        def totals(data):
            result=Counter()
            for section in data['sections']:
                if section.get('students'):result[section['course_code']]+=section['students']
            return result
        # Keep the original 2,300-student transform regression independent of the current capacity-fit population.
        after=json.loads((ROOT/'masar_v2_output/archive/before_student_capacity_fit/data/masar_data_v2.json').read_text())
        self.assertEqual(totals(before),totals(after))
        self.assertEqual(len(totals(after)),111)
        self.assertEqual(after['enrollment_projection']['estimated_students'],2300)
        self.assertEqual(before['enrollment_projection']['study_paths'],after['enrollment_projection']['study_paths'])

    def test_csv_retains_activities_without_room_or_fixed_time(self):
        with (ROOT/'masar_v2_output/timetable.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        selected=[r for r in rows if r['رقم المادة'] in self.codes]
        self.assertEqual(len(selected),10)
        for row in selected:
            self.assertNotIn('الحالة',row)
            self.assertEqual(row['القاعة'],'لا يتطلب قاعة')
            self.assertEqual(row['الحد الأقصى للطلبة'],'لا يتطلب قاعة')
            self.assertTrue(all(row[k]=='—' for k in ['من','إلى','الأيام']))
            self.assertGreater(int(row['عدد الطلبة']),0)

    def test_only_projects_and_field_training_may_be_marked_room_free(self):
        curriculum=json.loads((ROOT/'course_requirements/course_requirements.json').read_text())
        with self.assertRaises(InputError):with_room_free_activities(self.data,curriculum,['0612117'])


if __name__=='__main__':unittest.main()
