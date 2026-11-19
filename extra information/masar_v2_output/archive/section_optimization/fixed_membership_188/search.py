"""Try minimum-capacity sections with several coherent student seating orders."""
import sys,json,copy,math,time,random
from collections import defaultdict,Counter
from pathlib import Path
sys.path.insert(0,'/home/lime/PycharmProjects/Massar')
from ortools.sat.python import cp_model
from masar.validation import prepare
from masar.sections import section_pool
from masar.scheduling.planning import _check_enrollments, _solve_with_memory_limit
from masar.scheduling.checker import inspect_solution
from masar.scheduling.resources import room_requirements
from masar.scheduling.solver import _group_coverage
root=Path('/home/lime/PycharmProjects/Massar');out=root/'extra information/masar_v2_output/section_optimization/fixed_membership_188';out.mkdir(parents=True,exist_ok=True)
data=json.loads((root/'extra information/masar_v2_output/input_snapshot.json').read_text());ctx=prepare(data)
assert not data['teachers_enabled'] and not data['shared_classes'], 'This experimental seating search requires the current teacher-free, separate-course scenario.'
requirements,_=room_requirements(ctx);lower=sum(r['minimum_sections'] for r in requirements);assert lower==188
sources=defaultdict(list)
for sid in ctx['section_event']:
 s=ctx['sections'][sid];sources[section_pool(s,ctx['patterns'])].append(s)
allgroups=list(ctx['groups'].values());beginning=time.monotonic()

def seating(variant):
 if variant==0:order=sorted(allgroups,key=lambda g:(g['study_semester'],g['program_id'],g['id']))
 elif variant==1:order=sorted(allgroups,key=lambda g:(g['program_id'],g['study_semester'],g['id']))
 elif variant==2:order=sorted(allgroups,key=lambda g:(g['study_semester'],g['program_id'],g['id']),reverse=True)
 else:
  ranks={g['parent_cohort_id']:0 for g in allgroups};rng=random.Random(variant)
  for k in ranks:ranks[k]=rng.random()
  order=sorted(allgroups,key=lambda g:(ranks[g['parent_cohort_id']],g['study_path_id'],g['id']))
 if variant%2:order=list(reversed(order))
 sections=[];patterns={};numbers=Counter();group_seats=defaultdict(dict)
 for key,templates in sorted(sources.items()):
  total=sum(s['students'] for s in templates)
  rooms=[r for r in ctx['rooms'].values() if r['type'] in data['compatibility'][key[2]]]
  capacities=[total] if key[1]=='online' else sorted({r['capacity'] for r in rooms},reverse=True)
  maximum=capacities[0];small=capacities[1] if len(capacities)>1 else maximum
  count=math.ceil(total/maximum)
  big=math.ceil(max(0,total-small*count)/(maximum-small)) if maximum>small else count
  caps=[maximum]*big+[small]*(count-big)
  if variant%3==1:caps.reverse()
  bins=[];remaining=total
  for cap in caps:
   load=min(cap,remaining);remaining-=load;numbers[key[0]]+=1
   s=copy.deepcopy(templates[0]);sid=f'{key[0]}_minimum_{numbers[key[0]]}'
   s.update(id=sid,section_number=numbers[key[0]],students=load,unmodeled_student_count=0)
   sections.append(s);bins.append([sid,load])
   patterns[sid]=sorted({pid for t in templates for pid in [t['pattern_id']]+data.get('section_pattern_options',{}).get(t['id'],[])})
  assert remaining==0 and len(bins)==count
  index=0
  for group in order:
   if not any(section_pool(ctx['sections'][sid],ctx['patterns'])==key for sid in group['section_ids']):continue
   n=group['students'];assigned=[]
   while n:
    while bins[index][1]==0:index+=1
    take=min(n,bins[index][1]);assigned.append([bins[index][0],take]);n-=take;bins[index][1]-=take
   group_seats[group['id']][key]=assigned
 groups=[]
 for group in allgroups:
  queues=list(group_seats[group['id']].values());left=group['students'];part=0
  while left:
   take=min(q[0][1] for q in queues);part+=1
   g={k:copy.deepcopy(v) for k,v in group.items() if k!='event_ids'}
   g.update(id=f"{group['id']}@minimum{part}",source_group_id=group['id'],students=take,section_ids=[q[0][0] for q in queues]);groups.append(g)
   for q in queues:
    q[0][1]-=take
    if q[0][1]==0:q.pop(0)
   left-=take
 return dict(data,sections=sections,groups=groups,section_pattern_options=patterns),patterns

