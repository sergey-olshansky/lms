import { test as setup } from "@playwright/test";
import { authFile } from "./config";
import { authenticate } from "./auth";

// Every spec used to call cy.login() before nearly every `it()`, re-
// authenticating dozens of times per run for no reason — Cypress can only
// run one spec file at a time anyway, so nothing was ever gained by it. This
// runs once per shard: the storage state it writes is shared read-only by
// every spec via playwright.config.ts's `e2e` project, and specs that need
// their own fixtures (a course, a quiz, an instructor) create and tear those
// down themselves in `test.beforeAll`/`afterAll`.
setup("authenticate", async ({ page }) => {
	const user = process.env.PLAYWRIGHT_TEST_USER || "frappe@example.com";
	const password = process.env.PLAYWRIGHT_ADMIN_PASSWORD || "admin";

	await authenticate(page, user, password, authFile);
});
