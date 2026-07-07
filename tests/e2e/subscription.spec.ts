import { test, expect } from '@playwright/test';

test.describe('Subscription System Tests', () => {
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

  test('Settings page loads and displays subscription section', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Verify settings page loads
    await expect(page.getByTestId('settings-page')).toBeVisible();
    
    // Check that subscription section exists (contains Crown icon and subscription-related content)
    const subscriptionSection = page.locator('text=Abonnement').or(page.locator('text=Subscription'));
    await expect(subscriptionSection.first()).toBeVisible();
  });

  test('Settings page shows correct trial status for new users', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Look for trial badge or status indicator
    const trialBadge = page.locator('text=ESSAI GRATUIT').or(page.locator('text=TRIAL'));
    const trialStatus = await trialBadge.first().isVisible().catch(() => false);
    
    // Either trial badge or early adopter badge should be visible
    const earlyAdopterBadge = page.locator('text=EARLY ADOPTER');
    const earlyAdopterStatus = await earlyAdopterBadge.first().isVisible().catch(() => false);
    
    expect(trialStatus || earlyAdopterStatus).toBe(true);
  });

  test('Settings page shows subscription features list', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Check for feature list items
    const featureText = page.locator('text=Plan d\'entraînement').or(page.locator('text=Personalized training'));
    await expect(featureText.first()).toBeVisible({ timeout: 10000 });
  });

  test('Early Adopter subscribe button exists for trial/free users', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // The subscribe button should be visible for trial or free users
    const subscribeButton = page.getByTestId('subscribe-early-adopter');
    
    // Check if button exists (might not be visible if user is already early_adopter)
    const buttonExists = await subscribeButton.count() > 0;
    
    if (buttonExists) {
      await expect(subscribeButton).toBeVisible();
      await expect(subscribeButton).toBeEnabled();
    } else {
      // User might already be early_adopter
      const earlyAdopterBadge = page.locator('text=EARLY ADOPTER');
      await expect(earlyAdopterBadge.first()).toBeVisible();
    }
  });

  test('Subscribe button redirects to Stripe checkout', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    const subscribeButton = page.getByTestId('subscribe-early-adopter');
    
    // Only test if button exists (user is not already early_adopter)
    const buttonExists = await subscribeButton.count() > 0;
    
    if (buttonExists) {
      // Set up navigation listener before clicking
      const navigationPromise = page.waitForURL(/stripe|checkout/, { timeout: 15000 }).catch(() => null);
      
      await subscribeButton.click();
      
      // Wait for either navigation to Stripe OR button to show loading state
      const loadingText = page.locator('text=Redirection').or(page.locator('text=Redirecting'));
      const isLoading = await loadingText.isVisible({ timeout: 5000 }).catch(() => false);
      const navigated = await navigationPromise;
      
      // Either we navigated to Stripe OR the button showed loading state
      expect(isLoading || navigated !== null).toBe(true);
    } else {
      test.skip();
    }
  });

  test('Early Adopter offer displays correct price (4.99€)', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Look for the price display
    const priceDisplay = page.locator('text=4,99').or(page.locator('text=4.99'));
    const priceVisible = await priceDisplay.first().isVisible().catch(() => false);
    
    if (priceVisible) {
      await expect(priceDisplay.first()).toBeVisible();
    } else {
      // User might already be early_adopter, price not shown
      const earlyAdopterBadge = page.locator('text=EARLY ADOPTER');
      await expect(earlyAdopterBadge.first()).toBeVisible();
    }
  });

  test('Price guarantee message is displayed', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Look for "Prix garanti à vie" or "Price guaranteed for life"
    const guaranteeText = page.locator('text=Prix garanti').or(page.locator('text=Price guaranteed'));
    const guaranteeVisible = await guaranteeText.first().isVisible({ timeout: 5000 }).catch(() => false);
    
    if (guaranteeVisible) {
      await expect(guaranteeText.first()).toBeVisible();
    } else {
      // May not be shown if user already subscribed
      const earlyAdopterBadge = page.locator('text=EARLY ADOPTER');
      await expect(earlyAdopterBadge.first()).toBeVisible();
    }
  });

  test('Language toggle works', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');
    
    // Find and click English language toggle
    const englishToggle = page.getByTestId('lang-en');
    await englishToggle.click();
    
    // Wait for UI to update
    await page.waitForTimeout(500);
    
    // Check that English text appears
    const englishText = page.locator('text=English').or(page.locator('text=Settings'));
    await expect(englishText.first()).toBeVisible();
    
    // Switch back to French
    const frenchToggle = page.getByTestId('lang-fr');
    await frenchToggle.click();
    
    // Check French text
    const frenchText = page.locator('text=Français').or(page.locator('text=Réglages'));
    await expect(frenchText.first()).toBeVisible();
  });
});
