import copy
import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from masar.student_groups import with_plan_groups, prerequisite_levels
from masar.group_reporting import write_group_reports
from masar.solver import solve
from masar.validation import InputError, prepare
from test_planning import fixture


def course(code, requirements=(), program='P', category='تخصص إجباري', hours=3, basket='', minimum=None):
    return dict(program_id=program, program_name=program, course_code=code, course_name=code,
                credit_hours=hours, category=category, elective_basket=basket,
                minimum_completed_hours=minimum, source_image='sources/test.jpeg',
                requirements=[dict(course_code=c, concurrent_allowed=concurrent)
                              for c, concurrent in requirements])


def data_for(codes, count=20):
    data = fixture((count,))
    template = data['sections'][0]
    data['sections'] = [dict(template, id=code+'_1', course_code=code, name_ar=code) for code in codes]
    return data


class PlanGroupTests(unittest.TestCase):
    def test_strict_prerequisites_separate_and_concurrent_classes_can_stay_together(self):
        data = data_for(['A','B','C','LAB'])
        curriculum = [course('A'),course('B',[('A',False)]),course('C'),course('LAB',[('A',True)],hours=1)]
        output = with_plan_groups(data,curriculum)
        self.assertTrue(any({'A','LAB'} <= set(g['course_codes']) for g in output['groups']))
        self.assertFalse(any({'A','B'} <= set(g['course_codes']) for g in output['groups']))
        self.assertEqual(next(r for r in output['group_inference']['course_coverage']
                              if r['course_code']=='B')['modeled_students'],0)

    def test_program_specific_requirements_do_not_get_unified(self):
        data=data_for(['A','B','C'])
        curriculum=[course('A'),course('B',[('A',False)]),course('C'),
                    course('A',program='Q'),course('B',program='Q'),course('C',program='Q')]
        out=with_plan_groups(data,curriculum)
        self.assertTrue(any(g['program_id']=='Q' and {'A','B'} <= set(g['course_codes']) for g in out['groups']))
        self.assertFalse(any(g['program_id']=='P' and {'A','B'} <= set(g['course_codes']) for g in out['groups']))
        self.assertTrue(any(g['students']==10 for g in out['groups']))

    def test_no_course_or_source_section_overbooking_and_input_unchanged(self):
        data=data_for(['A','B'])
        data['sections'].append(dict(data['sections'][0],id='A_2',section_number=2,students=7))
        before=copy.deepcopy(data)
        records=[course('A'),course('B'),course('A',program='Q'),course('B',program='Q')]
        out=with_plan_groups(data,records)
        self.assertEqual(data,before)
        enrolled=Counter()
        for group in out['groups']:
            for sid in group['section_ids']:enrolled[sid]+=group['students']
        for section in out['sections']:
            self.assertLessEqual(enrolled[section['id']],section['students'])
        self.assertEqual(prepare(out)['groups'].keys(), {g['id'] for g in out['groups']})
        self.assertEqual(with_plan_groups(out,records),out)

    def test_elective_choices_are_not_all_forced_into_one_group(self):
        data=data_for(['A','B','C','D'])
        out=with_plan_groups(data,[course(c,category='تخصص اختياري') for c in ['A','B','C','D']])
        self.assertTrue(out['groups'])
        for group in out['groups']:
            self.assertLessEqual(group['credit_hours'],9)
            self.assertLessEqual(len(group['course_codes']),3)

    def test_university_elective_basket_limit(self):
        data=data_for(['A','B','C'])
        records=[course('A',category='جامعة اختياري',basket='one'),
                 course('B',category='جامعة اختياري',basket='one'),
                 course('C',category='جامعة اختياري',basket='two')]
        out=with_plan_groups(data,records)
        self.assertFalse(any({'A','B'}<=set(g['course_codes']) for g in out['groups']))

    def test_unknown_codes_and_remedial_courses_are_explicitly_unmodeled(self):
        data=data_for(['A','B','UNKNOWN','REMEDIAL'])
        out=with_plan_groups(data,[course('A'),course('B'),course('REMEDIAL',hours=0)])
        rows={r['course_code']:r for r in out['group_inference']['course_coverage']}
        self.assertEqual(rows['UNKNOWN']['reason'],'no_exact_plan_code_match')
        self.assertEqual(rows['REMEDIAL']['reason'],'zero_credit_or_remedial_track_not_inferred')
        self.assertEqual(rows['UNKNOWN']['unmodeled_students'],20)
        self.assertTrue(all(set(g['course_codes'])=={'A','B'} for g in out['groups']))

    def test_impossible_same_time_course_basket_is_not_invented(self):
        data=data_for(['A','B'])
        data['patterns']['P']['starts']=[510]
        out=with_plan_groups(data,[course('A'),course('B')])
        self.assertEqual(out['groups'],[])
        self.assertEqual(out['group_inference']['unmodeled_course_enrollments'],40)

    def test_completion_threshold_does_not_join_foundation_level(self):
        records=[course('A'),course('PROJECT',minimum=90)]
        levels=prerequisite_levels(records)
        self.assertGreater(levels['PROJECT'],levels['A'])
        self.assertEqual(with_plan_groups(data_for(['A','PROJECT']),records)['groups'],[])

    def test_inconsistent_graph_or_missing_requirement_rejected(self):
        for records in ([course('A',[('B',False)]),course('B',[('A',True)])],
                        [course('A',[('MISSING',False)])]):
            with self.assertRaises(InputError):prerequisite_levels(records)

    def test_solved_groups_and_exports_agree_after_sections_merge(self):
        data=data_for(['A','B'])
        data['sections'].append(dict(data['sections'][0],id='A_2',section_number=2,students=10))
        grouped=with_plan_groups(data,[course('A'),course('B')])
        result=solve(grouped,seconds=2)
        self.assertTrue(result['has_solution'])
        self.assertTrue(result['validation']['valid'])
        self.assertEqual(result['section_plan']['opened_sections'],2)
        self.assertEqual(result['group_inference'],grouped['group_inference'])
        with tempfile.TemporaryDirectory() as directory:
            write_group_reports(grouped,result,directory)
            with (Path(directory)/'student_groups.csv').open(encoding='utf-8-sig',newline='') as stream:
                rows=list(csv.DictReader(stream))
            ids={s['id'] for s in result['planned_sections']}
            self.assertTrue(all(row['معرف الشعبة'] in ids for row in rows))
            self.assertEqual(sum(int(row['عدد طلبة المجموعة']) for row in rows),
                             grouped['group_inference']['modeled_course_enrollments'])


if __name__=='__main__':unittest.main()
