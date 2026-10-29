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
