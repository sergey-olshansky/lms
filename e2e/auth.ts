import type { Page } from "@playwright/test";

export async function authenticate(
	page: Page,
	user: string,
	password: string,
	authFile: string
) {
	// Use the browser's request context so login and page bootstrap share sid.
	const login = await page.request.post("/api/method/login", {
		form: { usr: user, pwd: password },
	});
	if (!login.ok()) {
		throw new Error(`Login as ${user} failed: ${login.status()}`);
	}

	const app = await page.goto("/lms/courses");
	if (!app?.ok()) {
		throw new Error(`Authenticated app bootstrap failed: ${app?.status()}`);
	}

	// LMS embeds the server session token as window.csrf_token. Frappe does
	// not promise a csrf_token cookie; each subsequent page boot loads it anew.
	const token = await page.evaluate(
		() => (window as unknown as { csrf_token?: string }).csrf_token
	);
	if (typeof token !== "string" || !token.trim() || token === "None") {
		throw new Error("Authenticated app bootstrap did not expose a CSRF token");
	}
	// A read-only POST proves both authentication and server-side CSRF
	// validation work before saving state for the dependent spec projects.
	const identity = await page.request.post(
		"/api/method/frappe.auth.get_logged_user",
		{
			headers: { "X-Frappe-CSRF-Token": token },
		}
	);
	if (!identity.ok()) {
		throw new Error(`Authenticated CSRF probe failed: ${identity.status()}`);
	}
	if ((await identity.json()).message !== user) {
		throw new Error(
			"Authenticated CSRF probe did not retain the expected user"
		);
	}
	await page.context().storageState({ path: authFile });
}
