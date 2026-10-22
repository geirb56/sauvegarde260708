import { test, expect } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { c356Kinds, c356Workout } from '../fixtures/c356-workouts';

const stage = process.env.C356_STAGE || 'after';
if (!['before', 'after'].includes(stage)) throw new Error('C356_STAGE must be before or after');
const origin = 'http://localhost:3000';
const assets = path.resolve(__dirname, '../../docs/reports/assets/c356');
test.use({
  baseURL: origin,
  launchOptions: { executablePath: process.env.C356_CHROMIUM_PATH || '/opt/google/chrome/chrome' },
});

for (const [viewportName, viewport] of Object.entries({
  desktop: { width: 1440, height: 1100 },
  mobile: { width: 390, height: 844 },
})) {
  for (const kind of c356Kinds) {
    test(`${stage}: ${kind}, ${viewportName}`, async ({ page }) => {
      mkdirSync(assets, { recursive: true });
      const fixture = c356Workout(kind);
      const apiRequests: string[] = [];
      const blockedExternal: string[] = [];
      const unexpectedApi: string[] = [];
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setViewportSize(viewport);
      await page.addInitScript(() => {
        localStorage.setItem('access_token', 'c356-synthetic-illustrative-nonsecret');
        localStorage.setItem('runindex_lang', 'en');
        localStorage.setItem('runindex_unit_system', 'metric');
      });
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        // Mock API URLs even if the frontend was compiled with an external API origin.
        if (url.pathname.startsWith('/api/')) {
          apiRequests.push(url.pathname);
          let body: unknown;
          if (url.pathname === '/api/auth/me') body = { id: 'c356-synthetic-user', email: 'synthetic@example.invalid', name: 'Synthetic C356', onboarding_completed: true };
          else if (url.pathname === '/api/user/features') body = { plan: 'premium', has_premium_access: true, feature_access: { coach_workout_analysis: true } };
          else if (url.pathname === '/api/subscription/info') body = { plan: 'premium', status: 'active' };
          else if (url.pathname === `/api/workouts/${fixture.workout.id}`) body = fixture.workout;
          else if (url.pathname === `/api/coach/workout-analysis/${fixture.workout.id}`) body = fixture.analysis;
          else if (url.pathname === `/api/coach/workout-intelligence/${fixture.workout.id}`) body = fixture.intelligence;
          else {
            unexpectedApi.push(url.pathname);
            return route.fulfill({ status: 200, json: {} });
          }
          return route.fulfill({ status: 200, json: body });
        }
        if (url.origin !== origin) {
          blockedExternal.push(url.origin + url.pathname);
          return route.abort();
        }
        return route.continue();
      });
      const metrics: unknown[] = [];
      const routes = stage === 'before'
        ? [`/workout/${fixture.workout.id}`]
        : [`/workout/${fixture.workout.id}`, `/sessions/${fixture.workout.id}`, `/workout/${fixture.workout.id}/analysis`];
      for (const [index, pathname] of routes.entries()) {
        let initialCoachBounds: { x: number; y: number; width: number; height: number } | null = null;
        let initialScrollY: number | null = null;
        await page.goto(pathname);
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
        await expect.poll(() => apiRequests.filter(url => url.includes('/coach/workout-analysis/')).length).toBeGreaterThan(index);
        await expect(page.locator('[data-testid="narrative-coach"], [data-testid="coach-summary"], [data-testid="session-synthesis"]').first()).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        if (stage === 'after') {
          const coach = page.getByTestId('narrative-coach');
          await expect(coach).toHaveCount(1);
          await expect(coach).toBeVisible();
          await expect(coach.getByRole('heading', { level: 2 })).toBeVisible();
          await expect(coach.getByRole('heading', { level: 2 })).toHaveText(fixture.intelligence.narrative_coach_v3.headline);
          await expect(coach.getByRole('heading', { level: 2 })).toBeInViewport();
          const initial = await coach.evaluate(el => {
            const rect = el.getBoundingClientRect();
            return { bounds: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, scrollY };
          });
          initialCoachBounds = initial.bounds;
          initialScrollY = initial.scrollY;
          const evidence = page.getByTestId('workout-evidence');
          await expect(evidence).toBeVisible();
          const details = page.getByTestId('workout-analysis-details');
          if (kind === 'unknown-treadmill') {
            await expect(details).toHaveCount(0);
          } else {
            await expect(details).toBeAttached();
            const summary = details.locator(':scope > summary');
            await expect(summary).toBeVisible();
            await expect(details).not.toHaveAttribute('open', '');
          }
          if (index === 0) {
            await page.screenshot({ path: path.join(assets, `${stage}-${kind}-${viewportName}.png`), fullPage: true, animations: 'disabled' });
          }
          for (const summary of await details.locator('summary').all()) {
            if (!(await summary.evaluate(el => (el.parentElement as HTMLDetailsElement).open))) {
              await summary.focus();
              await page.keyboard.press('Enter');
              await expect.poll(() => summary.evaluate(el => (el.parentElement as HTMLDetailsElement).open)).toBe(true);
            }
          }
        }
        const postExpansionScrollY = await page.evaluate(() => scrollY);
        await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
        const layout = await page.evaluate(() => ({
          measurementScrollY: scrollY,
          viewportWidth: innerWidth, documentWidth: document.documentElement.scrollWidth,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
          heading: document.querySelector('[data-testid="narrative-coach"] h2')?.textContent || null,
          coachBounds: (() => {
            const rect = document.querySelector('[data-testid="narrative-coach"]')?.getBoundingClientRect();
            return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null;
          })(),
          detailsCount: document.querySelectorAll('[data-testid="workout-analysis-details"]').length,
          headings: Array.from(document.querySelectorAll('h1,h2')).map(el => el.textContent),
          bodyText: document.body.innerText,
        }));
        metrics.push({ pathname, initialCoachBounds, initialScrollY, postExpansionScrollY, ...layout });
        expect(layout.horizontalOverflow).toBe(false);
        if (stage === 'after') {
          expect(layout.coachBounds?.width).toBeLessThanOrEqual(768);
        }
        if (index === 0 && stage === 'before') {
          await page.screenshot({ path: path.join(assets, `${stage}-${kind}-${viewportName}.png`), fullPage: true, animations: 'disabled' });
        }
      }
      writeFileSync(path.join(assets, `${stage}-${kind}-${viewportName}.json`), JSON.stringify({
        stage, kind, viewportName, fixture: 'synthetic contract-based; not actual Garmin evidence',
        head: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
        workingTreeDirty: execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim().length > 0,
        sourceNote: stage === 'after'
          ? 'Captured against the working tree; head is the commit present at capture time. Consult workingTreeDirty for uncommitted changes; the final report records the validated committed source.'
          : 'Captured before C356 page integration; head identifies the baseline commit.',
        apiRequests, unexpectedApi, blockedExternal, errors, metrics,
      }, null, 2));
      expect(errors).toEqual([]);
      expect(unexpectedApi).toEqual([]);
    });
  }
}
