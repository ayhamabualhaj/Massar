"""Turn semester intake scenarios into cohort course demand, without multiplying
one course's enrollment by the entire four-year population.
"""
import copy
import csv
import math
import hashlib
import json
import random
from collections import Counter, defaultdict

from ortools.sat.python import cp_model

from masar.sections import section_pool
from .room_free import allocate_room_free_activity
from masar.validation import need, prepare


FRESHMAN_METHOD = 'balanced_prerequisites_v3'
UNIVERSITY_REQUIREMENTS = {'جامعة إجباري', 'جامعة اختياري'}


DEFAULT_POLICY = dict(
    enabled=True, reference_source='data/masar_section_templates.json',
    intake_source='extra information/student_numbers/student_expected_number_for_each_semester.csv',
    curriculum_source='course_requirements/five_majors_degree_plans.json',
    current_year=2026, current_semester=1, years=4, semesters_per_year=2,
    scheduling_categories=None, study_paths_per_program=1,
    plan_semesters=8, max_semester_credits=18, retain_all_cohorts=True,
    study_plan_method=FRESHMAN_METHOD,
    program_names={'SE':'هندسة البرمجيات','CS':'علم الحاسوب',
                   'AI':'علم البيانات والذكاء الاصطناعي','CYBER':'الأمن السيبراني',
                   'CIS':'نظم المعلومات الحاسوبية'})