for attempt in range(18):
 effective,options=seating(attempt);planned=prepare(effective);_check_enrollments(ctx,planned)
 model=cp_model.CpModel();room_intervals=defaultdict(list);patterns={};starts={};rooms={};student_intervals={}
 for s in effective['sections']:
  sid=s['id'];patterns[sid]={};starts[sid]={};rooms[sid]={}
  allowed=[None] if s['delivery']=='online' else [rid for rid,r in ctx['rooms'].items() if r['type'] in data['compatibility'][s['room_requirement']] and r['capacity']>=s['students']]
  for pid in options[sid]:
   p=ctx['patterns'][pid]
   if not p['starts']:continue
   flag=model.new_bool_var(f'{sid}@{pid}');start=model.new_int_var_from_domain(cp_model.Domain.from_values(p['starts']),f'start@{sid}@{pid}')
   patterns[sid][pid]=flag;starts[sid][pid]=start;rooms[sid][pid]={}
   for day in p['days']:student_intervals[sid,pid,day]=model.new_optional_fixed_size_interval_var(start,p['duration'],flag,f'{sid}@{pid}@{day}')
   for rid in allowed:
    chosen=model.new_bool_var(f'{sid}@{pid}@{rid}');rooms[sid][pid][rid]=chosen
    for day in p['days'] if rid is not None else []:room_intervals[rid,day].append(model.new_optional_fixed_size_interval_var(start,p['duration'],chosen,f'{sid}@{pid}@{rid}@{day}'))
   model.add(sum(rooms[sid][pid].values())==flag)
  model.add(sum(patterns[sid].values())==1)
 for rid,room in ctx['rooms'].items():
  for b in room['blackouts']:room_intervals[rid,b['day']].append(model.new_fixed_size_interval_var(b['start'],b['end']-b['start'],f"blackout@{rid}@{b['day']}@{b['start']}"))
 for intervals in room_intervals.values():model.add_no_overlap(intervals)
 for group in effective['groups']:
  daily=defaultdict(list)
  for sid in group['section_ids']:
   for pid in patterns[sid]:
    for day in ctx['patterns'][pid]['days']:daily[day].append(student_intervals[sid,pid,day])
  for intervals in daily.values():model.add_no_overlap(intervals)
 solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=25;solver.parameters.num_search_workers=4;solver.parameters.random_seed=attempt
 status,stopped,peak=_solve_with_memory_limit(solver,model,16384)
 print('Fixed seating trial',attempt,solver.status_name(status),'groups',len(effective['groups']),'peak MB',round(peak),flush=True)
 if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):continue
 assignments=[]
 for section in effective['sections']:
  sid=section['id'];pid=next(pid for pid,flag in patterns[sid].items() if solver.boolean_value(flag));rid=next(rid for rid,flag in rooms[sid][pid].items() if solver.boolean_value(flag));start=solver.value(starts[sid][pid]);p=ctx['patterns'][pid]
  section['pattern_id']=pid
  assignments.append(dict(event_id=sid,source_ids=[sid],start=start,room_id=rid,meetings=[dict(day=d,start=start,end=start+p['duration']) for d in p['days']]))
 effective['section_pattern_options']={};planned=prepare(effective);_check_enrollments(ctx,planned);validation=inspect_solution(planned,assignments);assert validation['valid'],validation['errors']
 route_counts=Counter(g['source_group_id'] for g in effective['groups']);data['solver_route_limit']=max(route_counts.values())
 (out/'input.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 result=dict(status='OPTIMAL',has_solution=True,assignments=assignments,validation=validation,diagnostics=[],mode='minimum_sections_fixed_membership',section_requirements=requirements,required_sections_lower_bound=lower,planned_sections=effective['sections'],planned_groups=effective['groups'],coverage=_group_coverage(planned),section_plan=dict(opened_sections=188,minimum_proven=True,section_count_bound=188,planning_seconds=time.monotonic()-beginning),search_statistics=dict(backend='fixed_membership',attempt=attempt,workers=4,route_limit=data['solver_route_limit'],observed_peak_rss_mb=peak,memory_limit_mb=16384),solver_seconds=time.monotonic()-beginning)
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('VALIDATED 188 SECTIONS',flush=True);break
else:
 (out/'input.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 (out/'result.json').write_text(json.dumps(dict(status='UNKNOWN',has_solution=False,diagnostics=['Fixed seating attempts found no timetable; unrestricted feasibility remains unknown.']),ensure_ascii=False,indent=2)+'\n')
