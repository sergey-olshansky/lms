// The one guest-to-login redirect (task #35 E01, R07): the FULL current
// address -- path, query and hash, exactly as the URL bar holds it, so the
// app's base path travels with it -- rides along as `redirect-to`, and the
// post-login landing is the very page the reader opened. Frappe's login page
// sanitizes the value server-side (same host or a plain path only), so this
// can never become an open redirect.
export const redirectToLogin = (): void => {
	const target = `${window.location.pathname}${window.location.search}${window.location.hash}`
	window.location.href = `/login?redirect-to=${encodeURIComponent(target)}`
}
