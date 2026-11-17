import copy
import unittest
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from masar.slot_planning import solve_slot_sections
from masar.planning import planned_data, _check_enrollments
from masar.validation import prepare, InputError
from masar.checker import inspect_solution
from masar.reporting import table_rows
from test_planning import fixture


class CompactSlotTests(unittest.TestCase):
    def data(self):
        data=fixture((60,),capacity=30)
        data['groups']=[dict(id=f'G{i}',students=20,section_ids=['C_1'],splittable=True)
                        for i in range(3)]
        return data

    def check(self,data,sections):
        before=copy.deepcopy(data)
        result=solve_slot_sections(data,seconds=5)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],sections)
        effective=planned_data(data,result)
        ctx=prepare(effective)
        _check_enrollments(prepare(data),ctx)
        self.assertTrue(inspect_solution(ctx,result['assignments'])['valid'])
        self.assertEqual(data,before)
        return result,effective

    def test_split_batches_fit_two_sections_and_export_actual_times(self):
        data=self.data()
        result,effective=self.check(data,2)
        self.assertEqual(sum(g['students'] for g in effective['groups']),60)
        self.assertTrue(result['section_plan']['minimum_proven'])
        rows=table_rows(data,result)
        self.assertEqual(sum(r['عدد الطلبة'] for r in rows),60)
        self.assertTrue(all(r['من']!='—' and r['القاعة']!='—' for r in rows))

    def test_multicourse_students_keep_complete_clash_free_schedules(self):
        data=self.data()
        data['rooms'].append(dict(data['rooms'][0],id='R2'))
        data['sections'].append(dict(data['sections'][0],id='D',course_code='D'))
        for group in data['groups']:group['section_ids'].append('D')
        result,effective=self.check(data,4)
        self.assertTrue(all(len(g['section_ids'])==2 for g in effective['groups']))
        bad=copy.deepcopy(effective)
        bad['groups'][0]['section_ids'].pop()
        with self.assertRaises(InputError):_check_enrollments(prepare(data),prepare(bad))

    def test_course_time_can_share_students_across_multiple_rooms(self):
        data=fixture((40,),capacity=20)
        data['patterns']['P']['starts']=[510]
        data['rooms'].append(dict(data['rooms'][0],id='R2'))
        data['groups']=[dict(id='G',students=40,section_ids=['C_1'],splittable=True)]
        result,effective=self.check(data,2)
        self.assertEqual({a['start'] for a in result['assignments']},{510})
        self.assertEqual(sorted(s['students'] for s in effective['sections']),[20,20])

    def test_alternative_patterns_respect_blackouts(self):
        data=self.data()
        data['patterns']['Q']=dict(days=[1,3],duration=60,starts=[510,570,630])
        data['section_pattern_options']={'C_1':['P','Q']}
        data['rooms'][0]['blackouts']=[dict(day=7,start=0,end=1440)]
        _,effective=self.check(data,2)
        self.assertTrue(all(s['pattern_id']=='Q' for s in effective['sections']))

    def test_online_delivery_needs_no_physical_room(self):
        data=self.data()
        data['rooms']=[]
        data['sections'][0].update(delivery='online',room_requirement='online')
        result,_=self.check(data,1)
        self.assertIsNone(result['assignments'][0]['room_id'])

    def test_restricted_search_failure_does_not_claim_global_infeasibility(self):
        data=self.data()
        data['patterns']['P']['starts']=[510]
        data['rooms'].extend([dict(data['rooms'][0],id=f'R{i}') for i in (2,3,4)])
        data['sections'].append(dict(data['sections'][0],id='D',course_code='D'))
        for group in data['groups']:group['section_ids'].append('D')
        result=solve_slot_sections(data,seconds=3,route_limit=1)
        self.assertFalse(result['has_solution'])
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertEqual(result['assignments'],[])

    def test_memory_guard_also_works_before_compact_search_starts(self):
        data=dict(self.data(),solver_memory_limit_mb=256)
        with patch('masar.planning._memory_mb',return_value=300):
            result=solve_slot_sections(data,seconds=2)
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertTrue(result['search_statistics']['stopped_for_memory'])

    def test_checked_incumbent_hints_expanded_routes_without_adding_sections(self):
        data=self.data()
        first=solve_slot_sections(data,seconds=3,route_limit=1)
        self.assertTrue(first['has_solution'])
        improved=solve_slot_sections(data,seconds=3,route_limit=2,hints=first)
        self.assertTrue(improved['has_solution'])
        self.assertTrue(improved['search_statistics']['incumbent_hint_applied'])
        self.assertLessEqual(improved['section_plan']['opened_sections'],first['section_plan']['opened_sections'])
        self.assertTrue(inspect_solution(prepare(planned_data(data,improved)),improved['assignments'])['valid'])

    def test_valid_incumbent_survives_a_search_memory_stop(self):
        data=self.data()
        first=solve_slot_sections(data,seconds=3,route_limit=1)
        with patch('masar.planning._memory_mb',return_value=300):
            retained=solve_slot_sections(dict(data,solver_memory_limit_mb=256),seconds=2,route_limit=1,hints=first)
        self.assertTrue(retained['has_solution'])
        self.assertTrue(retained['search_statistics']['incumbent_retained'])
        self.assertTrue(retained['search_statistics']['stopped_for_memory'])
        self.assertEqual(retained['assignments'],first['assignments'])

    def test_changed_enrollment_cannot_reuse_an_old_incumbent(self):
        data=self.data()
        first=solve_slot_sections(data,seconds=3,route_limit=1)
        data['groups'][0]['students']+=1
        data['sections'][0]['students']+=1
        with patch('masar.planning._memory_mb',return_value=300):
            result=solve_slot_sections(dict(data,solver_memory_limit_mb=256),seconds=2,route_limit=1,hints=first)
        self.assertFalse(result['has_solution'])
        self.assertFalse(result['search_statistics']['incumbent_hint_applied'])

    def test_invalid_room_assignment_cannot_seed_or_bound_search(self):
        data=self.data()
        first=solve_slot_sections(data,seconds=3,route_limit=1)
        first['assignments'][0]['room_id']='MISSING'
        with patch('masar.planning._memory_mb',return_value=300):
            result=solve_slot_sections(dict(data,solver_memory_limit_mb=256),seconds=2,route_limit=1,hints=first)
        self.assertFalse(result['has_solution'])
        self.assertFalse(result['search_statistics']['incumbent_hint_applied'])

    def test_main_resumes_matching_incumbent_on_a_short_followup_run(self):
        data=fixture((240,),capacity=120)
        data['groups']=[dict(id=f'G{i}',students=60,section_ids=['C_1'],splittable=True) for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            source=directory/'input.json'
            source.write_text(json.dumps(data))
            command=[sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'main.py'),
                     '--input',str(source),'--output',str(directory/'out'),'--routes','1','--workers','1']
            first=subprocess.run(command+['--seconds','3'],capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            original=json.loads((directory/'out/result.json').read_text())
            self.assertTrue(original['has_solution'])
            second=subprocess.run(command+['--seconds','0.001'],capture_output=True,text=True)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            resumed=json.loads((directory/'out/result.json').read_text())
            self.assertTrue(resumed['has_solution'])
            self.assertTrue(resumed['search_statistics']['incumbent_hint_applied'])
            self.assertTrue(resumed['search_statistics']['incumbent_retained'])
            self.assertEqual(resumed['assignments'],original['assignments'])

    def test_large_room_cover_allows_extra_sections_when_large_room_is_closed(self):
        data=fixture((94,),capacity=80)
        data['rooms'].append(dict(data['rooms'][0],id='SMALL2'))
        data['rooms'].append(dict(data['rooms'][0],id='BIG',capacity=100,
                                 blackouts=[dict(day=day,start=0,end=1440) for day in (7,2)]))
        data['groups']=[dict(id='G',students=94,section_ids=['C_1'],splittable=True)]
        result=solve_slot_sections(data,seconds=3,route_limit=2)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],2)
        self.assertFalse(any(a['room_id']=='BIG' for a in result['assignments']))
        self.assertTrue(inspect_solution(prepare(planned_data(data,result)),result['assignments'])['valid'])

    def test_explicit_intact_groups_require_the_other_backend(self):
        data=self.data()
        data['groups'][0]['splittable']=False
        with self.assertRaises(InputError):solve_slot_sections(data,seconds=1)


if __name__=='__main__':unittest.main()
