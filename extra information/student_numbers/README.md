> **Active scenario:** 1,600 estimated students; **188 scheduled teaching sections**, plus 10 room-free projects/training activities; all 111 catalog courses represented. Independent validation found zero hard-constraint violations. The 188-section count matches the capacity lower bound, proving the minimum for the current model. Maximum student population is not established. Earlier scenario descriptions below are historical.

> Current full-demand scenario: 56 IT courses, 2,300 represented students, 34 user-approved estimated meeting patterns. Current hours are unchanged. The model is INFEASIBLE: a 3,100 weekly student-hour shortage. Current CSV contains 192 unscheduled proposals; the earlier 108-section result below describes the archived partial scenario.

> Active IT-only scope: faculty compulsory, major compulsory, and selected major electives only. University courses are excluded. Each program selects 9 major-elective credits across the degree. Current timetable: 108 sections with times/rooms; zero detected hard violations; minimum proven for modeled demand. Missing IT-course meeting data remains in the reports.

> Current enlarged-room scenario: **2,300 estimated students; 109 scheduled sections; minimum proven; zero detected hard violations.** Classrooms are 80–100 seats and labs 40, by user request. CSV/JSON reports contain current section assignments and times; historical figures below describe earlier scenarios.

> Active scenario updated to **2,300 students**: 575/year, SE244 + CS73 + AI73 + CYBER73 + CIS112. The numerical discussion below describes the earlier 3,032-student audit; use the regenerated CSV/JSON reports for current results.

# أعداد الطلبة

## المقبولون حسب الفصل — 2023 إلى 2026

الملف: [student_expected_number_for_each_semester.csv](student_expected_number_for_each_semester.csv)

| التخصص | الفصل الأول سنويًا | مجموع أربع دفعات |
|---|---:|---:|
| هندسة البرمجيات | 322 | 1,288 |
| علم الحاسوب | 96 | 384 |
| علم البيانات والذكاء الاصطناعي | 96 | 384 |
| الأمن السيبراني | 96 | 384 |
| نظم المعلومات الحاسوبية | 148 | 592 |
| **الإجمالي** | **758** | **3,032** |

الأعداد الأصلية التي أفاد بها المستخدم للفصل الأول 2026 هي: 322 لهندسة البرمجيات، و148 لنظم المعلومات، و288 مجموع علم الحاسوب والذكاء الاصطناعي والأمن السيبراني معًا.

لفصل الأعداد، وُزّع العدد المشترك **بالتساوي كتقدير**: 288 ÷ 3 = **96 لكل تخصص**. هذا ليس عددًا فرديًا مؤكدًا لكل تخصص. لا تُضاف الـ288 مرة أخرى إلى صفوف التخصصات، لأنها مجموعها نفسه.

بموافقة المستخدم، استُخدمت أعداد الفصل الأول 2026 كتقدير للفصل الأول في السنوات 2023 و2024 و2025. تميّز أعمدة الحالة والملاحظات الأعداد المقدمة مباشرة عن التقديرات.

الفصل الثاني مدرج لكل سنة دون أرقام؛ وصف المستخدم العدد بأنه أقل بكثير من الفصل الأول، ولم يحدد عددًا أو نسبة. «غير محدد» لا تعني صفرًا.

## ملخص أربع سنوات

الملف: [four_year_student_summary.csv](four_year_student_summary.csv)

يمثل **3,032** مجموع قبول أربع دفعات للفصل الأول في السنوات 2023–2026. لا يشمل المقبولين في الفصول الثانية، ولم تُخصم منه حالات التخرج أو الانسحاب؛ لذلك ليس إحصاءً مؤكدًا للطلبة النشطين حاليًا.

تُستخدم هذه الأرقام الآن في المحسن لبناء 20 دفعة تخصص/سنة، ثم توقع طلب المواد وفق خطة تقدم دراسي مستنتجة. السياسة تفترض الاحتفاظ بكل الدفعات وتستبعد أعداد الفصل الثاني المجهولة. تفاصيل المنهج والحدود في `../student_groups/student_groups_method.md`.

ملفات التوقع الجديدة:

- `cohort_student_estimates.csv`: أعداد الدفعات العشرين وسنواتها وموادها المتاحة وغير المتاحة.
- `inferred_study_plans.csv`: توزيع دراسي مستنتج على ثمانية فصول لكل تخصص، وليس خطة فصلية رسمية.
- `course_enrollment_projection.csv`: الطلب المتوقع لكل مادة في القالب المرجعي، مع فصل المجهول عن الصفر.
- `section_requirements.csv`: الحد الأدنى للشعب حسب السعة، وليس جدولًا قابلًا للتنفيذ.
- `room_capacity_shortfalls.csv`: العجز المثبت في ساعات إشغال القاعات.
- `enrollment_projection.json`: التوقع والافتراضات وحالة المحسن بصيغة منظمة.

النتيجة الحالية غير قابلة للجدولة بالقاعات والأوقات المعرّفة؛ الحد الأدنى حسب السعة 209 شعب. راجع تقرير عجز القاعات.

## مجموع التسجيلات لكل مادة

الملف: [course_student_counts.csv](course_student_counts.csv)

يعرض الطلب المتوقع الحالي لكل مادة في القالب المرجعي. العدد صفر يعني أن المادة لم تختر في الفصل المفترض؛ «غير محدد» تعني رمزًا بلا تطابق مع الخطط. مواد التدريب والمشاريع بلا لقاءات لا تتطلب شعبًا زمنية. الطالب المسجل في أكثر من مادة يُحسب في مجموع كل مادة، لذلك لا يمثل مجموع هذا الملف عدد أشخاص فريدين، ولا يُقارن مباشرة بـ758 مقبولًا في الفصل الأول 2026 أو بمجموع الأربع دفعات المقدر بـ3,032.

تحديث التدقيق: لم تعد الخطة تدفع المواد المعروضة نحو الفصل الحالي. لا يزال المجتمع 3,032 طالبًا؛ تمثل المواد المعروضة 2,840 منهم، وتبقى بيانات 192 طالبًا في جدول الدفعات دون مواد معروضة في فصلهم المستنتج. راجع مجلد model_audit لفجوات التغطية ومقارنة الشعب.


Current section optimization: 197 → 191 teaching sections, with 1,600 students and all 111 courses unchanged. See `section_optimization.csv` for each course and `section_optimization.json` for the trials. The lower bound is 188; exact minimum is unproven. Ten projects/training activities remain outside the teaching-section count.


Current target result: **191 → 188 teaching sections**, keeping 1,600 students and all 111 courses. The 188-section lower bound is attained and the minimum is proved for the current model. Ten room-free activities remain separate. `section_optimization.json`, `section_optimization.csv`, and the certificate in `masar_v2_output/result.json` contain the evidence. The normal solver budget is now 1,800 seconds.
