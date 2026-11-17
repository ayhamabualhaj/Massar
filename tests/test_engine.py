import copy,json,unittest
from functools import partial
from pathlib import Path

from masar.solver import solve
from masar.validation import InputError, prepare
from masar.checker import inspect_solution
from masar.reporting import table_rows

# These tests exercise scheduling an explicitly fixed section list.
solve = partial(solve, plan_sections=False)

data = json.loads((Path(__file__).resolve().parents[1] / "data" / "masar_section_templates.json").read_text(encoding="utf-8"))




def fixture(starts=None,online=False):
    return {'schema_version':'2.0','teachers_enabled':False,
            'rooms':[{'id':'R','name_ar':'قاعة','type':'classroom','capacity':30,'blackouts':[]}],
            'patterns':{'P':{'days':[7,2,4],'duration':60,'starts':starts if starts is not None else [510,570,810]}},
            'compatibility':{'lecture':['classroom'],'computers':['computer_lab'],'online':[]},
            'sections':[{'id':f'S{i}','course_code':f'00{i}','name_ar':f'مادة {i}','section_number':1,
                         'status':'scheduled','pattern_id':'P','delivery':'online' if online else 'in_person',
                         'room_requirement':'online' if online else 'lecture','students':20,
                         'source_start':510 if i==1 else 810} for i in (1,2)],
            'groups':[{'id':'G','section_ids':['S1','S2'],'students':10}], 'shared_classes':[],
            'objective_weights':{'group_idle_minutes':100,'late_meeting_minutes':2,'source_shift_minutes':1,'parallel_same_start':30},
            'late_after':870}


class EngineTests(unittest.TestCase):
    def test_optimization_removes_gaps(self):
        d=fixture();r=solve(d,seconds=2)
        self.assertTrue(r['has_solution']);self.assertEqual(r['validation']['metrics']['group_idle_minutes'],0)
        self.assertEqual(r['validation']['hard_rule_violations'],0)

    def test_room_conflict_infeasible_without_groups(self):
        d=fixture([510]);d['groups']=[]
        self.assertEqual(solve(d)['status'],'INFEASIBLE')

    def test_parallel_rooms_are_allowed(self):
        d=fixture([510]);d['groups']=[];d['rooms'].append(dict(d['rooms'][0],id='R2'))
        self.assertTrue(solve(d)['has_solution'])

    def test_online_conflict_uses_student_rule(self):
        d=fixture([510],online=True);d['rooms']=[]
        self.assertEqual(solve(d)['status'],'INFEASIBLE')
        d['groups']=[];self.assertTrue(solve(d)['has_solution'])

    def test_capacity_reconfiguration(self):
        d=fixture();d['sections'][0]['students']=31
        self.assertEqual(solve(d)['status'],'INFEASIBLE')
        d['rooms'][0]['capacity']=31;self.assertTrue(solve(d)['has_solution'])

    def test_room_compatibility_is_data(self):
        d=fixture();d['rooms'][0]['type']='computer_lab'
        self.assertEqual(solve(d)['status'],'INFEASIBLE')
        d['compatibility']['lecture'].append('computer_lab')
        self.assertTrue(solve(d)['has_solution'])

    def test_blackout_and_union(self):
        d=fixture();d['rooms'][0]['blackouts']=[{'day':7,'start':510,'end':550},{'day':7,'start':540,'end':570}]
        r=solve(d);self.assertTrue(r['has_solution'])
        self.assertNotIn(510,[a['start'] for a in r['assignments']])
        self.assertEqual(len(prepare(d)['rooms']['R']['blackouts']),1)

    def test_shared_class_explicit_and_display_keeps_both(self):
        d=fixture([510]);d['shared_classes']=[{'id':'SHARED','section_ids':['S1','S2'],'students':20}]
        r=solve(d);self.assertTrue(r['has_solution']);self.assertEqual(len(r['assignments']),1)
        rows=table_rows(d,r);self.assertEqual(len(rows),2);self.assertEqual(rows[0]['من'],rows[1]['من'])

    def test_shared_capacity_uses_explicit_total(self):
        d=fixture([510]);d['shared_classes']=[{'id':'SHARED','section_ids':['S1','S2'],'students':40}]
        self.assertEqual(solve(d)['status'],'INFEASIBLE')

    def test_recurrence_and_adjacent_sessions(self):
        d=fixture([510,570]);r=solve(d)
        self.assertTrue(r['has_solution']);self.assertEqual({a['start'] for a in r['assignments']},{510,570})
        for a in r['assignments']:
            self.assertEqual([m['day'] for m in a['meetings']],[7,2,4])
            self.assertEqual(len({m['start'] for m in a['meetings']}),1)

    def test_group_counts_cannot_exceed_enrollment(self):
        d=fixture();d['groups'].append({'id':'G2','section_ids':['S1'],'students':15})
        with self.assertRaises(InputError):solve(d)

    def test_unknown_rule_and_bad_inputs_rejected(self):
        mutations=[lambda d:d['objective_weights'].update(unknown=1),lambda d:d.update(teachers_enabled=True),
                   lambda d:d['groups'][0]['section_ids'].append('MISSING'),lambda d:d['rooms'][0].update(capacity=True),
                   lambda d:d['patterns']['P']['days'].append(7),lambda d:d['sections'].append(d['sections'][0])]
        for change in mutations:
            with self.subTest(change=change):
                d=fixture();change(d)
                with self.assertRaises(InputError):solve(d)

    def test_bad_limits(self):
        for n in (0,-1,True,float('nan'),float('inf')):
            with self.subTest(n=n),self.assertRaises(InputError):solve(fixture(),seconds=n)

    def test_output_checker_detects_tampering(self):
        d=fixture();r=solve(d);ctx=prepare(d)
        a=copy.deepcopy(r['assignments']);a[0]['meetings'][0]['end']+=1
        self.assertFalse(inspect_solution(ctx,a)['valid'])
        a=copy.deepcopy(r['assignments']);a[1]['start']=a[0]['start'];a[1]['meetings']=copy.deepcopy(a[0]['meetings'])
        self.assertFalse(inspect_solution(ctx,a)['valid'])
        self.assertFalse(inspect_solution(ctx,r['assignments'][:1])['valid'])

    def test_full_dataset_no_mutation_and_all_rows(self):
        d=copy.deepcopy(data);before=copy.deepcopy(d)
        r=solve(d,optimize=False,seconds=5)
        self.assertTrue(r['has_solution']);self.assertEqual(len(r['assignments']),sum(s['status']=='scheduled' for s in d['sections']))
        self.assertEqual(r['validation']['hard_rule_violations'],0)
        self.assertEqual(len(table_rows(d,r)),len(d['sections']))
        self.assertEqual(sum(s['status']=='no_meeting_days' for s in d['sections']),46)
        self.assertEqual(d,before)

    def test_objective_weights_change_behavior(self):
        d=fixture();d['objective_weights']={k:0 for k in d['objective_weights']};d['objective_weights']['source_shift_minutes']=1
        r=solve(d);self.assertEqual(r['validation']['metrics']['source_shift_minutes'],0)
        self.assertEqual(r['validation']['metrics']['group_idle_minutes'],720)
        d['objective_weights']['group_idle_minutes']=100
        self.assertEqual(solve(d)['validation']['metrics']['group_idle_minutes'],0)



if __name__ == "__main__":
    unittest.main()
