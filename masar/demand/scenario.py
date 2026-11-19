"""Prepare the scheduling input and retain the source data needed for reporting."""
import json
from dataclasses import dataclass
from pathlib import Path

from masar.settings import (
    apply_major_totals, apply_room_capacities, apply_student_counts,
    read_course_switches, read_major_totals, read_settings,
)
from .enrollment import read_intakes, with_intake_enrollments
from .estimated_meetings import with_estimated_meetings
from .external_courses import with_external_courses
from .requests import with_course_requests
from .room_free import with_room_free_activities
from .student_groups import with_plan_groups


@dataclass
class Scenario:
    """Keep solver input and the reference data used to explain the results together."""
    data: dict
    reference: dict
    historical_reference: dict
    curriculum: dict | None
    demand_source: str


class ScenarioOptionError(ValueError):
    """The selected scheduling mode is incompatible with the input."""


def _read_json(path):
    """Load a saved JSON document as Python data."""
    return json.loads(path.read_text(encoding='utf-8'))


def _apply_course_requirements(reference, curriculum, meeting_codes, room_free_codes, external):
    """Add the meeting and room rules for courses with special teaching arrangements."""
    if meeting_codes:
        reference = with_estimated_meetings(reference, curriculum, meeting_codes)
    if room_free_codes:
        reference = with_room_free_activities(reference, curriculum, room_free_codes)
    if external.get('enabled'):
        reference = with_external_courses(reference, external)
    return reference


def _teaching_reference(historical, curriculum, forecast, room_capacities):
    """Build the list of enabled sections with the rooms and meeting patterns they can use."""
    reference = apply_room_capacities(historical, room_capacities)
    enabled = set(forecast['enabled_course_codes'])
    reference = _apply_course_requirements(
        reference, curriculum,
        [code for code in (forecast.get('estimated_meeting_courses') or []) if code in enabled],
        [code for code in (forecast.get('room_free_course_codes') or []) if code in enabled],
        forecast.get('external_courses', {}),
    )
    reference['sections'] = [s for s in reference['sections'] if s['course_code'] in enabled]
    reference['course_catalog_scope'] = {
        'records': [r for r in curriculum['records']
                    if r['category'] in ('كلية إجباري', 'تخصص إجباري', 'تخصص اختياري')]
    }
    return reference


def _project_intakes(root, data, reference, curriculum, student_counts):
    """Distribute each major's students across cohorts and estimate their course enrollments."""
    forecast = data['enrollment_generation']
    names = forecast['program_names']
    totals = read_major_totals(root / 'settings', names)
    counts = apply_major_totals(student_counts, totals)
    intakes = apply_student_counts(read_intakes(root / forecast['intake_source']), counts, names)
    forecast = dict(forecast, major_student_totals=totals,
                    major_student_totals_source='settings/student/major_students.csv')
    data = with_intake_enrollments(reference, curriculum, intakes, policy=forecast,
                                   cached_projection=data.get('enrollment_projection'))

    # A second projection can use meeting patterns inferred from the first pass.
    if forecast.get('estimate_missing_profile_meetings'):
        projection = data['enrollment_projection']
        missing = {code for cohort in projection['cohorts'] for code in cohort['unavailable_courses']}
        if missing:
            forecast = dict(data['enrollment_generation'])
            courses = sorted(set(forecast.get('estimated_meeting_courses', [])) | missing)
            forecast['estimated_meeting_courses'] = courses
            reference = _apply_course_requirements(
                reference, curriculum, courses, forecast.get('room_free_course_codes', []),
                forecast.get('external_courses', {}),
            )
            data = with_intake_enrollments(reference, curriculum, intakes, policy=forecast,
                                           cached_projection=projection)
    return data, reference


def prepare_scenario(root: Path, input_path=None, requests_path=None, *,
                     fixed_sections=False, save_projection=False):
    """Build the solver input from a section list, course requests, or an intake forecast."""
    data = _read_json(input_path or root / 'data/masar_data_v2.json')
    forecast = data.get('enrollment_generation', {})
    # An explicit section list supplies its own room inventory and capacities.
    if input_path is None or forecast.get('enabled'):
        room_capacities, student_counts = read_settings(root / 'settings')
        data = apply_room_capacities(data, room_capacities)
    reference = historical = data
    curriculum = None
    source = 'section_counts'

    if forecast.get('enabled'):
        curriculum = _read_json(root / forecast['curriculum_source'])
        switches = read_course_switches(root / 'settings/courses',
                                       {r['course_code'] for r in curriculum['records']})
        forecast = dict(forecast, enabled_course_codes=sorted(code for code in switches if switches[code]))
        data['enrollment_generation'] = forecast
        historical = _read_json(root / forecast['reference_source'])
        if fixed_sections:
            raise ScenarioOptionError('--fixed-sections requires a fixed section input, not an intake-demand snapshot.')
        reference = _teaching_reference(historical, curriculum, forecast, room_capacities)

    if requests_path:
        data = with_course_requests(reference, _read_json(requests_path))
        source = 'supplied_course_requests'
        print('Demand source: supplied course requests.')
    elif forecast.get('enabled'):
        data, reference = _project_intakes(root, data, reference, curriculum, student_counts)
        source = 'intake_forecast'
        print(f"Estimated students: {data['enrollment_projection']['estimated_students']}; "
              f"cohort groups: {len(data['groups'])}")
        if save_projection:
            (root / 'data/masar_data_v2.json').write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    if source != 'intake_forecast':
        policy = data.get('group_generation', {})
        if policy.get('enabled'):
            curriculum = _read_json(root / policy['source'])
            data = with_plan_groups(data, curriculum)
            report = data['group_inference']
            print(f"Plan-derived groups: {report['group_count']}; "
                  f"modeled course enrollments: {report['modeled_course_enrollments']}/"
                  f"{report['total_course_enrollments']}")
        else:
            data.pop('group_inference', None)
    return Scenario(data, reference, historical, curriculum, source)
