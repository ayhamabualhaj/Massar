"""Generate the Arabic guide from the current intake projection and solver result.
Run: python docs/generate_masar_ar.py, then print the HTML to A4 PDF with browser headers disabled.
Python standard library only; does not modify solver data.
"""
import ast
import html
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'data/masar_data_v2.json').read_text())
RESULT=json.loads((ROOT/'extra information/masar_v2_output/result.json').read_text())
PROJECTION=DATA['enrollment_projection']
POLICY=DATA['enrollment_generation']
COVERAGE=PROJECTION['course_coverage']
REQUIREMENTS=RESULT['section_requirements']
POPULATION=PROJECTION['estimated_students']
GROUPS=len(DATA['groups'])
LOWER=RESULT['required_sections_lower_bound']
TESTS=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')
          for p in (ROOT/'tests').glob('test_*.py') for n in ast.walk(ast.parse(p.read_text())))
MINIMA=Counter()
for row in REQUIREMENTS:MINIMA[row['course_code']]+=row['minimum_sections'] or 0
NAMES={row['course_code']:row['course_name'] for row in COVERAGE}

def esc(s):return html.escape(str(s))
def ltr(s):return '<span class="ltr">'+esc(s)+'</span>'
def table(headers,rows,cls=''):
    return '<table class="'+cls+'"><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table>'
PAGES=[]
def page(kicker,title,body):
    n=len(PAGES)+1
    PAGES.append(f'<section class="page" id="page-{n}"><header><span>مسار <b>MASAR</b></span><span>دليل توقع الطلب وتخطيط الشعب</span></header><div class="kicker">{kicker}</div><h1>{title}</h1>{body}<footer><span>مسار · {date.today().isoformat()} · سيناريو تقديري</span><span>{n:02d}</span></footer></section>')

status='يوجد جدول صالح' if RESULT['has_solution'] else 'لا يوجد جدول صالح بالقاعات والأوقات الحالية'
page('ابدأ من هنا','من دفعات القبول<br>إلى الطلب المتوقع على الشعب',f'''
<p class="lead">يستخدم مسار تقديرات قبول أربع سنوات لبناء مجموعات حسب التخصص وسنة الدراسة، ثم يحسب طلب المواد والشعب اللازمة.</p>
<div class="stats"><div><strong>{POPULATION:,}</strong><span>طالبًا في السيناريو التقديري</span></div><div class="featured"><strong>{GROUPS}</strong><span>مجموعة دفعة مقترحة</span></div><div><strong>{LOWER}</strong><span>شعبة على الأقل حسب السعة</span></div></div>
<div class="callout danger"><b>حالة التشغيل الحالي: {ltr(RESULT['status'])}</b><p>{status}. العدد {LOWER} حد أدنى للشعب المطلوبة، وليس عدد شعب جرى جدولتها بنجاح. لا تعرض النسخة الحالية الجدول القديم بوصفه نتيجة جديدة.</p></div>
<h2>ثلاثة أعداد يجب التمييز بينها</h2>
{table(['العدد','ماذا يمثل؟'],[[f'{POPULATION:,}','طلبة أربع دفعات أولى؛ يفترض بقاؤهم في الدراسة.'],[f"{DATA['group_inference']['modeled_course_enrollments']:,}",'تسجيلات في مواد ذات لقاءات؛ الطالب نفسه يُحسب مرة لكل مادة يأخذها.'],[str(LOWER),'حد أدنى للشعب، قبل اختبار إمكانية توزيعها على القاعات والأوقات.']])}
<h2>خريطة الدليل</h2>
<p>الصفحة 2: الأعداد والسنوات. الصفحة 3: الخطة الدراسية المفترضة. الصفحة 4: المجموعات والشعب. الصفحة 5: نتيجة الجدولة والموارد. الصفحة 6: التشغيل والملفات. ملحق النهاية: الطلب المتوقع لكل مادة في كتالوج السيناريو.</p>
<p class="small">هذه ليست تسجيلات طلاب فعلية. الأعداد السابقة لعام 2026، وتقسيم المقبولين بين ثلاثة تخصصات، والتقدم الدراسي، والاختيارات الحرة كلها افتراضات موثقة في التقارير.</p>''')

