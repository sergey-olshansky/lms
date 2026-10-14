import { readFileSync } from 'node:fs'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

const script = readFileSync(
	'../lms/public/js/mytutor-divider-motion.js',
	'utf8'
)
const controller = () => (window as any).lmsDividerMotion
let motion: EventTarget & { matches: boolean }

beforeEach(() => {
	vi.useFakeTimers()
	motion = Object.assign(new EventTarget(), { matches: false })
	vi.stubGlobal('matchMedia', () => motion)
	delete (window as any).lmsDividerMotion
	new Function(script)()
})
afterEach(() => {
	vi.useRealTimers()
	vi.unstubAllGlobals()
	document.body.innerHTML = ''
	delete (window as any).lmsDividerMotion
})

function stream() {
	const element = document.createElement('span')
	document.body.append(element)
	const moving = {
		animationName: 'lms-ai-wave-wander',
		playbackRate: 1,
		currentTime: 5000,
		effect: { getTiming: () => ({ duration: 61000 }) },
		updatePlaybackRate: vi.fn(),
	}
	moving.updatePlaybackRate.mockImplementation((rate) => {
		moving.playbackRate = rate
	})
	const other = { animationName: 'lms-ai-wave', updatePlaybackRate: vi.fn() }
	element.getAnimations = vi.fn(() => [other, moving] as any)
	return { element, moving, other }
}

describe('random travel of only the second divider stream', () => {
	it('chooses direction every 10–30 seconds and preserves phase when reversing', () => {
		const { element, moving, other } = stream()
		const random = vi
			.fn()
			.mockReturnValueOnce(0) // 10s wait
			.mockReturnValueOnce(0.25) // upwards
			.mockReturnValueOnce(0.5) // 20s wait
			.mockReturnValueOnce(0.75) // downwards
			.mockReturnValueOnce(1) // 30s wait
		const stop = controller().start(element, { random })
		vi.advanceTimersByTime(9999)
		expect(moving.updatePlaybackRate).not.toHaveBeenCalled()
		vi.advanceTimersByTime(1)
		vi.advanceTimersByTime(2000)
		expect(moving.updatePlaybackRate).toHaveBeenLastCalledWith(-1)
		expect(moving.currentTime % 61000).toBe(5000)
		expect(moving.currentTime).toBeGreaterThan(61000)
		vi.advanceTimersByTime(18000)
		vi.advanceTimersByTime(2000)
		expect(moving.updatePlaybackRate).toHaveBeenLastCalledWith(1)
		expect(other.updatePlaybackRate).not.toHaveBeenCalled()
		const calls = moving.updatePlaybackRate.mock.calls.length
		vi.advanceTimersByTime(27999)
		expect(moving.updatePlaybackRate).toHaveBeenCalledTimes(calls)
		stop()
		expect(vi.getTimerCount()).toBe(0)
	})
	it('suspends timers for reduced motion and resumes when the preference changes', () => {
		motion.matches = true
		const { element } = stream()
		const stop = controller().start(element)
		expect(vi.getTimerCount()).toBe(0)
		motion.matches = false
		motion.dispatchEvent(new Event('change'))
		expect(vi.getTimerCount()).toBe(1)
		motion.matches = true
		motion.dispatchEvent(new Event('change'))
		expect(vi.getTimerCount()).toBe(0)
		stop()
	})
	it('changes the third stream within bounded colour, height and visibility ranges', () => {
		const { element } = stream()
		const third = document.createElement('span')
		third.className = 'lms-ai-stream-third'
		element.append(third)
		const stop = controller().start(element, { random: () => 0 })
		vi.advanceTimersByTime(10000)
		expect(third.style.getPropertyValue('--lms-third-colour')).toBe('#4dc5c7')
		expect(third.style.getPropertyValue('--lms-third-center')).toBe('20%')
		expect(third.style.getPropertyValue('--lms-third-span')).toBe('22%')
		expect(
			Number(third.style.getPropertyValue('--lms-third-gain'))
		).toBeGreaterThan(0)
		expect(third.style.getPropertyValue('--lms-third-width')).toBe('20px')
		stop()
		expect(vi.getTimerCount()).toBe(0)
	})
	it('lets the third stream approach 40px with only a modest light increase', () => {
		const { element } = stream()
		const third = document.createElement('span')
		third.className = 'lms-ai-stream-third'
		element.append(third)
		const stop = controller().start(element, { random: () => 0.999999 })
		vi.advanceTimersByTime(30000)
		expect(
			parseFloat(third.style.getPropertyValue('--lms-third-width'))
		).toBeCloseTo(40)
		expect(
			Number(third.style.getPropertyValue('--lms-third-gain'))
		).toBeCloseTo(0.9)
		expect(third.style.getPropertyValue('--lms-third-colour')).toBe('#b8a1ce')
		stop()
	})
	it('stops when its element is detached', () => {
		const { element, moving } = stream()
		controller().start(element, { random: () => 0 })
		element.remove()
		vi.advanceTimersByTime(10000)
		expect(moving.updatePlaybackRate).not.toHaveBeenCalled()
		expect(vi.getTimerCount()).toBe(0)
	})
})
