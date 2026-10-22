import { safeUrl } from './safeUrl'

// F04 (task #35): a same-origin download that no popup blocker can eat --
// a programmatic anchor click instead of window.open. The URL clears the
// same scheme allowlist as every bound href; the server sets
// Content-Disposition, so the browser saves instead of navigating, and the
// current page (and the app state in it) stays put.
export const downloadViaAnchor = (url?: string | null): void => {
	const href = safeUrl(url)
	if (!href) return
	const anchor = document.createElement('a')
	anchor.href = href
	anchor.rel = 'noopener'
	// Hint only: same-origin + Content-Disposition decides the real
	// behaviour; an empty download keeps the server's filename.
	anchor.download = ''
	document.body.appendChild(anchor)
	anchor.click()
	anchor.remove()
}
