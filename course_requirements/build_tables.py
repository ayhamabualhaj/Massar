"""Export manually transcribed degree-plan data; Python standard library only."""
import csv
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

import transcription as t

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = {
1: 'WhatsApp Image 2026-11-14 at 9.33.53 PM.jpeg',
2: 'WhatsApp Image 2026-11-14 at 9.33.53 PM (1).jpeg',
3: 'WhatsApp Image 2026-11-14 at 9.33.54 PM.jpeg',
4: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (1).jpeg',
5: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (2).jpeg',
6: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (3).jpeg',
7: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (4).jpeg',
8: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (5).jpeg',
9: 'WhatsApp Image 2026-11-14 at 9.33.54 PM (6).jpeg',
}
records = []


def add(program, text, category, photo, position, basket=''):
    for number, line in enumerate(text.strip().splitlines(), 1):
        parts = line.split('|')
        assert len(parts) == 6, line
        code, name, hours, req1, req2, notes = parts
        assert re.fullmatch(r'\d{7}', code), code
        requirements = []
        minimum_hours = None
        for column, req in enumerate((req1, req2), 1):
            if not req:
                continue
            if 'ساعة' in req:
                minimum_hours = int(req.split()[0])
            else:
                token = req.rstrip('*')
                assert re.fullmatch(r'\d{7}', token), req
                requirements.append(dict(column=column, course_code=token,
                                         concurrent_allowed=req.endswith('*')))
        records.append(dict(
            program_id=program, program_name=t.PROGRAMS[program][0], plan_year=2026,
            course_code=code, course_name=name, credit_hours=int(hours),
            category=category, elective_basket=basket,
            source_symbol='ن' if 'رمز إ.س في المصدر: ن' in notes else 'ع',
            requirements=requirements, minimum_completed_hours=minimum_hours,
            requirement_1_raw=req1, requirement_2_raw=req2,
            source_image=f'sources/plan-{photo:02d}.jpeg',
            source_original_filename=SOURCE_FILES[photo],
            source_position=f'{position} / الصف {number}',
            verification_status='تحتاج تتمة الاسم إلى مراجعة الصورة' if 'حافة العمود' in notes
                                else 'منقول بصريًا من الصورة',
            notes=notes))


for program, (name, main, continuation) in t.PROGRAMS.items():
    add(program, t.UNIVERSITY_REQUIRED, 'جامعة إجباري', main, 'العمود الأيمن / الجدول الأعلى')
    add(program, t.UNIVERSITY_HUMANITIES, 'جامعة اختياري', main, 'العمود الأيمن / الحزمة الأولى', 'العلوم الإنسانية')
    add(program, t.UNIVERSITY_SOCIAL, 'جامعة اختياري', main, 'العمود الأيمن / الحزمة الثانية', 'العلوم الاجتماعية والاقتصاد')
    add(program, t.UNIVERSITY_SCIENCE, 'جامعة اختياري', main, 'العمود الأوسط / الجدول الأعلى', 'العلوم والتكنولوجيا والزراعة والصحة')
    college = t.COLLEGE
    if program in ('CS','CYBER','SE'):
        lines = college.strip().splitlines()
        lines[2], lines[3] = lines[3], lines[2]
        college = '\n'.join(lines)
    add(program, college, 'كلية إجباري', main, 'العمود الأوسط / كلية إجباري')
    add(program, getattr(t, program+'_REQUIRED_MIDDLE'), 'تخصص إجباري', main, 'العمود الأوسط / الجدول الأسفل')
    add(program, getattr(t, program+'_REQUIRED_LEFT'), 'تخصص إجباري', main, 'العمود الأيسر / الجدول الأعلى')
    add(program, getattr(t, program+'_ELECTIVE_LEFT', getattr(t, program+'_ELECTIVE', '')),
        'تخصص اختياري', main, 'العمود الأيسر / الجدول الأسفل')
    if continuation:
        add(program, getattr(t, program+'_ELECTIVE_CONT'), 'تخصص اختياري', continuation,
            'الجدول الوحيد / تتمة تخصص اختياري')

