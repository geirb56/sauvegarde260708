// Synthetic, contract-based presentation examples; not actual Garmin evidence.
export const c356Kinds = ['intervals', 'probable-easy', 'unknown-treadmill'] as const;

export function c356Workout(kind: typeof c356Kinds[number]) {
  const unknown = kind === 'unknown-treadmill';
  const intervals = kind === 'intervals';
  const workout = {
    id: `c356-${kind}`, name: intervals ? 'Synthetic · 4 × 4 min' : unknown ? 'Synthetic · Treadmill' : 'Synthetic · Probable easy run',
    type: 'run', date: '2026-10-18T08:00:00Z',
    distance_km: unknown ? null : intervals ? 7.2 : 6,
    duration_minutes: unknown ? 30 : 40,
    avg_pace_min_km: unknown ? null : intervals ? 5.55 : 6.67,
    avg_heart_rate: unknown ? null : intervals ? 151 : 132,
    max_heart_rate: unknown ? null : intervals ? 175 : 145,
    km_splits: unknown ? [] : Array.from({ length: 6 }, (_, i) => ({
      km: i + 1, pace_min_km: intervals ? [6.5, 4.8, 6.4, 4.7, 6.3, 4.8][i] : 6.65 + i * 0.01,
    })),
  };
  const primaryText = intervals
    ? 'Tes quatre efforts sont restés proches les uns des autres.'
    : unknown ? 'Les données disponibles ne permettent pas de caractériser cette séance.'
      : 'Cette sortie ressemble à une endurance facile, sans certitude physiologique.';
  const item = (code: string, text: string, evidence: object, kind = 'observation') => ({
    code, text, evidence, kind, source_paths: ['workout.duration_minutes'], replaces_factual_codes: [],
  });
  const analysis = {
    version: 'v2', workout,
    summary: { code: 'summary.standard_structural', text: primaryText },
    signals: {
      intensity: { available: false, code: null, text: null, reason_unavailable: 'Pas de zones individualisées.' },
      volume: { available: false, code: null },
      session_type: { available: true, code: 'standard', text: 'Séance enregistrée' },
      session_structure: { available: !unknown, code: unknown ? null : intervals ? 'intervals' : 'continuous' },
    },
    physiology: { available: !unknown, avg_hr: workout.avg_heart_rate, max_hr: workout.max_heart_rate, zone_distribution: null, hr_drift: null },
    pacing: { available: !unknown, average_pace_min_km: workout.avg_pace_min_km, average_speed_kmh: null,
      fastest_split_min_km: unknown ? null : intervals ? 4.7 : 6.65,
      slowest_split_min_km: unknown ? null : intervals ? 6.5 : 6.7,
      pace_drop_min_km: unknown ? null : 0, negative_split: null, consistency_score: null, variability: null },
    comparison: { available: false, baseline_period_days: 14, baseline_sample_count: 0, distance_km: null, duration_minutes: null,
      avg_heart_rate: null, avg_pace_min_km: null, avg_speed_kmh: null, reason_unavailable: 'Pas de référence comparable.' },
    meaning: { code: 'meaning.structural', text: primaryText, factual_observations: [] },
    advice: { available: false, code: null, text: null },
    evidence: { has_heart_rate: !unknown, has_hr_zones: false, has_splits: !unknown, has_baseline: false, has_cadence: false, has_elevation: false },
    session_synthesis: {
      version: 'v2', status: 'available',
      primary: item(unknown ? 'synthesis.unknown' : intervals ? 'synthesis.execution' : 'synthesis.probable_easy', primaryText,
        { duration_minutes: workout.duration_minutes }, unknown || !intervals ? 'interpretation' : 'observation'),
      supporting: unknown ? [] : [item('synthesis.measured', intervals ? 'Quatre répétitions de quatre minutes sont enregistrées.' : 'Les kilomètres enregistrés sont proches en allure.',
        intervals ? { effort_count: 4, effort_duration_s: 240 } : { split_count: 6 })],
      limitations: [{ code: 'limit.hr', text: unknown ? 'Distance, allure et fréquence cardiaque indisponibles.' : 'Sans zones individualisées, l’intensité physiologique reste incertaine.', source_paths: ['physiology'] }],
      abstention: null,
    },
    phase_analysis: intervals ? {
      available: true, analysis_type: 'structured_phases',
      phases: Array.from({ length: 8 }, (_, i) => ({
        order: i + 1, phase_type: i % 2 ? 'recovery' : 'effort',
        ...(i % 2 ? { recovery_number: (i + 1) / 2 } : { effort_number: i / 2 + 1 }),
        duration_s: i % 2 ? 120 : 240, distance_m: i % 2 ? 200 : 830,
        pace_sec_per_km: i % 2 ? 600 : 289, average_hr: i % 2 ? 130 : 158, max_hr: i % 2 ? 145 : 175,
      })),
      efforts: [], recoveries: [],
      effort_statistics: { count: 4, total_duration_s: 960, total_distance_m: 3320, average_pace_sec_per_km: 289, average_hr: 158, max_hr: 175 },
      recovery_statistics: { count: 4, total_duration_s: 480, total_distance_m: 800 },
      effort_regularity: { available: true, effort_count: 4, comparable_effort_count: 4, comparability_basis: 'duration', pace_sample_count: 4, partial_comparison: false, pace_dispersion_sec_per_km: 0, first_to_last_pace_change_sec_per_km: 0, average_hr_change_bpm: 0 },
      missing_data: [], limitations: [],
    } : { available: false },
  };
  if (intervals) {
    analysis.phase_analysis.efforts = analysis.phase_analysis.phases.filter(p => p.phase_type === 'effort') as never[];
    analysis.phase_analysis.recoveries = analysis.phase_analysis.phases.filter(p => p.phase_type === 'recovery') as never[];
  }
  const headline = intervals ? 'Four efforts, a controlled rhythm'
    : unknown ? 'Too little evidence to classify this treadmill session'
      : 'A probable easy run, not a confirmed physiological zone';
  const limitation = unknown
    ? 'Distance, pace and heart rate are unavailable; no intensity or progression can be inferred.'
    : 'Without individualized thresholds, physiological intensity remains uncertain.';
  const intelligence = {
    workout_id: workout.id,
    workout_intelligence_v3: {
      version: 'v3', workout_id: workout.id, analyzed_date: workout.date,
      data_used: ['synthetic_contract_fixture'],
      intensity_assessment: {
        position: 'unknown', confidence: 'none', hr_used_bpm: workout.avg_heart_rate,
        session_max_hr_bpm: workout.max_heart_rate, limitations: [limitation], source_paths: [],
      },
      session_classification: {
        type: unknown ? 'unknown' : intervals ? 'intervals' : 'easy_run_probable',
        decision_tier: unknown ? 'insufficient_data' : intervals ? 'garmin_phases' : 'individual_history',
        confidence: unknown ? 'none' : intervals ? 'high' : 'medium',
        evidence: intervals ? { effort_count: 4, recovery_count: 4 } : {},
        rules: [], limitations: [limitation], source_paths: [],
        relative_effort: {
          status: !unknown && !intervals ? 'used' : 'not_applicable',
          relative_position: !unknown && !intervals ? 'low' : null,
          reference_count: !unknown && !intervals ? 6 : 0,
          workout_ids: !unknown && !intervals ? Array.from({ length: 6 }, (_, i) => `synthetic-reference-${i}`) : [],
        },
      },
      historical_comparison: {
        status: 'insufficient', comparability: 'insufficient', candidate_count: 0, reference_count: 0,
        window_days: 90, pace_at_comparable_hr: { reference_count: 0, hr_tolerance_bpm: 5 },
        hr_at_comparable_pace: { reference_count: 0, pace_tolerance_sec_per_km: 15 },
        v2_similar_reference: { available: false, sample_count: 0, workout_ids: [] },
        limitations: ['Insufficient comparable history.'], source_paths: [],
      },
      performance_trend: { status: 'insufficient_data', confidence: 'none', observation_count: 0, limitations: [], source_paths: [] },
      prescription_assessment: { status: 'unavailable', reasons: ['No synthetic prescription supplied.'], source_paths: [] },
      coach_assessment: {
        language: 'en', diagnosis: { code: 'synthetic.diagnosis', text: headline, evidence: {}, source_paths: [] },
        evidence: [], limitations: [], advice: null,
      },
    },
    narrative_coach_v3: {
      headline, language: 'en', generation_mode: 'deterministic_fallback',
      analysis: intervals ? 'The recorded phases show four four-minute efforts, each followed by a two-minute recovery.'
        : unknown ? 'Only the thirty-minute duration is recorded in this synthetic example.'
          : 'The recorded kilometres have similar paces, and this synthetic personal-history comparison places the effort toward the lower end.',
      interpretation: unknown ? 'The session remains unclassified rather than being described as an easy run.'
        : intervals ? 'This describes the repeated work, not a physiological intensity zone.'
          : 'Probable easy running is a relative interpretation, not proof of being below LT1.',
      recommendation: null, limitations: [limitation], evidence_refs: ['workout_intelligence_v3.session_classification'],
    },
  };
  return { workout, analysis, intelligence };
}