pop=Counter()
for cohort in PROJECTION['cohorts']:pop[cohort['program_id']]+=cohort['students']
page('01 · المجتمع الطلابي','كيف نستخدم السنوات الأربع؟',f'''
{table(['التخصص','الفصل الأول سنويًا','أربع دفعات'],[[esc(POLICY['program_names'][p]),str(pop[p]//4),f'{pop[p]:,}'] for p in ['SE','CS','AI','CYBER','CIS']]+[['الإجمالي',f'{POPULATION//4:,}',f'{POPULATION:,}']])}
<div class="callout"><b>ما هو مؤكد وما هو تقديري؟</b><p>أفاد المستخدم بـ322 لهندسة البرمجيات، و148 لنظم المعلومات، و288 مجموع الحاسوب والذكاء الاصطناعي والأمن السيبراني في الفصل الأول 2026. قُسمت الـ288 بالتساوي كتقدير: 96 لكل تخصص. وبطلب المستخدم ضُبط السيناريو الحالي إلى {POPULATION:,} طالب: {POPULATION//4} لكل سنة، مع الحفاظ على النسب السابقة بالتقريب. الأعداد المعروضة أدناه تقديرات السيناريو الحالي.</p></div>
<h2>التقدم الدراسي المفترض في الفصل الأول 2026</h2>
{table(['سنة القبول','السنة الدراسية المفترضة','الفصل الدراسي المفترض'],[['2026','الأولى','1'],['2025','الثانية','3'],['2024','الثالثة','5'],['2023','الرابعة','7']])}
<p>يفترض السيناريو أن كل دفعة تقدمت بصورة منتظمة، دون انسحاب أو تخرج مبكر أو إعادة مواد. هذه ليست معلومة مستخرجة من كشف علامات.</p>
<div class="formula">{POPULATION//4} طالبًا في الدفعة الأولى × 4 سنوات = {POPULATION:,} طالبًا تقديريًا</div>
<p>أعداد المقبولين في الفصول الثانية غير محددة، ولذلك لم تُخترع لها أعداد أو نسبة. إضافتها لاحقًا تغيّر المجتمع والطلب. لا تُجمع صفوف الإجماليات مرة ثانية مع صفوف التخصصات.</p>''')

