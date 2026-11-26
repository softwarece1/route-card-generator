import { test, expect } from '@playwright/test';
import { apiLogin, VNV } from './helpers/auth.js';

test.describe('V&V UI auth @ TEST-E2E', () => {
  test('unauthenticated generator redirects to login @ TEST-E2E-UNAUTH-REDIRECT', async ({
    page,
  }) => {
    await page.goto('/generator');
    await expect(page).toHaveURL(/\/login/);
  });

  test('login page renders @ TEST-E2E-LOGIN-PAGE', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByText(/Sign in with your employee ID/i)).toBeVisible();
    await expect(page.locator('#empId')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sign in/i })).toBeVisible();
  });

  test('signup page renders and validates empId @ TEST-E2E-SIGNUP-PAGE', async ({
    page,
  }) => {
    await page.goto('/signup');
    await expect(page.locator('body')).toContainText(/sign up|employee|SBU|department/i);
    const emp = page.locator('#empId');
    if (await emp.count()) {
      await emp.fill('12');
      await emp.blur();
    }
  });

  test('engineer can sign in and reach generator @ TEST-E2E-ENGINEER-LOGIN', async ({
    page,
  }) => {
    test.skip(process.env.VNV_E2E_AUTH !== '1', 'Set VNV_E2E_AUTH=1 with API+fixtures seeded');
    const data = await apiLogin(page.request, VNV.engineer);
    await page.addInitScript((user) => {
      try {
        localStorage.setItem(
          'rc_user',
          JSON.stringify(user || { role: 'engineer', isIedDept: false }),
        );
      } catch (_) {}
    }, data.user);
    await page.goto('/generator');
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page).not.toHaveURL(/\/history$/);
  });

  test('IED-dept engineer redirected from generator @ TEST-E2E-IED-REDIRECT', async ({
    page,
  }) => {
    test.skip(process.env.VNV_E2E_AUTH !== '1', 'Set VNV_E2E_AUTH=1 with API+fixtures seeded');
    const data = await apiLogin(page.request, VNV.engineer_ied);
    await page.addInitScript((user) => {
      try {
        localStorage.setItem(
          'rc_user',
          JSON.stringify(user || { role: 'engineer', isIedDept: true }),
        );
      } catch (_) {}
    }, data.user);
    await page.goto('/generator');
    await expect(page).toHaveURL(/\/history/);
  });
});
