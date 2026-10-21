import { vi } from 'vitest'
import { config } from '@vue/test-utils'
import { safeHtml, vExternal } from '../directives'

// main.js registers these on the app, so a component that uses one renders
// wrong under a bare mount() and the failure looks like missing data rather
// than a missing directive. Registering them here keeps component tests
// rendering what the app renders.
config.global.directives = {
	...config.global.directives,
	'safe-html': safeHtml,
	external: vExternal,
}

// main.js puts `__` on window; without it a script-block translation dies on a
// bare ReferenceError. Mirrors translate(), including the contract that a
// message with {0} returns a { format } object rather than a string.
vi.stubGlobal('__', (message: string) => {
	if (!/{\d+}/.test(message)) return message
	return {
		format: (...args: unknown[]) =>
			message.replace(/{(\d+)}/g, (match, index) =>
				args[Number(index)] === undefined ? match : String(args[Number(index)])
			),
	}
})

// Node >= 26 ships an experimental global Web Storage. Without
// --localstorage-file its instance shadows jsdom's implementation and exposes
// no prototype methods, which kills every suite that calls
// localStorage.clear() in beforeEach or spies on Storage.prototype (the same
// seven files pass under NODE_OPTIONS=--no-experimental-webstorage -- the same
// diagnosis, reached without a Node-version-dependent flag). Probing the
// storage and installing an in-memory one when it is broken keeps the suite
// green on any runtime; this file runs in test workers only, never in the app.
// The replacement is a class with the methods on its PROTOTYPE and registered
// as Storage itself, so `vi.spyOn(Storage.prototype, 'setItem')` keeps
// intercepting exactly the way it does against jsdom's own implementation.
const storageWorks = (): boolean => {
	try {
		return (
			typeof localStorage !== 'undefined' &&
			localStorage !== null &&
			typeof localStorage.getItem === 'function' &&
			typeof localStorage.setItem === 'function'
		)
	} catch {
		return false
	}
}
if (!storageWorks()) {
	class MemoryStorage {
		private store: Record<string, string> = {}
		get length(): number {
			return Object.keys(this.store).length
		}
		clear(): void {
			this.store = {}
		}
		getItem(key: string): string | null {
			return key in this.store ? this.store[key] : null
		}
		key(index: number): string | null {
			return Object.keys(this.store)[index] ?? null
		}
		removeItem(key: string): void {
			delete this.store[key]
		}
		setItem(key: string, value: string): void {
			this.store[key] = String(value)
		}
	}
	vi.stubGlobal('Storage', MemoryStorage)
	vi.stubGlobal('localStorage', new MemoryStorage())
	vi.stubGlobal('sessionStorage', new MemoryStorage())
}
