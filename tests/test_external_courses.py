import copy
import json
import unittest
from pathlib import Path
from collections import Counter

from masar.external_courses import with_external_courses, EXTERNAL_COURSES
from masar.validation import prepare
from masar.solver import solve
from masar.planning import planned_data
from test_planning import fixture

ROOT=Path(__file__).resolve().parents[1]


class ExternalCourseTests(unittest.TestCase):
    def test_external_courses_cannot_consume_IT_rooms_and_IT_cannot_consume_external_rooms(self):
        data=json.loads((ROOT/'data/masar_data_v2.json').read_text());ctx=prepare(data)
        external={r['id'] for r in data['rooms'] if r.get('location')=='outside_it'}
        for section in data['sections']:
            if section['status']!='scheduled':continue
            allowed={rid for rid,r in ctx['rooms'].items() if r['type'] in data['compatibility'][section['room_requirement']]}
            if section['course_code'] in EXTERNAL_COURSES:
                self.assertTrue(allowed)
                self.assertTrue(allowed<=external)
                self.assertEqual(section['delivery'],'in_person')
            else:self.assertFalse(allowed&external)

    def test_splitting_resources_preserves_all_course_enrollments_and_population(self):
        current=json.loads((ROOT/'masar_v2_output/archive/before_student_capacity_fit/data/masar_data_v2.json').read_text())
        previous=json.loads((ROOT/'masar_v2_output/archive/before_external_courses/data/masar_data_v2.json').read_text())
        def counts(data):
            result=Counter()
            for s in data['sections']:
                if s.get('students'):result[s['course_code']]+=s['students']
            return result
        self.assertEqual(counts(current),counts(previous))
        self.assertEqual(len(counts(current)),111)
        self.assertEqual(sum(g['students'] for g in current['groups']),2300)

    def test_external_meetings_still_create_student_conflicts(self):
        data=fixture((20,),capacity=40)
        data['sections'].append(dict(data['sections'][0],id='E',course_code='0202100'))
        data['groups']=[dict(id='G',students=20,section_ids=['C_1','E'])]
        original=copy.deepcopy(data)
        external=with_external_courses(data,{'enabled':True})
        self.assertEqual(data,original)
        result=solve(external,seconds=4,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(len({a['start'] for a in result['assignments']}),2)
        effective=planned_data(external,result)
        byid={s['id']:s for s in effective['sections']}
        for a in result['assignments']:
            if byid[a['event_id']]['course_code']=='0202100':self.assertEqual(a['room_id'],'EXT_LANG_1')
        data['patterns']['P']['starts']=[510]
        result=solve(with_external_courses(data,{'enabled':True}),seconds=2,optimize=False)
        self.assertEqual(result['status'],'INFEASIBLE')

    def test_external_room_estimates_are_finite_and_explicit_and_transform_is_idempotent(self):
        data=fixture((20,),capacity=40)
        first=with_external_courses(data,{'enabled':True})
        second=with_external_courses(first,{'enabled':True})
        self.assertEqual(first,second)
        outside=[r for r in first['rooms'] if r.get('location')=='outside_it']
        self.assertEqual(len(outside),4)
        self.assertTrue(all(0<r['capacity']<=100 for r in outside))
        self.assertTrue(all(r['inventory_status']=='scenario_placeholder_not_verified' for r in outside))


if __name__=='__main__':unittest.main()