page('02 · من الطالب إلى المادة','الخطة المستنتجة تحدد من يأخذ ماذا',f'''
<p>كتالوج المواد هو جداول الخطط الدراسية. تُجدول متطلبات الكلية الإجبارية والتخصص الإجبارية واختياري التخصص المختار فقط، وتُستبعد متطلبات الجامعة الإجبارية والاختيارية. يُختار لكل دفعة مواد فصلها الحالي فقط؛ لا تُجدول جميع مواد الدرجة في فصل واحد.</p>
{table(['القاعدة','كيف تطبق؟'],[
['المتطلب السابق','المتطلب غير المعلّم بنجمة يُدرس قبل المادة في فصل سابق.'],['التزامن المسموح','النجمة تسمح بدراسة المتطلب في الفصل نفسه؛ لا تجعل التزامن إلزاميًا.'],['الساعات','تحتوي الخطة الكاملة على 132 ساعة، ولا يتجاوز الفصل 18 ساعة.'],['الاختياري','9 ساعات تخصص اختياري لكل طالب عبر الدرجة الكاملة؛ يوزع الطلبة على بدائل مختلفة ليبقى طلب موجب لجميع مواد الكتالوج. تبقى ساعات الجامعة في حساب التقدم الداخلي فقط، وتُستبعد من الجدول.'],['شرط 90 ساعة','لا تظهر المادة قبل اكتمال الحد الأدنى من الساعات وفق الخطة المفترضة.'],['توزيع الفصول','توازن الساعات دون دفع المواد المعروضة نحو الفصل الحالي؛ تبقى الخطة تقديرية.']])}
<div class="callout success"><b>مثال: لغة برمجة (1)</b><p>طلب المادة الحالي هو {next(r['students'] for r in COVERAGE if r['course_code']=='0612112')} طالبًا من دفعات 2026؛ تمثل الدفعات الأربع {POPULATION:,} طالبًا. تفترض الخطة أن الدفعات الأكبر اجتازتها في مراحلها السابقة.</p></div>
<h2>حدود الاستنتاج</h2>
<p>الخطة الفصلية مستنتجة وليست توزيعًا رسميًا من الجامعة. تفترض اختيارات ومسارات تقدم متنوعة لكل تخصص، مع توزيع الطلاب بالتساوي بينها ومسارات إضافية لتغطية كل المواد، واجتياز متطلبات المراحل السابقة لكل مسار ومتطلبات تحديد المستوى. لا توجد سجلات فردية لتأكيد ذلك.</p>
<p>لا يستبدل البرنامج رمز مادة قديمًا برمز مشابه تلقائيًا. تُعرض جميع مواد كتالوج الكلية الـ111 كل فصل، ولكل منها طلب تقديري موجب من شرائح الطلاب. التقدم الأكاديمي لا يساوي الفصل الزمني دائمًا؛ بعض شرائح التغطية متقدمة أو متأخرة بخطوة أكاديمية واحدة كتقدير صريح. تُستبعد رموز الجدول القديم التي لا تطابق كتالوج الكلية. وافق المستخدم على سياسة أنماط تقديرية للمواد الناقصة، وتُستخدم كذلك للمواد التي تحتاجها المسارات المتنوعة: ثلاث ساعات محاضرات 3×60 أو 2×90، وساعتان 2×60، ومختبر بساعة لقاء أسبوعي 60 دقيقة. كل المحاضرات والمختبرات المطلوبة لها أنماط، وتبقى تقديرية. التدريب ومشاريع التخرج أنشطة بلا قاعات أو مواعيد أسبوعية ثابتة بطلب المستخدم. أما المادة المطابقة غير المختارة في الفصل الحالي فطلبها صفر ضمن هذا السيناريو.</p>
<p class="small">يُحفظ توزيع الفصول ويُتحقق منه عند كل تشغيل. تعديل أعداد القبول يغيّر الأعداد مع إبقاء الخطة نفسها؛ تعديل الخطط أو السياسة ذات الصلة يعيد حسابها.</p>''')

sample_codes=['0612112','0612102','0613101','0612214']
rows=[]
for code in sample_codes:
    item=next(r for r in COVERAGE if r['course_code']==code)
    rows.append([ltr(code),esc(item['course_name']),str(item['students']),str(MINIMA[code])])
