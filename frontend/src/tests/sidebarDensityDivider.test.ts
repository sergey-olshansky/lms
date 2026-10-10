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
	it('uses the measured visible wave on both surfaces, with a seamless loop and reduced-motion equivalent', () => {
		expect(common).toContain(':is(.lms-tutor-theme, body[data-path="login"])')
		expect(common).toContain('width: 12px')
		expect(common).toContain('pointer-events: none')
		expect(common).toContain('opacity: 0.28')
		for (const hue of ['#368b96', '#6285ab', '#8c7aa9']) {
			expect(common).toContain(hue)
		}
		expect(common).toContain('background-size: 100% 50%')
		expect(common).toContain('mask-size: 100% 50%')
		expect(common).toContain('animation: lms-ai-wave 24s linear infinite')
		expect(common).toContain('transform: translateY(-50%)')
		expect(common).toMatch(
			/prefers-reduced-motion: reduce[\s\S]*animation: none/
		)
	})
})
