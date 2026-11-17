import copy
import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter
from pathlib import Path

from masar.audit import data_quality, write_audit_reports
from masar.checker import inspect_solution
from masar.enrollment import with_intake_enrollments
from masar.planning import planned_data, _check_enrollments
from masar.requests import with_course_requests
from masar.solver import solve
from masar.validation import InputError, prepare
from test_planning import fixture
from test_enrollment import REFERENCE, CURRICULUM, INTAKES, SNAPSHOT


class SectioningRegressionTests(unittest.TestCase):
    def test_memory_guard_before_search_reports_unknown_without_crashing(self):
        with patch('masar.planning._memory_mb', return_value=300):
            result=solve(dict(fixture(), solver_memory_limit_mb=256),seconds=2)
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertFalse(result['has_solution'])
        self.assertTrue(result['search_statistics']['stopped_for_memory'])
        self.assertIn('memory budget',result['diagnostics'][0])

    def test_seat_weighted_capacity_detects_shortage_hidden_by_room_hours(self):
        # Two 100-seat rooms and a 10-seat room. Three sections appear sufficient
        # at the largest capacity, but 250 students cannot fit the 210 seats.
        data=fixture((250,),capacity=100)
        data['patterns']['P']=dict(days=[7],duration=60,starts=[510])
        data['rooms'] += [dict(data['rooms'][0],id='BIG2'),dict(data['rooms'][0],id='SMALL',capacity=10)]
        result=solve(data,seconds=2)
        self.assertEqual(result['status'],'INFEASIBLE')
        proofs=[p for p in result['resource_diagnostics'] if p['reason']=='weekly_student_seat_capacity_exceeded']
        self.assertEqual(len(proofs),1)
        self.assertEqual(proofs[0]['minimum_student_minutes'],250*60)
        self.assertEqual(proofs[0]['available_student_minutes'],210*60)
        self.assertFalse(any(p['reason']=='weekly_room_workload_exceeded' for p in result['resource_diagnostics']))

    def batch_fixture(self):
        data=fixture((60,),capacity=30)
        data['groups']=[dict(id=f'G{i}',students=20,section_ids=['C_1'],splittable=True) for i in range(3)]
        return data

    def test_estimated_batches_do_not_force_three_sections_for_sixty_students(self):
        data=self.batch_fixture()
        result=solve(data,seconds=5,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertTrue(result['section_plan']['minimum_proven'])
        self.assertEqual(result['section_plan']['opened_sections'],2)
        self.assertEqual(sum(g['students'] for g in result['planned_groups']),60)
        _check_enrollments(prepare(data),prepare(planned_data(data,result)))

    def test_explicit_intact_groups_remain_intact(self):
        data=self.batch_fixture()
        for g in data['groups']:g['splittable']=False
        result=solve(data,seconds=5,optimize=False)
        self.assertEqual(result['section_plan']['opened_sections'],3)
        self.assertEqual(sorted(g['students'] for g in result['planned_groups']),[20,20,20])

    def test_members_keep_complete_course_bundles_with_no_clashes(self):
        data=self.batch_fixture()
        data['sections'].append(dict(data['sections'][0],id='D',course_code='D'))
        data['rooms'].append(dict(data['rooms'][0],id='R2'))
        for group in data['groups']:group['section_ids'].append('D')
        result=solve(data,seconds=8,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],4)
        ctx=prepare(planned_data(data,result))
        self.assertTrue(inspect_solution(ctx,result['assignments'])['valid'])
        self.assertTrue(all(len(g['section_ids'])==2 for g in result['planned_groups']))
        _check_enrollments(prepare(data),ctx)
        broken=copy.deepcopy(planned_data(data,result))
        broken['groups'][0]['section_ids'].pop()
        with self.assertRaises(InputError):_check_enrollments(prepare(data),prepare(broken))

    def test_split_groups_can_use_smaller_available_rooms(self):
        data=fixture((40,),capacity=20)
        data['groups']=[dict(id='G',students=40,section_ids=['C_1'],splittable=True)]
        data['rooms'].append(dict(data['rooms'][0],id='BIG',capacity=40,
                                 blackouts=[dict(day=7,start=0,end=1440)]))
        result=solve(data,seconds=5,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],2)

    def test_pattern_options_validated_before_infeasibility_certificate(self):
        data=fixture((1000,),capacity=30)
        data['patterns']['BAD']=dict(days=[7],duration=60,starts=[510])
        data['section_pattern_options']={'C_1':['BAD']}
        with self.assertRaisesRegex(InputError,'weekly teaching hours'):solve(data,seconds=1)


