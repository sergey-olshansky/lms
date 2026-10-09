import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('frappe-ui', async () => {
	const actual = await vi.importActual<typeof import('frappe-ui')>('frappe-ui')
	return {
		...actual,
		call: vi.fn(),
		createResource: () => ({ data: null, loading: false, submit: vi.fn() }),
		toast: { success: vi.fn(), error: vi.fn() },
		SidebarHeader: {
			name: 'SidebarHeader',
			props: ['title', 'subtitle', 'menuItems'],
			template: '<div><slot name="prefix" /></div>',
		},
	}
})
vi.mock('@/stores/session', () => ({
	sessionStore: () => ({ logout: { submit: vi.fn() }, branding: { data: null }, isLoggedIn: true }),
}))
vi.mock('@/stores/user', () => ({ usersStore: () => ({ userResource: { data: { full_name: 'Ada Lovelace' } } }) }))
vi.mock('@/stores/settings', () => ({ useSettings: () => ({ settings: { data: null } }) }))
vi.mock('@/composables/useSettingsHash', () => ({ pushSettingsHash: vi.fn() }))
vi.mock('@/utils/openExternal', () => ({ openExternal: vi.fn() }))
vi.mock('@/utils/dialogs', () => ({ createDialog: vi.fn() }))
vi.mock('@/components/Settings/Settings.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.stubGlobal('__', (text: string) => text)

import UserDropdown from '@/components/Sidebar/UserDropdown.vue'

function build() {
	setActivePinia(createPinia())
	return mount(UserDropdown, { global: { mocks: { __: (t: string) => t } } })
}

describe('UserDropdown', () => {
	it('shows the real user identity and has no theme selector', () => {
		const header = build().findComponent({ name: 'SidebarHeader' })
		expect(header.props('title')).toBe('Ada Lovelace')
		const options = (header.props('menuItems') as any[])[0].options
		expect(options.map((option: any) => option.label)).not.toContain('Theme')
		expect(options.map((option: any) => option.label)).toContain('My Profile')
	})
})