page('03 · المجموعات والشعب','المجموعة دفعة مشتركة، وليست عدد شعبة ثابتًا',f'''
<p>توجد 20 دفعة قبول تخصص/سنة، موزعة على 144 شريحة تعلم عبر مسارات متنوعة ومسارات تغطية تضمن طلبًا موجبًا لكل مادة. تختلف مواد الفصل الحالي والمواد المجتازة المفترضة بين المسارات داخل السنة نفسها. تُقسم الأعداد إلى دفعات طلب تقديرية؛ يمكن تقسيمها بين الشعب مع حفظ مجموعة مواد كل طالب ومنع تعارضها.</p>
<div class="stats"><div><strong>20</strong><span>دفعة تخصص / سنة</span></div><div class="featured"><strong>{GROUPS}</strong><span>مجموعة مقترحة</span></div><div><strong>40</strong><span>حد المجموعة المرجعي للمختبر</span></div></div>
<p>مجموع أعداد المجموعات هو {PROJECTION['represented_students']:,} من أصل {POPULATION:,}. يبقى {POPULATION-PROJECTION['represented_students']} طالبًا في جدول الدفعات دون مواد معروضة في فصلهم المستنتج. العدد المتكرر في صفوف مواد المجموعة نفسها يظل عدد الطلاب أنفسهم، ولا يمثل طلابًا إضافيين. تبقى الأعداد الصغيرة المتبقية كما هي دون تقريبها أو إسقاطها.</p>
<h2>أمثلة على طلب المواد وحد الشعب الأدنى</h2>
{table(['رمز المادة','اسم المادة','الطلبة المتوقعون','شعب على الأقل'],rows)}
<div class="callout"><b>اختلاف متطلبات القاعات</b><p>إذا كان للمادة أكثر من نمط حضوري/عن بُعد أو متطلب تجهيز، يُوزع طلبها بنسب الأعداد المرجعية لتلك الأنماط. هذه النسب تقديرية. لا تُرفع سعات القاعات ولا تُلغى متطلبات المختبر لمجرد تقليل الشعب.</p></div>
<h2>ماذا يضمن المحسن؟</h2>
<p>يحافظ على مجموع طلب المادة وأفراد كل مجموعة، ويحترم سعة القاعة وتوافقها وأوقات إغلاقها، ويمنع تعارض القاعة وتعارض مواد المجموعة عند إيجاد جدول صالح.</p>
<p class="small">حالة المجموعات: {"مجدولة مع معرفات الشعب في التقارير" if RESULT["has_solution"] else "مقترحة وغير مجدولة"}. الأعداد تمثل تقديرات السيناريو الحالي.</p>''')

certs=RESULT.get('resource_diagnostics',[])
cert_rows=[]
for d in certs:
    if d['reason']=='weekly_student_seat_capacity_exceeded':
        cert_rows.append(['جميع القاعات · ساعات طلبة (مقاعد × وقت)',f"{d['minimum_student_minutes']/60:g}",f"{d['available_student_minutes']/60:g}",f"{d['shortfall_student_minutes']/60:g}"])
    if d['reason']=='weekly_room_workload_exceeded':
        label='قاعات كلية تكنولوجيا المعلومات' if set(d['room_ids'])=={r['id'] for r in DATA['rooms'] if r.get('location')!='outside_it'} else 'مجموعة القاعات المحددة في التقرير'
        cert_rows.append([label,f"{d['minimum_weekly_minutes']/60:g}",f"{d['available_weekly_minutes']/60:g}",f"{d['shortfall_minutes']/60:g}"])