class StaffingTests(unittest.TestCase):
    def data(self):
        data=fixture((20,),capacity=30)
        data['teachers_enabled']=True
        data['teachers']=[dict(id='T',name_ar='مدرس',blackouts=[],max_weekly_minutes=240)]
        data['sections'][0]['teacher_ids']=['T']
        data['sections'].append(dict(data['sections'][0],id='D',course_code='D'))
        data['rooms'].append(dict(data['rooms'][0],id='R2'))
        return data

    def test_teacher_clashes_prevented_in_both_solver_modes(self):
        for planning in (False,True):
            data=self.data()
            result=solve(data,seconds=5,plan_sections=planning)
            self.assertTrue(result['has_solution'],result['diagnostics'])
            self.assertEqual(len({a['start'] for a in result['assignments']}),2)
            self.assertTrue(all(a['teacher_id']=='T' for a in result['assignments']))
            ctx=prepare(planned_data(data,result))
            changed=copy.deepcopy(result['assignments'])
            changed[1]['start']=changed[0]['start']
            changed[1]['meetings']=copy.deepcopy(changed[0]['meetings'])
            self.assertTrue(any('Teacher clash' in e for e in inspect_solution(ctx,changed)['errors']))

    def test_teacher_availability_and_workload_are_hard_limits(self):
        for planning in (False,True):
            data=self.data()
            data['teachers'][0]['max_weekly_minutes']=120
            self.assertEqual(solve(data,seconds=2,plan_sections=planning)['status'],'INFEASIBLE')
            data['teachers'][0]['max_weekly_minutes']=240
            data['teachers'][0]['blackouts']=[dict(day=7,start=0,end=1440)]
            self.assertEqual(solve(data,seconds=2,plan_sections=planning)['status'],'INFEASIBLE')

    def test_missing_teacher_mapping_rejected_when_enabled(self):
        data=self.data()
        del data['sections'][0]['teacher_ids']
        with self.assertRaises(InputError):solve(data,seconds=1)


class ForecastAndRequestTests(unittest.TestCase):
    def test_offering_list_no_longer_changes_inferred_study_plan(self):
        reference=copy.deepcopy(REFERENCE)
        reference['sections']=[s for s in reference['sections'] if s['course_code']!='0612112']
        reference['groups']=[]
        result=with_intake_enrollments(reference,CURRICULUM,INTAKES,
            policy=SNAPSHOT['enrollment_generation'],cached_projection=SNAPSHOT['enrollment_projection'])
        self.assertEqual(result['enrollment_projection']['study_plans'],SNAPSHOT['enrollment_projection']['study_plans'])
        self.assertEqual(result['enrollment_projection']['plan_fingerprint'],SNAPSHOT['enrollment_projection']['plan_fingerprint'])
        self.assertEqual(result['enrollment_projection']['estimated_students'],3032)
        self.assertTrue(any('0612112' in c['unavailable_courses'] for c in result['enrollment_projection']['cohorts']))

    def test_bad_intake_semester_is_not_silently_second_semester(self):
        rows=copy.deepcopy(INTAKES)
        next(r for r in rows if r['نوع الصف']=='تخصص مستقل')['الفصل']='typo'
        with self.assertRaisesRegex(InputError,'semester label'):
            with_intake_enrollments(REFERENCE,CURRICULUM,rows,policy=SNAPSHOT['enrollment_generation'],cached_projection=SNAPSHOT['enrollment_projection'])

    def test_requests_replace_synthetic_counts_without_mutating_reference(self):
        reference=fixture((15,15),capacity=30)
        before=copy.deepcopy(reference)
        data=with_course_requests(reference,[dict(id='A',students=35,course_codes=['C'])])
        self.assertEqual(sum(s['students'] for s in data['sections']),35)
        self.assertEqual(reference,before)
        result=solve(data,seconds=4)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],2)

    def test_ambiguous_request_pools_require_explicit_mapping(self):
        reference=fixture()
        reference['sections'][1].update(delivery='online',room_requirement='online')
        request=dict(id='A',students=5,course_codes=['C'])
        with self.assertRaises(InputError):with_course_requests(reference,[request])
        request['pool_source_ids']={'C':'C_2'}
        result=with_course_requests(reference,[request])
        self.assertEqual(result['sections'][0]['delivery'],'online')

    def test_unknown_request_course_is_never_silently_dropped(self):
        with self.assertRaises(InputError):
            with_course_requests(fixture(),[dict(id='A',students=1,course_codes=['missing'])])

    def test_audit_reports_missing_population_and_assumed_capacity(self):
        quality=data_quality(SNAPSHOT)
        counts={i['code']:i['count'] for i in quality['issues']}
        self.assertEqual(counts['unverified_room_capacities'],13)
        self.assertEqual(counts['students_without_offered_courses'],3032-SNAPSHOT['enrollment_projection']['represented_students'])
        result=solve(SNAPSHOT,seconds=1)
        with tempfile.TemporaryDirectory() as directory:
            write_audit_reports(SNAPSHOT,REFERENCE,result,directory)
            with (Path(directory)/'real_section_comparison.csv').open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(sum(int(r['real_teaching_sections']) for r in rows),109)
            self.assertEqual(sum(int(r['projected_students']) for r in rows if r['projected_students']!='unknown'),
                             SNAPSHOT['group_inference']['modeled_course_enrollments'])


if __name__=='__main__':unittest.main()
