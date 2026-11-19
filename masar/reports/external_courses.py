"""Export externally taught courses and room estimates."""
import csv
from collections import defaultdict
from pathlib import Path
from masar.reports.timetable import table_rows, TABLE_COLUMNS


def write_external_reports(data,result,directory):
    """List externally taught courses and the outside rooms available to teach them."""
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    policy=data['external_course_allocation']
    def write(name,headers,rows):
        """Write one report with its column headings and data rows."""
        with (directory/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
    sources=defaultdict(list)
    for section in data['sections']:
        if section.get('teaching_location')=='outside_it' and section['status']=='scheduled':
            sources[section['course_code']].append(section)
    requirements=defaultdict(list)
    for row in result.get('section_requirements',[]):
        requirements[row['course_code']].append(row)
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
        writer=csv.DictWriter(stream,fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(row for row in table_rows(data,result) if row['رقم المادة'] in policy['courses'])