# Every requirement must be retained in its own program context, including
# differences between majors for courses that share a code.
index = {(r['program_id'], r['course_code']): r for r in records}
assert len(index) == len(records), 'Duplicate course code within a plan.'
for record in records:
    for requirement in record['requirements']:
        other = index.get((record['program_id'], requirement['course_code']))
        assert other is not None, (record['program_id'], record['course_code'], requirement)
        requirement['course_name'] = other['course_name']
        assert requirement['course_code'] != record['course_code']

# Compare obligatory credits to the printed totals, rather than the sum of all
# electives (which are choices, not all required courses).
for program in t.PROGRAMS:
    rows = [r for r in records if r['program_id'] == program]
    sums = Counter()
    for row in rows:
        sums[row['category']] += row['credit_hours']
    assert sums['جامعة إجباري'] == 18, (program, sums)
    assert sums['كلية إجباري'] == 21, (program, sums)
    assert sums['تخصص إجباري'] == 75, (program, sums)
    assert 18+9+21+75+9 == 132

# Course prerequisites (ignoring permitted concurrency) must have no accidental
# self/circular dependencies introduced by transcription.
for program in t.PROGRAMS:
    visited, stack = set(), set()
    def visit(code):
        if code in visited:
            return
        assert code not in stack, (program, 'cycle', code)
        stack.add(code)
        for requirement in index[program, code]['requirements']:
            if not requirement['concurrent_allowed']:
                visit(requirement['course_code'])
        stack.remove(code)
        visited.add(code)
    for row in records:
        if row['program_id'] == program:
            visit(row['course_code'])

HEADERS = ['التخصص', 'رقم المادة', 'اسم المادة', 'الساعات المعتمدة', 'نوع المتطلب', 'الحزمة',
           'المتطلب 1', 'اسم المتطلب 1', 'المتطلب 2', 'اسم المتطلب 2',
           'الحد الأدنى للساعات المجتازة', 'رمز إ.س كما في المصدر', 'ملاحظات',
           'حالة النقل', 'الصورة المصدر', 'موقع الصف في الصورة']


def values(record):
    reqs = {r['column']: r for r in record['requirements']}
    return [record['program_name'], record['course_code'], record['course_name'], record['credit_hours'],
            record['category'], record['elective_basket'],
            record['requirement_1_raw'] if record['minimum_completed_hours'] is None else '',
            reqs.get(1, {}).get('course_name', ''), record['requirement_2_raw'],
            reqs.get(2, {}).get('course_name', ''), record['minimum_completed_hours'] or '',
            record['source_symbol'], record['notes'], record['verification_status'],
            record['source_image'], record['source_position']]


