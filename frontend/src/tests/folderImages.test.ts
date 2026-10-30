import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.stubGlobal('__', (text: string) => text)

// frappe's translation layer patches String.prototype.format onto the page at
// runtime; the queue messages use it. Same shim as assignmentsCount.test.ts.
String.prototype.format = function (this: string, ...args: unknown[]): string {
	return this.replace(/{(\d+)}/g, (match, index) =>
		args[Number(index)] === undefined ? match : String(args[Number(index)])
	)
}

import {
	FOLDER_IMAGE_MAX_BATCH,
	FOLDER_IMAGE_MAX_SIZE,
	buildUploadItems,
	extensionOf,
	formatFileSize,
	queueFinished,
	queueProgress,
	retryTargets,
	uploadFolderImage,
	validateFolderImage,
} from '@/utils/folderImages'

function file(name: string, size: number, type = 'image/png'): File {
	return new File([new Uint8Array(size)], name, { type })
}

describe('folder image uploads (task #39)', () => {
	beforeEach(() => {
		vi.clearAllMocks()
	})

	it('recognises image extensions case-insensitively', () => {
		expect(extensionOf('Photo.JPG')).toBe('jpg')
		expect(extensionOf('photo.webp')).toBe('webp')
		expect(extensionOf('noext')).toBe('')
	})

	it('accepts JPG, PNG, WebP and GIF within the size limit', () => {
		expect(validateFolderImage(file('a.jpg', 10))).toBeNull()
		expect(validateFolderImage(file('a.JPEG', 10))).toBeNull()
		expect(validateFolderImage(file('a.png', 10))).toBeNull()
		expect(validateFolderImage(file('a.webp', 10))).toBeNull()
		expect(validateFolderImage(file('a.gif', 10))).toBeNull()
	})

	it('rejects other formats and oversize files with a reason', () => {
		expect(validateFolderImage(file('notes.txt', 10))).toContain('JPG')
		expect(validateFolderImage(file('vector.svg', 10))).toContain('JPG')
		expect(
			validateFolderImage(file('big.png', FOLDER_IMAGE_MAX_SIZE + 1))
		).toContain('MB')
	})

	it('builds a queue: valid files accepted, invalid rejected with reasons', () => {
		const { accepted, rejected } = buildUploadItems([
			file('ok.png', 10),
			file('bad.txt', 10),
			file('big.png', FOLDER_IMAGE_MAX_SIZE + 1),
		])
		expect(accepted).toHaveLength(1)
		expect(accepted[0].file.name).toBe('ok.png')
		expect(accepted[0].status).toBe('pending')
		expect(rejected.map((r) => r.file.name)).toEqual(['bad.txt', 'big.png'])
		expect(rejected.every((r) => r.reason.length > 0)).toBe(true)
	})

	it('caps one operation at the batch limit and reports the overflow', () => {
		const files = Array.from(
			{ length: FOLDER_IMAGE_MAX_BATCH + 5 },
			(_v, i) => file(`f${i}.png`, 1)
		)
		const { accepted, rejected } = buildUploadItems(files)
		expect(accepted).toHaveLength(FOLDER_IMAGE_MAX_BATCH)
		expect(rejected).toHaveLength(5)
		expect(rejected[0].reason).toContain(String(FOLDER_IMAGE_MAX_BATCH))
	})

	it('retry targets are exactly the failed items', () => {
		const { accepted } = buildUploadItems([
			file('a.png', 1),
			file('b.png', 1),
			file('c.png', 1),
		])
		accepted[0].status = 'done'
		accepted[1].status = 'error'
		accepted[1].error = 'boom'
		accepted[2].status = 'skipped'
		const targets = retryTargets(accepted)
		expect(targets).toHaveLength(1)
		expect(targets[0].file.name).toBe('b.png')
	})

	it('the queue is finished only when nothing is pending or failed', () => {
		const { accepted } = buildUploadItems([file('a.png', 1), file('b.png', 1)])
		expect(queueFinished(accepted)).toBe(false)
		accepted[0].status = 'done'
		expect(queueFinished(accepted)).toBe(false)
		accepted[1].status = 'error'
		expect(queueFinished(accepted)).toBe(false)
		accepted[1].status = 'skipped'
		expect(queueFinished(accepted)).toBe(true)
	})

	it('progress aggregates finished items at 100 and the rest by percent', () => {
		const { accepted } = buildUploadItems([file('a.png', 1), file('b.png', 1)])
		accepted[0].status = 'done'
		accepted[1].status = 'uploading'
		accepted[1].progress = 50
		expect(queueProgress(accepted)).toBe(75)
	})

	it('formats file sizes for the queue rows', () => {
		expect(formatFileSize(0)).toBe('0 KB')
		expect(formatFileSize(512 * 1024)).toBe('512 KB')
		expect(formatFileSize(3 * 1024 * 1024)).toBe('3.0 MB')
	})
})

// The upload request itself (task #39 fix): a raw XHR carries the session's
// CSRF token like every other frappe-ui request. Without the header, frappe
// rejects the POST as CSRFTokenError ("Invalid request" / «Неверный запрос»)
// before the method runs — the human-acceptance defect where every folder
// image upload failed, JPG or otherwise, whatever the file name.
interface ProgressEventLike {
	lengthComputable: boolean
	loaded: number
	total: number
}