if RESULT['has_solution']:
    plan=RESULT['section_plan']
    stats=RESULT.get('search_statistics',{})
    page('04 · صلاحية التنفيذ','النتيجة الحالية: جدول اجتاز الفحص',f'''
<p>بعد خفض تقدير الطلبة لملاءمة الموارد بطلب المستخدم، وجد المحسن جدولًا صالحًا للمواد والطلبة الممثلين في نموذج الفصل الحالي. لا يثبت هذا أكبر عدد طلبة يمكن استيعابه.</p>
{table(['القياس','النتيجة'],[['عدد الشعب المجدولة',str(plan['opened_sections'])],['مخالفات القيود الصلبة',str(RESULT['validation']['hard_rule_violations'])],['الحد الأدنى المستقل حسب السعة',str(LOWER)],['هل أقل عدد شعب مثبت؟','نعم' if plan['minimum_proven'] else 'لا؛ يوجد جدول صالح ويظل تحسين العدد ممكنًا'],['زمن التشغيل بالثواني',f"{RESULT.get('solver_seconds',0):.1f}"],['استهلاك الذاكرة المرصود MB',f"{stats.get('observed_peak_rss_mb',0):.0f}"]])}
<h2>السعات المستخدمة في هذا السيناريو</h2>
<p>ضُوعفت سعات القاعات العادية إلى 80–100 طالب، وأصبحت سعة كل مختبر 40 طالبًا. هذه سعات سيناريو طلبها المستخدم وتحتاج إلى تحقق ميداني قبل التطبيق.</p>
<h2>ماذا تم فحصه؟</h2>
<p>سعة القاعة وتوافقها وأوقات إغلاقها، وتكرار اللقاءات، ومنع تعارض القاعات ومواد كل مجموعة، وحفظ أعداد الطلبة وتسجيلات المواد. تستخدم خوارزمية البحث مسارات طلبة بأعداد متغيرة ثم توزعهم على الشعب وتحافظ على مجموعة مواد كل طالب.</p>
<div class="callout"><b>حدود التغطية ما زالت قائمة</b><p>يمثل الجدول المواد المتاحة لـ{PROJECTION['represented_students']:,} طالبًا من أصل {POPULATION:,}. يبقى {POPULATION-PROJECTION['represented_students']} طالبًا دون مواد معروضة في فصلهم المستنتج. المواد برموز قديمة خارج كتالوج الكلية مستبعدة، والمشاريع والتدريب (10 مواد) أنشطة بلا حجز قاعة أو لقاء أسبوعي ثابت؛ أعداد طلبتها محفوظة. القاعات الخارجية الأربع تقديرات غير موثقة، وبيانات المدرسين غير مفعلة. صحة الجدول ضمن النموذج لا تعني اكتمال بيانات الجامعة.</p></div>
<p>تجد الأوقات والقاعات وأعداد كل شعبة في {ltr('masar_v2_output/timetable.csv')}، والتفاصيل والفحص المستقل في {ltr('result.json')}.</p>''')
else:
    page('04 · صلاحية التنفيذ','المواد الخارجية وعجز قاعات الكلية',f'''
    <p>التدريب الميداني ومشاريع التخرج (10 مواد) أنشطة بلا حجز قاعة أو لقاء أسبوعي ثابت، مع حفظ أعداد الطلبة والساعات المعتمدة. المواد العشر الخارجية تستخدم مجموعات قاعات خارج الكلية، وتبقى لقاءاتها ضمن فحص تعارضات الطلبة. أضيفت أربع قاعات خارجية كتقدير سيناريو: ثلاث قاعات بسعة 100 ومختبر بسعة 40؛ ليست جردًا خارجيًا مؤكدًا. قبل البحث عن المواعيد، يحسب مسار حدًا أدنى للشعب من الطلب وأكبر سعة مناسبة. ثم يقارن زمن التدريس اللازم بنوافذ الوقت المسموحة للقاعات، ويفحص ساعات الطلبة: عدد المقاعد × زمن إتاحتها. لا تكفي مقارنة ساعات القاعات وحدها عند اختلاف السعات.</p>
    {table(['المورد','ساعات لازمة أسبوعيًا على الأقل','ساعات متاحة على الأكثر','العجز بالساعات'],cert_rows)}
    <div class="callout danger"><b>هذا إثبات عجز، وليس مجرد انتهاء مهلة الحل</b><p>حتى الحدود المتفائلة للاحتياج تتجاوز الوقت المتاح. لذلك لا يمكن توليد جدول صالح بنفس القاعات والنوافذ والطلب. زيادة مهلة البحث وحدها لا تعالج العجز.</p></div>
    <h2>ما معنى «{LOWER} شعبة على الأقل»؟</h2>
    <p>هو مجموع الحدود الدنيا حسب السعة لكل مادة ونمط تدريس. لا يثبت إمكان جدولة {LOWER} شعبة، وقد تحتاج الظروف إلى أكثر منها. لا يوجد في الحالة الحالية عدد نهائي من الشعب المفتوحة في جدول صالح.</p>
    <h2>ما الذي بقي ثابتًا؟</h2>
    <p>أنواع القاعات وسعاتها ونوافذ الأوقات مأخوذة من القالب المرجعي. أكد المستخدم متطلبات الحاسوب للمواد المرجعية، وتبقى قيود المختبر مفعلة. يدعم المحسن قيود المدرسين عند توفير معرفاتهم وتأهيلهم وأوقاتهم، لكن هذه البيانات غير مفعّلة في السيناريو الحالي. أوقات المسار المسائي وسعات القاعات تبقى افتراضات مصدرية تحتاج إلى تأكيد.</p>
    <h2>أين ترى التفاصيل؟</h2>
    <p>في مجلد {ltr('extra information/student_numbers/')}:</p>
    <ul><li>{ltr('section_requirements.csv')}: الطلب وسعة القاعة والحد الأدنى للشعب.</li>
    <li>{ltr('room_capacity_shortfalls.csv')}: حساب العجز الأسبوعي.</li>
    <li>{ltr('course_enrollment_projection.csv')}: الطلب المقدر والمجهول لكل مادة.</li></ul>
    <p class="small">تغيير الموارد أو الأوقات أو فرضيات الطلب يتطلب بيانات أو قرارًا واضحًا؛ لا يغيّر البرنامج هذه القيود تلقائيًا ليظهر حلًا ناجحًا.</p>''')

