> **Current settings:** Nine university-listed computer labs plus LAB_DUAL are configured. `settings/student/major_students.csv` now sets 891 estimated students across five majors for the next intake-based CP-SAT run. The saved `masar_v2_output/` timetable is from the earlier 1,600-student run; rerun `main.py` to apply the new major totals. Older scenario descriptions below are historical.

# Masar

College timetable optimizer. Requires Python 3.11 or newer.

## Run in PyCharm

Install dependencies in the project terminal:

```bash
python -m pip install -r requirements.txt
```

Right-click `main.py` and choose **Run**. Results are saved in `masar_v2_output/` as JSON and CSV.
The default scheduling budget is 600 seconds (10 minutes); override it with `--seconds`.

The default solver sums the current `students` values for each course and opens
the minimum feasible number of sections. Room capacity limits the enrollment of
each in-person section. Online sections have no physical capacity limit. Sections
with different delivery modes, room requirements, or weekly teaching hours remain
separate; patterns with the same weekly teaching hours are alternatives. Existing
student groups are reassigned to the opened sections. Explicit groups stay intact;
estimated intake batches are splittable while preserving each member's complete course bundle.
Only required sections are opened, including additional sections when demand
cannot fit the original section list.

Section count is minimized before optimizing timetable preferences. `result.json`
records whether the minimum count was proven, the projected enrollment and opened
section count for each course, and the chosen sections and student-group assignments.
If a time limit prevents proving the minimum, the result explicitly reports this.
The original section templates are preserved in `data/masar_section_templates.json`. In intake mode, each run regenerates the derived `data/masar_data_v2.json` snapshot from the intake table; it never scales the previous projection again.

`timetable.csv` contains only opened sections, with allocated enrollment in
`عدد الطلبة`. Entries with `no_meeting_days` and unknown enrollment are excluded
from section planning and listed in `section_plan.unplanned_section_ids` instead.
The reference contains 46 non-meeting entries. Intake mode reports their course demand separately; they never consume timed room sections.
To schedule a fixed section list (including explicit `shared_classes`), call
`solve(data, plan_sections=False)`.

## Files

- `main.py`: application entry point.
- `settings/`: editable major intake counts, classroom/lab capacities, and course on/off switches; see [settings instructions](settings/README.md). These CSV values are loaded on each normal intake-based run. The older root `settings.yaml` has been replaced.
- `masar/`: validation, scheduling constraints, solver, result checker, and reporting.
- `data/masar_data_v2.json`: editable scheduling input.
- `docs/`: Arabic and English reference PDFs and the original sample HTML timetable.
- `tests/`: fixed-section scheduling tests and enrollment-based section planning tests.
- `extra information/`: organized folders for student numbers, inferred student groups, and university schedule references.
- `masar_v2_output/`: generated timetable CSV and detailed solver results.

Run the tests from the project root:

```bash
python -m unittest discover -s tests -v
```

The optimizer checks room and configured student-group conflicts. Optional teacher
qualification, availability, conflicts and workload constraints are supported;
the current scenario does not yet have verified teacher mappings and keeps them disabled.
Room capacities and student groups remain estimates. The HTML in
`docs/` is a saved experimental output, not the original university schedule.

## Degree-plan student groups

The earlier course-budget heuristic remains available when `group_generation.enabled`
is true and intake projection is disabled. The active intake pipeline uses the same
degree-plan records to infer cohort study plans instead. It uses program-specific
prerequisite levels, permitted concurrency, enrollment budgets, elective limits,
and the offered time patterns. These groups are inferred co-enrollment scenarios;
actual major shares and passed courses are unknown. Exact code mismatches and
unpaired enrollment remain explicitly unmodeled.

Group CSV and JSON reports in `extra information/student_groups/` are refreshed
with chosen sections after success, or explicitly proposed/unscheduled memberships
after an infeasible intake projection. See
`extra information/student_groups/student_groups_method.md` for the assumptions
and limitations. Student counts and intake estimates are in
`extra information/student_numbers/`; original university schedule references are
in `extra information/university_schedule/`. Intake counts describe new admissions,
not course registrations or the total number of active students.

## Four-year intake projection (active)

`main.py` reads the individual-major rows for 2023–2026 from
`extra information/student_numbers/student_expected_number_for_each_semester.csv`.
It models 2,300 estimated students in 20 cohorts, assuming normal progression
and full retention, and excludes unknown second-semester admissions. The three CS/AI/Cybersecurity majors retain equal estimated shares.

