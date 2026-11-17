import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from masar.audit import data_quality
from masar.historical_audit import audit_historical_schedule
from masar.requests import with_course_requests
from masar.solver import solve
from masar.reporting import table_rows
from masar.validation import InputError
from test_planning import fixture

ROOT=Path(__file__).resolve().parents[1]


class RegistrationRepairTests(unittest.TestCase):
    def test_approved_alternative_is_preserved_and_can_be_scheduled(self):
        data=fixture((20,),capacity=30)
        data['patterns']['Q']=dict(days=[1,3],duration=60,starts=[510])
        data['section_pattern_options']={'C_1':['P','Q']}
        data['rooms'][0]['blackouts']=[dict(day=7,start=0,end=1440)]
        requests=with_course_requests(data,[dict(id='R',students=20,course_codes=['C'])])
        self.assertEqual(next(iter(requests['section_pattern_options'].values())),['P','Q'])
        result=solve(requests,seconds=3,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['planned_sections'][0]['pattern_id'],'Q')

    def test_bad_original_pattern_option_is_not_silently_discarded(self):
        data=fixture((20,),capacity=30)
        data['patterns']['BAD']=dict(days=[1],duration=60,starts=[510])
        data['section_pattern_options']={'C_1':['BAD']}
        with self.assertRaises(InputError):
            with_course_requests(data,[dict(id='R',students=20,course_codes=['C'])])

    def test_room_free_registrations_keep_counts_without_conflict_events(self):
        data=fixture((20,),capacity=30)
        data['sections'].append(dict(id='PROJECT',course_code='PROJECT',name_ar='مشروع تخرج',
            status='no_meeting_days',room_free_activity=True,students=None,section_number=1))
        requests=with_course_requests(data,[dict(id='R',students=20,course_codes=['C','PROJECT']),
            dict(id='PROJECT_ONLY',students=3,course_codes=['PROJECT'])])
        self.assertEqual(requests['request_provenance']['students'],23)
        self.assertEqual(requests['request_provenance']['course_registrations'],43)
        self.assertEqual(requests['request_provenance']['room_free_only_students'],3)
        self.assertEqual(len(requests['groups']),1)
        result=solve(requests,seconds=3,optimize=False)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        activity=next(row for row in table_rows(requests,result) if row['رقم المادة']=='PROJECT')
        self.assertEqual(activity['عدد الطلبة'],23)
        self.assertNotIn('الحالة',activity)

    def test_failed_request_run_exports_counts_without_assigned_times(self):
        requests=with_course_requests(fixture((20,),capacity=30),
            [dict(id='R',students=1000,course_codes=['C'])])
        result=solve(requests,seconds=2)
        self.assertEqual(result['status'],'INFEASIBLE')
        rows=table_rows(requests,result)
        self.assertEqual(sum(row['عدد الطلبة'] for row in rows),1000)
        self.assertTrue(all(row['من']=='—' and 'لا يمثل هذا جدولًا صالحًا' in row['ملاحظات'] for row in rows))

    def test_cli_uses_full_current_catalog_external_rooms_and_activities(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            request=directory/'requests.json'
            request.write_text(json.dumps([dict(id='R',students=2,course_codes=['0202100','0612390'])]))
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'main.py'),'--requests',str(request),
                '--output',str(directory/'out'),'--seconds','3','--no-optimize'],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            output=json.loads((directory/'out/result.json').read_text())
            self.assertTrue(output['has_solution'],output['diagnostics'])
            self.assertEqual(output['run_metadata']['demand_source'],'supplied_course_requests')
            snapshot=json.loads((directory/'out/input_snapshot.json').read_text())
            self.assertEqual(next(s for s in snapshot['sections'] if s['course_code']=='0202100')['room_requirement'],
                             'external_languages_classroom')
            self.assertEqual(output['timetable_export']['room_free_activity_rows'],1)
            self.assertEqual(snapshot['room_free_course_codes'],['0612390'])
            self.assertEqual(len(snapshot['estimated_meeting_patterns']),1)

    def test_cli_failed_requests_keep_csv_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/'input.json').write_text(json.dumps(fixture((20,),capacity=30)))
            (directory/'requests.json').write_text(json.dumps([dict(id='R',students=1000,course_codes=['C'])]))
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'main.py'),'--input',str(directory/'input.json'),
                '--requests',str(directory/'requests.json'),'--output',str(directory/'out'),
                '--seconds','2'],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            result=json.loads((directory/'out/result.json').read_text())
            self.assertEqual(result['timetable_export']['kind'],'unscheduled_capacity_proposals')
            with (directory/'out/timetable.csv').open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(sum(int(r['عدد الطلبة']) for r in rows),1000)


class SourceAuditTests(unittest.TestCase):
    def test_overlap_report_does_not_use_synthetic_groups_or_counts(self):
        data=fixture((20,20),capacity=30)
        for s in data['sections']:s['source_room']=data['rooms'][0]['id'];s['source_start']=510
        before=copy.deepcopy(data)
        report=audit_historical_schedule(data)
        self.assertEqual(len(report['overlapping_pairs']),1)
        self.assertEqual(report['overlapping_pairs'][0]['days'],[7,2])
        self.assertEqual(data,before)

    def test_user_confirmed_requirements_are_preserved(self):
        data=json.loads((ROOT/'data/masar_section_templates.json').read_text())
        computers=[s for s in data['sections'] if s.get('room_requirement')=='computers']
        self.assertTrue(computers)
        self.assertTrue(all(s.get('room_requirement_status')=='user_confirmed' for s in computers))
        audit=data_quality(dict(data,sections=computers))
        self.assertNotIn('inferred_room_requirements',{i['code'] for i in audit['issues']})
        self.assertGreater(audit['user_confirmed_computer_courses'],0)

    def test_historical_inconsistencies_are_reported_without_relaxing_requirements(self):
        data=json.loads((ROOT/'data/masar_section_templates.json').read_text())
        report=audit_historical_schedule(data)
        self.assertEqual(report['timed_sections'],109)
        self.assertEqual(len(report['overlapping_pairs']),5)
        self.assertIn('0613442_2: unknown room.',report['issues'])
        self.assertIn('0615334_1: incompatible room.',report['issues'])
        self.assertIn('0615344_1: incompatible room.',report['issues'])


if __name__=='__main__':unittest.main()
