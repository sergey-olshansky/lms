export interface LessonFrame {
	file: string
	image_url: string
	timestamp_sec: number
	caption: string
	board_text: string
}
export interface LessonSection {
	id: number
	title: string
	start_sec: number
	end_sec: number
	tags: string[]
	bullets: string[]
	equations: string[]
	frames: LessonFrame[]
}
export interface LessonManifest {
	schema_version: string
	lecture_title: string
	summary: string
	top_tags: string[]
	source: { duration_sec: number }
	sections: LessonSection[]
}
export interface VideoArchiveData {
	video_src?: string
	// Accepted for blocks saved by the original placeholder.
	iframe?: string
	archive?: { file_url: string; file_name?: string }
	manifest?: LessonManifest
}
export interface LessonUploadContext {
	course?: string
	docname?: string | null
	fieldname?: string
}

// Keep only the URL. No iframe HTML or pasted attributes enter the live DOM.
export function vkVideoSource(input: string): string {
	try {
		const raw = input.trim().startsWith('<')
			? new DOMParser()
					.parseFromString(input, 'text/html')
					.querySelector('iframe')
					?.getAttribute('src')
			: input
		const url = new URL(raw || '')
		return url.protocol === 'https:' &&
			['vkvideo.ru', 'vk.com'].includes(url.hostname) &&
			url.pathname === '/video_ext.php' &&
			!url.username &&
			!url.password &&
			!url.port
			? url.href
			: ''
	} catch {
		return ''
	}
}

export function lessonTimecode(value: number): string {
	const n = Math.max(0, Math.floor(value || 0))
	const seconds = String(n % 60).padStart(2, '0')
	return n >= 3600
		? `${Math.floor(n / 3600)}:${String(Math.floor(n / 60) % 60).padStart(
				2,
				'0'
		  )}:${seconds}`
		: `${String(Math.floor(n / 60)).padStart(2, '0')}:${seconds}`
}

export function videoAtTime(source: string, seconds: number): string {
	const safe = vkVideoSource(source)
	if (!safe) return ''
	const url = new URL(safe)
	const n = Math.max(0, Math.floor(seconds))
	url.searchParams.set(
		't',
		`${Math.floor(n / 3600)}h${Math.floor(n / 60) % 60}m${n % 60}s`
	)
	url.searchParams.set('autoplay', '1')
	return url.href
}
