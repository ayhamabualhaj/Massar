# Positive demand for every IT course

The active policy offers all 111 IT catalog courses every calendar semester and
assigns each positive estimated enrollment. Original admissions remain 2,300
students in 20 major/year cohorts. Coverage paths were added to the original
three diversified paths: AI8, CIS5, CS5, CYBER12 and SE6. The result is 144 learning
profiles and 162 scheduling batches. Counts are distributed with equal weights
and exact integer remainders; no student is counted twice in the population.

Every complete path preserves all compulsory courses, strict prerequisites,
permitted concurrency, completed-credit thresholds, 132 degree credits and
exactly nine major-elective credits. Courses already completed by a profile are
not registered again. Counts for each course are the sum of profile headcounts
that actually request it; no arbitrary minimum-enrollment floor is added.

Calendar semester does not determine academic eligibility. Some coverage profiles
are estimated one academic step ahead during first semester, or one step behind
during second semester. Their completed-course histories and current bundles are
validated independently. This variation and the equal path shares are explicit
modeling assumptions, not observations of summer study, transfers, repeats or
actual transcripts. The first three paths retain varied current bundles within
each admission cohort; additional paths ensure positive demand for every course.

`../student_numbers/student_learning_profiles.csv` shows the original cohort,
profile, headcount, current courses, assumed completed courses, calendar stage
and academic-progress offset. `study_path_plans.csv` and
`major_elective_selections.csv` show complete path assignments and nine elective
credits per alternative path. Do not sum elective credits across alternative
paths as one student's load.

The positive-demand scenario still exceeds available resources: 29,122 physical
student-hours/week against 26,640 available, and 607 minimum room-hours against
468 available. Current `timetable.csv` has all 111 courses in 261 explicitly
unscheduled proposal rows. No room or time assignments are claimed. The current
teaching hours and 80–100-seat classrooms / 40-seat labs remain unchanged.
