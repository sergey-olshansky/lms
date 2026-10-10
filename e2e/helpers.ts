import type { Page } from "@playwright/test";

// Ported from cypress/support/commands.js's closeOnboardingModal.
export async function closeOnboardingModal(page: Page) {
	const modal = page.getByTestId("onboarding-help-modal");

	// The modal mounts only after the user resource resolves and an
	// onboarding-status API call returns, which can land after a fixed sleep
	// would have already given up and moved on — leaving it to pop up later,
	// mid-test. Waiting on the element itself is the correct condition; it's
	// bounded because a returning user with onboarding already complete never
	// gets one.
	const appeared = await modal
		.waitFor({ state: "visible", timeout: 2000 })
		.then(() => true)
		.catch(() => false);
	if (!appeared) return;

	// HelpModal uses v-show, so closing it hides the root but leaves it
	// mounted. Select the actual accessible Close control instead of relying
	// on header button order (which can include More options and Minimize).
	await modal.getByRole("button", { name: "Close", exact: true }).click();
	await modal.waitFor({ state: "hidden" });
}

export function button(page: Page, name: string | RegExp) {
	return page.getByRole("button", { name });
}

// Ported from cypress's cy.intercept().as() + cy.wait('@alias') pairs.
// Must be called BEFORE the action that triggers the request (it returns a
// promise to await afterwards), same as page.waitForResponse itself.
export function waitForApiCall(
	page: Page,
	urlSubstring: string,
	timeout = 15000
) {
	return page.waitForResponse(
		(res) =>
			res.url().includes(urlSubstring) && res.request().method() === "POST",
		{ timeout }
	);
}
