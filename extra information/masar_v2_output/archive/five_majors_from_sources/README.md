# Five-major timetable, 2026 first semester

The timetable is in `timetable.csv`; `by_major/` contains five views of the same scheduled sections. A shared course appears in each eligible major view.

Source plans: `course_requirements/sources/plan-01.jpeg` through `plan-09.jpeg`. The curriculum files in `data/` were rebuilt from the previous manual transcription preserved in Git, checked against the nine source pages. The 274 college and major records are in `data/five_majors_curriculum.json`; full degree-plan records used to infer academic progression are in `data/five_majors_degree_plans.json`. University-required and university-elective courses are excluded from every timetable output.

The run uses the current 85 enabled course switches and 891 estimated students across five majors. It has 123 timed sections plus 27 room-free project and field-training rows, covers 85 course codes, and has zero checked hard-constraint violations. Its status is FEASIBLE; the 121-section lower bound has not been reached or proved optimal. The time budget was 240 seconds. Enrollment, rooms outside IT, contact patterns, and academic progression remain scenario estimates rather than verified university registrations.
