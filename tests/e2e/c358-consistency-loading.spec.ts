import { test, expect, Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { c358Workout, copy, Language, referenceDistances, referenceMAD, referenceStd, partialSyntheticStd } from '../fixtures/c358-workouts';

const origin = 'http://localhost:3000';
const assets = path.resolve(__dirname, '../test-results/c358-evidence');
const root = path.resolve(__dirname, '../..');
const baseline = process.env.C358_BASE_SHA || execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const scenarios = ['delayed', 'immediate', 'http500', 'absent', 'incomplete', 'v2-error', 'partial', 'v2-pending-v3-error'] as const;
const routes = {
  WorkoutDetail: (id: string) => `/workout/${id}`,
  SessionDetail: (id: string) => `/sessions/${id}`,
  DetailedAnalysis: (id: string) => `/workout/${id}/analysis`,
};
const legacySelectors = '[data-testid="session-synthesis"], [data-testid="coach-language"], [data-testid="meaning-text"], [data-testid="advice-text"], [data-testid="header-context"]';
test.use({ baseURL: origin, launchOptions: { executablePath: '/opt/google/chrome/chrome' } });

function gate() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}

async function layout(page: Page) {
  return page.evaluate(() => ({
    viewportWidth: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    scrollY,
    text: document.body.innerText,
    coachCount: document.querySelectorAll('[data-testid="narrative-coach"]').length,
    openDetails: document.querySelectorAll('details[open]').length,
  }));
}

test('SYNTHETIC reference arithmetic is independently reproducible', () => {
  const paces = referenceDistances.map(distance => 240000 / distance);
  const sorted = [...paces].sort((a, b) => a - b);
  const median = (sorted[1] + sorted[2]) / 2;
  const mean = paces.reduce((sum, value) => sum + value, 0) / 4;
  expect(c358Workout('en').analysis.phase_analysis.effort_statistics.average_pace_sec_per_km).toBeCloseTo(283.03125651330096, 12);
  expect(paces.reduce((sum, value) => sum + Math.abs(value - median), 0) / 4).toBeCloseTo(referenceMAD, 12);
  expect(Math.sqrt(paces.reduce((sum, value) => sum + (value - mean) ** 2, 0) / 4)).toBeCloseTo(referenceStd, 12);
});

