"""Keep externally taught courses in student schedules, outside IT resources."""
import copy

from .validation import need, prepare


EXTERNAL_COURSES = {
    '0202100': ('languages', False),
    '0302106': ('science', False), '0302131': ('science', False),
    '0302241': ('science', False), '0303106': ('science', False),
    '0511231': ('engineering', False), '0511233': ('engineering', False),
    '0511234': ('engineering', True), '0511336': ('engineering', True),
    '0512443': ('engineering', True),
}


DEFAULT_ROOMS = [
    dict(id='EXT_LANG_1', name_ar='خارج الكلية — قاعة لغات تقديرية',
         type='external_languages_classroom', capacity=100),
    dict(id='EXT_SCIENCE_1', name_ar='خارج الكلية — قاعة علوم تقديرية',
         type='external_science_classroom', capacity=100),
    dict(id='EXT_ENG_1', name_ar='خارج الكلية — قاعة هندسة تقديرية',
         type='external_engineering_classroom', capacity=100),
    dict(id='EXT_ENG_LAB_1', name_ar='خارج الكلية — مختبر هندسة تقديري',
         type='external_engineering_lab', capacity=40),
]


def with_external_courses(reference, policy):
    """Use finite, explicitly estimated outside rooms; never model them as online.

    External timetable information is unknown. These dedicated resource pools
    allow estimated meetings to participate in student-conflict constraints
    without consuming the known IT rooms. Replace them with verified inventory
    when available.
    """
    if not policy.get('enabled'):
        return copy.deepcopy(reference)
    output=copy.deepcopy(reference)
    existing={r['id'] for r in output['rooms']}
    rooms=copy.deepcopy(policy.get('rooms', DEFAULT_ROOMS))
    for room in rooms:
        room.setdefault('blackouts', [])
        room.update(location='outside_it', capacity_status='estimated_external_inventory',
                    inventory_status='scenario_placeholder_not_verified')
        if room['id'] not in existing:
            output['rooms'].append(room)
        else:
            need(any(r['id']==room['id'] and r==room for r in output['rooms']),
                 'External room ID collides with another room.')
    for room in output['rooms']:
        room.setdefault('location','it_college')
    mappings={}
    for code,(department,lab) in EXTERNAL_COURSES.items():
        kind=f'external_{department}_'+('lab' if lab else 'classroom')
        output['compatibility'][kind]=[kind]
        mappings[code]=dict(department=department,room_requirement=kind)
    for section in output['sections']:
        if section['course_code'] not in mappings:
            section['teaching_location']='it_college'
            continue
        item=mappings[section['course_code']]
        section.update(room_requirement=item['room_requirement'], teaching_location='outside_it',
                       external_department=item['department'], source_room=None)
        note='Taught outside IT; uses a separate estimated external-room pool and remains in student conflict checks.'
        if note not in section.setdefault('assumptions',[]):section['assumptions'].append(note)
    output['external_course_allocation']=dict(courses=mappings,rooms=rooms,
        inventory_status='estimated_not_verified',
        basis='Ten explicitly identified outside-IT courses; scenario room pools, not a verified external timetable.')
    prepare(output)
    return output


def write_external_reports(data,result,directory):
    import csv
    from collections import defaultdict
    from pathlib import Path
    from .reporting import table_rows, TABLE_COLUMNS
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    policy=data['external_course_allocation']
    def write(name,headers,rows):
        with (directory/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(headers);writer.writerows(rows)
    sources=defaultdict(list)
    for section in data['sections']:
        if section.get('teaching_location')=='outside_it' and section['status']=='scheduled':
            sources[section['course_code']].append(section)
    requirements=defaultdict(list)
    for row in result.get('section_requirements',[]):requirements[row['course_code']].append(row)
    write('external_course_summary.csv',
        ['رقم المادة','اسم المادة','القسم الخارجي التقديري','عدد الطلبة','الحد الأدنى للشعب',
         'القاعات الخارجية المتاحة في النموذج','حالة الحل'],
        [[code,sections[0]['name_ar'],policy['courses'][code]['department'],sum(s['students'] for s in sections),
          sum(r['minimum_sections'] or 0 for r in requirements[code]),
          ' | '.join(sorted({rid for r in requirements[code] for rid in r['eligible_room_ids']})),result['status']]
         for code,sections in sorted(sources.items())])
    write('external_room_estimates.csv',['معرف القاعة','اسم القاعة','النوع','السعة التقديرية','حالة البيانات'],
        [[r['id'],r['name_ar'],r['type'],r['capacity'],'تقدير سيناريو؛ ليس جردًا فعليًا مؤكدًا']
         for r in policy['rooms']])
    with (directory/'external_classes.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=TABLE_COLUMNS);writer.writeheader()
        writer.writerows(row for row in table_rows(data,result) if row['رقم المادة'] in policy['courses'])