page('05 · التشغيل والملفات','أعد التشغيل بعد تعديل التقديرات',f'''
<pre dir="ltr">cd /home/lime/PycharmProjects/Massar
source .venv/bin/activate
python main.py</pre>
{table(['المصدر أو الملف','وظيفته'],[
[ltr('student_expected_number_for_each_semester.csv'),'داخل student_numbers؛ صفوف التخصصات المستقلة هي مصدر أعداد القبول.'],
[ltr('data/masar_section_templates.json'),'مرجع أنماط التدريس والقاعات؛ أعداده القديمة ليست طلبًا يُضاف إلى التوقع.'],
[ltr('data/masar_data_v2.json'),'لقطة مشتقة تُحدّث تلقائيًا بالأعداد والمجموعات الحالية.'],
[ltr('cohort_student_estimates.csv'),'الدفعات العشرون وموادها المتاحة وغير المتاحة.'],
[ltr('inferred_study_plans.csv'),'التوزيع المفترض للفصول الثمانية لكل تخصص.'],
[ltr('student_group_summary.csv'),'داخل student_groups؛ ملخص المجموعات وسنوات قبولها وحالة جدولة كل مجموعة.'],
[ltr('extra information/masar_v2_output/result.json'),'حالة الحل الحالية، الطلب، افتراضات المجموعات، وتشخيص الموارد.']])}
<div class="callout"><b>انتبه إلى ملف الجدول</b><p>عند فشل سيناريو القبول، يحتوي {ltr('timetable.csv')} على شعب مقترحة وأعداد الطلبة، مع ترك الأوقات والأيام والقاعات غير مسندة. هذه تقسيمات حسب السعة فقط ولا تشمل توزيع المجموعات على الشعب. تُحفظ النسخة الناجحة السابقة في مجلد {ltr('extra information/masar_v2_output/archive/')}، ولا تُعرض كجدول جديد. عند نجاح الحل يحتوي الملف على أوقات وقاعات فعلية ومجموعات مسندة، ويمكن مراجعة حالته في result.json.</p></div>
<p>عمود «الفئة» يعرض all إذا كانت المادة متاحة للتخصصات الخمسة؛ وإلا يسرد التخصصات التي تسمح خططها بالمادة، بما فيها اختياري التخصص. حُذف عمود «الحالة» من CSV؛ تبقى حالة المحلل والفحوص في result.json.</p>
<p>الحالة {ltr('INFEASIBLE')} تعني استحالة تحقيق القيود الحالية. أما {ltr('UNKNOWN')} فتعني توقف البحث دون حسم. وعند نجاح تشغيل لاحق، اقرأ إثبات أقل عدد من الشعب منفصلًا عن مثالية تفضيلات الأوقات.</p>
<p class="small">اجتاز المشروع {TESTS} اختبارًا، تشمل حفظ أعداد الدفعات، وعدم تكرار الإجماليات، والتقدم حسب المتطلبات، وإعادة التشغيل دون تضخيم الأعداد، وصحة قيود الجدولة وإظهار العجز.</p>''')

