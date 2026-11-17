"""Export inferred-group membership, evidence, and enrollment gaps."""
import csv
import json
from collections import Counter
from pathlib import Path

from .planning import planned_data


def _write(path, headers, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_group_reports(data, result, directory, allow_unscheduled=False):
    scheduled = bool(result.get('has_solution'))
    if not scheduled and not allow_unscheduled:
        raise ValueError('Group assignment exports require a valid solved timetable.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    chosen = planned_data(data, result)
    sections = {s['id']: s for s in chosen['sections']}
    members, summaries = [], []
    assigned = Counter()
    for group in chosen['groups']:
        evidence = {e['course_code']: e for e in group.get('course_evidence', [])}
        names = []
        for sid in group['section_ids']:
            section = sections[sid]
            code = section['course_code']
            item = evidence[code]
            names.append(section['name_ar'])
            requirements = '، '.join(req['course_code'] + ('*' if req['concurrent_allowed'] else '')
                                     for req in item['prerequisites'])
            assigned[code] += group['students']
            members.append({
                'المجموعة': group['id'], 'التخصص': group['program_name'],
                'المرحلة الدراسية المفترضة': group['prerequisite_level'],
                'عدد طلبة المجموعة': group['students'], 'رقم المادة': code,
                'اسم المادة': section['name_ar'], 'الشعبة المسندة': section['section_number'] if scheduled else 'غير مجدول',
                'معرف الشعبة': sid if scheduled else '', 'الساعات المعتمدة في الخطة': item['credit_hours'],
                'نوع المتطلب في الخطة': item['category'], 'المتطلبات حسب الخطة': requirements,
                'نوع المجموعة': group['status'],
                'حالة الجدولة': 'مجدول' if scheduled else 'مقترح؛ لم تتم الجدولة',
                'سنة القبول': group.get('intake_year', ''), 'السنة الدراسية': group.get('study_year', ''),
                'الصورة المصدر': item['source_image'],
            })
        summaries.append({
            'المجموعة': group['id'], 'التخصص': group['program_name'],
            'المرحلة الدراسية المفترضة': group['prerequisite_level'],
            'عدد طلبة المجموعة': group['students'], 'عدد المواد': len(group['section_ids']),
            'مجموع الساعات المعتمدة': group['credit_hours'],
            'رموز المواد': '، '.join(group['course_codes']), 'أسماء المواد': '؛ '.join(names),
            'متطلبات مفترض اجتيازها': '، '.join(group['assumed_completed_course_codes']),
            'نوع المجموعة': group['status'],
                'حالة الجدولة': 'مجدول' if scheduled else 'مقترح؛ لم تتم الجدولة',
                'سنة القبول': group.get('intake_year', ''), 'السنة الدراسية': group.get('study_year', ''),
        })
    member_headers = ['المجموعة', 'التخصص', 'المرحلة الدراسية المفترضة', 'عدد طلبة المجموعة',
                      'رقم المادة', 'اسم المادة', 'الشعبة المسندة', 'معرف الشعبة',
                      'الساعات المعتمدة في الخطة', 'نوع المتطلب في الخطة', 'المتطلبات حسب الخطة',
                      'نوع المجموعة', 'حالة الجدولة', 'سنة القبول', 'السنة الدراسية', 'الصورة المصدر']
    summary_headers = ['المجموعة', 'التخصص', 'المرحلة الدراسية المفترضة', 'عدد طلبة المجموعة',
                       'عدد المواد', 'مجموع الساعات المعتمدة', 'رموز المواد', 'أسماء المواد',
                       'متطلبات مفترض اجتيازها', 'نوع المجموعة', 'حالة الجدولة', 'سنة القبول', 'السنة الدراسية']
    lookup={g['id']:g for g in chosen['groups']}
    for row in members+summaries:
        g=lookup[row['المجموعة']]
        row['المسار الدراسي']=g.get('study_path_id','P1')
        row['دفعة القبول الأصلية']=g.get('parent_cohort_id',g.get('cohort_id',''))
    member_headers+=['المسار الدراسي','دفعة القبول الأصلية']
    summary_headers+=['المسار الدراسي','دفعة القبول الأصلية']
    _write(directory/'student_groups.csv', member_headers, members)
    _write(directory/'student_group_summary.csv', summary_headers, summaries)
    labels = {
        'no_exact_plan_code_match': 'لا يوجد تطابق حرفي لرمز المادة مع الخطط',
        'zero_credit_or_remedial_track_not_inferred': 'مسار استدراكي أو بلا ساعات؛ لا يُستنتج من المسار العادي',
        'unpaired_remainder_or_group_limits': 'أعداد متبقية بلا مادة مرافقة ضمن المستوى والحدود',
        'fully_modeled': 'جميع أعداد المادة ممثلة في المجموعات المستنتجة',
        'not_selected_this_semester': 'لم تختر المادة في الفصل الحالي وفق خطة التقدم المفترضة',
        'non_meeting_course': 'مادة بلا لقاءات؛ لا تفتح لها شعب تدريس أو تفرض تعارضات زمنية',
    }
    coverage = []
    for row in data['group_inference']['course_coverage']:
        if assigned[row['course_code']] != row['modeled_students']:
            raise ValueError('Exported group enrollment differs from the inference report.')
        coverage.append({
            'رقم المادة': row['course_code'], 'اسم المادة': row['course_name'],
            'إجمالي الطلبة': row['students'] if row['students'] is not None else 'غير محدد', 'طلبة ضمن مجموعات مستنتجة': row['modeled_students'],
            'طلبة بلا ربط بمجموعات': row['unmodeled_students'] if row['unmodeled_students'] is not None else 'غير محدد',
            'توزيع التخصصات المفترض': '؛ '.join(f'{p}: {n}' for p, n in row['program_allocation'].items()),
            'التفسير': labels[row['reason']],
        })
    _write(directory/'student_group_coverage.csv',
           ['رقم المادة', 'اسم المادة', 'إجمالي الطلبة', 'طلبة ضمن مجموعات مستنتجة',
            'طلبة بلا ربط بمجموعات', 'توزيع التخصصات المفترض', 'التفسير'], coverage)
    report = dict(data['group_inference'], assignment_status='scheduled' if scheduled else 'unscheduled',
                  input_group_count=len(data['groups']), group_count=len(chosen['groups']),
                  solver_status=result['status'], groups=chosen['groups'],
                  solved_section_coverage=result.get('coverage'))
    (directory/'student_group_inference.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
