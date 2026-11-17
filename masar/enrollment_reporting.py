"""Write demand and resource reports even when the timetable is infeasible."""
import csv
import json
from collections import defaultdict
from pathlib import Path


def _csv(path,headers,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)


def write_enrollment_reports(data,result,curriculum,directory):
    directory=Path(directory)
    report=data['enrollment_projection']
    index={(r['program_id'],r['course_code']):r for r in curriculum['records']}
    names=data['enrollment_generation']['program_names']
    paths=report.get('study_paths') or {p:[dict(id='P1',**plan)] for p,plan in report['study_plans'].items()}
    _csv(directory/'cohort_student_estimates.csv',
         ['معرف الدفعة','التخصص','سنة القبول','فصل القبول','السنة الدراسية المفترضة','الفصل الدراسي المفترض',
          'عدد الطلبة التقديري','الساعات المخططة','ساعات المواد المتاحة','رموز المواد المتاحة','مواد مخططة غير متاحة'],
         [[c['id'],c['program_name'],c['intake_year'],c['intake_semester'],c['study_year'],c['study_semester'],
           c['students'],c['planned_credit_hours'],c['offered_credit_hours'],'، '.join(c['offered_courses']),
           '، '.join(c['unavailable_courses'])] for c in report['cohorts']])
    _csv(directory/'inferred_study_plans.csv',
         ['التخصص','المسار','الفصل الدراسي المفترض','السنة الدراسية المفترضة','رقم المادة','اسم المادة','الساعات المعتمدة','نوع المتطلب','حالة الخطة'],
         [[names[p],path['id'],semester,(semester+1)//2,code,index[p,code]['course_name'],index[p,code]['credit_hours'],
           index[p,code]['category'],'مسار مستنتج وليس سجلًا جامعيًا فعليًا']
          for p,variants in sorted(paths.items()) for path in variants
          for code,semester in sorted(path['semesters'].items(),key=lambda item:(item[1],item[0]))
          if not data['enrollment_generation'].get('scheduling_categories')
          or index[p,code]['category'] in data['enrollment_generation']['scheduling_categories']])
    catalog=data.get('course_catalog_scope',{}).get('records',[])
    _csv(directory/'it_course_catalog.csv',
         ['التخصص','رقم المادة','اسم المادة','نوع المتطلب','الساعات المعتمدة','المسارات التي اختارت المادة','فصل الدراسة المستنتج'],
         [[r['program_id'],r['course_code'],r['course_name'],r['category'],r['credit_hours'],
           '، '.join(path['id'] for path in paths[r['program_id']] if r['course_code'] in path['semesters']),
           '، '.join(f"{path['id']}: {path['semesters'][r['course_code']]}" for path in paths[r['program_id']] if r['course_code'] in path['semesters'])]
          for r in catalog])
    _csv(directory/'study_path_plans.csv',
         ['التخصص','المسار','رقم المادة','اسم المادة','نوع المتطلب','الساعات المعتمدة','الفصل المستنتج'],
         [[p,path['id'],code,index[p,code]['course_name'],index[p,code]['category'],index[p,code]['credit_hours'],term]
          for p,variants in sorted(paths.items()) for path in variants
          for code,term in sorted(path['semesters'].items(),key=lambda item:(item[1],item[0]))
          if not data['enrollment_generation'].get('scheduling_categories')
          or index[p,code]['category'] in data['enrollment_generation']['scheduling_categories']])
    _csv(directory/'major_elective_selections.csv',
         ['التخصص','المسار','رقم المادة','اسم المادة','الساعات المعتمدة','فصل الدراسة المستنتج','حد الساعات الاختيارية في الدرجة'],
         [[p,path['id'],code,index[p,code]['course_name'],index[p,code]['credit_hours'],term,9]
          for p,variants in sorted(paths.items()) for path in variants for code,term in sorted(path['semesters'].items())
          if index[p,code]['category']=='تخصص اختياري'])
    _csv(directory/'student_learning_profiles.csv',
         ['الدفعة الأصلية','معرف الشريحة','التخصص','سنة القبول','المسار','عدد الطلبة','الفصل الحالي',
          'الساعات الحالية','المواد الحالية','مواد مفترض اجتيازها','مواد دون لقاءات','المرحلة حسب سنة القبول','فرق التقدم الدراسي'],
         [[c.get('parent_cohort_id',c['id']),c['id'],c['program_id'],c['intake_year'],c.get('study_path_id','P1'),
           c['students'],c['study_semester'],c['planned_credit_hours'],'، '.join(c['planned_courses']),
           '، '.join(c.get('assumed_completed_course_codes',[])),'، '.join(c['unavailable_courses']),
           c.get('calendar_study_semester',c['study_semester']),c.get('progression_offset',0)]
          for c in report['cohorts']])
    _csv(directory/'estimated_meeting_patterns.csv',
         ['رقم المادة','اسم المادة','الساعات المعتمدة','متطلب القاعة','بدائل اللقاء','الحالة'],
         [[row['course_code'],row['course_name'],row['credits'],row['room_requirement'],
           ' | '.join(row['pattern_ids']),row['status']]
          for row in data.get('estimated_meeting_patterns',[])])
    requirements=result.get('section_requirements',[])
    _csv(directory/'section_requirements.csv',
         ['رقم المادة','نمط التدريس','متطلب القاعة','عدد الطلبة المتوقع','أكبر سعة مناسبة',
          'الحد الأدنى للشعب حسب السعة','دقائق تدريس الشعبة أسبوعيًا','حالة الجدولة'],
         [[r['course_code'],r['delivery'],r['room_requirement'],r['students'],
           r['maximum_room_capacity'] if r['maximum_room_capacity'] is not None else 'غير محدود',
           r['minimum_sections'] if r['minimum_sections'] is not None else 'لا توجد قاعة مناسبة',
           r['weekly_minutes'],result['status']] for r in requirements])
    minima=defaultdict(int)
    for r in requirements:
        if r['minimum_sections'] is not None:minima[r['course_code']]+=r['minimum_sections']
    opened=defaultdict(int)
    for section in result.get('planned_sections',[]):opened[section['course_code']]+=1
    reason_labels={'fully_modeled':'طلب متوقع من دفعات محددة',
                   'non_meeting_course':'مادة بلا لقاءات؛ لا تتطلب شعب تدريس زمنية',
                   'not_selected_this_semester':'لا طلب في الفصل الحالي وفق الخطة المفترضة',
                   'no_exact_plan_code_match':'الطلب غير معروف: رمز قديم بلا تطابق حرفي في الخطط'}
    rows=[]
    for row in report['course_coverage']:
        rows.append([row['course_code'],row['course_name'],row['students'] if row['students'] is not None else 'غير محدد',
                     minima[row['course_code']] if row['students'] else '',
                     opened[row['course_code']] if result['has_solution'] else 'لم تتم الجدولة',
                     reason_labels[row['reason']]])
    _csv(directory/'course_enrollment_projection.csv',
         ['رقم المادة','اسم المادة','عدد الطلبة المتوقع','الحد الأدنى للشعب حسب السعة','الشعب المجدولة','أساس التقدير'],rows)
    _csv(directory/'course_student_counts.csv',['رقم المادة','اسم المادة','إجمالي عدد الطلبة'],
         [[row[0],row[1],row[2]] for row in rows])
    _csv(directory/'room_capacity_shortfalls.csv',
         ['التشخيص','القاعات','الحد الأدنى لساعات التدريس الأسبوعية','الساعات الأسبوعية المتاحة','العجز بالساعات','التفاصيل','ساعات الطلبة المطلوبة','ساعات المقاعد المتاحة','العجز بساعات الطلبة'],
         [[d['reason'],'، '.join(d.get('room_ids',[])),d.get('minimum_weekly_minutes',0)/60,
           d.get('available_weekly_minutes',0)/60,d.get('shortfall_minutes',0)/60,d['message'],d.get('minimum_student_minutes',0)/60,
           d.get('available_student_minutes',0)/60,d.get('shortfall_student_minutes',0)/60]
          for d in result.get('resource_diagnostics',[])])
    (directory/'enrollment_projection.json').write_text(json.dumps(dict(report,solver_status=result['status'],
        has_timetable=result['has_solution'],required_sections_lower_bound=result.get('required_sections_lower_bound'),
        resource_diagnostics=result.get('resource_diagnostics',[])),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
