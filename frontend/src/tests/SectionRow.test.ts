import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import SectionRow from '@/components/SectionRow.vue'
import type { OutlineChapter } from '@/types'

const pushMock = vi.hoisted(() => vi.fn())
const focusMock = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({
	useRoute: () => ({ params: {}, query: {} }),
	useRouter: () => ({ push: pushMock }),
}))

vi.mock('frappe-ui', () => ({
	Button: {
		template: `<button><slot name="prefix" /><slot /></button>`,
	},
	TextInput: {
		props: ['modelValue'],
		emits: ['update:modelValue'],
		expose: ['focus'],
		methods: { focus: focusMock },
		template: `
			<div>
				<input
					:value="modelValue"
					@input="$emit('update:modelValue', $event.target.value)"
				/>
			</div>
		`,
	},
	Tooltip: {
		template: `<span><slot /></span>`,
	},
	toast: {
		success: vi.fn(),
	},
}))

vi.mock('vuedraggable', () => ({
	default: {
		name: 'Draggable',
		props: ['list', 'group', 'handle', 'disabled'],
		emits: ['end'],
		template: `
			<div>
				<div v-for="item in list" :key="item.key">
					<slot name="item" :element="item" />
				</div>
			</div>
		`,
	},
}))

vi.stubGlobal('__', (s: string) => s)

const section: OutlineChapter = {
	name: 'CH-2',
	title: 'Old Chapter',
	idx: 2,
	level: 1,
	is_scorm_package: 0 as const,
	lessons: [
		{ name: 'LESSON-1', title: 'Lesson 1', number: '2-1', position: 1 },
	],
}

const mountRow = (
	sectionOverride: OutlineChapter = section,
	allowEdit = true,
	extraProps: Record<string, unknown> = {}
) =>
	mount(SectionRow, {
		props: {
			section: sectionOverride,
			courseName: 'course-1',
			allowEdit,
			...extraProps,
		},
		global: {
			mocks: { __: (s: string) => s },
			provide: { $user: { data: { name: 'admin@example.com' } } },
			stubs: {
				'router-link': { template: '<a><slot /></a>' },
			},
		},
	})

beforeEach(() => {
	pushMock.mockReset()
	focusMock.mockReset()
})

describe('SectionRow inline rename', () => {
	it('focuses the rename input through its exposed focus()', async () => {
		const wrapper = mountRow()

		await wrapper.get('[title="Old Chapter"]').trigger('dblclick')
		await nextTick()

		expect(focusMock).toHaveBeenCalledTimes(1)
	})

	it('commits on Enter without toggling the section disclosure', async () => {
		const wrapper = mountRow()

		expect(wrapper.text()).not.toContain('Lesson 1')
		await wrapper.get('[title="Old Chapter"]').trigger('dblclick')

		const input = wrapper.get('input')
		await input.setValue('Renamed Section')
		await input.trigger('keydown.enter')

		expect(wrapper.emitted('rename-chapter')?.[0]).toMatchObject([
			{ chapter: section, title: 'Renamed Section' },
		])
		expect(wrapper.text()).not.toContain('Lesson 1')
	})
})

describe('SectionRow lesson count', () => {
	const count = (allowEdit: boolean) =>
		mountRow(section, allowEdit).get('[data-testid="section-count"]')

	it('stays readable while the always-visible edit actions are shown', () => {
		expect(count(true).text()).toBe('1')
		expect(count(true).classes()).not.toContain('group-hover:hidden')
		expect(count(true).classes()).not.toContain('[@media(hover:none)]:hidden')
	})

	it('stays visible when the section is not editable', () => {
		expect(count(false).text()).toBe('1')
		expect(count(false).classes()).not.toContain('group-hover:hidden')
		expect(count(false).classes()).not.toContain('[@media(hover:none)]:hidden')
	})
})

describe('SectionRow editor actions', () => {
	it('prevents duplicate lesson creation while the first request is pending', async () => {
		const wrapper = mountRow({ ...section, idx: 1 }, true, {
			creatingLesson: true,
		})
		const add = wrapper.get('button[aria-label="Add Lesson"]')
		expect((add.element as HTMLButtonElement).disabled).toBe(true)
		await add.trigger('click')
		const fallback = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Add Lesson')!
		await fallback.trigger('click')
		expect(wrapper.emitted('create-lesson')).toBeUndefined()
	})

	it('keeps the move action visible and exposes reorder controls to the keyboard', () => {
		const wrapper = mountRow()

		expect(wrapper.get('button[aria-label="Move up"]').element.tagName).toBe(
			'BUTTON'
		)
		expect(wrapper.get('button[aria-label="Move down"]').element.tagName).toBe(
			'BUTTON'
		)
		expect(
			wrapper
				.findAll('button')
				.some((button) => button.text().includes('Move to…'))
		).toBe(true)
	})

	it('wraps long section names instead of truncating them beside actions', () => {
		const wrapper = mountRow({
			...section,
			title:
				'A very long section name that needs to remain distinguishable in the editor',
		})

		const title = wrapper.get('[title^="A very long section name"]')
		expect(title.classes()).toContain('whitespace-normal')
		expect(title.classes()).toContain('break-words')
		expect(title.text()).toBe(
			'A very long section name that needs to remain distinguishable in the editor'
		)
	})
})