Each cohort takes only its inferred current-semester courses; the model does not
assign every student to every course. Inferred eight-semester plans honor prerequisites,
concurrency, credit thresholds and elective limits, and are cached and independently
validated. The original section templates supply room requirements and allowed patterns.
Unmatched legacy codes and unavailable courses are explicitly reported.

The active scenario now uses **2,300 students**, as requested: 575 per annual
cohort (2023–2026). Each annual cohort has SE 244, CS 73, AI 73, Cybersecurity 73,
and CIS 112. These are scaled scenario estimates preserving the earlier major
proportions approximately. The original 3,032-student scenario is archived in
`masar_v2_output/archive/before_2300_students/` and remains the overload regression
fixture. Current solver status, section count and coverage are in `result.json`.
Forecast failures export explicitly unscheduled capacity proposals in `timetable.csv`.

See `extra information/student_groups/student_groups_method.md` and
`extra information/student_numbers/room_capacity_shortfalls.csv`.


## Audit and realistic input

See [the GitHub comparison and audit](docs/GITHUB_COMPARISON_AND_AUDIT.md).
`extra information/model_audit/` contains the actual-versus-projected section
comparison, assumed room capacity inventory and missing-data reports.
The inferred semester plan now balances credits independently of current offerings;
it must not be treated as actual registration data. The old 120-student conclusion
was conditional on assumptions and is not a university capacity estimate.

For a separate scenario, without replacing the current forecast or output:

```bash
python main.py --output /tmp/masar-scenario --seconds 30
python main.py --input data/masar_section_templates.json --fixed-sections --output /tmp/masar-reference
```

To bypass admission inference, supply a JSON list of course request bundles:

```json
[
  {"id": "anonymous-request-1", "students": 1, "course_codes": ["0612112"]}
]
```

```bash
python main.py --requests requests.json --output /tmp/masar-requests
```

Use anonymous IDs. A bundle may represent several students taking exactly the same
courses. For a course with multiple delivery/equipment pools, explicitly select
`"pool_source_ids": {"0612112": "<a matching reference section ID>"}`; ambiguous
requests and missing courses are rejected, never silently dropped. The request
file replaces synthetic enrollment totals; it does not add to them. The caller
must ensure bundles represent disjoint students.

Teacher-enabled inputs require `"teachers_enabled": true`, a `teachers` list
such as `[{"id":"T1","name_ar":"Teacher 1","blackouts":[],"max_weekly_minutes":720}]`,
and `"teacher_ids":["T1"]` on every teaching section. These are example values,
not estimates of the university's staffing. CSV includes the assigned teacher
when enabled; otherwise it explicitly says unassigned.

Section search defaults to four workers (`--workers` accepts 1, 2, 4 or 8). The default sampled process-memory guard is 16,384 MB (`--memory-mb`, 16 GB); it stops search if observed RSS reaches the budget. It is not a hard operating-system allocation limit. A stopped search may remain UNKNOWN.

The revised seat-weighted check proves the current 2,300-student scenario requires 14,996 physical student-hours/week against 14,940 available, a 56 student-hour deficit. Earlier room-hour-only estimates (including 2,604 students) were insufficient and must not be used as feasibility guarantees. More RAM cannot remove this shortage.


## Requested larger-room scenario

Classrooms T101/T102/T104/T105 now have 80 seats, T103 has 100, and all eight
computer labs have 40 seats, per the user's request. These are scenario capacities,
not verified physical measurements. The population remains 2,300 and teaching hours
are unchanged. The previous capacity input/output is archived under
`masar_v2_output/archive/before_capacity_increase/`.

Large scenarios with splittable groups and no teacher constraints now use
`masar/slot_planning.py`. It chooses actual room/time placements directly and
variable-size student schedule routes, then splits routes into section assignments.
Independent validation checks every resulting group, capacity, meeting and enrollment.
A bounded-route search failure reports UNKNOWN; it never proves full infeasibility.
A feasible result reports whether a global minimum is proven. Extra section count
may still be reduced when the global lower bound has not been met. The earlier
student-hour shortage describes the archived smaller-room scenario.


## Active IT-only course scope

The degree-plan tables are the authoritative course catalog. Scheduling includes
only `كلية إجباري`, `تخصص إجباري`, and selected `تخصص اختياري` courses, using each
program's category for each code. University compulsory/elective courses are
excluded from timetable demand. A representative student selects exactly nine
major-elective credits over the entire degree; unselected options do not generate
sections. The complete eight-semester plan retains university credits internally
only to preserve progression and 90-completed-credit prerequisites; IT scheduling
reports omit university courses.

