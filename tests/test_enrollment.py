import copy
import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from masar.enrollment import with_intake_enrollments, read_intakes, _check_study_plan
from masar.group_reporting import write_group_reports
from masar.enrollment_reporting import write_enrollment_reports
from masar.solver import solve
from masar.validation import InputError
from test_planning import fixture

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=json.loads((ROOT/'masar_v2_output/archive/before_capacity_increase/data/masar_section_templates.json').read_text())
# Preserve the overloaded 3,032-student regression scenario independently of active intake edits.
BASELINE=ROOT/'masar_v2_output/archive/before_2300_students'
SNAPSHOT=json.loads((BASELINE/'data/masar_data_v2.json').read_text())
CURRICULUM=json.loads((ROOT/'course_requirements/course_requirements.json').read_text())
INTAKES=read_intakes(BASELINE/'extra information/student_numbers/student_expected_number_for_each_semester.csv')
SNAPSHOT=with_intake_enrollments(REFERENCE,CURRICULUM,INTAKES,
    policy=SNAPSHOT['enrollment_generation'],cached_projection=SNAPSHOT['enrollment_projection'])


def rebuild(intakes=None):
    return with_intake_enrollments(REFERENCE,CURRICULUM,intakes or INTAKES,
        policy=SNAPSHOT['enrollment_generation'],cached_projection=SNAPSHOT['enrollment_projection'])