def write_csv(path, headers, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


program_rows = {p: [r for r in records if r['program_id']==p] for p in t.PROGRAMS}
write_csv(ROOT / 'all_course_requirements.csv', HEADERS, [values(r) for r in records])
for program, rows in program_rows.items():
    write_csv(ROOT / f'{program.lower()}_course_requirements.csv', HEADERS, [values(r) for r in rows])
(ROOT / 'course_requirements.json').write_text(json.dumps(dict(
    institution='جامعة الحسين بن طلال', plan_year=2026, plan_document_date='2026-09-23',
    source='Nine supplied photographs; manual visual transcription, not official digital registration data.',
    concurrency_note='An asterisk permits concurrent enrollment with that prerequisite; it does not require concurrency.',
    records=records), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

edge_headers=['التخصص','رقم المادة','اسم المادة','المتطلب السابق','اسم المتطلب السابق','التزامن مسموح','عمود المتطلب','الصورة المصدر']
edges=[]
for row in records:
    for req in row['requirements']:
        edges.append([row['program_name'], row['course_code'], row['course_name'], req['course_code'],
                      req['course_name'], 'نعم' if req['concurrent_allowed'] else 'لا', req['column'], row['source_image']])
write_csv(ROOT/'prerequisite_links.csv', edge_headers, edges)

summary_headers=['التخصص','عدد السجلات المنقولة','جامعة إجباري','جامعة اختياري مطلوب','كلية إجباري','تخصص إجباري','تخصص اختياري مطلوب','مجموع التخرج الأدنى','عدد علاقات المتطلبات']
summary=[]
for p, rows in program_rows.items():
    summary.append([t.PROGRAMS[p][0],len(rows),18,9,21,75,9,132,sum(len(r['requirements']) for r in rows)])
write_csv(ROOT/'program_summary.csv',summary_headers,summary)
manifest=[]
for number, original_name in SOURCE_FILES.items():
    path=ROOT/f'sources/plan-{number:02d}.jpeg'
    program=next(p for p,(_,main,cont) in t.PROGRAMS.items() if number in (main,cont))
    manifest.append([number,t.PROGRAMS[program][0],1 if number==t.PROGRAMS[program][1] else 2,
                     str(path.relative_to(ROOT)),original_name,hashlib.sha256(path.read_bytes()).hexdigest()])
write_csv(ROOT/'source_manifest.csv',['الصورة','التخصص','صفحة الخطة','المسار المحلي','اسم الصورة داخل الأرشيف','SHA256'],manifest)

# Write a dependency-free OOXML workbook. Course/prerequisite codes are inline
# strings, so Excel retains the leading zero. All tables have frozen headers,
# filters, Arabic right-to-left views, and alternate row shading.
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ET.register_namespace('',NS)
ET.register_namespace('r',REL)

def tag(name):
    return '{'+NS+'}'+name


def column_name(i):
    out=''
    while i:
        i,remain=divmod(i-1,26)
        out=chr(65+remain)+out
    return out


def worksheet(headers, rows, widths=None):
    root=ET.Element(tag('worksheet'))
    views=ET.SubElement(root,tag('sheetViews'))
    view=ET.SubElement(views,tag('sheetView'),workbookViewId='0',rightToLeft='1')
    ET.SubElement(view,tag('pane'),ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
    cols=ET.SubElement(root,tag('cols'))
    for i in range(1,len(headers)+1):
        ET.SubElement(cols,tag('col'),min=str(i),max=str(i),width=str((widths or {}).get(i,20)),customWidth='1')
    sheet=ET.SubElement(root,tag('sheetData'))
    for number,row in enumerate([headers]+rows,1):
        row_node=ET.SubElement(sheet,tag('row'),r=str(number),ht='34' if number==1 else '42',customHeight='1')
        for i,value in enumerate(row,1):
            style='1' if number==1 else ('2' if number%2==0 else '3')
            node=ET.SubElement(row_node,tag('c'),r=f'{column_name(i)}{number}',s=style)
            if isinstance(value,(int,float)):
                ET.SubElement(node,tag('v')).text=str(value)
            else:
                node.set('t','inlineStr')
                ET.SubElement(ET.SubElement(node,tag('is')),tag('t')).text=str(value)
    if rows:
        ET.SubElement(root,tag('autoFilter'),ref=f'A1:{column_name(len(headers))}{len(rows)+1}')
    ET.SubElement(root,tag('pageMargins'),left='0.25',right='0.25',top='0.4',bottom='0.4',header='0.2',footer='0.2')
    ET.SubElement(root,tag('pageSetup'),paperSize='9',orientation='landscape',fitToWidth='1',fitToHeight='0')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

styles=f'''<styleSheet xmlns="{NS}">
<fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17394A"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEDF5F7"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1" readingOrder="2"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
notes_headers=['الموضوع','الشرح']
notes=[
['المصدر','تسع صور لخطط جامعة الحسين بن طلال لسنة 2026 بتاريخ 2026-09-23.'],
['المتطلبات','الحقل الفارغ يعني عدم وجود متطلب مطبوع، وليس تحقق أهلية الطالب. المتطلبان يبقيان منفصلين كما في الصورة.'],
['علامة *','تسمح بالتسجيل المتزامن مع المتطلب؛ لا تعني أن التزامن إلزامي.'],
['90 ساعة','شرط حد أدنى للساعات المجتازة، وليس رمز مادة.'],
['الاختياري','جامعة: 9 ساعات، بحد أقصى 3 ساعات من كل حزمة. تخصص: 9 ساعات من قائمة البدائل.'],
['رمز إ.س','تُنقل قيمتا ع و ن كما طبعتا دون افتراض معنى أكاديمي غير موضح.'],
['الساعات العملية','تذكر الصور أن ساعة معتمدة واحدة تكافئ ساعتين عمليتين حيث تنطبق العلامة **. لم تُحوّل الساعات تلقائيًا.'],
['أسماء ممتدة','الأسماء الممتدة عند حافة العمود موضحة في الملاحظات؛ راجع الصورة لتأكيد النص الكامل.'],
['عدم دمج الخطط','نفس رمز المادة قد يختلف في متطلباته أو ساعاته بين التخصصات. أبقينا كل خطة مستقلة.'],
['المحسن','هذه جداول مرجعية منفصلة، ولا تُعدّل بيانات المحسن ولا تطبق قيودًا جديدة عليه.'],
['الأصفار الأولى','رموز المواد خلايا نصية في Excel حتى تبقى أصفار البداية.'],
]
sheet_names={'AI':'البيانات والذكاء الاصطناعي','CS':'علم الحاسوب','CYBER':'الأمن السيبراني والسحابة','CIS':'نظم المعلومات','SE':'هندسة البرمجيات'}
widths={1:28,2:15,3:52,4:13,5:20,6:28,7:19,8:44,9:19,10:44,11:18,12:16,13:62,14:32,15:30,16:50}
sheets=[('اقرأ أولًا',notes_headers,notes,{1:27,2:125}),('ملخص الخطط',summary_headers,summary,{1:43})]
for p,rows in program_rows.items():
    sheets.append((sheet_names[p],HEADERS,[values(r) for r in rows],widths))
sheets += [('كل المواد',HEADERS,[values(r) for r in records],widths),('علاقات المتطلبات',edge_headers,edges,{1:28,2:16,3:50,4:17,5:50,6:18,7:16,8:32})]
workbook=ET.Element(tag('workbook'))
sheet_nodes=ET.SubElement(workbook,tag('sheets'))
for i,(name,_,_,_) in enumerate(sheets,1):
    ET.SubElement(sheet_nodes,tag('sheet'),name=name,sheetId=str(i),attrib={'{'+REL+'}id':f'rId{i}'})
relationships='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(
    f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="{REL}/styles" Target="styles.xml"/></Relationships>'
content_types='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>'
with ZipFile(ROOT/'course_requirements.xlsx','w',ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml',content_types)
    z.writestr('_rels/.rels',f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr('xl/workbook.xml',ET.tostring(workbook,encoding='utf-8',xml_declaration=True))
    z.writestr('xl/_rels/workbook.xml.rels',relationships)
    z.writestr('xl/styles.xml',styles)
    for i,(_,headers,rows,colwidths) in enumerate(sheets,1):
        z.writestr(f'xl/worksheets/sheet{i}.xml',worksheet(headers,rows,colwidths))
with ZipFile(ROOT/'course_requirements.xlsx') as z:
    assert z.testzip() is None
    for name in z.namelist():
        ET.fromstring(z.read(name))
    # Verify that a leading-zero course code is stored as a string.
    first=ET.fromstring(z.read('xl/worksheets/sheet3.xml'))
    cell=first.find('.//'+tag('c')+'[@r="B2"]')
    assert cell.get('t')=='inlineStr' and cell.find('.//'+tag('t')).text=='0612098'

print('Course rows:',len(records),'distinct codes:',len({r['course_code'] for r in records}),'prerequisite links:',len(edges))
print('Program rows:',{p:len(rows) for p,rows in program_rows.items()})
print('All five programs: obligatory credits 18 + 21 + 75; elective requirements 9 + 9; minimum total 132.')
print('Workbook:',len(sheets),'sheets; all source links and leading-zero codes verified.')