`extra information/student_numbers/it_course_catalog.csv` lists the IT catalog,
including compulsory courses with no source meeting information.
`major_elective_selections.csv` lists selected major electives, totaling nine
credits per program across the degree. The previous schedule supplies meeting
patterns only. Missing meeting information is reported; no aliases or new teaching
patterns are invented automatically. The previous scenario is archived under
`masar_v2_output/archive/before_it_course_scope/`.


## All needed IT courses: approved missing-meeting estimates

The active policy `estimated_meeting_courses` lists 34 degree-plan courses for
which the user approved estimated meetings: 3-credit lectures use 3x60 or 2x90,
2-credit lectures use 2x60, and 1-credit labs meet once for 60 minutes. A single
weekly lab may use any existing teaching day within the current windows. These
are estimates, including the requested project/training course placeholders, not
verified official contact hours. The source templates remain unchanged.

All 56 needed IT courses now have templates; all 2,300 estimated students are
represented, with no missing current-semester IT course demand. University
courses remain excluded and major electives remain nine credits per full degree.
The user explicitly kept the existing teaching hours. The resulting full-demand
scenario is proven infeasible: 29,740 physical student-hours are required against
26,640 available, and at least 472 room-hours against 468 available. The 192 rows
in the current `timetable.csv` cover all 56 courses as **unscheduled proposals**.
No room/time assignments are claimed. The earlier valid partial timetable is in
`masar_v2_output/archive/before_missing_course_patterns/masar_v2_output/timetable.csv`.
See `estimated_meeting_patterns.csv` and `room_capacity_shortfalls.csv` under
`extra information/student_numbers/` for the assumptions and proofs.


## Diverse study paths (active)

Each major/year is now divided across three prerequisite-valid complete degree
paths rather than assigning one identical course bundle to its whole cohort.
The scenario has 20 admission cohorts, 60 learning profiles and 82 scheduling
batches, conserving all 2,300 students. Shares are equal estimates with integer
remainders. Every path retains 132 degree credits and nine major-elective credits;
completed course histories, concurrency and minimum completed credits are checked.
The cached paths are independent of offered room capacity and intake changes.

See `extra information/student_numbers/student_learning_profiles.csv`,
`study_path_plans.csv` and `major_elective_selections.csv`. The group files include
path IDs and original cohort IDs. The same approved meeting-estimation policy was
applied to 13 additionally needed courses, so every current request is represented.

The resulting 81-course demand still exceeds fixed resources: 29,401 physical
student-hours/week against 26,640 available, and 534 minimum room-hours against
468 available. The current CSV has 219 unscheduled proposals; no students or
course requests were silently dropped to obtain a timetable. Earlier figures in
this README refer to archived scenarios.


## Every IT course has positive demand (active policy)

The user requires all 111 IT catalog courses to be available every calendar
semester and to have strictly positive estimated enrollment. The policy
`require_positive_course_demand` adds complete prerequisite-valid coverage paths
and distributes the same 2,300 students across them. It does not add an arbitrary
minimum count or duplicate students. Each complete path still has 132 degree
credits and exactly nine major-elective credits.

Academic progression is separate from calendar semester. Coverage profiles can
be one academic step ahead in the first semester or one step behind in the
second semester, with their own prerequisite-complete histories. This is an
explicit scenario assumption, not verified accelerated progression or repeat
rates. It prevents even-numbered plan terms from making courses unavailable in
the first calendar semester. Shares between paths remain equal estimates.

Current paths: AI8, CIS5, CS5, Cyber12, SE6, giving 144 learning profiles and
162 scheduling batches. Every one of the 111 IT courses has positive student
assignments. University courses remain excluded. All course demand is listed in
`timetable.csv`; the current resource settings still prove infeasible (29,122
student-hours needed, 26,640 available; minimum 607 room-hours, 468 available).
The 261 CSV rows are explicitly unscheduled proposals, without assigned times.
Earlier zero-demand and 81-course results refer to archived scenarios.


## Courses taught outside IT

The ten explicitly identified courses (0202100, 0302106, 0302131, 0302241,
0303106, 0511231, 0511233, 0511234, 0511336, 0512443) now use external room types.
They retain positive course enrollment, physical attendance and student-conflict
constraints. IT courses cannot use external rooms and external courses cannot
use IT rooms. The main CSV has a `مكان التدريس` column identifying the location.