class FakeXHR {
	open = vi.fn()
	setRequestHeader = vi.fn()
	send = vi.fn<(form: FormData) => void>()
	onload: (() => void) | null = null
	onerror: (() => void) | null = null
	upload: { onprogress: ((event: ProgressEventLike) => void) | null } = { onprogress: null }
	status = 0
	response: unknown = null

	respond(status: number, body: unknown) {
		this.status = status
		this.response = typeof body === 'string' ? body : JSON.stringify(body)
		this.onload?.()
	}
}

describe('folder image upload request (task #39 CSRF fix)', () => {
	let xhr: FakeXHR

	beforeEach(() => {
		xhr = new FakeXHR()
		// the upload flow creates exactly one XHR per call; hand it the fake
		// (a class constructor may return a pre-built object, which becomes the
		// constructed instance — keeps every property a vi mock)
		class FakeXMLHttpRequest {
			constructor() {
				return xhr
			}
		}
		vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest)
		// afterEach unstubs globals, which also drops the module-level __ shim
		vi.stubGlobal('__', (text: string) => text)
		delete (window as { csrf_token?: string }).csrf_token
	})

	afterEach(() => {
		vi.unstubAllGlobals()
	})

	it('sends the session CSRF token rendered by the SPA shell', async () => {
		;(window as { csrf_token?: string }).csrf_token = 'server-session-token'
		const promise = uploadFolderImage({ folder: '7183 Тема 1', file: file('a.png', 4) })
		expect(xhr.open).toHaveBeenCalledWith(
			'POST',
			'/api/method/lms.lms.api.upload_folder_image'
		)
		expect(xhr.setRequestHeader).toHaveBeenCalledWith('X-Frappe-CSRF-Token', 'server-session-token')
		xhr.respond(200, {
			message: {
				status: 'uploaded',
				file: { name: 'f1', file_name: 'a.png', file_url: '/private/files/a.png', file_size: 4 },
			},
		})
		await expect(promise).resolves.toMatchObject({ status: 'uploaded' })
	})

	it('keeps the picker file name unchanged, spaces and parentheses included', async () => {
		;(window as { csrf_token?: string }).csrf_token = 'token'
		const photo = file('photo_2025-05-05_14-19-43 (2).jpg', 633, 'image/jpeg')
		const promise = uploadFolderImage({ folder: '7183 Тема 1', file: photo })
		const form = (xhr.send as ReturnType<typeof vi.fn>).mock.calls[0][0] as FormData
		expect(form.get('folder')).toBe('7183 Тема 1')
		expect(form.get('file')).toBe(photo)
		xhr.respond(200, {
			message: {
				status: 'uploaded',
				file: {
					name: 'f2',
					file_name: 'photo_2025-05-05_14-19-43 (2)45115d.jpg',
					file_url: '/private/files/photo_2025-05-05_14-19-43 (2)45115d.jpg',
					file_size: 633,
				},
			},
		})
		await expect(promise).resolves.toMatchObject({ status: 'uploaded' })
	})

	it('omits the header when the shell provided no token', async () => {
		const promise = uploadFolderImage({ folder: 'f', file: file('a.png', 1) })
		expect(xhr.setRequestHeader).not.toHaveBeenCalledWith(
			'X-Frappe-CSRF-Token',
			expect.anything()
		)
		xhr.respond(200, { message: { status: 'skipped', file: { name: 'f1' } } })
		await expect(promise).resolves.toMatchObject({ status: 'skipped' })
	})

	it('treats an unrendered token placeholder as absent', async () => {
		;(window as { csrf_token?: string }).csrf_token = '{{ csrf_token }}'
		const promise = uploadFolderImage({ folder: 'f', file: file('a.png', 1) })
		expect(xhr.setRequestHeader).not.toHaveBeenCalledWith(
			'X-Frappe-CSRF-Token',
			expect.anything()
		)
		xhr.respond(200, { message: { status: 'uploaded', file: { name: 'f1' } } })
		await expect(promise).resolves.toMatchObject({ status: 'uploaded' })
	})

	it('reports upload progress from the xhr events', async () => {
		const onProgress = vi.fn()
		const promise = uploadFolderImage({ folder: 'f', file: file('a.png', 10), onProgress })
		xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 10 })
		xhr.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 })
		expect(onProgress).toHaveBeenNthCalledWith(1, 40)
		expect(onProgress).toHaveBeenNthCalledWith(2, 100)
		xhr.respond(200, { message: { status: 'uploaded', file: { name: 'f1' } } })
		await promise
	})

	it('rejects with the server message of a CSRF-shaped 400 (the reported defect)', async () => {
		;(window as { csrf_token?: string }).csrf_token = undefined
		const promise = uploadFolderImage({ folder: 'f', file: file('a.jpg', 3) })
		xhr.respond(400, {
			exc_type: 'CSRFTokenError',
			_server_messages:
				'[{"message":"Неверный запрос","as_table":false,"title":"Сообщение","indicator":"red","raise_exception":1}]',
		})
		await expect(promise).rejects.toThrow('Неверный запрос')
	})

	it('maps a 413 to the size-limit message and unknowns stay generic', async () => {
		const tooBig = uploadFolderImage({ folder: 'f', file: file('a.png', 11) })
		xhr.respond(413, '')
		await expect(tooBig).rejects.toThrow('Image is larger than the 10 MB limit.')

		const broken = uploadFolderImage({ folder: 'f', file: file('a.png', 1) })
		xhr.respond(500, 'not json at all')
		await expect(broken).rejects.toThrow('Error Uploading File')
	})
})
