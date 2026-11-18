# Current timetable output

- `timetable.csv`: active five-major timetable. University-required and university-elective courses are excluded.
- `by_major/`: five views of the active timetable; shared courses appear in each eligible major's file.
- `result.json`: solver status, validation, and section details.
- `input_snapshot.json`: the exact scheduling input associated with `result.json`.
- `archive/`: older scenarios and experiments, not the current timetable.

The active curriculum is in `course_requirements/`. The editable course switches and student totals are in `settings/`.
