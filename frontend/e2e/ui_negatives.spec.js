import { test, expect } from '@playwright/test';

test.describe('V&V UI negatives @ TEST-E2E-UI-NEGATIVES', () => {
  test('protected history redirects to login when signed out', async ({ page }) => {
    await page.goto('/history');
    await expect(page).toHaveURL(/\/login/);
  });

  test('protected users redirects to login when signed out', async ({ page }) => {
    await page.goto('/users');
    await expect(page).toHaveURL(/\/login/);
  });

  test('protected org redirects to login when signed out', async ({ page }) => {
    await page.goto('/org');
    await expect(page).toHaveURL(/\/login/);
  });

  test('about page is reachable', async ({ page }) => {
    await page.goto('/about');
    await expect(page.locator('body')).toBeVisible();
  });
});
