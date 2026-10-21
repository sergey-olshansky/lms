// The one deadline rendering rule (task #35 spec 4.1, U01): the deadline is
// computed on the SITE's calendar day, and every place that shows it reads the
// same site-local wall clock straight out of the server's offset-bearing ISO
// string -- never `dayjs(naive)`, which would repaint the moment in the
// BROWSER's zone and make the board, the detail page and the assign dialog
// disagree about one and the same deadline. The zone label is explicit so the
// reader can tell a site-local time from their own.

export const siteWallClock = (iso?: string | null): string => {
	const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '')
	if (!match) return ''
	return `${match[3]}.${match[2]}.${match[1]} ${match[4]}:${match[5]}`
}

export const siteWallClockShort = (iso?: string | null): string => {
	const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '')
	if (!match) return ''
	return `${match[3]}.${match[2]} ${match[4]}:${match[5]}`
}

export const siteZoneLabel = (iso?: string | null): string => {
	const match = /([+-]\d{2}:\d{2})$/.exec(iso || '')
	return match ? `UTC${match[1]}` : ''
}

export const formatDueAt = (
	iso?: string | null,
	{ withZone = true }: { withZone?: boolean } = {}
): string => {
	const clock = siteWallClock(iso)
	if (!clock) return ''
	return withZone ? `${clock} (${siteZoneLabel(iso)})` : clock
}
