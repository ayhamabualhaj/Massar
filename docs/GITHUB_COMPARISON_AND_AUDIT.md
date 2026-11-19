> **Historical audit (16 November 2026).** It describes the earlier 2,300-student scenario, not the current five-major, 891-student scenario; see the [project overview](../README.md) for the current one.
>
> Subsequent correction: the 2,300-student scenario needs 14,996 physical student-hours/week but the modeled rooms/windows provide 14,940. The new seat-weighted certificate proves infeasibility before student expansion. The earlier room-hour-only capacity estimates below missed this necessary bound. Room and population assumptions remain estimates.

# Masar audit and GitHub comparison — 16 November 2026

The largest problem was the model of demand, not the choice of CP-SAT. The old
forecast deliberately preferred currently offered courses in the current semester
parity. It then used that biased forecast to assert room shortages. All 13 room
capacities are assumptions, and some mandatory laboratory requirements were
inferred only from where a course happened to be taught. The earlier statement
that the real schedule fits only 120 students is **not a university capacity
estimate** and must not be used to reduce the estimated population.

## Projects examined

| Project and primary source | Relevant design | Masar before this audit | Change made |
|---|---|---|---|
| [UniTime CPSolver](https://github.com/UniTime/cpsolver), [student scheduling manual](https://github.com/UniTime/unitime-doc/blob/main/manuals/student-scheduling.md), [SectionLimit.java](https://github.com/UniTime/cpsolver/blob/master/src/org/cpsolver/studentsct/constraint/SectionLimit.java) | Student course requests, valid section combinations, explicit enrollment limits, hard constraints and preferences | Every inferred batch had to remain together across all courses; no direct request import | Explicit request-bundle import; estimated batches can split while every member retains a complete conflict-free course bundle. Explicit intact groups remain intact. |
| [Google OR-Tools course scheduling model](https://github.com/google/or-tools/blob/stable/ortools/scheduling/course_scheduling.proto) | Separate students' requested courses, teachers and their restrictions, rooms and capacities, and result assignments/status | Admission projections and scheduling were tightly coupled; teacher constraints unavailable | Separate `masar/demand/requests.py`; optional instructor qualification, availability, weekly loads and conflict validation; clearer separate planning/preference statuses. |
| [Timefold school timetabling example](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/getting-started/hello-world/README.md), [constraint implementation](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/getting-started/hello-world/src/main/java/org/acme/schooltimetabling/solver/TimetableConstraintProvider.java) | Distinct hard room/teacher/student conflicts and soft preferences | Room and group constraints existed; teachers explicitly disabled | Teacher hard constraints added to both fixed scheduling and section planning, and independently checked. Preferences cannot compensate for hard violations. |

These are design comparisons, not claims that all three solve the same model.
Timefold's example assigns an existing lesson list; it does not infer admissions
or determine this university's enrollment. UniTime has substantially broader
operational functionality. No external implementation was copied and no new
solver dependency was added. CP-SAT remains suitable for Masar.

## Corrections and evidence

1. **Demand no longer depends on current offering parity.** Inferred plans balance
   credit loads and honor prerequisites, concurrency, elective limits and completed
   credit thresholds. They remain scenarios, not official recommended plans.
   Their cache fingerprint no longer depends on which courses appear in the
   current timetable. A regression removes an offered course and confirms that
   the inferred study plan does not move other courses to compensate.
2. **Estimated groups can split.** A regression with 60 students in three estimated
   batches of 20 and 30-seat rooms now opens exactly two sections. Previously it
   required three. The same explicit intact groups still require three. Another
   regression checks complete two-course schedules after splitting, and one checks
   use of smaller available rooms when a larger room is closed. Anonymous members
   with identical assignments are recombined into readable subgroups for export.
3. **Teacher support.** Enable `teachers_enabled`, provide `teachers` with stable
   IDs, optional `blackouts` and `max_weekly_minutes`, and provide qualified
   `teacher_ids` on each source section. Planning uses the union of qualified
   teachers within a demand pool; fixed scheduling respects each section's list.
   Shared events require a common qualified teacher. No real qualifications or
   workload limits are inferred from historical teacher names. The current
   forecast remains teacher-disabled until these inputs are supplied.
4. **Validation before infeasibility claims.** Alternative patterns must preserve
   weekly minutes and reference valid patterns before resource bounds run. Invalid
   semester labels are rejected instead of silently becoming second semester.
5. **Separate estimates and evidence.** `extra information/model_audit/` lists
   assumed capacities, missing course demand, unavailable planned courses, student
   coverage and a per-course/pool comparison against all 109 reference teaching
   sections. Unknown demand is explicitly unknown. Seat bounds do not constitute
   maximum unique student population: students register for multiple courses.
6. **Reproducible, isolated runs.** CLI options support alternative inputs, direct
   requests, fixed sections and separate output folders. Scenario runs with
   `--output` do not overwrite the active projection or its reports. Results record
   input hashes, runtime versions, constraints and time budget. Failed runs clear
   stale current CSV rows; forecast failures retain clearly marked capacity-only
   proposals as requested.

## Current scenario: before and after

The same first-semester intake estimates and room capacities are retained.

| Measure | Before | After |
|---|---:|---:|
| Estimated four-year population | 3,032 | 3,032 |
| Modeled timed course registrations | 16,762 | 7,702 |
| Courses with positive timed demand | 39 | 23 |
| Proposed input batches | 116 | 99 |
| Students represented in offered-course batches | 3,032 | 2,840 |
| Population without a modeled offered course this term | 0 | 192 |
| Capacity-only section lower bound | 446 | 209 |
| Minimum weekly lab teaching hours | 722 | 299 |
| Maximum modeled lab hours available | 288 | 288 |
| Minimum weekly teaching hours, all physical rooms | 1,151 | 539 |
| Maximum modeled hours, all physical rooms | 468 | 468 |
| Feasible complete modeled timetable | No | No |

The decrease is a **changed forecast**, not a measured scheduling speedup or a
verified demand correction. The two uncovered 96-student cohorts remain in the
population table. Their planned courses lack teaching templates this term. There
are 10,874 estimated student-course requests in unavailable planned courses and
18 offered legacy course codes with unknown demand. These gaps are now prominent
in the audit instead of being hidden by moving courses between semesters.

The 209 proposals in `timetable.csv` have no assigned rooms/times. Even the modeled
subset needs at least 299 laboratory hours against 288 available. Missing
registrations cannot be assumed schedulable. A valid university timetable still
requires verified capacities and equipment, official semester plans or actual
requests, resolution of legacy codes and missing offerings, and instructor data.

## Validation and limits

The original 51 tests passed before changes. The expanded suite tests the above
regressions, both teacher-enabled solver modes, preservation of complete course
bundles and populations, data-quality exports and ambiguous request rejection.
Run `python -m unittest discover -s tests -v` for the current test count/result.
Small fixtures demonstrate correctness; this is not an ITC benchmark comparison.

Splittable batches use anonymous individual members internally, which can grow
large for feasible high-enrollment inputs. Resource proofs run before expansion.
Model construction time counts against the search budget, but the build itself is
not interruptible. There is no promise of a solution within every requested time
limit. Secondary preference optimization holds selected sections, patterns and
memberships fixed; its optimum is not a global optimum over all minimum-section
solutions. Travel times, linked lecture/lab combinations, individualized elective
choices, graduation/withdrawal/repeat rates and an official curriculum-to-legacy
code mapping remain outside the present model.