describe('SectionRow locked lesson', () => {
	it('renders a lock and no router-link for a locked lesson', () => {
		const wrapper = mountRow({
			...section,
			idx: 1,
			lessons: [
				{ name: 'LESSON-1', title: 'Lesson 1', number: '2-1', locked: 1 },
			],
		})

		expect(wrapper.find('.lucide-lock-keyhole').exists()).toBe(true)
		expect(wrapper.find('a').exists()).toBe(false)
	})

	// The locked row is a plain <div> (implicit role="generic"), and ARIA
	// prohibits naming a generic element, so `aria-label` on it is not
	// guaranteed to reach a screen reader. The state travels as real text
	// instead, which is exposed whatever the role, and the icon is hidden so
	// it is not announced twice.
	it('exposes the locked state as text, not as aria-label on a div', () => {
		const wrapper = mountRow({
			...section,
			idx: 1,
			lessons: [
				{ name: 'LESSON-1', title: 'Lesson 1', number: '2-1', locked: 1 },
			],
		})

		const row = wrapper.get('.cursor-not-allowed')
		expect(row.attributes('aria-label')).toBeUndefined()
		expect(row.attributes('aria-disabled')).toBeUndefined()
		expect(row.get('.sr-only').text()).toBe('Locked')
		expect(row.text()).toContain('Lesson 1')

		const lock = wrapper.get('.lucide-lock-keyhole')
		expect(lock.attributes('aria-hidden')).toBe('true')
	})

	it('still links an unlocked lesson', () => {
		const wrapper = mountRow({
			...section,
			idx: 1,
			lessons: [
				{ name: 'LESSON-1', title: 'Lesson 1', number: '2-1', locked: 0 },
			],
		})

		expect(wrapper.find('a').exists()).toBe(true)
		expect(wrapper.find('.lucide-lock-keyhole').exists()).toBe(false)
		expect(wrapper.text()).not.toContain('Locked')
	})

	// A SCORM section renders no DisclosurePanel, so it never reaches the per-lesson
	// lock affordance above: it used to look identical to an open section, and
	// the student learned it was locked only after SCORMChapter.vue bounced them back.
	const scormSection = (locked: 0 | 1): OutlineChapter => ({
		...section,
		idx: 1,
		is_scorm_package: 1 as const,
		lessons: [
			{ name: 'LESSON-1', title: 'SCORM Lesson', number: '1-1', locked },
		],
	})

	it('marks a locked SCORM section and refuses to open it', async () => {
		const wrapper = mountRow(scormSection(1))

		const lock = wrapper.get('.lucide-lock-keyhole')
		expect(lock.attributes('aria-hidden')).toBe('true')
		expect(wrapper.get('.sr-only').text()).toBe('Locked')

		await wrapper.get('[title="Old Chapter"]').trigger('click')
		expect(pushMock).not.toHaveBeenCalled()
	})

	it('still opens an unlocked SCORM section', async () => {
		const wrapper = mountRow(scormSection(0))

		expect(wrapper.find('.lucide-lock-keyhole').exists()).toBe(false)

		await wrapper.get('[title="Old Chapter"]').trigger('click')
		expect(pushMock).toHaveBeenCalledWith(
			expect.objectContaining({
				name: 'SCORMChapter',
				params: { courseName: 'course-1', chapterName: 'CH-2' },
			})
		)
	})

	it('does not emit select-lesson when a locked inline row is clicked', async () => {
		const wrapper = mount(SectionRow, {
			props: {
				section: {
					...section,
					idx: 1,
					lessons: [
						{
							name: 'LESSON-1',
							title: 'Lesson 1',
							number: '2-1',
							locked: 1,
						},
					],
				},
				courseName: 'course-1',
				inlineSelect: true,
			},
			global: {
				mocks: { __: (s: string) => s },
				provide: { $user: { data: { name: 'admin@example.com' } } },
			},
		})

		await wrapper.get('.cursor-not-allowed').trigger('click')

		expect(wrapper.emitted('select-lesson')).toBeUndefined()
	})
})

