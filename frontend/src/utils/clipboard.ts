/** Clipboard API is unavailable on the HTTP preprod. Keep sharing usable there. */
export async function copyText(text: string): Promise<void> {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text)
			return
		}
	} catch {
		// The browser may refuse clipboard permission; try the user-click fallback.
	}
	const previousFocus = document.activeElement as HTMLElement | null
	const field = document.createElement('textarea')
	field.value = text
	field.style.cssText = 'position:fixed;left:-9999px;top:0'
	field.setAttribute('readonly', '')
	document.body.appendChild(field)
	try {
		field.select()
		if (!document.execCommand('copy')) throw new Error('Clipboard unavailable')
	} finally {
		field.remove()
		previousFocus?.focus()
	}
}