for (const [viewportName, viewport] of Object.entries({
  desktop: { width: 1920, height: 1080 },
  mobile: { width: 390, height: 844 },
})) {
  for (const language of ['fr', 'en', 'es'] as Language[]) {
    for (const [routeName, pathname] of Object.entries(routes)) {
      for (const scenario of scenarios) {
        if (scenario === 'v2-pending-v3-error' && routeName !== 'DetailedAnalysis') continue;
        test(`SYNTHETIC ${routeName} ${viewportName} ${language} ${scenario}`, async ({ page }) => {
          mkdirSync(assets, { recursive: true });
          const fixture = c358Workout(language, scenario === 'partial');
          const contentGate = gate();
          const v3Gate = gate();
          const requests: string[] = [];
          const unexpectedApi: string[] = [];
          const blockedExternal: string[] = [];
          const errors: string[] = [];
          const states: unknown[] = [];
          const captures: string[] = [];
          const capture = language === 'en' && ['delayed', 'http500'].includes(scenario);
          let v3Started = 0;
          let v3Completed = 0;
          page.on('pageerror', error => errors.push(error.message));
          await page.setViewportSize(viewport);
          await page.addInitScript(({ language }) => {
            localStorage.setItem('access_token', 'c358-synthetic-illustrative-nonsecret');
            localStorage.setItem('runindex_lang', language);
            localStorage.setItem('runindex_unit_system', 'metric');
          }, { language });
          await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            if (url.pathname.startsWith('/api/')) {
              requests.push(url.pathname);
              if (url.pathname === '/api/auth/me') return route.fulfill({ json: {
                id: 'c358-synthetic-user', email: 'synthetic@example.invalid',
                name: 'SYNTHETIC C358', onboarding_completed: true,
              } });
              if (url.pathname === '/api/user/features') return route.fulfill({ json: {
                plan: 'premium', has_premium_access: true, feature_access: { coach_workout_analysis: true },
              } });
              if (url.pathname === '/api/subscription/info') return route.fulfill({ json: { plan: 'premium', status: 'active' } });
              if (url.pathname === `/api/workouts/${fixture.workout.id}`) {
                if (scenario === 'delayed') await contentGate.promise;
                return route.fulfill({ json: fixture.workout });
              }
              if (url.pathname === `/api/coach/workout-analysis/${fixture.workout.id}`) {
                if (scenario === 'delayed' || scenario === 'v2-pending-v3-error') await contentGate.promise;
                return route.fulfill({ status: scenario === 'v2-error' ? 500 : 200, json: fixture.analysis });
              }
              if (url.pathname === `/api/coach/workout-intelligence/${fixture.workout.id}`) {
                expect(url.searchParams.get('language')).toBe(language);
                v3Started = Date.now();
                if (scenario === 'delayed') await v3Gate.promise;
                const body = scenario === 'absent' ? {} : scenario === 'incomplete'
                  ? { ...fixture.intelligence, narrative_coach_v3: { ...fixture.intelligence.narrative_coach_v3, interpretation: '' } }
                  : fixture.intelligence;
                v3Completed = Date.now();
                return route.fulfill({ status: ['http500', 'v2-pending-v3-error'].includes(scenario) ? 500 : 200, json: body });
              }
              unexpectedApi.push(url.pathname);
              return route.fulfill({ status: 200, json: {} });
            }
            // API interception precedes this check, including externally configured
            // API origins. No Garmin or other external request reaches the network.
            if (url.origin !== origin) {
              blockedExternal.push(url.origin + url.pathname);
              return route.abort();
            }
            return route.continue();
          });
          const record = async (state: string, screenshot = capture) => {
            await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
            const measured = await layout(page);
            states.push({ state, ...measured });
            expect(measured.horizontalOverflow, `${state}: horizontal overflow`).toBe(false);
            if (screenshot) {
              const filename = `${routeName}-${viewportName}-${language}-${scenario}-${state}.png`;
              await page.screenshot({ path: path.join(assets, filename), fullPage: true, animations: 'disabled' });
              captures.push(filename);
            }
          };
          const assertPending = async () => {
            await expect(page.getByTestId('coach-pending')).toHaveText(copy[language].pending);
            await expect(page.getByTestId('coach-pending')).toBeVisible();
            await expect(page.getByTestId('narrative-coach')).toHaveCount(0);
            await expect(page.locator(legacySelectors)).toHaveCount(0);
            await expect(page.getByText(copy[language].legacy, { exact: true })).toHaveCount(0);
            await expect(page.getByRole('heading', { level: 1 })).toHaveText(fixture.workout.name);
            await expect(page.getByText(/151.*bpm/).first()).toBeVisible();
          };
          try {
            await page.goto(pathname(fixture.workout.id), { waitUntil: 'domcontentloaded' });
            if (scenario === 'v2-pending-v3-error') {
              await expect.poll(() => v3Completed).toBeGreaterThan(0);
              await expect(page.getByRole('heading', { level: 1 })).toHaveText(fixture.workout.name);
              await expect(page.getByText(/151.*bpm/).first()).toBeVisible();
              await expect(page.getByRole('status').filter({
                hasText: /temporarily unavailable|temporairement indisponible|no está disponible temporalmente/,
              })).toBeVisible();
              await expect(page.getByTestId('analysis-not-found')).toHaveCount(0);
              await expect(page.getByTestId('coach-language')).toHaveCount(0);
              await record('v2-pending-after-v3-error', false);
              contentGate.release();
            }
            if (scenario === 'delayed') {
              await expect.poll(() => v3Started).toBeGreaterThan(0);
              await record('initial');
              contentGate.release();
              await assertPending();
              await record('local-placeholder');
              // A gated network response remains unresolved for a real 2500 ms,
              // independent of animation clocks and screenshot timing.
              await new Promise(resolve => setTimeout(resolve, 2500));
              await assertPending();
              await record('delayed-2500ms');
              v3Gate.release();
            }
            const valid = ['delayed', 'immediate', 'v2-error', 'partial'].includes(scenario);
            await expect.poll(() => v3Completed).toBeGreaterThan(0);
            await expect(page.getByTestId('coach-pending')).toHaveCount(0);
            await expect(page.getByRole('heading', { level: 1 })).toHaveText(fixture.workout.name);
            await expect(page.getByText(/151.*bpm/).first()).toBeVisible();
            if (valid) {
              const coach = page.getByTestId('narrative-coach');
              await expect(coach).toHaveCount(1);
              await expect(coach).toBeVisible();
              await expect(coach.getByRole('heading', { level: 2 })).toHaveText(scenario === 'partial' ? copy[language].partialHeadline : copy[language].headline);
              await expect(coach.getByText(scenario === 'partial' ? copy[language].partial : copy[language].analysis, { exact: true })).toBeVisible();
              const paragraphs = (await coach.locator('p').allTextContents()).map(text => text.trim()).filter(Boolean);
              expect(new Set(paragraphs).size, 'Coach paragraphs must not duplicate narrative prose').toBe(paragraphs.length);
              if (scenario === 'partial') {
                await expect(coach.getByText(copy[language].partialInterpretation, { exact: true })).toBeVisible();
                await expect(coach.getByText(copy[language].limitation, { exact: true })).toHaveCount(1);
              }
              await expect(page.locator(legacySelectors)).toHaveCount(0);
              await expect(coach).not.toContainText(language === 'en' ? '7.7' : '7,7');
              await expect(coach).not.toContainText(/16[.,]6/);
              await expect(page.getByTestId('workout-evidence')).toBeVisible();
              const details = page.getByTestId('workout-analysis-details');
              await expect(details).toHaveCount(1);
              await expect(details).not.toHaveAttribute('open', '');
              await record('valid');
              await details.locator(':scope > summary').click();
              if (scenario !== 'v2-error') {
                const regularity = page.getByTestId('effort-regularity');
                await expect(regularity).toBeVisible();
                await expect(regularity).toContainText(copy[language].std);
                await expect(regularity).toContainText(scenario === 'partial' ? /16[.,]6/ : /7[.,]7/);
                await expect(regularity).toContainText(scenario === 'partial' ? '4/6' : '4/4');
                await expect(regularity).not.toContainText(/\b6[.,]6\b/);
                await expect(page.getByTestId('phase-effort-row')).toHaveCount(scenario === 'partial' ? 6 : 4);
              }
              for (const summary of await details.locator('details > summary').all()) {
                await summary.click();
              }
              await record('expanded', false);
            } else {
              await expect(page.getByTestId('narrative-coach')).toHaveCount(0);
              await expect(page.getByText(copy[language].legacy, { exact: false }).first()).toBeVisible();
              await record('fallback');
            }
            if (scenario === 'delayed') expect(v3Completed - v3Started).toBeGreaterThanOrEqual(2500);
            expect(errors).toEqual([]);
            expect(unexpectedApi).toEqual([]);
          } finally {
            contentGate.release();
            v3Gate.release();
            const sourcePaths = [
              'tests/e2e/c358-consistency-loading.spec.ts', 'tests/fixtures/c358-workouts.ts',
              'tests/fixtures/c356-workouts.ts', 'frontend/src/pages/WorkoutDetail.jsx',
              'frontend/src/pages/SessionDetail.jsx', 'frontend/src/pages/DetailedAnalysis.jsx',
              'frontend/src/hooks/useWorkoutIntelligence.js', 'frontend/src/components/workout/WorkoutPhaseAnalysis.jsx',
              'frontend/src/components/workout/WorkoutCoachPending.jsx', 'frontend/src/lib/i18n.js',
            ];
            const sourceHashes = Object.fromEntries(sourcePaths.map(file => [
              file, createHash('sha256').update(readFileSync(path.join(root, file))).digest('hex'),
            ]));
            writeFileSync(path.join(assets, `${routeName}-${viewportName}-${language}-${scenario}.json`), JSON.stringify({
              provenance: 'SYNTHETIC intercepted API responses in the actual locally served React app; not actual Garmin observations.',
              base: baseline,
              baseNote: 'C358_BASE_SHA if supplied, otherwise HEAD at suite module load; not an inferred integration-branch merge base.',
              head: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
              workingTreeDirty: execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim().length > 0,
              sourceHashes, routeName, viewportName, viewport, language, scenario,
              reference: { durations_s: [240, 240, 240, 240], distances_m: referenceDistances, meanAbsoluteDeviationAroundMedian: referenceMAD, populationStd: referenceStd },
              partialSyntheticStd: scenario === 'partial' ? partialSyntheticStd : null,
              partialNote: scenario === 'partial' ? 'Injected 16.5621 is synthetic UI contract input, not recomputed from reference paces; six efforts with four usable paces, no regularity verdict.' : null,
              v3PendingDurationMs: v3Completed && v3Started ? v3Completed - v3Started : null,
              captures,
              captureSha256: Object.fromEntries(captures.map(filename => [
                filename, createHash('sha256').update(readFileSync(path.join(assets, filename))).digest('hex'),
              ])),
              requests, unexpectedApi, blockedExternal, errors, states,
            }, null, 2));
          }
        });
      }
    }
  }
}