Actual external inventory is unknown. Four finite scenario placeholders are used:
one languages classroom, one science classroom, one engineering classroom (100
seats each), and one engineering lab (40 seats). These are explicitly unverified
estimates, with existing teaching windows and no assumed real room assignment.
They are not unlimited resources or online classes. Replace `external_courses.rooms`
with verified inventory when available.

`extra information/external_courses/` contains external_course_summary.csv,
external_room_estimates.csv and external_classes.csv. All 111 courses and all
2,300 estimated students remain represented. The current scenario still proves
an IT-only workload shortage: at least 541 room-hours/week versus 468 available.
Current section rows remain explicitly unscheduled. The pre-separation scenario
is archived in `masar_v2_output/archive/before_external_courses/`.


## Room-free field training and graduation projects

The ten field-training/graduation-project courses now retain positive student
enrollments and their degree/prerequisite credits without a fixed weekly room or
meeting reservation. They use `status=no_meeting_days` and
`room_free_activity=true`; they are not reclassified as online lectures.
`room_free_course_codes` overrides estimated meeting templates for those courses.
They remain in `timetable.csv` as `نشاط دون قاعة`, with their actual estimated
headcounts and `لا يتطلب قاعة`. Student learning profiles retain the activity
registrations; timed conflict groups contain only courses with fixed meetings.

All 111 courses remain represented: 101 timed courses and 10 room-free activities.
The CSV has 251 unscheduled teaching-section proposals plus 10 activity rows.
The solver still proves an IT workload shortage: 511 minimum room-hours/week
versus 468 available. Room capacities, outside-course treatment, study paths,
nine-credit major electives and the 2,300-student estimate are unchanged.


## Confirmed computer requirements and registration-import fixes (2026-11-16)

The user confirmed the computer requirements. Existing `computers` sections remain restricted to computer labs, including Programming 2. Their source records now carry `room_requirement_status: user_confirmed`; confirmation does not verify room capacities or resolve inconsistent historical room assignments. No population, teaching hours, lab capacities, study paths, or course enrollments were changed.

Each run now saves its actual solver input to `masar_v2_output/input_snapshot.json` (or the selected output directory). The input is evidence for that run; the normal intake pipeline still regenerates forecasts when enabled.

Direct `--requests` runs now use the full configured teaching catalog, including approved missing-course patterns, external rooms, and room-free training/projects. They preserve alternative meeting patterns. A bundle may contain only room-free activities if other bundles include timed courses; an entirely room-free input is explicitly unsupported. Failed request runs export labeled capacity proposals with counts instead of an empty CSV. Compact-search memory stops identify the memory limit in their diagnostics.

`extra information/model_audit/historical_schedule_audit.json` checks imported source room/time placements without synthetic enrollment, student groups, or instructor constraints. `historical_room_overlaps.csv` lists five overlapping section pairs, with course names, days and original source references. The source also has room `0` for `0613442_2` and classroom placements inconsistent with the preserved computer requirements for `0615334_1` and `0615344_1`. These records need source clarification; the code does not silently merge courses or relax equipment rules.

`course_room_requirements.csv` records current requirements and evidence. The active 2,300-student scenario still requires at least 511 IT room-hours against 468 available, so its timed rows remain unscheduled proposals. Ten projects/training activities retain their student counts without room/time reservations.


## Student capacity-fit run (2026-11-16)

At the user's request, the estimated student population was reduced proportionally across the same four intake years and five majors. The active total is 1,600 students. This run scheduled all 101 timed courses in 197 teaching sections and retained ten room-free activities. `masar_v2_output/timetable.csv` has 207 rows, with assigned times and rooms for every timed row and student counts for every course. Room capacities, permitted hours, and the confirmed computer requirements remain enforced.

The eight-worker compact search uses one complete timetable route per original estimated batch, with room seating still splittable. Its section lower bounds are now supplied directly to CP-SAT to strengthen search. The route count is saved in `enrollment_generation.solver_route_limit` and the worker count in `enrollment_generation.solver_workers`; `--routes` and `--workers` override them. Search is still bounded by 600 seconds and the 16 GB sampled memory guard by default.

`extra information/student_numbers/student_capacity_trials.json` records the trials. No timetable was found for the higher tested populations within their search limits; that is not a proof that those populations are impossible. The selected result is FEASIBLE, with 197 sections against a capacity-only lower bound of 188. Neither maximum population nor minimum section count is established. Four external rooms and the course enrollments remain scenario estimates, and instructors are not modeled.

The previous 2,300-student inputs and outputs are preserved in `masar_v2_output/archive/before_student_capacity_fit/`. Historical regression fixtures now read their archived intake table; active-population checks read the current intake source. The Arabic guide and forecast reports reflect the selected result.


