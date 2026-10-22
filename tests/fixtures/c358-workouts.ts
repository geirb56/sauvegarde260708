import { c356Workout } from './c356-workouts';

export const referenceDistances = [832.07, 851.11, 885.81, 825.41];
export const referenceMAD = 6.569673797567631;
export const referenceStd = 7.687007906315586;
export const partialSyntheticStd = 16.5621;
export type Language = 'fr' | 'en' | 'es';

export const copy = {
  en: {
    headline: 'SYNTHETIC · Four recorded efforts',
    partialHeadline: 'SYNTHETIC · Six efforts, four usable paces',
    analysis: 'Noticeable pace variations across four efforts: mean absolute deviation around the median (MAD), an average gap of 6.6 s/km.',
    interpretation: 'These noticeable pace variations describe the recorded execution, not a physiological intensity zone.',
    limitation: 'SYNTHETIC API fixture, not Garmin evidence. Individualized thresholds are unavailable.',
    partial: 'Only 4 of 6 efforts have a usable pace; the partial sample does not support a regularity verdict.',
    partialInterpretation: 'This partial comparison does not establish regularity or irregularity.',
    legacy: 'SYNTHETIC · Legacy V2 narrative',
    pending: 'Coach analysis in progress…',
    std: 'Pace standard deviation',
  },
  fr: {
    headline: 'SYNTHETIC · Quatre efforts enregistrés',
    partialHeadline: 'SYNTHETIC · Six efforts, quatre allures exploitables',
    analysis: 'Variations d’allure notables sur quatre efforts : écart absolu moyen autour de la médiane (MAD), soit un écart moyen de 6,6 s/km.',
    interpretation: 'Ces variations d’allure notables décrivent l’exécution enregistrée, pas une zone physiologique.',
    limitation: 'SYNTHETIC : réponse API simulée, pas une preuve Garmin. Seuils individualisés indisponibles.',
    partial: 'Seuls 4 efforts sur 6 ont une allure exploitable ; cet échantillon partiel ne permet aucun verdict de régularité.',
    partialInterpretation: 'Cette comparaison partielle ne permet d’établir ni régularité ni irrégularité.',
    legacy: 'SYNTHETIC · Ancienne synthèse V2',
    pending: 'Analyse Coach en cours…',
    std: 'Écart-type des allures',
  },
  es: {
    headline: 'SYNTHETIC · Cuatro esfuerzos registrados',
    partialHeadline: 'SYNTHETIC · Seis esfuerzos, cuatro ritmos utilizables',
    analysis: 'Variaciones de ritmo notables en cuatro esfuerzos: desviación absoluta media respecto a la mediana (MAD), una diferencia media de 6,6 s/km.',
    interpretation: 'Estas variaciones de ritmo notables describen la ejecución registrada, no una zona fisiológica.',
    limitation: 'SYNTHETIC: respuesta API simulada, no evidencia Garmin. No hay umbrales individualizados.',
    partial: 'Solo 4 de 6 esfuerzos tienen un ritmo utilizable; la muestra parcial no permite un veredicto de regularidad.',
    partialInterpretation: 'Esta comparación parcial no permite establecer regularidad ni irregularidad.',
    legacy: 'SYNTHETIC · Síntesis anterior V2',
    pending: 'Análisis del Coach en curso…',
    std: 'Desviación estándar de los ritmos',
  },
};

export function c358Workout(language: Language, partial = false) {
  const fixture = c356Workout('intervals');
  const total = partial ? 6 : 4;
  fixture.workout.id = `c358-synthetic-${partial ? 'partial' : 'reference'}`;
  fixture.workout.name = `SYNTHETIC · ${total} × 4 min · C358`;
  const phases = fixture.analysis.phase_analysis;
  phases.phases = Array.from({ length: total * 2 }, (_, i) => {
    const effortIndex = Math.floor(i / 2);
    const recovery = i % 2 === 1;
    const distance = recovery ? 200 : referenceDistances[effortIndex] ?? null;
    return {
      order: i + 1, phase_type: recovery ? 'recovery' : 'effort',
      ...(recovery ? { recovery_number: effortIndex + 1 } : { effort_number: effortIndex + 1 }),
      duration_s: recovery ? 120 : 240,
      distance_m: distance,
      pace_sec_per_km: distance === null ? null : (recovery ? 120 : 240) * 1000 / distance,
      average_hr: recovery ? 130 : 158, max_hr: recovery ? 145 : 175,
    };
  }) as typeof phases.phases;
  phases.efforts = phases.phases.filter(p => p.phase_type === 'effort') as never[];
  phases.recoveries = phases.phases.filter(p => p.phase_type === 'recovery') as never[];
  phases.effort_statistics = {
    count: total, total_duration_s: total * 240,
    total_distance_m: referenceDistances.reduce((sum, value) => sum + value, 0),
    average_pace_sec_per_km: referenceDistances.reduce((sum, distance) => sum + 240000 / distance, 0) / 4,
    average_hr: 158, max_hr: 175,
  };
  phases.recovery_statistics = { count: total, total_duration_s: total * 120, total_distance_m: total * 200 };
  phases.effort_regularity = {
    available: true, effort_count: total, comparable_effort_count: total,
    comparability_basis: 'duration', pace_sample_count: 4, partial_comparison: partial,
    pace_dispersion_sec_per_km: partial ? partialSyntheticStd : referenceStd,
    first_to_last_pace_change_sec_per_km: 290.76458971904873 - 288.43727090268845,
    average_hr_change_bpm: 0,
  };
  if (partial) {
    Object.assign(phases.effort_statistics, { total_distance_m: null, average_pace_sec_per_km: null });
    Object.assign(phases.effort_regularity, { first_to_last_pace_change_sec_per_km: null });
  }
  // The partial 16.5621 is deliberately injected presentation evidence, not a
  // statistic derived from the four reference efforts.
  const text = copy[language];
  fixture.analysis.summary.text = text.legacy;
  fixture.analysis.meaning.text = text.legacy;
  fixture.analysis.session_synthesis.primary.text = text.legacy;
  fixture.analysis.session_synthesis.supporting = [];
  fixture.analysis.session_synthesis.limitations[0].text = text.limitation;
  fixture.analysis.signals.intensity.reason_unavailable = text.limitation;
  Object.assign(fixture.analysis, { coach_language: {
    version: 'v1',
    conclusions: [{
      available: true, kind: 'descriptive', code: 'synthetic.c358.legacy',
      category: 'execution', priority: 1, text: text.legacy,
      evidence: { effort_count: total }, source_paths: ['phase_analysis.effort_statistics.count'],
      replaces_factual_codes: [],
    }],
  } });
  fixture.intelligence.workout_id = fixture.workout.id;
  const facts = fixture.intelligence.workout_intelligence_v3;
  facts.workout_id = fixture.workout.id;
  facts.session_classification.evidence = { effort_count: total, recovery_count: total };
  facts.coach_assessment.language = language;
  facts.coach_assessment.diagnosis.text = partial ? text.partialHeadline : text.headline;
  fixture.intelligence.narrative_coach_v3 = {
    headline: partial ? text.partialHeadline : text.headline, language, generation_mode: 'deterministic_fallback',
    analysis: partial ? text.partial : text.analysis,
    interpretation: partial ? text.partialInterpretation : text.interpretation,
    recommendation: null, limitations: [text.limitation],
    evidence_refs: ['workout_intelligence_v3.session_classification'],
  };
  return fixture;
}