all_rows=sorted(COVERAGE,key=lambda row:row['course_code'])
for start in range(0,len(all_rows),24):
    rows=[]
    for item in all_rows[start:start+24]:
        code=item['course_code'];count=item['students']
        status='بلا لقاءات' if item['reason']=='non_meeting_course' else 'رمز غير مطابق' if count is None else 'غير مختارة' if count==0 else 'طلب متوقع'
        rows.append([ltr(code),esc(item['course_name']),'غير محدد' if count is None else str(count),str(MINIMA[code]) if code in MINIMA else '—',status])
    page('ملحق · الطلب حسب المادة',f'الطلب والشعب المطلوبة <span class="part">{ltr(str(start//24+1)+" / "+str((len(all_rows)+23)//24))}</span>',f'''
    <p class="appendix-intro">كل مادة من القالب المرجعي، دون دمج رموز متشابهة. «غير محدد» ليست صفرًا. الصفر طلب صفري ضمن الخطة الفصلية المفترضة فقط. عدد الشعب حد أدنى حسب السعة، وليس نتيجة جدولة ناجحة.</p>
    {table(['رمز المادة','اسم المادة','الطلبة المتوقعون','شعب على الأقل','حالة الطلب'],rows,'catalog')}
    <p class="small">المواد {start+1}–{start+len(rows)} من أصل {len(all_rows)}. مجموع الحدود الدنيا للشعب ذات الطلب هو {LOWER}.</p>''')

