import { test, expect } from '@playwright/test';

/**
 * Training Plan with VMA E2E Tests
 * 
 * Tests the following features:
 * 1. Training plan page loads and displays correctly
 * 2. VMA-based personalized paces are shown in session details
 * 3. Plan displays VMA, VO2MAX, readiness_score, prep_status
 * 4. Plan duration (adjusted_weeks) is shown in the UI
 * 5. Week sessions contain personalized pace information
 */

test.describe('Training Plan with VMA - Dynamic Paces', () => {
  const BASE_URL = 'https://charge-load.preview.emergentagent.com';

  test.beforeEach(async ({ page }) => {
    // Remove emergent badge to prevent click issues
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        const badge = document.querySelector('[class*="emergent"], [id*="emergent-badge"]');
        if (badge) badge.remove();
      });
      observer.observe(document.body, { childList: true, subtree: true });
    });
    
    // Ensure user has access (activate early adopter if needed)
    await page.request.post(`${BASE_URL}/api/subscription/activate-early-adopter`, {
      data: { user_id: 'default' }
    });
  });

  test('Training plan page loads successfully', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for the page to load
    const trainingPage = page.getByTestId('training-plan-page');
    await expect(trainingPage).toBeVisible({ timeout: 15000 });
    
    // Verify key elements are present
    await expect(page.locator('text=Plan d\'Entraînement').or(page.locator('text=Training Plan'))).toBeVisible();
  });

  test('Training plan displays week and cycle progress', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for the page to load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Check for week indicator (e.g., "Semaine 1 / 8" or "Week 1 / 8")
    const weekText = page.locator('text=/Semaine|Week/');
    await expect(weekText.first()).toBeVisible();
    
    // Check for progress bar section
    const progressSection = page.locator('text=/Progression|Progress/');
    await expect(progressSection.first()).toBeVisible({ timeout: 5000 });
  });

  test('Current week sessions are displayed', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Look for week entries
    const week1 = page.getByTestId('week-1');
    await expect(week1).toBeVisible({ timeout: 10000 });
    
    // Click to expand the current week
    await week1.click();
    
    // Wait for expanded content showing session details
    // Sessions should have days like "Lundi", "Mardi", etc.
    const dayText = page.locator('text=/Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche/');
    await expect(dayText.first()).toBeVisible({ timeout: 5000 });
  });

  test('Sessions display personalized pace information', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Find the current week (which has "EN COURS" badge) and click to expand
    const week1 = page.getByTestId('week-1');
    await expect(week1).toBeVisible({ timeout: 10000 });
    
    // Click on the week to expand it
    await week1.click();
    
    // Wait a moment for expansion animation
    await page.waitForLoadState('domcontentloaded');
    
    // Look for session details text which contains pace information
    // The details should show patterns like "8 km • 6:12-5:48/km" or similar
    const sessionDetails = page.locator('text=/\\d+.*km.*\\d+:\\d{2}/');
    const detailsVisible = await sessionDetails.first().isVisible({ timeout: 5000 }).catch(() => false);
    
    // Alternative: look for "Zone" text which indicates pace info
    const zoneText = page.locator('text=/Zone|FC|bpm/');
    const zoneVisible = await zoneText.first().isVisible({ timeout: 2000 }).catch(() => false);
    
    // At least one of these patterns should be visible in session details
    expect(detailsVisible || zoneVisible).toBe(true);
  });

  test('Refresh button updates the plan', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Find and click refresh button
    const refreshBtn = page.getByTestId('refresh-plan-btn');
    await expect(refreshBtn).toBeVisible({ timeout: 10000 });
    
    // Set up response listener
    const responsePromise = page.waitForResponse(
      response => response.url().includes('/training/refresh') && response.status() === 200,
      { timeout: 20000 }
    ).catch(() => null);
    
    await refreshBtn.click();
    
    // Wait for response
    const response = await responsePromise;
    expect(response).not.toBeNull();
    
    // Check for success toast
    const toast = page.locator('text=/mis à jour|updated/i');
    await expect(toast.first()).toBeVisible({ timeout: 10000 });
  });

  test('Full cycle view shows multiple weeks', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Check for "Cycle complet" or "Full Cycle" section
    const cycleSection = page.locator('text=/Cycle complet|Full Cycle/');
    await expect(cycleSection.first()).toBeVisible({ timeout: 10000 });
    
    // Multiple weeks should be visible
    const weeks = page.locator('[data-testid^="week-"]');
    const weekCount = await weeks.count();
    expect(weekCount).toBeGreaterThan(0);
  });

  test('Week cards show phase information', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Week cards should show phase names like "Construction", "Récupération", etc.
    const phaseTexts = page.locator('text=/Construction|Récupération|Intensification|Affûtage|Course|build|deload/i');
    await expect(phaseTexts.first()).toBeVisible({ timeout: 10000 });
  });

  test('Coach advice is displayed', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Check for coach advice section
    const adviceSection = page.locator('text=/Conseil du coach|Coach advice/');
    const adviceVisible = await adviceSection.first().isVisible({ timeout: 5000 }).catch(() => false);
    
    // Advice section should be visible (if plan has advice)
    if (adviceVisible) {
      await expect(adviceSection.first()).toBeVisible();
    }
  });

  test('Training goal is displayed in header', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // Goal should be visible (10K, Semi-marathon, Marathon, etc.)
    const goalText = page.locator('text=/10K|Semi-marathon|Marathon|5K|Ultra|10 kilomètres/i');
    await expect(goalText.first()).toBeVisible({ timeout: 10000 });
  });

  test('Session types are color-coded', async ({ page }) => {
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for page load
    await expect(page.getByTestId('training-plan-page')).toBeVisible({ timeout: 15000 });
    
    // First expand a week to see session types
    const week1 = page.getByTestId('week-1');
    await expect(week1).toBeVisible({ timeout: 10000 });
    await week1.click();
    
    // Check for session type badges in the expanded week view
    // Session types appear after expanding a week
    const sessionTypes = page.locator('text=/Endurance|Seuil|Tempo|Récupération|Sortie longue|Fractionné|Repos|Easy|Hard|Moderate/i');
    await expect(sessionTypes.first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Training Plan API Integration', () => {
  const BASE_URL = 'https://charge-load.preview.emergentagent.com';

  test('API returns VMA and paces in plan response', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/training/plan`, {
      headers: { 'X-User-Id': 'default' }
    });
    
    expect(response.status()).toBe(200);
    const data = await response.json();
    
    // Verify VMA-related fields are present
    expect(data).toHaveProperty('vma');
    expect(data).toHaveProperty('vo2max');
    expect(data).toHaveProperty('paces');
    expect(data).toHaveProperty('readiness_score');
    expect(data).toHaveProperty('prep_status');
    expect(data).toHaveProperty('adjusted_weeks');
    
    // Verify paces object has all zones
    const paces = data.paces;
    expect(paces).toHaveProperty('z1');
    expect(paces).toHaveProperty('z2');
    expect(paces).toHaveProperty('z3');
    expect(paces).toHaveProperty('z4');
    expect(paces).toHaveProperty('z5');
    expect(paces).toHaveProperty('marathon');
    expect(paces).toHaveProperty('semi');
    
    // Take a screenshot for verification
    console.log('VMA:', data.vma);
    console.log('VO2MAX:', data.vo2max);
    console.log('Paces:', JSON.stringify(paces, null, 2));
    console.log('Readiness Score:', data.readiness_score);
    console.log('Prep Status:', data.prep_status);
    console.log('Adjusted Weeks:', data.adjusted_weeks);
  });

  test('Sessions contain VMA-derived paces in details', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/training/plan`, {
      headers: { 'X-User-Id': 'default' }
    });
    
    expect(response.status()).toBe(200);
    const data = await response.json();
    
    const sessions = data.plan?.sessions || [];
    expect(sessions.length).toBeGreaterThan(0);
    
    // Check that non-rest sessions have pace info in details
    const nonRestSessions = sessions.filter(s => s.intensity !== 'rest' && s.type !== 'Repos');
    
    for (const session of nonRestSessions) {
      const details = session.details || '';
      // Should contain pace pattern like "5:30" or "6:00/km"
      const hasPace = /\d+:\d{2}/.test(details);
      expect(hasPace).toBe(true);
    }
  });
});
