import { describe, expect, it } from 'vitest'

import {
	formatDueAt,
	siteWallClock,
	siteWallClockShort,
	siteZoneLabel,
} from '@/utils/dueDate'

// Task #35 (U01): every deadline renders from the server's offset-bearing ISO
// straight to the site-local wall clock — the browser's zone never repaints
// it, and the zone label names the offset so site-local time cannot be
// misread as the reader's own.
describe('dueDate helpers', () => {
	it('reads the site-local wall clock from the ISO string', () => {
		expect(siteWallClock('2026-10-24T23:59:59+03:00')).toBe('24.10.2026 23:59')
		expect(siteWallClockShort('2026-10-24T23:59:59+03:00')).toBe('24.10 23:59')
	})

	it('labels the zone from the offset tail', () => {
		expect(siteZoneLabel('2026-10-24T23:59:59+03:00')).toBe('UTC+03:00')
		expect(siteZoneLabel('2026-10-24T23:59:59-05:00')).toBe('UTC-05:00')
		expect(siteZoneLabel('')).toBe('')
	})

	it('formats the full deadline with the zone', () => {
		expect(formatDueAt('2026-10-24T23:59:59+03:00')).toBe(
			'24.10.2026 23:59 (UTC+03:00)'
		)
	})

	it('returns empty for missing values, never a rendered blank zero', () => {
		expect(siteWallClock(null)).toBe('')
		expect(siteWallClock(undefined)).toBe('')
		expect(formatDueAt(null)).toBe('')
		expect(formatDueAt('not-an-iso')).toBe('')
	})
})
