# Masar

> **Current output:** `masar_v2_output/timetable.csv` is the five-major, 891-student scenario from the nine source plan images. It uses the current course switches and excludes university-required and university-elective courses. The latest validated result has 142 timed sections (capacity lower bound 111; minimum not proven) and 10 room-free project/training courses, with 0 hard-rule violations. See `extra information/masar_v2_output/result.json` for exact figures. Older scenario descriptions are historical.

College timetable optimizer. Requires Python 3.11 or newer.

## Follow a timetable run

Start in [the command-line workflow](masar/cli.py). Its `main()` connects these three steps.

| Step | Start reading here | What happens |
| --- | --- | --- |
| 1. Prepare demand | [Scenario preparation](masar/demand/scenario.py) | Read room settings and course switches. Use intake estimates, supplied course requests, or an existing section list. |
| 2. Build the timetable | [Solver entry point](masar/scheduling/solver.py) | Choose fixed-section scheduling or section planning, assign rooms and times, and check the solution. |
| 3. Write results | [Output writer](masar/reports/output.py) | Save the input snapshot, timetable, result JSON, and audit reports. |

For a concrete example, look up Discrete Mathematics (`0612102`) in the [CS degree plan](course_requirements/majors/CS.json) and the [saved timetable](masar_v2_output/timetable.csv). The degree plan records the requirement. The timetable shows how projected students fit into sections, rooms, and meeting times.

## Run in PyCharm

Install dependencies in the project terminal:

```bash
python -m pip install -r requirements.txt
```

Right-click `main.py` and choose **Run**. Each run is saved in its own folder under
`extra information/masar_v2_output/runs/`. If its timetable passes independent validation, it is
published to `masar_v2_output/timetable.csv`. Its supporting files and the
reports in `extra information/` are replaced together. Otherwise the active
timetable is left unchanged and the program exits with status 2. See
[the output README](<extra information/masar_v2_output/README.md>).
The default scheduling budget is 240 seconds (4 minutes). `--seconds` may be set
up to 285 seconds, keeping the CP-SAT search below five minutes.

The default solver sums the current `students` values for each course and opens
the minimum feasible number of sections. Room capacity limits the enrollment of
each in-person section. Online sections have no physical capacity limit. Sections
with different delivery modes, room requirements, or weekly teaching hours remain
separate; patterns with the same weekly teaching hours are alternatives. Existing
student groups are reassigned to the opened sections. Explicit groups stay intact;
estimated intake batches are splittable while preserving each member's complete course bundle.
Only required sections are opened, including additional sections when demand
cannot fit the original section list.

Section count is minimized first. The chosen sections are then re-timed to reduce
student idle gaps, late meetings and shifts from the reference times (about a quarter
of the time budget; skip with `--no-optimize`). This runs whether or not the minimum
section count was proven, and `result.json` reports `preference_score_before` and
`preference_score_after`. `result.json`
records whether the minimum count was proven, the projected enrollment and opened
section count for each course, and the chosen sections and student-group assignments.
If a time limit prevents proving the minimum, the result explicitly reports this.
The original section templates are preserved in `data/masar_section_templates.json`. In intake mode, each run regenerates the derived `data/masar_data_v2.json` snapshot from the intake table; it never scales the previous projection again.

`timetable.csv` contains only opened sections, with allocated enrollment in
`عدد الطلبة`. Entries with `no_meeting_days` and unknown enrollment are excluded
from section planning and listed in `section_plan.unplanned_section_ids` instead.
The reference contains 46 non-meeting entries. Intake mode reports their course demand separately; they never consume timed room sections.
Graduation project demand is divided into groups of five students. When a final group
would have fewer than five, those students are assigned to existing project groups,
which may then have six students. A project enrollment that cannot be divided into
groups of five or six is rejected rather than creating an undersized group. Field
training remains one room-free activity per course.
To schedule a fixed section list (including explicit `shared_classes`), call
`solve(data, plan_sections=False)`.

## Files

- `main.py`: application entry point.
- `course_requirements/`: five major course lists, combined curriculum, full degree-plan context, and nine source photographs.
- `settings/`: editable major intake counts, classroom/lab capacities, and course on/off switches; see [settings instructions](settings/README.md). These CSV values are loaded on each normal intake-based run. The older root `settings.yaml` has been replaced.
- `masar/demand/`, `masar/scheduling/`, and `masar/reports/` contain the implementation for the three steps above. Shared input checks are in `masar/validation.py` and settings readers are in `masar/settings.py`.
- `data/masar_data_v2.json`: editable scheduling input.
- `docs/`: Arabic and English reference PDFs and the original sample HTML timetable.
- `tests/`: fixed-section scheduling tests and enrollment-based section planning tests.
- `extra information/`: organized folders for student numbers, inferred student groups, and university schedule references.
- `masar_v2_output/`: the published timetable CSV. Run details and archives live in `extra information/masar_v2_output/`.

Run the tests from the project root:

```bash
python -m unittest discover -s tests -v
```

The optimizer checks room and configured student-group conflicts. Optional teacher
qualification, availability, conflicts and workload constraints are supported;
the current scenario does not yet have verified teacher mappings and keeps them disabled.
Room capacities and student groups remain estimates. The HTML in
`docs/` is a saved experimental output, not the original university schedule.

For course-request examples, modeling assumptions, and earlier optimization runs, see the [model and scenario notes](docs/SCENARIO_NOTES.md).
