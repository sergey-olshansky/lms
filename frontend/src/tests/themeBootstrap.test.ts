import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const ROOT = resolve(__dirname, '../..')
const html = readFileSync(resolve(ROOT, 'index.html'), 'utf8')
const bootstrap = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
	.map((match) => match[1]).find((source) => source.includes('data-theme'))!

type Scenario = { stored: Record<string, string>; systemDark: boolean }
const runBootstrap = ({ stored }: Scenario): string | null => {
	let result: string | null = null
	const values = { ...stored }
	new Function('document', 'localStorage', bootstrap)(
		{ documentElement: { setAttribute: (_: string, value: string) => { result = value } } },
		{ getItem: (key: string) => values[key] ?? null, setItem: (key: string, value: string) => { values[key] = value } }
	)
	return result
}

const storage = new Map<string, string>()
const mockStorage = {
	getItem: (key: string) => storage.get(key) ?? null,
	setItem: (key: string, value: string) => { storage.set(key, value) },
	clear: () => storage.clear(),
}
const runComposable = async ({ stored }: Scenario): Promise<string> => {
	storage.clear()
	for (const [key, value] of Object.entries(stored)) mockStorage.setItem(key, value)
	vi.stubGlobal('localStorage', mockStorage)
	vi.resetModules()
	return (await import('../utils/theme')).theme.value
}

afterEach(() => {
	vi.unstubAllGlobals()
	storage.clear()
	document.documentElement.removeAttribute('data-theme')
})

describe('learner app light-only theme bootstrap', () => {
	const scenarios: Scenario[] = [
		{ stored: {}, systemDark: false },
		{ stored: { themePreference: 'dark' }, systemDark: false },
		{ stored: { themePreference: 'system' }, systemDark: true },
		{ stored: { theme: 'dark' }, systemDark: true },
	]

	it.each(scenarios)('normalizes legacy and OS dark preferences to light', (scenario) => {
		expect(runBootstrap(scenario)).toBe('light')
	})

	it.each(scenarios)('matches the runtime theme composable', async (scenario) => {
		expect(await runComposable(scenario)).toBe('light')
	})

	it('runs a light bootstrap from the document head', () => {
		const head = html.slice(html.indexOf('<head>'), html.indexOf('</head>'))
		expect(head).toContain(bootstrap)
		expect(bootstrap).toContain("setItem('themePreference', 'light')")
	})
})