describe('SectionRow mixed children (task 28)', () => {
	const mixed: OutlineChapter = {
		name: 'CH-1',
		title: 'Mixed',
		idx: 1,
		level: 1,
		lesson_count: 2,
		section_count: 1,
		lessons: [
			{ name: 'LESSON-A', title: 'First', number: '1-1', position: 1 },
			{ name: 'LESSON-B', title: 'Second', number: '1-2', position: 3 },
		],
		sections: [
			{
				name: 'SUB-1',
				title: 'Nested',
				idx: 1,
				level: 2,
				position: 2,
				lessons: [
					{
						name: 'LESSON-C',
						title: 'Nested lesson',
						number: '1-1-1',
						position: 1,
					},
				],
			},
		],
	}

	it('interleaves lessons and nested sections in the single child order', () => {
		const wrapper = mountRow(mixed)

		const items = wrapper.findAll(
			'[data-testid="outline-lesson"], .outline-section-row'
		)
		expect(items).toHaveLength(3)
		expect(items[0].text()).toContain('First')
		expect(items[1].text()).toContain('Nested')
		expect(items[2].text()).toContain('Second')
	})

	it('shows the combined direct counts for a mixed section', () => {
		const wrapper = mountRow(mixed)

		expect(wrapper.text()).toContain('1 section · 2 lessons')
	})

	it('renders the empty-section placeholder for a childless section', () => {
		const wrapper = mountRow({
			name: 'CH-EMPTY',
			title: 'Empty',
			idx: 1,
			level: 1,
			lessons: [],
			sections: [],
		})

		expect(wrapper.find('[data-testid="empty-section"]').exists()).toBe(true)
		expect(wrapper.text()).toContain('Empty section')
	})
})

describe('SectionRow depth limit (task 28)', () => {
	it('disables adding a section at level 4 with a screen-reader reason', () => {
		const wrapper = mountRow({
			name: 'CH-L4',
			title: 'Deepest',
			idx: 1,
			level: 4,
			lessons: [],
			sections: [],
		})

		const affordance = wrapper.get(
			'button[aria-label="Maximum depth reached — 4 section levels"]'
		)
		expect(affordance.attributes('aria-disabled')).toBe('true')
		expect((affordance.element as HTMLButtonElement).disabled).toBe(true)

		expect(wrapper.text()).toContain('Maximum depth reached — 4 section levels')
	})

	it('offers adding a section at level 3 and emits the parent on click', async () => {
		const level3: OutlineChapter = {
			name: 'CH-L3',
			title: 'Third level',
			idx: 1,
			level: 3,
			lessons: [],
			sections: [],
		}
		const wrapper = mountRow(level3)

		const affordance = wrapper.find('.lucide-folder-plus')
		expect(affordance.exists()).toBe(true)
		expect(affordance.attributes('aria-disabled')).toBeUndefined()

		await affordance.trigger('click')
		expect(wrapper.emitted('add-section')?.[0]).toEqual([level3])
	})
})

describe('SectionRow drag events', () => {
	const parent: OutlineChapter = {
		...section,
		idx: 1,
		sections: [
			{ name: 'SUB-1', title: 'Nested', idx: 1, level: 2, position: 2 },
		],
	}

	it('reorders the dragged nested section instead of its ancestor', () => {
		const wrapper = mountRow(parent)
		const draggable = wrapper.findComponent({ name: 'Draggable' })
		const child = draggable.props('list')[1]
		const container = { dataset: { chapter: parent.name } }

		draggable.vm.$emit('end', {
			item: { __draggable_context: { element: child } },
			from: container,
			to: container,
			oldIndex: 1,
			newIndex: 0,
		})

		expect(wrapper.emitted('reorder-section')).toEqual([
			[{ section: parent.sections![0], parent: parent.name, idx: 0 }],
		])
		expect(wrapper.emitted('move-lesson')).toBeUndefined()
	})

	it('keeps cross-section transfer enabled only for lessons', () => {
		const wrapper = mountRow(parent)
		const draggable = wrapper.findComponent({ name: 'Draggable' })
		const group = draggable.props('group')
		const lesson = document.createElement('div')
		lesson.className = 'outline-lesson-row'
		const nested = document.createElement('div')
		nested.className = 'outline-section-row'

		for (const permission of [group.pull, group.put]) {
			expect(permission(null, null, lesson)).toBe(true)
			expect(permission(null, null, nested)).toBe(false)
		}

		draggable.vm.$emit('end', {
			item: { __draggable_context: { element: draggable.props('list')[0] } },
			from: { dataset: { chapter: parent.name } },
			to: { dataset: { chapter: 'OTHER' } },
			oldIndex: 0,
			newIndex: 1,
		})
		expect(wrapper.emitted('move-lesson')?.[0][0]).toMatchObject({
			item: { __draggable_context: { element: parent.lessons![0] } },
			from: { dataset: { chapter: parent.name } },
			to: { dataset: { chapter: 'OTHER' } },
			newIndex: 1,
		})
	})

	it('does not submit an unchanged order after a cancelled drag', () => {
		const wrapper = mountRow(parent)
		const draggable = wrapper.findComponent({ name: 'Draggable' })
		const container = { dataset: { chapter: parent.name } }
		draggable.vm.$emit('end', {
			item: { __draggable_context: { element: draggable.props('list')[1] } },
			from: container,
			to: container,
			oldIndex: 1,
			newIndex: 1,
		})
		expect(wrapper.emitted('reorder-section')).toBeUndefined()
		expect(wrapper.emitted('move-lesson')).toBeUndefined()
	})
})
