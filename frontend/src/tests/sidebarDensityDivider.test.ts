import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/styles/mytutor.css', 'utf8')
const common = readFileSync('../lms/public/css/mytutor-common.css', 'utf8')
const sidebar = readFileSync('src/components/Sidebar/AppSidebar.vue', 'utf8')

describe('owner-corrected compact sidebar and visible divider', () => {
	it('keeps compact desktop controls and generous coarse-pointer targets', () => {
		expect(css).toMatch(/sidebar-item'\] \{\s*min-height: 32px/)
		expect(css).toMatch(/sidebar-header'\] \{\s*height: 40px/)
		expect(css).toMatch(/sidebar-item'\] svg \{\s*width: 16px;\s*height: 16px/)
		expect(css).toMatch(/@media \(pointer: coarse\)[\s\S]*min-height: 44px/)
		expect(css).toContain('outline: 2px solid var(--lms-action)')
		expect(sidebar).toContain('overflow-y-auto px-2 pt-1')
		expect(sidebar).toContain('flex flex-col gap-0.5')
	})
	it('keeps solid quiz actions secondary/primary even under native disabled utilities', () => {
		expect(css).toMatch(
			/\.lms-quiz-secondary:disabled \{\s*background: var\(--lms-secondary\);\s*color: var\(--lms-secondary-text\)/
		)
		expect(css).toMatch(
			/\.lms-quiz-primary:disabled \{\s*background: var\(--lms-action\);\s*color: var\(--lms-surface\)/
		)
	})
	it('keeps secondary quiz text accessible without changing the primary palette', () => {
		expect(css).toContain('--lms-secondary: #d8eff1')
		expect(css).toContain('--lms-secondary-text: #077581')
		expect(css).toContain('--lms-action: #087985')
		expect(css).toMatch(
			/\.lms-quiz-secondary \{\s*background: var\(--lms-secondary\);\s*color: var\(--lms-secondary-text\)/
		)
		const luminance = (hex: string) => {
			const channels = hex.match(/[a-f\d]{2}/gi)!.map((channel) => {
				const value = parseInt(channel, 16) / 255
				return value <= 0.04045
					? value / 12.92
					: ((value + 0.055) / 1.055) ** 2.4
			})
			return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
		}
		expect(css).toMatch(
			/\.lms-quiz-secondary:hover:not\(:disabled\) \{\s*background: var\(--lms-secondary-hover\);\s*color: var\(--lms-action-hover\)/
		)
		expect(css).toMatch(
			/\.lms-quiz-secondary:active:not\(:disabled\) \{\s*background: var\(--lms-pressed\);\s*color: var\(--lms-action-pressed\)/
		)
		for (const [background, foreground] of [
			['d8eff1', '077581'],
			['c9e7ea', '066a75'],
			['cde3e8', '055c66'],
		]) {
			expect(
				(luminance(background) + 0.05) / (luminance(foreground) + 0.05)
			).toBeGreaterThanOrEqual(4.5)
		}
	})
	it('uses one softly travelling, hue-changing R6 wave on both surfaces, with a seamless loop and reduced-motion equivalent', () => {
		expect(common).toContain(':is(.lms-tutor-theme, body[data-path="login"])')
		expect(common).toContain('width: 14px')
		expect(common).toContain('pointer-events: none')
		expect(common).toContain('opacity: 0.10')
		expect(common.match(/opacity:/g)).toHaveLength(1)
		expect(common).not.toContain('.lms-ai-divider::after')
		expect(common).not.toContain('lms-ai-wave-blue')
		expect(common).toContain('lms-ai-hue 24s ease-in-out infinite')
		expect(common).toContain('0%, 100% { background-color: #71c7cc; }')
		expect(common).toContain('rgb(0 0 0 / 0.8536) 37.5%')
		for (const hue of ['#71c7cc', '#99bbd8', '#b7b0d5']) {
			expect(common).toContain(hue)
		}
		expect(common).toContain('mask-size: 100% 50%')
		expect(common).toContain('animation: lms-ai-wave 24s linear infinite')
		expect(common).toContain('transform: translateY(-50%)')
		expect(common).toMatch(
			/prefers-reduced-motion: reduce[\s\S]*animation: none/
		)
	})
})