def read_intakes(path):
    """Read the admission counts for each major and semester from the intake CSV."""
    with open(path, encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def _study_plan(records, offered, config, avoid=None, variant=0, required_current_code=None, hint=None, target_terms=None):
    """Infer one complete eight-semester plan, not an official semester schedule.

    Prerequisites are hard constraints. Balance credit loads first, then prefer
    earlier foundational teaching. Current offerings must not determine parity:
    doing that biases the very enrollment demand we are trying to estimate.
    """
    index={r['course_code']:r for r in records if r['credit_hours']>0}
    need(len(index)==sum(r['credit_hours']>0 for r in records),'Duplicate plan courses.')
    model=cp_model.CpModel()
    slots={}
    selected={}
    terms=config['plan_semesters']
    for code,row in index.items():
        selected[code]=model.new_bool_var('selected@'+code)
        slots[code]=[model.new_bool_var(f'{code}@term{s+1}') for s in range(terms)]
        model.add(sum(slots[code])==selected[code])
        if 'اختياري' not in row['category']:
            model.add(selected[code]==1)
    for semester in range(terms):
        model.add(sum(index[c]['credit_hours']*slots[c][semester] for c in index)
                  <=config['max_semester_credits'])
    if config['study_plan_method'] == FRESHMAN_METHOD:
        # Term one is relative to admission, for both fall and spring entrants.
        model.add(sum(r['credit_hours'] * slots[c][0] for c, r in index.items()) == 12)
        university = sum(r['credit_hours'] * slots[c][0] for c, r in index.items()
                         if r['category'] in UNIVERSITY_REQUIREMENTS)
        model.add_linear_constraint(university, 6, 9)
    for code,row in index.items():
        for requirement in row['requirements']:
            prerequisite=requirement['course_code']
            if prerequisite not in index:
                # Zero-credit placement/remedial requirements are assumed met;
                # no remedial intake rate was supplied.
                continue
            model.add(selected[code]<=selected[prerequisite])
            for semester in range(terms):
                end=semester+int(requirement['concurrent_allowed'])
                model.add(slots[code][semester]<=sum(slots[prerequisite][:end]))
        threshold=row.get('minimum_completed_hours') or 0
        if threshold:
            for semester in range(terms):
                completed=sum(index[c]['credit_hours']*sum(slots[c][:semester]) for c in index)
                model.add(completed>=threshold).only_enforce_if(slots[code][semester])
    uni=[c for c,r in index.items() if r['category']=='جامعة اختياري']
    electives=[c for c,r in index.items() if r['category']=='تخصص اختياري']
    if uni:
        model.add(sum(index[c]['credit_hours']*selected[c] for c in uni)==9)
        for basket in {index[c]['elective_basket'] for c in uni}:
            model.add(sum(index[c]['credit_hours']*selected[c] for c in uni
                          if index[c]['elective_basket']==basket)<=3)
    if electives:
        model.add(sum(index[c]['credit_hours']*selected[c] for c in electives)==9)
    # A varied path must differ in every currently represented study semester,
    # not merely shuffle an unrelated future course or rename a group.
    categories=set(config.get('scheduling_categories') or [r['category'] for r in records])
    for previous in avoid or []:
        for term in range(config['current_semester'],terms+1,2):
            old=[c for c,semester in previous.items() if semester==term and index[c]['category'] in categories]
            if old:
                model.add(sum(slots[c][term-1] for c in old)<=len(old)-1)
    objective=[]
    maximum_load=model.new_int_var(0,config['max_semester_credits'],'maximum_credit_load')
    for semester in range(terms):
        model.add(sum(index[c]['credit_hours']*slots[c][semester] for c in index)<=maximum_load)
    # This coefficient dominates every possible secondary objective difference.
    objective.append(maximum_load*(1+terms*sum(r['credit_hours'] for r in index.values()))*(1000 if variant else 1))
    rng=random.Random(variant)
    for code,row in index.items():
        for semester,flag in enumerate(slots[code]):
            if variant:
                objective.append(flag*((semester+1)*row['credit_hours']*100+rng.randrange(100)))
            else:
                objective.append(flag*(semester+1)*row['credit_hours'])
    model.minimize(sum(objective))
    if required_current_code:
        need(required_current_code in index,'Coverage target is not in this program.')
        model.add(selected[required_current_code]==1)
        if target_terms is not None:
            model.add(sum(slots[required_current_code][term - 1] for term in target_terms) == 1)
        for term in range(config['current_semester'],terms+1,2):
            model.add(sum(slots[c][term-1] for c in index
                          if index[c]['category'] in categories)>=1)
        if hint:
            for code,flags in slots.items():
                model.add_hint(selected[code],int(code in hint))
                for term,flag in enumerate(flags,1):
                    model.add_hint(flag,int(hint.get(code)==term))
        # Find a complete valid path; coverage is independent of room capacity.
        model.clear_objective()
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=20 if variant or required_current_code else 5
    solver.parameters.num_search_workers=4 if variant or required_current_code else 1
    solver.parameters.random_seed=0
    status=solver.solve(model)
    need(status in (cp_model.OPTIMAL,cp_model.FEASIBLE),f'Cannot construct study path variant {variant}, target {required_current_code} ({solver.status_name(status)}).')
    assignment={code:next(s+1 for s,flag in enumerate(flags) if solver.boolean_value(flag))
                for code,flags in slots.items() if solver.boolean_value(selected[code])}
    return assignment,dict(status=solver.status_name(status), inferred=True,
                           method=config['study_plan_method'],
                           credits=sum(index[c]['credit_hours'] for c in assignment))


def _allocate(total,weights):
    """Divide a student total by weight while keeping the rounded counts equal to the original total."""
    denominator=sum(weights.values())
    need(denominator>0,'Template pool weights must be positive.')
    allocation={key:total*value//denominator for key,value in weights.items()}
    remainder=total-sum(allocation.values())
    order=sorted(weights,key=lambda key:(-(total*weights[key]%denominator),key))
    for key in order[:remainder]:
        allocation[key]+=1
    return allocation


def _check_study_plan(records, assignment, config):
    """Check that a semester plan follows the degree requirements before using it."""
    index={r['course_code']:r for r in records if r['credit_hours']>0}
    need(set(assignment)<=index.keys(),'Cached study plan contains unknown courses.')
    need(all(type(s) is int and 1<=s<=config['plan_semesters'] for s in assignment.values()),
         'Invalid study semester.')
    need(all(c in assignment for c,r in index.items() if 'اختياري' not in r['category']),
         'Study plan dropped a compulsory course.')
    credits=Counter()
    for code,semester in assignment.items():
        row=index[code]
        credits[semester]+=row['credit_hours']
        for req in row['requirements']:
            if req['course_code'] not in index:
                continue
            need(req['course_code'] in assignment,'Study plan dropped a prerequisite.')
            before=assignment[req['course_code']]
            need(before<semester or (req['concurrent_allowed'] and before==semester),
                 'Study plan violates a prerequisite.')
        completed=sum(index[c]['credit_hours'] for c,s in assignment.items() if s<semester)
        need(completed>=(row.get('minimum_completed_hours') or 0),'Study plan violates completed-credit threshold.')
    need(all(n<=config['max_semester_credits'] for n in credits.values()),'Semester credit limit exceeded.')
    if config['study_plan_method'] == FRESHMAN_METHOD:
        university = sum(index[c]['credit_hours'] for c, term in assignment.items()
                         if term == 1 and index[c]['category'] in UNIVERSITY_REQUIREMENTS)
        need(credits[1] == 12 and 6 <= university <= 9, 'Invalid first-semester credit load.')
    for category in ('جامعة اختياري','تخصص اختياري'):
        options=[c for c,r in index.items() if r['category']==category]
        if options:
            need(sum(index[c]['credit_hours'] for c in options if c in assignment)==9,
                 'Study plan elective selection must equal 9 credits.')
    baskets=Counter()
    for c in assignment:
        if index[c]['category']=='جامعة اختياري':
            baskets[index[c]['elective_basket']]+=index[c]['credit_hours']
    need(all(n<=3 for n in baskets.values()),'University elective basket limit exceeded.')


def with_intake_enrollments(reference,curriculum,intakes,policy=None, cached_projection=None):
    """Estimate each cohort's courses and use those estimates to fill the section enrollments."""
    config=dict(DEFAULT_POLICY,**(policy or {}))
    need(config['study_plan_method'] in (FRESHMAN_METHOD, 'balanced_prerequisites_v2'),'Unsupported study plan method.')
    need(config['current_semester'] in (1,2),'Current semester must be 1 or 2.')
    need(config['retain_all_cohorts'] is True,'Only the explicitly documented full-retention scenario is supported.')
    need(config['years']==4 and config['semesters_per_year']==2 and config['plan_semesters']==8,
         'Expected four years and eight study semesters.')
    need(type(config['max_semester_credits']) is int and config['max_semester_credits']>0,
         'Invalid semester credit limit.')
    output=copy.deepcopy(reference)
    output['groups']=[]
    output.pop('group_inference',None)
    output.pop('enrollment_projection',None)
    output.pop('resource_diagnostics',None)
    prepare(output)
    need(not output.get('shared_classes'),'Intake projection requires separate courses.')
    records=curriculum['records'] if isinstance(curriculum,dict) else curriculum
    programs=defaultdict(list)
    for row in records:
        programs[row['program_id']].append(row)
    offered=defaultdict(list)
    for section in reference['sections']:
        if section['status']=='scheduled':
            offered[section['course_code']].append(section)
    matched={row['course_code'] for row in records}&offered.keys()
    indexes={p:{r['course_code']:r for r in rows} for p,rows in programs.items()}
    categories=config.get('scheduling_categories')
    need(categories is None or (isinstance(categories,list) and categories
         and set(categories)<={'كلية إجباري','تخصص إجباري','تخصص اختياري'}),
         'Only faculty compulsory, major compulsory and major elective scheduling categories are supported.')
    enabled_codes=set(config.get('enabled_course_codes',
        [r['course_code'] for r in records]))
    eligible_category=lambda row: categories is None or row['category'] in categories
    eligible=lambda row: eligible_category(row) and row['course_code'] in enabled_codes
    allowed_codes={r['course_code'] for r in records if eligible(r)}
    offered={code:sections for code,sections in offered.items() if code in allowed_codes}
    fingerprint=hashlib.sha256(json.dumps(dict(records=records, method=config['study_plan_method'],
        semesters=config['plan_semesters'], credits=config['max_semester_credits'],
        ),sort_keys=True).encode()).hexdigest()
    plans={}
    plan_info={}
    cached=cached_projection or {}
    for program,rows in sorted(programs.items()):
        if cached.get('plan_fingerprint')==fingerprint and program in cached.get('study_plans',{}):
            plans[program]=copy.deepcopy(cached['study_plans'][program]['semesters'])
            plan_info[program]=copy.deepcopy(cached['study_plans'][program]['info'])
        else:
            plans[program],plan_info[program]=_study_plan(rows,matched,config)
        _check_study_plan(rows,plans[program],config)
    path_count=config.get('study_paths_per_program',1)
    need(type(path_count) is int and 1<=path_count<=5,'Expected 1 to 5 study paths per program.')
    path_fingerprint=hashlib.sha256((fingerprint+str(path_count)+str(config['current_semester'])+
        str(categories)+'diverse_paths_v1').encode()).hexdigest()
    study_paths={}
    for program,rows in sorted(programs.items()):
        if (cached.get('study_path_fingerprint')==path_fingerprint
                and program in cached.get('study_paths',{})):
            study_paths[program]=copy.deepcopy(cached['study_paths'][program])
        else:
            study_paths[program]=[dict(id='P1',semesters=copy.deepcopy(plans[program]),info=copy.deepcopy(plan_info[program]))]
            for variant in range(1,path_count):
                assignment,info=_study_plan(rows,matched,config,
                    avoid=[path['semesters'] for path in study_paths[program]],variant=variant)
                study_paths[program].append(dict(id=f'P{variant+1}',semesters=assignment,info=info))
        need(len(study_paths[program])>=path_count if config.get('require_positive_course_demand') else len(study_paths[program])==path_count,'Cached path count changed.')
        for path in study_paths[program]:
            _check_study_plan(rows,path['semesters'],config)
        need(len({path['id'] for path in study_paths[program]})==len(study_paths[program]),'Duplicate study path IDs.')
        if path_count>1:
            for term in range(config['current_semester'],config['plan_semesters']+1,2):
                bundles={tuple(sorted(c for c,s in path['semesters'].items() if s==term and eligible_category(indexes[program][c])))
                         for path in study_paths[program][:path_count]}
                need(len(bundles)==path_count,f'{program}: cached paths do not diversify term {term}.')
    intake_index={}
    skipped_second=[]
    for row in intakes:
        if row['نوع الصف']!='تخصص مستقل':
            continue
        year=int(row['السنة المرجعية'])
        if not config['current_year']-config['years']+1<=year<=config['current_year']:
            continue
        need(row['الفصل'] in ('الأول','الثاني'),'Invalid intake semester label.')
        semester=1 if row['الفصل']=='الأول' else 2
        program=next((p for p,name in config['program_names'].items()
                      if name==row['التخصص أو مجموعة التخصصات']),None)
        need(program in programs,f"Unknown intake program: {row['التخصص أو مجموعة التخصصات']}")
        token=row['عدد الطلبة الجدد']
        if token=='غير محدد':
            if semester==2:
                skipped_second.append(dict(program_id=program,intake_year=year))
            need(semester==2,'Missing first-semester individual-program intake estimate.')
            continue
        count=int(token)
        need(count>=0,'Intake must be nonnegative.')
        key=(program,year,semester)
        need(key not in intake_index,'Duplicate individual-program intake row.')
        intake_index[key]=count

    def academic_term(calendar_term, offset):
        """Keep first-time entrants at term one even on accelerated study paths."""
        if config['study_plan_method'] == FRESHMAN_METHOD:
            if calendar_term == 1:
                return 1
            return max(2, min(config['plan_semesters'], calendar_term + offset))
        return calendar_term + offset

    calendar_terms = defaultdict(set)
    for (program, year, semester), count in intake_index.items():
        term = (config['current_year'] - year) * 2 + config['current_semester'] - semester + 1
        if count and 1 <= term <= config['plan_semesters']:
            calendar_terms[program].add(term)

    if config.get('require_positive_course_demand'):
        def covered_codes():
            """Find the courses represented by the study paths at the eligible semester stages."""
            return {code for program,paths in study_paths.items() for path in paths
                    for code,term in path['semesters'].items()
                    if eligible(indexes[program][code])
                    and term in {academic_term(t, path.get('progression_offset', 0))
                                 for t in calendar_terms[program]}}
        for code in sorted(allowed_codes-covered_codes()):
            if code in covered_codes():
                continue
            options=sorted((p for p in programs if calendar_terms[p] and code in indexes[p] and eligible(indexes[p][code])),
                           key=lambda p:(len(study_paths[p]),p))
            need(bool(options),f'{code}: no eligible major for positive demand.')
            # Existing plans can cover other academic stages in the SAME calendar
            # semester; course availability is never tied to odd/even plan terms.
            program=options[0]
            reachable = {academic_term(t, offset) for t in calendar_terms[program] for offset in (0, 1, -1)}
            existing = next((path for path in study_paths[program]
                             if path['semesters'].get(code) in reachable), None)
            if existing:
                assignment=copy.deepcopy(existing['semesters'])
                info=copy.deepcopy(existing['info'])
            else:
                assignment,info=_study_plan(programs[program],matched,config,
                    required_current_code=code,hint=plans[program],target_terms=reachable)
            offset=0 if assignment[code]%2==config['current_semester']%2 else (1 if config['current_semester']==1 else -1)
            if config['study_plan_method'] == FRESHMAN_METHOD:
                offsets = [n for n in (0, 1, -1) if assignment[code] in
                           {academic_term(t, n) for t in calendar_terms[program]}]
                need(bool(offsets), f'{code}: no enrolled cohort can attend this study stage.')
                offset = offsets[0]
            _check_study_plan(programs[program],assignment,config)
            study_paths[program].append(dict(id=f'P{len(study_paths[program])+1}',semesters=assignment,
                info=info,coverage_target=code,progression_offset=offset))
        need(allowed_codes<=covered_codes(),'Some catalog courses have no valid current-semester path.')
    cohorts=[]
    demand=Counter()
    all_demand=Counter()
    program_allocation=defaultdict(Counter)
    for (program,year,intake_semester),students in sorted(intake_index.items()):
        calendar_term=(config['current_year']-year)*2+config['current_semester']-intake_semester+1
        if not 1<=calendar_term<=config['plan_semesters']:
            continue
        shares=_allocate(students,{path['id']:1 for path in study_paths[program]})
        for path in study_paths[program]:
            study_semester=academic_term(calendar_term, path.get('progression_offset', 0))
            need(1<=study_semester<=config['plan_semesters'],'Profile academic progress is outside its degree plan.')
            path_students=shares[path['id']]
            if path_students==0:
                continue
            planned=sorted(c for c,s in path['semesters'].items() if s==study_semester and eligible(indexes[program][c]))
            available=[c for c in planned if c in offered]
            activities=[c for c in planned if c in config.get('room_free_course_codes',[])]
            missing=[c for c in planned if c not in offered and c not in activities]
            cohort=dict(id=f'INTAKE_{program}_{year}_S{intake_semester}'+(f"_{path['id']}" if len(study_paths[program])>1 else ''),program_id=program,
                        program_name=config['program_names'][program],intake_year=year,
                        intake_semester=intake_semester,study_year=(study_semester+1)//2,
                        study_semester=study_semester,calendar_study_semester=calendar_term,
                        progression_offset=study_semester-calendar_term,students=path_students,
                        study_path_id=path['id'],parent_cohort_id=f'INTAKE_{program}_{year}_S{intake_semester}',
                        assumed_completed_course_codes=sorted(c for c,s in path['semesters'].items() if s<study_semester),
                        planned_courses=planned,offered_courses=available,room_free_courses=activities,unavailable_courses=missing,
                        planned_credit_hours=sum(indexes[program][c]['credit_hours'] for c in planned),
                        offered_credit_hours=sum(indexes[program][c]['credit_hours'] for c in available))
            if config['study_plan_method'] == FRESHMAN_METHOD:
                term_rows = [indexes[program][c] for c, t in path['semesters'].items() if t == study_semester]
                cohort['total_credit_hours'] = sum(r['credit_hours'] for r in term_rows)
                cohort['university_credit_hours'] = sum(r['credit_hours'] for r in term_rows
                                                       if r['category'] in UNIVERSITY_REQUIREMENTS)
            cohorts.append(cohort)
            for code in planned:
                all_demand[code]+=path_students
                program_allocation[code][program]+=path_students
            for code in available:
                demand[code]+=path_students
    need(bool(demand),'Intake scenario has no offered course demand.')
    pool_sections=defaultdict(list)
    for code in demand:
        for section in offered[code]:
            pool_sections[section_pool(section,reference['patterns'])].append(section)
    by_course=defaultdict(list)
    for pool in pool_sections:
        by_course[pool[0]].append(pool)
    budgets={}
    refs={}
    caps={}
    for code in sorted(demand):
        weights={pool:sum(s['students'] for s in pool_sections[pool]) for pool in by_course[code]}
        amounts=_allocate(demand[code],weights)
        for pool,amount in amounts.items():
            if amount==0:
                continue
            template=copy.deepcopy(sorted(pool_sections[pool],key=lambda s:s['id'])[0])
            template['students']=amount
            template['id']=f'{code}_demand_{len(refs)+1}'
            template['unmodeled_student_count']=0
            template['assumptions']=[a for a in template.get('assumptions',[])
                                     if 'Enrollment' not in a]
            template['assumptions'].append('Enrollment projected from four intake cohorts, inferred semester plan, and reference pool proportions.')
            template['enrollment_status']='estimated_from_intakes'
            refs[pool]=template
            if reference['teachers_enabled']:
                template['teacher_ids']=sorted({tid for s in pool_sections[pool] for tid in s['teacher_ids']})
            budgets[pool]=amount
            allowed=[r['capacity'] for r in reference['rooms']
                     if r['type'] in reference['compatibility'][pool[2]]]
            caps[pool]=amount if pool[1]=='online' else max(allowed,default=0)
            need(caps[pool]>0,f'{code}: no room type supports its reference requirements.')
    groups=[]
    for cohort in cohorts:
        courses=cohort['offered_courses']
        remaining=cohort['students']
        if not courses:
            continue
        sequence=0
        while remaining:
            chosen={code:min((pool for pool in by_course[code] if budgets.get(pool,0)>0),
                             key=lambda pool:(-budgets[pool],pool)) for code in courses}
            size=min([remaining]+[min(budgets[pool],caps[pool]) for pool in chosen.values()])
            need(size>0,'Cannot allocate cohort enrollment to source pools.')
            sequence+=1
            program=cohort['program_id']
            evidence=[dict(course_code=c,course_name=indexes[program][c]['course_name'],
                           credit_hours=indexes[program][c]['credit_hours'],
                           category=indexes[program][c]['category'],
                           prerequisites=copy.deepcopy(indexes[program][c]['requirements']),
                           source_image=indexes[program][c].get('source_image',''),notes='') for c in courses]
            groups.append(dict(id=f"{cohort['id']}_G{sequence:02d}",students=size,
                splittable=True,
                section_ids=[refs[chosen[c]]['id'] for c in courses],
                status='estimated_from_four_year_intakes',program_id=program,
                program_name=cohort['program_name'],intake_year=cohort['intake_year'],
                intake_semester=cohort['intake_semester'],study_year=cohort['study_year'],
                study_semester=cohort['study_semester'],prerequisite_level=cohort['study_semester'],
                cohort_id=cohort['id'],study_path_id=cohort['study_path_id'],
                parent_cohort_id=cohort['parent_cohort_id'],progression_offset=cohort.get('progression_offset',0),course_codes=courses,
                credit_hours=cohort['offered_credit_hours'],course_evidence=evidence,
                assumed_completed_course_codes=cohort['assumed_completed_course_codes'],
                requirements_source=config['curriculum_source'],
                basis='Four-year intake forecast; normal progression and full retention assumed; splittable demand batches, not mandatory intact classes.'))
            for pool in chosen.values():
                budgets[pool]-=size
            remaining-=size
    need(not any(budgets.values()),'Cohort assignments did not conserve pool enrollment.')
    # Preserve every allowed pattern for each pool without adding its enrollment
    # again. The planner reads these as alternatives, not extra demanded sections.
    activities=[]
    for section in reference['sections']:
        if section['status']=='no_meeting_days' and section['course_code'] in allowed_codes:
            if section.get('room_free_activity'):
                if not all_demand[section['course_code']]:
                    continue
                for group in allocate_room_free_activity(section, all_demand[section['course_code']]):
                    group['enrollment_status']='estimated_from_intakes'
                    activities.append(group)
            else:
                activities.append(copy.deepcopy(section))
    output['sections']=list(refs.values())+activities
    output['section_pattern_options']={refs[pool]['id']:sorted({s['pattern_id'] for s in templates})
                                       for pool,templates in pool_sections.items() if pool in refs}
    output['groups']=groups
    output['group_generation']=dict(enabled=False,method='four_year_intake_cohorts')
    output['enrollment_generation']=config
    course_coverage=[]
    all_reference=defaultdict(list)
    plan_codes={r['course_code'] for r in records}
    for section in reference['sections']:
        if categories is None or section['course_code'] in allowed_codes:
            all_reference[section['course_code']].append(section)
    for code in sorted(all_reference):
        non_meeting=code not in offered
        known=code in plan_codes
        course_coverage.append(dict(course_code=code,course_name=all_reference[code][0]['name_ar'],
            students=(all_demand[code] if non_meeting else demand[code]) if known else None,
            modeled_students=demand[code],unmodeled_students=all_demand[code] if non_meeting and known else 0 if known else None,
            program_allocation=dict(program_allocation[code]),
            reason='non_meeting_course' if non_meeting else 'fully_modeled' if demand[code] else
                   ('not_selected_this_semester' if code in matched else 'no_exact_plan_code_match')))
    scoped_curriculum=[copy.deepcopy(r) for r in records if eligible(r)]
    output['course_catalog_scope']=dict(categories=categories,records=scoped_curriculum,
        major_elective_credits_per_degree=9,
        excluded_records=len(records)-len(scoped_curriculum),
        basis='Degree-plan codes and per-program categories; source schedule provides meeting information only.')
    represented=sum(g['students'] for g in groups)
    total_students=sum(c['students'] for c in cohorts)
    report=dict(method='four_year_intake_cohorts',inferred=True,actual_registrations=False,
                policy=config,group_count=len(groups),cohort_count=len(cohorts),
                inferred_group_students=represented,estimated_students=total_students,
                students_without_offered_courses=total_students-represented,
                scheduled_courses=len(demand),exact_plan_matched_courses=len(matched),grouped_courses=len(demand),
                modeled_course_enrollments=sum(demand.values()),total_course_enrollments=sum(demand.values()),
                unmodeled_course_enrollments=None,course_coverage=course_coverage,
                assumptions=[
                  'All four first-semester intake cohorts are retained; no graduation, withdrawal or repeat rates were supplied.',
                  'Intake values come from the current individual-major scenario rows; CS/AI/CYBER retain equal estimated shares derived from their original combined intake.',
                  'Unknown second-semester intakes are excluded, not treated as confirmed zero.',
                  'Normal progression: 2026/2025/2024/2023 cohorts attend study semesters 1/3/5/7 in first semester 2026.',
                  'An inferred eight-semester, 132-credit plan respects strict prerequisites, permitted concurrency, elective limits and 90-credit thresholds.',
                  'Credit loads are balanced without using current offerings to choose semester parity; the inferred plan is not an official recommended study plan.',
                  'Estimated groups are demand batches; their members can attend different sections, each retaining the complete requested course combination.',
                  'Only currently offered exact course codes are assigned; unavailable planned courses are explicitly reported.',
                  'Enrollment among different reference delivery/equipment pools is proportional to their reference counts; these proportions remain estimates.',
                  'Legacy course codes without an exact plan match have unknown demand and are not assigned the old synthetic counts.'])
    if config['study_plan_method'] == FRESHMAN_METHOD:
        report['assumptions'].append('The first semester after admission has 12 total credits, including 6 to 9 university requirement credits, for both fall and spring entrants.')
    if categories is not None:
        report['assumptions'].append('Only faculty compulsory, major compulsory and selected major electives are scheduled. University courses remain context for degree progression and completed-credit thresholds, and are excluded from timetable demand.')
        report['assumptions'].append('Each representative student selects exactly 9 major-elective credits over the full degree, not 9 each semester; unselected electives do not create sections.')
    if config.get('require_positive_course_demand'):
        need(allowed_codes<=set(all_demand),'Every IT catalog course must have genuine positive profile demand.')
        report['assumptions'].append('Every IT course is offered each calendar semester. Coverage profiles may differ by one academic step, representing estimated varied progression. Their own completed-course histories satisfy prerequisites; no course is assigned solely by calendar parity. Shares are illustrative, not measured acceleration or repeat rates.')
    output['group_inference']=report
    output['enrollment_projection']=dict(estimated_students=total_students,represented_students=represented,
        plan_fingerprint=fingerprint,
        study_path_fingerprint=path_fingerprint,study_paths=study_paths,
        cohorts=cohorts,study_plans={p:dict(info=plan_info[p],semesters=plans[p]) for p in plans},
        excluded_unknown_second_semester_intakes=skipped_second,
        course_coverage=course_coverage,assumptions=report['assumptions'])
    if path_count>1:
        report['admission_cohort_count']=len(intake_index)
        report['assumptions'].append('Prerequisite-valid paths per major: '+str({p:len(v) for p,v in study_paths.items()})+'. Each intake is divided equally using integer remainders. Extra coverage paths ensure every IT course has positive current-semester demand. These are scenario estimates, not observed shares.')
        report['assumptions'].append('Students of the same major/year can have different completed courses, current course bundles and major electives. Every path still completes 132 degree credits and 9 major-elective credits; credits are not reduced to force room feasibility.')
    output.setdefault('provenance',{})['group_basis']='Four-year intake cohort projection; see enrollment_projection and group_inference.'
    prepare(output)
    return output
