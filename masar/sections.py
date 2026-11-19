"""Section grouping and schedule reconstruction shared by demand, planning, and reports."""


def section_pool(section, patterns):
    """Identify interchangeable sections with the same course, delivery, room type and weekly minutes."""
    pattern = patterns[section['pattern_id']]
    return (section['course_code'], section['delivery'],
            section['room_requirement'], len(pattern['days']) * pattern['duration'])


def planned_data(data, result):
    """Reconstruct the chosen input for reporting or independent checking."""
    if 'planned_sections' not in result:
        return data
    return dict(data, sections=result['planned_sections'],
                groups=result['planned_groups'], shared_classes=[], section_pattern_options={})