CSS = '\n@font-face {font-family:Vazir;src:url("file:///usr/share/fonts/vazirmatn-vf-fonts/Vazirmatn[wght].ttf");font-weight:100 900}\n@page {size:A4; margin:15mm 16mm 16mm}\n*{box-sizing:border-box}html{direction:rtl}body{width:178mm;margin:0;color:#183347;font:14px/1.72 Vazir,"DejaVu Sans",sans-serif;background:white}\na{color:inherit;text-decoration:none}.page{height:264mm;position:relative;padding:0 0 14mm;break-after:page}.page:last-child{break-after:auto}\nheader{display:flex;justify-content:space-between;align-items:center;border-top:4px solid #087f83;padding-top:10px;margin-bottom:14px;color:#607584;font-size:10.5px}\nheader span:first-child{color:#087f83;font-size:16px;font-weight:800}header b{font:9px sans-serif;letter-spacing:2px;margin-right:5px}\nfooter{position:absolute;bottom:0;left:0;right:0;border-top:1px solid #cfdee3;padding-top:7px;display:flex;justify-content:space-between;font-size:10px;color:#657c89}\n.kicker{font-size:12px;letter-spacing:.3px;color:#087f83;font-weight:750;margin-bottom:7px}h1{font-size:29px;line-height:1.45;margin:0 0 16px;font-weight:800;letter-spacing:-.6px}\nh2{font-size:17px;line-height:1.5;color:#08777b;margin:16px 0 8px;font-weight:750}p{margin:0 0 10px}strong{font-weight:750}.subtitle{font-size:15px;color:#657c89;margin-bottom:24px}.lead{font-size:18px;line-height:1.9}\n.ltr{display:inline-block;direction:ltr;unicode-bidi:isolate;font-family:Vazir,"DejaVu Sans",sans-serif}.small{font-size:11.5px;line-height:1.75;color:#526b7a}\ntable{border-collapse:collapse;width:100%;font-size:12.5px;line-height:1.7;margin:10px 0 14px;table-layout:auto}\nth{background:#17394a;color:white;text-align:right;padding:9px 10px;font-weight:650}td{padding:7px 10px;border-bottom:1px solid #dce6ea;vertical-align:top}tr:nth-child(even) td{background:#f2f7f8}tr{break-inside:avoid}thead{display:table-header-group}\n.callout{border-right:4px solid #e4ad44;background:#fcf7e9;padding:10px 15px;margin:12px 0;font-size:13px;line-height:1.8;break-inside:avoid}.callout b{display:block;color:#6b501e;margin-bottom:3px}.callout p{margin:0}.callout.success{background:#eaf6f3;border-color:#087f83}.callout.success b{color:#066d70}\n.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:23px 0}.stats div{border:1px solid #d6e4e7;border-radius:8px;padding:16px 8px;text-align:center;background:#f5f9fa}.stats strong{display:block;font-size:38px;line-height:1.3;color:#17394a}.stats span{font-size:12px;display:block;margin-top:7px}.stats .featured{background:#087f83;border-color:#087f83;color:white}.stats .featured strong{color:white}\n.cover h1{font-size:39px;line-height:1.55;letter-spacing:-1px}.cover header{margin-bottom:32px}.contents{display:grid;grid-template-columns:1fr 1fr;gap:11px 16px;font-size:13px}.contents a{padding:5px 0;border-bottom:1px solid #e3ebee}.contents b{color:#087f83;margin-left:8px}\n.steps{display:grid;gap:10px;margin:0 0 18px}.steps div{display:flex;gap:12px;padding:11px 14px;background:#f1f7f8;border-radius:7px}.steps b{background:#087f83;color:white;border-radius:50%;height:29px;min-width:29px;text-align:center;font-size:16px;line-height:29px}.steps p{font-size:13px;line-height:1.8;margin:0}.formula{padding:12px;text-align:center;background:#eaf6f3;color:#076b70;font-weight:700;font-size:17px;margin:16px 0}\n.examples{font-size:12px}.examples th,.examples td{padding:7px 8px}.examples td:not(:first-child){text-align:center}.rooms{font-size:12px}.rooms .ltr{margin:0 3px}\n.group-example{display:flex;flex-wrap:wrap;gap:8px;background:#eff6f7;padding:13px;border-radius:6px;font-size:12px;margin-bottom:12px;align-items:center}.group-example span{background:white;border:1px solid #d2e4e7;padding:7px}.group-example b{color:#087f83}\npre{background:#17394a;color:#f1f7f8;border-radius:7px;padding:16px 18px;font:12.5px/1.9 "DejaVu Sans Mono",monospace;white-space:pre-wrap;overflow-wrap:anywhere;text-align:left;margin:10px 0 13px}\n.catalog{font-size:12.5px;line-height:1.55}.catalog td,.catalog th{padding:4px 8px}.catalog td:first-child{width:17%;font-size:11.5px}.catalog td:nth-child(2){width:41%}.catalog td:nth-child(n+3){text-align:center;width:14%}.catalog th:nth-child(n+3){text-align:center}.unknown{color:#6a7e89;font-size:11px}.part{color:#7a909a;font-size:18px;font-weight:400}.appendix h1{font-size:26px}.appendix header{margin-bottom:16px}.appendix-intro{font-size:12.5px;line-height:1.8;margin-bottom:13px}\n\n.danger{border-color:#b94d43;background:#fcefed}.danger b{color:#98352f}\n'
OUTPUT=ROOT/'docs/Masar_Optimizer_V2_AR.html'
OUTPUT.write_text('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>مسار | توقع أربع سنوات وتخطيط الشعب</title><style>'+CSS+'</style></head><body>'+''.join(PAGES)+'</body></html>',encoding='utf-8')
print('Generated',len(PAGES),'pages:',OUTPUT)
