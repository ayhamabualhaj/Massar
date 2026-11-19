import unittest

from masar.demand.enrollment import with_intake_enrollments
from test_planning import fixture


class FreshmanEnrollmentTests(unittest.TestCase):
    def project(self, semester, university_courses=2):
        # The fifth course requires the four introductory courses. This makes
        # the second semester's load independently distinguishable from the first.
        intro_university = [f'U{i+1}' for i in range(university_courses)]
        intro_faculty = [f'C{i+1}' for i in range(4 - university_courses)]
        courses = intro_university + intro_faculty + ['NEXT']
        records = [
            dict(program_id='CS', course_code=code, course_name=code, credit_hours=3,
                 category='جامعة إجباري' if code.startswith('U') else 'كلية إجباري',
                 requirements=[dict(course_code=c, concurrent_allowed=False)
                               for c in courses[:4]] if code == 'NEXT' else [])
            for code in courses
        ]
        reference = fixture()
        template = reference['sections'][0]
        reference['sections'] = [dict(template, id=c, course_code=c) for c in intro_faculty + ['NEXT']]

        def intake(year, term, students):
            return {'نوع الصف': 'تخصص مستقل', 'السنة المرجعية': str(year),
                    'الفصل': term, 'التخصص أو مجموعة التخصصات': 'CS',
                    'عدد الطلبة الجدد': str(students)}
        if semester == 1:
            intakes = [intake(2026, 'الأول', 20), intake(2025, 'الثاني', 10)]
        else:
            intakes = [intake(2026, 'الثاني', 20), intake(2026, 'الأول', 10)]
        return with_intake_enrollments(reference, records, intakes, policy={
            'current_semester': semester, 'program_names': {'CS': 'CS'},
            'scheduling_categories': ['كلية إجباري'],
        })

    def test_fall_and_spring_entrants(self):
        for semester in (1, 2):
            with self.subTest(semester=semester):
                data = self.project(semester)
                cohorts = {c['calendar_study_semester']: c for c in data['enrollment_projection']['cohorts']}
                freshman = cohorts[1]
                self.assertEqual(freshman['intake_semester'], semester)
                self.assertEqual(freshman['total_credit_hours'], 12)
                self.assertEqual(freshman['university_credit_hours'], 6)
                self.assertEqual(freshman['planned_courses'], ['C1', 'C2'])
                self.assertEqual(freshman['assumed_completed_course_codes'], [])
                self.assertEqual(cohorts[2]['planned_courses'], ['NEXT'])
                self.assertEqual(cohorts[2]['total_credit_hours'], 3)
                self.assertEqual({s['course_code']: s['students'] for s in data['sections']},
                                 {'C1': 20, 'C2': 20, 'NEXT': 10})

    def test_nine_university_credits_leave_three_faculty_credits(self):
        data = self.project(semester=2, university_courses=3)
        freshman = next(c for c in data['enrollment_projection']['cohorts']
                        if c['calendar_study_semester'] == 1)
        self.assertEqual(freshman['total_credit_hours'], 12)
        self.assertEqual(freshman['university_credit_hours'], 9)
        self.assertEqual(freshman['planned_credit_hours'], 3)
