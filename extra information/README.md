# Extra information

| Folder | Contents |
|---|---|
| [student_numbers/](student_numbers/) | Course enrollment totals and new-student intake counts/expectations by semester |
| [student_groups/](student_groups/) | Inferred group memberships, group summaries, coverage gaps, JSON evidence, and the grouping method |
| [university_schedule/](university_schedule/) | Original university timetable and its saved comparison with a generated timetable |

Start with [student_expected_number_for_each_semester.csv](student_numbers/student_expected_number_for_each_semester.csv) for the 2023–2026 intake table (2026 aggregate figures supplied by the user; earlier years and the equal three-major split estimated), [four_year_student_summary.csv](student_numbers/four_year_student_summary.csv) for the four-cohort summary, or [student_group_summary.csv](student_groups/student_group_summary.csv) for the inferred timetable groups.

These datasets describe different things: new admissions per semester, registrations per course, and inferred co-enrollment groups. They must not be added together or treated as interchangeable.

`main.py` refreshes group reports in `student_groups/` after a successful solve. The intake table, course-count summary, and university references are separate saved datasets.

The active intake model also writes cohort counts, inferred semester plans, course demand, section lower bounds, and room-capacity diagnostics into `student_numbers/`. Group files distinguish proposed from scheduled memberships. On an infeasible intake run, the current CSV shows clearly marked capacity-only proposals without assigned times or rooms, rather than showing an obsolete schedule.

## model_audit

تقارير جودة البيانات، سعات القاعات وافتراضاتها، مقارنة أعداد الشعب المرجعية بالطلب المتوقع، والمواد المخططة التي لا توجد لها شعب معروضة. راجع أيضًا `docs/GITHUB_COMPARISON_AND_AUDIT.md`.

## external_courses

ملخص المواد العشر التي تدرّس خارج الكلية، شعبها المقترحة، وتقديرات القاعات الخارجية. تبقى تعارضات مواد الطلبة مفعلة، ولا تستهلك هذه المواد قاعات تقنية المعلومات. القاعات الخارجية في النموذج تقديرية وليست جردًا مؤكدًا.


Updated source checks are in `model_audit/historical_schedule_audit.json`, with the five overlapping section pairs and their provenance in `model_audit/historical_room_overlaps.csv`. These check the imported source, not actual student registrations. `model_audit/course_room_requirements.csv` distinguishes user-confirmed computer requirements from other unverified requirements. All previously computer-required courses retain lab eligibility.