## Section minimization with unchanged enrollment (2026-11-16)

The active timetable now has 191 scheduled teaching sections, reduced from 197, plus the same ten room-free activities. All 1,600 students, all 111 courses, every course enrollment count, rooms, capacities, computer requirements, and permitted teaching times were retained. The independently checked schedule has zero hard-constraint violations. The mathematical section lower bound is 188; the global minimum remains unproven.

Compact search now accepts a checked incumbent through `hints`. It reconstructs room/time placements and complete student routes, validates enrollments and allowed meeting options, and caps the search at the incumbent section count. `main.py` automatically offers the saved timetable as a hint only when its input hash matches. If a compatible search stops before finding a new incumbent, the validated starting timetable is retained. Invalid room assignments and stale enrollment hints are rejected. The selected run used eight workers, a 600-second budget and approximately 2.8 GB observed process memory, within the 16 GB guard.

The original 197-section timetable is archived under `masar_v2_output/archive/before_section_minimization/`. `extra information/student_numbers/section_optimization.csv` compares sections per course before and after; `section_optimization.json` records the search results and remaining gap. All 115 tests pass, including restart, stale-hint rejection, route expansion, and memory-stop retention checks.


## 188-section target achieved (2026-11-16)

The current timetable is OPTIMAL for section count: **188 teaching sections for 1,600 students**, plus ten room-free activities. All 111 courses and every course's enrollment total are preserved. The previous 191-section timetable is archived under `masar_v2_output/archive/before_188_section_search/`. The active CSV has 198 rows; every timed section has an assigned room and time, and independent checking found zero hard violations. `optimality_certificate` in `result.json` records equality between the 188-section capacity lower bound and the validated 188-section timetable.

The default search budget in `main.py` is now **1,800 seconds (30 minutes)**. The compact model has valid large-room capacity covers that strengthen propagation while still permitting more small-room sections when a larger room is unavailable. The successful alternative search assigned the same students to minimum-capacity sections in a coherent order, split estimated batches as permitted, and then scheduled all sections jointly. It preserved complete course bundles; it did not reduce demand or change room capacities or teaching windows. The successful attempt is saved in `masar_v2_output/section_optimization/fixed_membership_188/`, including its search source.

The saved input uses up to four timetable routes per estimated batch so `main.py` can reuse the optimal incumbent. Restart tests verify that a matching saved 188-section timetable survives a short search. Instructors remain unmodeled and external rooms remain scenario estimates. The section minimum is proved for these modeled assumptions. Other searches were stopped once the bound was attained. All 116 regression tests pass.


## Timetable columns and eligible majors

The timetable CSV omits `الحالة` (Status). Internal section status and solver validation remain in the model and `result.json`. The existing `الفئة` column now lists eligible majors by their full degree-plan names, including programs where the course is a major elective. It describes course eligibility, not the majors currently enrolled in a particular section. Courses eligible for all five majors display `all`; other shared courses list their eligible majors; courses with no curriculum evidence are labeled `غير محدد في الخطط الدراسية` rather than claiming they are for everyone. The same export rules apply to external-class and capacity-proposal rows. The active 188-section schedule is unchanged. All 117 tests pass.


## University lab-capacity update (2026-11-17)

The user supplied university device counts and confirmed that numbered labs 1–7 map to LAB1–LAB7. Their modeled capacities are LAB1=38, LAB2=38, LAB3=28, LAB4=28, LAB5=27, LAB6=28, and LAB7=21, assuming one scheduled student per usable device. IoT (LAB_IOT, 13 computers) and GIZ (LAB_GIZ, 20 computers) are also active, separate labs. LAB_DUAL remains a separate lab with a user-requested capacity of 30; this capacity is not a verified university device count. `data/university_lab_inventory.csv` records the nine university-listed labs. Lab supervisors and room area are inventory details, not instructor assignments or scheduling capacities. The saved output includes the IoT/GIZ and LAB_DUAL changes, but predates the editable major-student totals.

The previous 188-section schedule is invalid under the new capacities: 69 of its assigned numbered-lab rows exceeded the university device counts. A 600-second search with four routes per estimated group and a second 600-second search with eight routes both returned UNKNOWN. Neither found a validated schedule or proved infeasibility. The current CSV contains unassigned capacity proposals; see `masar_v2_output/result.json` for search diagnostics and `extra information/model_audit/room_capacity_inventory.csv` for room data provenance.
