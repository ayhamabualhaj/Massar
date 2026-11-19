"""Read user-editable room capacities and major intake counts."""

import csv
import copy
from pathlib import Path

from .validation import need


def _rows(path, columns):
    """Read a settings CSV and check its column names before using its values."""
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        need(reader.fieldnames == columns, f'{path}: expected columns {columns}.')
        rows = list(reader)
    need(bool(rows), f'{path}: no data rows.')
    need(all(None not in row and all(value is not None for value in row.values()) for row in rows),
         f'{path}: every row must have exactly {len(columns)} columns.')
    return rows


def read_settings(directory):
    """Return validated settings; an empty second-semester count means unknown."""
    directory = Path(directory)
    rooms = {}
    for row in _rows(directory/'rooms.csv', ['room_id', 'room_name', 'room_type', 'capacity']):
        rid = row['room_id'].strip()
        value = row['capacity'].strip()
        need(rid and rid not in rooms, f'Duplicate or blank room ID: {rid}.')
        need(value.isdecimal() and int(value) > 0, f'{rid}: capacity must be a positive integer.')
        rooms[rid] = int(value)
    students = {}
    for row in _rows(directory/'student'/'students.csv', ['year', 'semester', 'major', 'students']):
        year, semester, major = (row[key].strip() for key in ('year', 'semester', 'major'))
        value = row['students'].strip()
        need(year.isdecimal() and semester in ('1', '2') and major,
             f'Invalid student row: {row}.')
        key = (year, semester, major)
        need(key not in students, f'Duplicate student row: {key}.')
        need(value == '' or value.isdecimal(), f'{key}: students must be a nonnegative integer or blank.')
        need(semester == '2' or value != '', f'{key}: first-semester students cannot be blank.')
        students[key] = None if value == '' else int(value)
    return rooms, students


def read_major_totals(directory, program_names):
    """Read editable active-student totals for every configured major."""
    path = Path(directory)/'student'/'major_students.csv'
    totals = {}
    for row in _rows(path, ['major', 'students']):
        major, value = row['major'].strip(), row['students'].strip()
        need(major in program_names, f'{path}: unknown major {major}.')
        need(major not in totals, f'{path}: duplicate major {major}.')
        need(value.isdecimal(), f'{path}: {major} students must be a nonnegative integer.')
        totals[major] = int(value)
    need(set(totals) == set(program_names),
         f'{path}: every major must have exactly one total; missing {sorted(set(program_names)-set(totals))}.')
    need(sum(totals.values()) > 0, f'{path}: at least one student is required.')
    return totals


def apply_major_totals(counts, totals):
    """Allocate each major's total across known cohorts using their CSV weights.

    Unknown second-semester cohorts stay unknown. Largest remainders preserve the
    exact requested total while making edits deterministic.
    """
    output = copy.deepcopy(counts)
    need(set(totals) == {key[2] for key in output}, 'Major totals do not match student settings.')
    for major, target in totals.items():
        need(type(target) is int and target >= 0, f'{major}: invalid major total.')
        keys = sorted(key for key, value in output.items() if key[2] == major and value is not None)
        need(bool(keys), f'{major}: no known cohorts to receive the major total.')
        weight = sum(output[key] for key in keys)
        need(weight > 0 or target == 0,
             f'{major}: positive major total needs a positive cohort weight in students.csv.')
        if target == 0:
            for key in keys:
                output[key] = 0
            continue
        allocations = {key: target*output[key]//weight for key in keys}
        remainder = target-sum(allocations.values())
        order = sorted(keys, key=lambda key: (-(target*output[key] % weight), key))
        for key in order[:remainder]:
            allocations[key] += 1
        output.update(allocations)
    return output


COURSE_FOLDERS = (
    'Faculty Requirements',
    'University Requirements',
    'University Elective Courses',
    'Faculty-College Elective Courses',
    'Major Elective Courses',
)


def read_course_switches(directory, catalog_codes):
    """Read the single editable on/off switch for each listed course code."""
    directory = Path(directory)
    switches = {}
    categories = {}
    path = directory/'All Courses'/'courses.csv'
    for row in _rows(path, ['course_code', 'course_name', 'category_folder', 'catalog_types', 'enabled']):
        code = row['course_code'].strip()
        flag = row['enabled'].strip()
        folder = row['category_folder'].strip()
        need(code in catalog_codes, f'{path}: unknown catalog course {code}.')
        need(code not in switches, f'{path}: duplicate course {code}.')
        need(folder in COURSE_FOLDERS, f'{path}: invalid category folder for {code}.')
        need(flag in ('0', '1'), f'{path}: {code} enabled must be 1 or 0.')
        switches[code] = flag == '1'
        categories[code] = folder
    listed = set()
    for folder in COURSE_FOLDERS:
        path = directory/folder/'courses.csv'
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == ['course_code', 'course_name', 'catalog_types'],
                 f'{path}: invalid columns.')
            for row in reader:
                need(None not in row and all(value is not None for value in row.values()),
                     f'{path}: invalid row.')
                code = row['course_code'].strip()
                need(code not in listed and categories.get(code) == folder,
                     f'{path}: course {code} is missing or in the wrong category.')
                listed.add(code)
    need(listed == set(switches), f'{directory}: category lists do not match All Courses.')
    return switches


def apply_room_capacities(data, capacities):
    """Overlay capacities on an input without changing its source object."""
    output = copy.deepcopy(data)
    available = {room['id'] for room in output['rooms']}
    need(set(capacities) <= available, f'Settings refer to unknown rooms: {sorted(set(capacities)-available)}.')
    internal = {room['id'] for room in output['rooms'] if room.get('location') != 'outside_it'}
    need(internal <= set(capacities), f'Missing room settings: {sorted(internal-set(capacities))}.')
    for room in output['rooms']:
        if room['id'] in capacities:
            room['capacity'] = capacities[room['id']]
    return output


def apply_student_counts(intakes, counts, program_names):
    """Replace individual-major counts and recalculate displayed totals."""
    output = copy.deepcopy(intakes)
    names = {name: code for code, name in program_names.items()}
    source_keys = set()
    totals = {}
    for row in output:
        if row['نوع الصف'] != 'تخصص مستقل':
            continue
        key = (row['السنة المرجعية'], '1' if row['الفصل'] == 'الأول' else '2',
               names.get(row['التخصص أو مجموعة التخصصات']))
        need(key[2] is not None, f'Unknown major in intake source: {row["التخصص أو مجموعة التخصصات"]}.')
        need(key not in source_keys, f'Duplicate major in intake source: {key}.')
        source_keys.add(key)
        need(key in counts, f'Missing student setting for {key}.')
        value = counts[key]
        row['عدد الطلبة الجدد'] = 'غير محدد' if value is None else str(value)
        totals.setdefault(key[:2], []).append(value)
    need(set(counts) == source_keys, f'Unknown student settings: {sorted(set(counts)-source_keys)}.')
    for row in output:
        if row['نوع الصف'] == 'إجمالي الفصل':
            key = (row['السنة المرجعية'], '1' if row['الفصل'] == 'الأول' else '2')
            values = totals[key]
            row['عدد الطلبة الجدد'] = str(sum(values)) if all(v is not None for v in values) else 'غير محدد'
    return output
