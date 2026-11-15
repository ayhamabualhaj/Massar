from .validation import prepare


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
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def table_rows(data, result):
    """Build bulletin rows for every section, including those without meetings."""
    ctx = prepare(data)
    assignments = {
        assignment["event_id"]: assignment
        for assignment in result["assignments"]
    }
    rows = []

    for section_id, section in ctx["sections"].items():
        event_id = ctx["section_event"].get(section_id)
        assignment = assignments.get(event_id)
        row = {
            "رقم المادة": section["course_code"],
            "اسم المادة": section["name_ar"],
            "الشعبة": section["section_number"],
            "من": "—",
            "إلى": "—",
            "الأيام": "—",
            "القاعة": "—",
            "الحالة": (
                "بلا أيام تدريس"
                if section["status"] == "no_meeting_days"
                else "لم يتم الحل"
            ),
            "ملاحظات": "؛ ".join(section.get("assumptions", [])),
            "الفئة": section.get("audience", "لجميع الطلبة"),
        }

        if assignment:
            pattern = ctx["patterns"][section["pattern_id"]]
            room_id = assignment["room_id"]
            shared = len(ctx["events"][event_id]["source_ids"]) > 1
            row.update({
                "من": _format_time(assignment["start"]),
                "إلى": _format_time(assignment["start"] + pattern["duration"]),
                "الأيام": "،".join(DAY_NAMES[day] for day in pattern["days"]),
                "القاعة": ctx["rooms"][room_id]["name_ar"] if room_id else "Online",
                "الحالة": "مشترك صريح" if shared else "مجدولة",
            })

        rows.append(row)

    return sorted(rows, key=lambda row: (row["رقم المادة"], row["الشعبة"]))
