# Course requirements

- `sources/`: nine photographed 2026 degree-plan pages for the five majors.
- `majors/`: one non-university course list per major (`AI`, `CS`, `CYBER`, `CIS`, `SE`).
- `five_majors_curriculum.json`: combined college-required, major-required, and major-elective records (274 program/course records, 111 distinct course codes).
- `five_majors_degree_plans.json`: full degree-plan context used to infer academic progression. It includes university courses, but the scheduler excludes `جامعة إجباري` and `جامعة اختياري` from the timetable.

The structured records come from the project's earlier manual transcription, checked against the source photographs. They are not an official digital registration feed. The active course switches are in `settings/courses/All Courses/courses.csv`.
