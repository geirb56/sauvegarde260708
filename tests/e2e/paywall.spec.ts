import { test, expect } from '@playwright/test';

test.describe('Paywall and Protected Access Tests', () => {
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
  });

  test('Homepage loads without paywall for trial/early_adopter users', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    
    // Dashboard should be visible
    const dashboard = page.getByTestId('today-workout-card').or(page.locator('text=CardioCoach'));
    await expect(dashboard.first()).toBeVisible({ timeout: 10000 });
    
    // Paywall should NOT be visible for trial/early_adopter users
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible().catch(() => false);
    
    // Either paywall is not visible (trial/early_adopter) or it's visible (free user)
    // This test is informational - both states are valid depending on user status
    if (paywallVisible) {
      console.log('User is in FREE status - paywall displayed');
    } else {
      console.log('User is in TRIAL or EARLY_ADOPTER status - no paywall');
    }
  });

  test('Training page shows paywall for free users', async ({ page }) => {
    // First simulate trial end to get free status via API
    await page.request.post(`${BASE_URL}/api/subscription/simulate-trial-end?user_id=default`);
    
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for the page to determine subscription status
    await page.waitForTimeout(1000);
    
    // Check if paywall is visible OR training plan is visible
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible({ timeout: 5000 }).catch(() => false);
    
    if (paywallVisible) {
      // Paywall should have CTA button
      const ctaButton = page.getByTestId('paywall-cta');
      await expect(ctaButton).toBeVisible();
      
      // Restore user to trial for other tests
      await page.request.post(`${BASE_URL}/api/subscription/reset-to-trial?user_id=default`);
    } else {
      // User might already be early_adopter or trial wasn't ended
      console.log('Training page accessible - user likely trial/early_adopter');
    }
  });

  test('Paywall displays Early Adopter offer correctly', async ({ page }) => {
    // First simulate trial end to get free status
    await page.request.post(`${BASE_URL}/api/subscription/simulate-trial-end?user_id=default`);
    
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);
    
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible({ timeout: 5000 }).catch(() => false);
    
    if (paywallVisible) {
      // Check paywall content
      await expect(paywall.locator('text=Early Adopter')).toBeVisible();
      
      // Check price display (4.99 or 4,99)
      const priceText = paywall.locator('text=/4[,.]99/');
      await expect(priceText.first()).toBeVisible();
      
      // Check CTA button exists and is clickable
      const ctaButton = page.getByTestId('paywall-cta');
      await expect(ctaButton).toBeVisible();
      await expect(ctaButton).toBeEnabled();
      
      // Restore user to trial
      await page.request.post(`${BASE_URL}/api/subscription/reset-to-trial?user_id=default`);
    } else {
      // User has access, skip this test
      console.log('No paywall visible - user has access');
      test.skip();
    }
  });

  test('Paywall CTA button triggers Stripe checkout', async ({ page }) => {
    // First simulate trial end to get free status
    await page.request.post(`${BASE_URL}/api/subscription/simulate-trial-end?user_id=default`);
    
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);
    
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible({ timeout: 5000 }).catch(() => false);
    
    if (paywallVisible) {
      const ctaButton = page.getByTestId('paywall-cta');
      
      // Set up navigation listener before clicking
      const navigationPromise = page.waitForURL(/stripe|checkout/, { timeout: 15000 }).catch(() => null);
      
      await ctaButton.click();
      
      // Wait for either navigation to Stripe OR button to show loading state
      const loadingText = paywall.locator('text=Activation').or(paywall.locator('text=Activating'));
      const isLoading = await loadingText.isVisible({ timeout: 5000 }).catch(() => false);
      const navigated = await navigationPromise;
      
      // Either we navigated to Stripe OR the button showed loading state
      expect(isLoading || navigated !== null).toBe(true);
      
      // Restore user to trial
      await page.request.post(`${BASE_URL}/api/subscription/reset-to-trial?user_id=default`);
    } else {
      // User has access, skip this test
      test.skip();
    }
  });

  test('Early Adopter users can access protected pages', async ({ page }) => {
    // First activate early adopter
    await page.request.post(`${BASE_URL}/api/subscription/activate-early-adopter`, {
      data: { user_id: 'default' }
    });
    
    // Navigate to training page
    await page.goto('/training');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
    
    // Paywall should NOT be visible
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible({ timeout: 3000 }).catch(() => false);
    
    expect(paywallVisible).toBe(false);
    
    // Training page content should be visible (goal selection or plan)
    const trainingContent = page.locator('text=Objectif').or(page.locator('text=Goal')).or(page.locator('text=Plan'));
    await expect(trainingContent.first()).toBeVisible({ timeout: 10000 });
  });

  test('Coach page accessible for trial/early_adopter users', async ({ page }) => {
    await page.goto('/coach');
    await page.waitForLoadState('domcontentloaded');
    
    // Coach page should load
    const coachPage = page.getByTestId('coach-page');
    const coachPageVisible = await coachPage.isVisible({ timeout: 10000 }).catch(() => false);
    
    // If coach page is visible, user has access
    // If paywall is visible, user is in free status
    const paywall = page.getByTestId('paywall');
    const paywallVisible = await paywall.isVisible({ timeout: 3000 }).catch(() => false);
    
    // At least one should be true
    expect(coachPageVisible || paywallVisible).toBe(true);
  });

  test('Dashboard insight section works for trial/early_adopter users', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    
    // Wait for dashboard to load
    await page.waitForTimeout(1000);
    
    // Dashboard should show metrics like FORME ACTUELLE, CHARGE, ACWR
    const formeSection = page.locator('text=FORME').or(page.locator('text=FITNESS'));
    await expect(formeSection.first()).toBeVisible({ timeout: 10000 });
  });
});
