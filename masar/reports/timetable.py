"""Build the rows displayed in the exported timetable."""
from masar.validation import prepare
from masar.sections import planned_data, section_pool
from collections import defaultdict

TABLE_COLUMNS = ["رقم المادة", "اسم المادة", "الشعبة", "عدد الطلبة", "الحد الأقصى للطلبة",
                 "من", "إلى", "الأيام", "القاعة", "مكان التدريس", "المدرس", "ملاحظات", "الفئة"]


DAY_NAMES = {
    7: "أحد",
    1: "إثنين",
    2: "ثلاثاء",
    3: "أربعاء",
    4: "خميس",
    5: "جمعة",
    6: "سبت",
}


def _format_time(minutes):
    """Convert minutes since midnight to a clock time for the timetable."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _course_majors(data):
    """Eligibility from degree plans, including major electives, not enrollment."""
    by_course = defaultdict(dict)
    names = data.get('enrollment_generation', {}).get('program_names', {})
    order = {program: index for index, program in enumerate(('SE', 'CS', 'AI', 'CYBER', 'CIS'))}
    for record in data.get('course_catalog_scope', {}).get('records', []):
        program = record['program_id']
        by_course[record['course_code']][program] = record.get('program_name', names.get(program, program))
    return {code: 'all' if set(programs) == set(order) else
            '، '.join(programs[p] for p in sorted(programs, key=lambda p: (order.get(p, 99), p)))
            for code, programs in by_course.items()}


MAJOR_ORDER = ('SE', 'CS', 'AI', 'CYBER', 'CIS')


def _course_programs(data):
    """Map each course code to the programs whose degree plans include it."""
    programs = defaultdict(set)
    for record in data.get('course_catalog_scope', {}).get('records', []):
        programs[record['course_code']].add(record['program_id'])
    return programs


def major_views(data, rows):
    """Split exported rows into one view per major; shared courses appear in each eligible major."""
    programs = _course_programs(data)
    names = set(MAJOR_ORDER) | {p for codes in programs.values() for p in codes}
    return {program: [row for row in rows if program in programs.get(row['رقم المادة'], ())]
            for program in sorted(names, key=lambda p: (MAJOR_ORDER.index(p) if p in MAJOR_ORDER else 99, p))}


def _room_free_rows(data, majors=None):
    """Build timetable rows for projects and training that have no classroom meeting."""
    majors = _course_majors(data) if majors is None else majors
    return [{"رقم المادة":s['course_code'],"اسم المادة":s['name_ar'],"الشعبة":s.get('section_number',1),
             "عدد الطلبة":s['students'],"الحد الأقصى للطلبة":6 if 'مشروع تخرج' in s['name_ar'] and s['students']==6 else
                 5 if 'مشروع تخرج' in s['name_ar'] else "لا يتطلب قاعة",
             "من":"—","إلى":"—","الأيام":"—","القاعة":"لا يتطلب قاعة",
             "مكان التدريس":"نشاط دون حجز قاعة","المدرس":"غير مسند",
             "ملاحظات":"؛ ".join(s.get('assumptions',[])),"الفئة":majors.get(s['course_code'],'غير محدد في الخطط الدراسية')}
            for s in data['sections'] if s.get('room_free_activity')]


def _proposed_section_rows(data):
    """Export a capacity-only demand breakdown, never a fabricated timetable.

    Student groups have not been assigned to these rows; a feasible timetable
    may need different sections. Only the aggregate course/pool demand and
    compatible capacity are represented.
    """
    ctx = prepare(data)
    majors = _course_majors(data)
    pools = defaultdict(list)
    for section_id in ctx["section_event"]:
        section = ctx["sections"][section_id]
        pools[section_pool(section, ctx["patterns"])].append(section)
    rows = []
    numbering = defaultdict(int)
    for key, sections in sorted(pools.items()):
        section = sections[0]
        remaining = sum(s["students"] for s in sections)
        online = section["delivery"] == "online"
        capacities = [room["capacity"] for room in ctx["rooms"].values()
                      if room["type"] in data["compatibility"][section["room_requirement"]]]
        capacity = remaining if online else max(capacities, default=remaining)
        maximum = "غير محدود" if online else max(capacities) if capacities else "غير محدد"
        requirement = {"computers": "مختبر حاسوب", "lecture": "قاعة مناسبة للمحاضرات",
                       "online": "عن بعد",
                       "external_languages_classroom": "قاعة لغات خارج الكلية",
                       "external_science_classroom": "قاعة علوم خارج الكلية",
                       "external_engineering_classroom": "قاعة هندسة خارج الكلية",
                       "external_engineering_lab": "مختبر هندسة خارج الكلية"}.get(section["room_requirement"], section["room_requirement"])
        while remaining:
            students = min(remaining, capacity)
            numbering[key[0]] += 1
            rows.append({
                "رقم المادة": key[0], "اسم المادة": section["name_ar"],
                "الشعبة": numbering[key[0]], "عدد الطلبة": students,
                "الحد الأقصى للطلبة": maximum,
                "من": "—", "إلى": "—", "الأيام": "—", "القاعة": "—",
                "مكان التدريس": "خارج الكلية" if section.get("teaching_location")=="outside_it" else "كلية تكنولوجيا المعلومات",
                "المدرس": "غير مسند",
                "ملاحظات": f"متطلب القاعة: {requirement}؛ تقسيم الطلب حسب السعة فقط. "
                           "السعة حد مرجعي وليست قاعة مسندة. لم توزع مجموعات الطلبة أو الأوقات؛ "
                           "لا يمثل هذا جدولًا صالحًا، وقد يلزم تعديل عدد الشعب عند الجدولة.",
                "الفئة": majors.get(section["course_code"], "غير محدد في الخطط الدراسية"),
            })
            remaining -= students
    return rows+_room_free_rows(data, majors)


def table_rows(data, result):
    """Export scheduled rows, or explicit demand proposals for failed intake runs."""
    if not result.get("has_solution") and result.get("mode", "").startswith("minimum_sections"):
        if data.get("enrollment_projection") or data.get("request_provenance"):
            return _proposed_section_rows(data)
        return []
    majors = _course_majors(data)
    ctx = prepare(planned_data(data, result))
    assignments = {
        assignment["event_id"]: assignment
        for assignment in result["assignments"]
    }
    rows = []

    for section_id, section in ctx["sections"].items():
        if section.get("room_free_activity"):
            continue
        event_id = ctx["section_event"].get(section_id)
        assignment = assignments.get(event_id)
        row = {
            "رقم المادة": section["course_code"],
            "اسم المادة": section["name_ar"],
            "الشعبة": section["section_number"],
            "عدد الطلبة": section.get("students") if section.get("students") is not None else "غير محدد",
            "الحد الأقصى للطلبة": "غير محدد",
            "من": "—",
            "إلى": "—",
            "الأيام": "—",
            "القاعة": "—",
            "مكان التدريس": "خارج الكلية" if section.get("teaching_location")=="outside_it" else "كلية تكنولوجيا المعلومات",
                "المدرس": "غير مسند",
            "ملاحظات": "؛ ".join(section.get("assumptions", [])),
            "الفئة": majors.get(section["course_code"], "غير محدد في الخطط الدراسية"),
        }

        if assignment:
            pattern = ctx["patterns"][section["pattern_id"]]
            room_id = assignment["room_id"]
            row.update({
                "من": _format_time(assignment["start"]),
                "إلى": _format_time(assignment["start"] + pattern["duration"]),
                "الأيام": "،".join(DAY_NAMES[day] for day in pattern["days"]),
                "القاعة": ctx["rooms"][room_id]["name_ar"] if room_id else "Online",
                "الحد الأقصى للطلبة": ctx["rooms"][room_id]["capacity"] if room_id else "غير محدود",
            })
            if assignment.get('teacher_id'):
                teacher = ctx['teachers'][assignment['teacher_id']]
                row['المدرس'] = teacher.get('name_ar', teacher['id'])

        rows.append(row)

    return sorted(rows+_room_free_rows(data, majors), key=lambda row: (row["رقم المادة"], row["الشعبة"]))
