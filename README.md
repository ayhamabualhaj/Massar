# Masar

College timetable optimizer. Requires Python 3.11 or newer.

## Run in PyCharm

Install dependencies in the project terminal:

```bash
python -m pip install -r requirements.txt
```

Right-click `main.py` and choose **Run**. Results are saved in `masar_v2_output/` as JSON and CSV.

## Files

- `main.py`: application entry point.
- `masar/`: validation, scheduling constraints, solver, result checker, and reporting.
- `data/masar_data_v2.json`: editable scheduling input.
- `docs/`: Arabic and English reference PDFs and the original sample HTML timetable.
- `tests/test_engine.py`: the 16 behavioral tests preserved from the original notebook.
- `extra information/`: the original university schedule and its comparison with the output.
- `masar_v2_output/`: generated timetable CSV and detailed solver results.

Run the tests from the project root:

```bash
python -m unittest discover -s tests -v
```

The optimizer checks room and configured student-group conflicts. Teacher conflicts
are not modeled; some capacities and student groups are synthetic. The HTML in
`docs/` is a saved experimental output, not the original university schedule.