class FourYearEnrollmentTests(unittest.TestCase):
    def test_real_population_and_each_year_major_count_conserved(self):
        data=rebuild()
        self.assertEqual(data['enrollment_projection']['estimated_students'],3032)
        represented=sum(g['students'] for g in data['groups'])
        missing=sum(c['students'] for c in data['enrollment_projection']['cohorts'] if not c['offered_courses'])
        self.assertEqual(represented+missing,3032)
        self.assertEqual(represented,data['enrollment_projection']['represented_students'])
        counts=Counter()
        for g in data['enrollment_projection']['cohorts']:counts[g['program_id'],g['intake_year']]+=g['students']
        for year in range(2023,2027):
            for program,count in [('SE',322),('CS',96),('AI',96),('CYBER',96),('CIS',148)]:
                self.assertEqual(counts[program,year],count)

    def test_first_year_course_is_not_multiplied_by_all_four_cohorts(self):
        data=rebuild()
        demand=sum(s['students'] for s in data['sections'] if s['course_code']=='0612112')
        self.assertEqual(demand,758)
        self.assertNotEqual(demand,3032)
        expected=Counter()
        for cohort in data['enrollment_projection']['cohorts']:
            for code in cohort['offered_courses']:expected[code]+=cohort['students']
        actual=Counter()
        for section in data['sections']:
            if section['status']=='scheduled':actual[section['course_code']]+=section['students']
        self.assertEqual(expected,actual)

    def test_rebuilding_is_idempotent_and_does_not_mutate_sources(self):
        before=copy.deepcopy(REFERENCE)
        first=rebuild();second=rebuild()
        self.assertEqual(first,second)
        self.assertEqual(first,SNAPSHOT)
        self.assertEqual(REFERENCE,before)

    def test_updated_intake_changes_only_the_appropriate_cohort_demand(self):
        rows=copy.deepcopy(INTAKES)
        row=next(r for r in rows if r['السنة المرجعية']=='2026' and r['الفصل']=='الأول'
                 and r['التخصص أو مجموعة التخصصات']=='هندسة البرمجيات')
        row['عدد الطلبة الجدد']='323'
        data=rebuild(rows)
        self.assertEqual(data['enrollment_projection']['estimated_students'],3033)
        self.assertEqual(sum(s['students'] for s in data['sections'] if s['course_code']=='0612112'),759)
        self.assertEqual(rebuild(rows),data)

    def test_aggregate_rows_are_not_counted_again(self):
        rows=copy.deepcopy(INTAKES)
        rows.extend(copy.deepcopy([r for r in INTAKES if r['نوع الصف']!='تخصص مستقل']))
        self.assertEqual(rebuild(rows),SNAPSHOT)

    def test_unknown_second_semester_intakes_are_explicit_and_known_values_can_be_added(self):
        self.assertEqual(len(SNAPSHOT['enrollment_projection']['excluded_unknown_second_semester_intakes']),20)
        rows=copy.deepcopy(INTAKES)
        row=next(r for r in rows if r['السنة المرجعية']=='2025' and r['الفصل']=='الثاني'
                 and r['التخصص أو مجموعة التخصصات']=='هندسة البرمجيات')
        row['عدد الطلبة الجدد']='10'
        data=rebuild(rows)
        self.assertEqual(data['enrollment_projection']['estimated_students'],3042)
        added=next(c for c in data['enrollment_projection']['cohorts'] if c['id']=='INTAKE_SE_2025_S2')
        self.assertEqual(added['study_semester'],2)

    def test_study_plans_respect_prerequisites_credits_and_elective_limits(self):
        for program,plan in SNAPSHOT['enrollment_projection']['study_plans'].items():
            records=[r for r in CURRICULUM['records'] if r['program_id']==program]
            _check_study_plan(records,plan['semesters'],SNAPSHOT['enrollment_generation'])
            self.assertEqual(plan['info']['credits'],132)
            broken=dict(plan['semesters'])
            broken['0612117']=broken['0612112']
            with self.assertRaises(InputError):_check_study_plan(records,broken,SNAPSHOT['enrollment_generation'])

    def test_intake_resource_shortfall_is_proven_and_no_schedule_is_claimed(self):
        result=solve(SNAPSHOT,seconds=1,optimize=False)
        self.assertEqual(result['status'],'INFEASIBLE')
        self.assertFalse(result['has_solution'])
        self.assertEqual(result['assignments'],[])
        self.assertGreater(result['required_sections_lower_bound'],75)
        for item in result['resource_diagnostics']:
            if item['reason']=='weekly_student_seat_capacity_exceeded':
                self.assertGreater(item['minimum_student_minutes'],item['available_student_minutes'])
            else:
                self.assertGreater(item['minimum_weekly_minutes'],item['available_weekly_minutes'])

    def test_pattern_options_are_preserved_without_duplicating_demand(self):
        data=fixture((30,))
        data['patterns']['Q']=dict(days=[1,3],duration=60,starts=[510,570])
        data['rooms'][0]['blackouts']=[dict(day=7,start=0,end=1440)]
        data['section_pattern_options']={'C_1':['P','Q']}
        result=solve(data,seconds=2)
        self.assertTrue(result['has_solution'],result['diagnostics'])
        self.assertEqual(result['section_plan']['opened_sections'],1)
        self.assertEqual(sum(s['students'] for s in result['planned_sections']),30)
        self.assertEqual(result['planned_sections'][0]['pattern_id'],'Q')

    def test_unscheduled_group_and_demand_exports_are_explicit(self):
        result=solve(SNAPSHOT,seconds=1,optimize=False)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_group_reports(SNAPSHOT,result,root/'groups',allow_unscheduled=True)
            write_enrollment_reports(SNAPSHOT,result,CURRICULUM,root/'numbers')
            with (root/'groups/student_groups.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            self.assertTrue(rows)
            self.assertTrue(all(row['معرف الشعبة']=='' and row['الشعبة المسندة']=='غير مجدول' for row in rows))
            with (root/'groups/student_group_summary.csv').open(encoding='utf-8-sig',newline='') as f:groups=list(csv.DictReader(f))
            self.assertEqual(sum(int(g['عدد طلبة المجموعة']) for g in groups),SNAPSHOT['enrollment_projection']['represented_students'])
            with (root/'numbers/section_requirements.csv').open(encoding='utf-8-sig',newline='') as f:requirements=list(csv.DictReader(f))
            self.assertEqual(sum(int(r['الحد الأدنى للشعب حسب السعة']) for r in requirements),result['required_sections_lower_bound'])



class ITCourseScopeTests(unittest.TestCase):
    def scoped(self):
        return with_intake_enrollments(REFERENCE,CURRICULUM,INTAKES,
            policy=dict(SNAPSHOT['enrollment_generation'],scheduling_categories=[
                'كلية إجباري','تخصص إجباري','تخصص اختياري']),
            cached_projection=SNAPSHOT['enrollment_projection'])

    def test_only_it_categories_generate_demand_and_group_memberships(self):
        data=self.scoped()
        allowed={'كلية إجباري','تخصص إجباري','تخصص اختياري'}
        index={(r['program_id'],r['course_code']):r for r in CURRICULUM['records']}
        for cohort in data['enrollment_projection']['cohorts']:
            for code in cohort['planned_courses']:
                self.assertIn(index[cohort['program_id'],code]['category'],allowed)
        self.assertNotIn('0614100',{s['course_code'] for s in data['sections']})
        self.assertNotIn('0612099',{s['course_code'] for s in data['sections']})
        self.assertTrue(all(r['category'] in allowed for r in data['course_catalog_scope']['records']))
        self.assertEqual(data['enrollment_projection']['estimated_students'],3032)

    def test_major_electives_are_nine_credits_over_degree_and_unselected_have_no_demand(self):
        data=self.scoped()
        index={(r['program_id'],r['course_code']):r for r in CURRICULUM['records']}
        for program,plan in data['enrollment_projection']['study_plans'].items():
            selected=[code for code in plan['semesters'] if index[program,code]['category']=='تخصص اختياري']
            self.assertEqual(sum(index[program,c]['credit_hours'] for c in selected),9)
            for cohort in data['enrollment_projection']['cohorts']:
                if cohort['program_id']!=program:continue
                for code in cohort['planned_courses']:
                    if index[program,code]['category']=='تخصص اختياري':self.assertIn(code,selected)

    def test_it_catalog_keeps_missing_faculty_courses_without_inventing_meetings(self):
        data=self.scoped()
        codes={r['course_code'] for r in data['course_catalog_scope']['records']}
        self.assertIn('0303106',codes)
        self.assertNotIn('0303106',{s['course_code'] for s in data['sections']})
        result=solve(data,seconds=1)
        with tempfile.TemporaryDirectory() as directory:
            write_enrollment_reports(data,result,CURRICULUM,directory)
            with (Path(directory)/'it_course_catalog.csv').open(encoding='utf-8-sig') as f:catalog=list(csv.DictReader(f))
            self.assertTrue(catalog)
            self.assertTrue(all(r['نوع المتطلب'] in {'كلية إجباري','تخصص إجباري','تخصص اختياري'} for r in catalog))
            with (Path(directory)/'major_elective_selections.csv').open(encoding='utf-8-sig') as f:electives=list(csv.DictReader(f))
            totals=Counter()
            for row in electives:totals[row['التخصص']]+=int(row['الساعات المعتمدة'])
            self.assertEqual(dict(totals),{p:9 for p in SNAPSHOT['enrollment_projection']['study_plans']})


class InfeasibleTimetableExportTests(unittest.TestCase):
    def test_capacity_proposals_preserve_all_course_demand_without_faking_assignments(self):
        from masar.reporting import table_rows
        result=solve(SNAPSHOT,seconds=1,optimize=False)
        rows=table_rows(SNAPSHOT,result)
        self.assertFalse(result['has_solution'])
        self.assertEqual(result['assignments'],[])
        self.assertEqual(len(rows),result['required_sections_lower_bound'])
        totals=Counter()
        numbering={}
        for row in rows:
            totals[row['رقم المادة']]+=row['عدد الطلبة']
            self.assertNotIn('الحالة',row)
            self.assertIn('لا يمثل هذا جدولًا صالحًا',row['ملاحظات'])
            self.assertTrue(all(row[key]=='—' for key in ('من','إلى','الأيام','القاعة')))
            if isinstance(row['الحد الأقصى للطلبة'],int):
                self.assertLessEqual(row['عدد الطلبة'],row['الحد الأقصى للطلبة'])
            self.assertGreater(row['عدد الطلبة'],0)
            numbering.setdefault(row['رقم المادة'],[]).append(row['الشعبة'])
        expected=Counter()
        for section in SNAPSHOT['sections']:
            if section['status']=='scheduled':expected[section['course_code']]+=section['students']
        self.assertEqual(totals,expected)
        for numbers in numbering.values():self.assertEqual(numbers,list(range(1,len(numbers)+1)))

if __name__=='__main__':unittest.main()
