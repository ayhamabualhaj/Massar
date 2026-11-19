# Editable scheduling settings

Edit these CSV files in PyCharm or a spreadsheet and save them before **you** run `main.py`:

- `student/students.csv`: admission-year cohort weights by major. `SE` = Software Engineering, `CS` = Computer Science, `AI` = Data Science and AI, `CYBER` = Cybersecurity, `CIS` = Computer Information Systems. Semester `1` is the first semester and `2` is the second. An empty second-semester cell means the cohort is unknown and remains excluded; enter `0` for a known zero. These values determine how each major total is distributed across known cohorts during a normal intake-based run.
- `student/major_students.csv`: editable current student total for each of the five majors. Change the `students` number and save; the next normal `main.py` run divides it across the known cohorts in `students.csv`, projects course demand, and passes that demand to CP-SAT. The initial 190/188/171/150/192 values total 891 and are rough course-capacity estimates, not registrations. Every major must appear exactly once. Totals take precedence over the absolute counts in `students.csv`; its counts act as relative cohort weights.
- `rooms.csv`: seat or usable-computer capacity for each listed classroom and lab. Edit the `capacity` column. `room_name` and `room_type` help identify each room; changing them does not change the room model. Keep the room IDs and rows in place.
- `courses/All Courses/courses.csv`: the single editable list of 111 timetable courses. Set `enabled` to `1` to offer a course or `0` to exclude it from the next intake-based timetable. Each switch applies to the course code across all majors. The course roles come from `course_requirements/five_majors_curriculum.json`.

The other course folders are category lists for browsing. Edit the `enabled` column in `All Courses/courses.csv`; the category lists have no separate switches.

The course folders are `Faculty Requirements`, `University Requirements`, `University Elective Courses`, `Faculty-College Elective Courses`, and `Major Elective Courses`. The source catalog has no faculty/college elective type, and the current timetable has no university courses, so those three CSVs currently contain headers only. Source types `كلية إجباري` and `تخصص إجباري` both appear under `Faculty Requirements`; `تخصص اختياري` appears under `Major Elective Courses` unless the same course is required by another major. Keep the course codes unique across the folders.

To find every timetable course listed as `تخصص اختياري` for at least one major, open `courses/Major Elective Courses/all_elective_roles.csv`. It lists all 49 such course codes and the majors where each is elective. Edit their switches in `All Courses/courses.csv`.

The program validates these files, applies the room capacities to its scheduling input, and uses the major totals and cohort weights when projecting course demand. It recalculates the displayed semester totals. Explicit `--requests` runs use their supplied registrations instead of these major totals. The historical source CSV under `extra information/student_numbers/` is kept as reference. To add or remove rooms or courses, update their full model definitions; these CSV files only edit counts for existing records.

Turning off a course removes its projected sections from the next normal intake-based run. It does not erase the course from the degree plan: prerequisites and student progression still use the full curriculum. A section-list JSON supplied with `--input` uses its own room inventory and capacities. Intake forecasts use the project room settings. The course switches do not filter a `--fixed-sections` run, which schedules the section list explicitly supplied as input.

Saving a CSV does not update the existing timetable. The next run you start will use the new values and write its effective input to `extra information/masar_v2_output/input_snapshot.json`.
