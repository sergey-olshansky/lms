import type { OutlineFolderImage } from '@/types'

/** Authoring limits for image folders (task #39). Mirrored server-side in
 * lms/lms/api.py: FOLDER_IMAGE_MAX_SIZE, FOLDER_MAX_IMAGES and the extension
 * allowlist; the server is the authority, these only fail fast in the picker. */
export const FOLDER_IMAGE_MAX_SIZE = 10 * 1024 * 1024
export const FOLDER_IMAGE_MAX_BATCH = 50
export const FOLDER_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif']

export const FOLDER_IMAGE_ACCEPT = [
	'image/jpeg',
	'image/png',
	'image/webp',
	'image/gif',
].join(',')

export type FolderUploadStatus = 'pending' | 'uploading' | 'done' | 'skipped' | 'error'

export interface FolderUploadItem {
	id: string
	file: File
	status: FolderUploadStatus
	/** 0..100, upload progress of the current attempt. */
	progress: number
	error?: string
	/** Server payload of the stored File on done/skipped. */
	uploadedFile?: OutlineFolderImage
}

export interface RejectedFile {
	file: File
	reason: string
}

let uploadSeq = 0

export function extensionOf(name: string): string {
	const dot = name.lastIndexOf('.')
	return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

/** Structural client-side validation; the server re-validates everything. */
export function validateFolderImage(file: File): string | null {
	const extension = extensionOf(file.name)
	if (!FOLDER_IMAGE_EXTENSIONS.includes(extension)) {
		return __('Only JPG, PNG, WebP and GIF images are allowed.')
	}
	if (file.size > FOLDER_IMAGE_MAX_SIZE) {
		return __('Image is larger than the {0} MB limit.').format(
			Math.round(FOLDER_IMAGE_MAX_SIZE / (1024 * 1024))
		)
	}
	return null
}

/** Build the queue from a file-picker selection.

 * Files past the per-operation cap are rejected whole (never silently
 * dropped), and each invalid file carries its own reason.
 */
export function buildUploadItems(files: File[]): {
	accepted: FolderUploadItem[]
	rejected: RejectedFile[]
} {
	const accepted: FolderUploadItem[] = []
	const rejected: RejectedFile[] = []
	for (const file of files) {
		if (accepted.length >= FOLDER_IMAGE_MAX_BATCH) {
			rejected.push({
				file,
				reason: __('A single upload takes at most {0} files.').format(
					FOLDER_IMAGE_MAX_BATCH
				),
			})
			continue
		}
		const reason = validateFolderImage(file)
		if (reason) {
			rejected.push({ file, reason })
			continue
		}
		uploadSeq += 1
		accepted.push({
			id: `folder-upload-${uploadSeq}`,
			file,
			status: 'pending',
			progress: 0,
		})
	}
	return { accepted, rejected }
}

/** Queue items a "retry failed" pass must re-send: exactly the errored ones. */
export function retryTargets(items: FolderUploadItem[]): FolderUploadItem[] {
	return items.filter((item) => item.status === 'error')
}

/** Finished means no item is still pending, uploading or errored. */
export function queueFinished(items: FolderUploadItem[]): boolean {
	return items.every((item) => ['done', 'skipped'].includes(item.status))
}

/** Aggregated 0..100 progress across the queue's current statuses. */
export function queueProgress(items: FolderUploadItem[]): number {
	if (!items.length) return 0
	const total = items.reduce(
		(sum, item) =>
			sum + (['done', 'skipped'].includes(item.status) ? 100 : item.progress),
		0
	)
	return Math.round(total / items.length)
}

export function formatFileSize(bytes: number): string {
	if (!bytes || bytes < 0) return '0 KB'
	if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Server payload of one stored folder image, as the upload API returns it. */
export interface FolderUploadResponse {
	status: 'uploaded' | 'skipped'
	file: OutlineFolderImage
}

interface UploadXHRLike {
	status: number
	response: unknown
}

/** POST one image to the folder upload API through a raw XHR, for per-file
 * progress.
 *
 * The request must carry the session's CSRF token exactly like every
 * frappe-ui request does: frappe validates the token on POSTs before any
 * whitelisted method runs, so a bare XHR (no `X-Frappe-CSRF-Token` header,
 * no `csrf_token` field) is rejected as `CSRFTokenError` — "Invalid request"
 * in the UI — for every file, whatever its name or format. The SPA shell
 * renders `window.csrf_token` at page load; the `{{ csrf_token }}` guard is
 * the same unrendered-template check frappe-ui itself uses. */
export function uploadFolderImage(options: {
	folder: string
	file: File
	onProgress?: (percent: number) => void
}): Promise<FolderUploadResponse> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest()
		xhr.open('POST', '/api/method/lms.lms.api.upload_folder_image')
		xhr.setRequestHeader('Accept', 'application/json')
		const csrfToken = (window as Window & { csrf_token?: string }).csrf_token
		if (csrfToken && csrfToken !== '{{ csrf_token }}') {
			xhr.setRequestHeader('X-Frappe-CSRF-Token', csrfToken)
		}
		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable && options.onProgress) {
				options.onProgress(Math.round((event.loaded / event.total) * 100))
			}
		}
		xhr.onerror = () => reject(new Error(__('Network error')))
		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) {
				try {
					const body =
						typeof xhr.response === 'string' ? JSON.parse(xhr.response) : xhr.response
					const message = body?.message ?? body
					if (message?.file?.name) resolve(message)
					else reject(new Error(__('Error Uploading File')))
				} catch {
					reject(new Error(__('Error Uploading File')))
				}
			} else {
				reject(new Error(serverErrorMessage(xhr)))
			}
		}
		const form = new FormData()
		form.append('folder', options.folder)
		form.append('file', options.file)
		xhr.send(form)
	})
}

/** Pull the human-readable reason out of a Frappe JSON error body. */
export function serverErrorMessage(xhr: UploadXHRLike): string {
	try {
		const body =
			typeof xhr.response === 'string' && xhr.response
				? JSON.parse(xhr.response)
				: xhr.response
		const raw = body?._server_messages
		if (typeof raw === 'string') {
			const messages = JSON.parse(raw)
			const first = typeof messages?.[0] === 'string' ? JSON.parse(messages[0]) : messages?.[0]
			const text = first?.message ?? first
			if (typeof text === 'string' && text) return stripTags(text)
		}
		if (typeof body?.message === 'string' && body.message) {
			return stripTags(body.message)
		}
	} catch {
		// fall through to the generic message
	}
	if (xhr.status === 413) {
		return __('Image is larger than the {0} MB limit.').format(10)
	}
	return __('Error Uploading File')
}

function stripTags(text: string): string {
	return text.replace(/<[^>]*>/g, '').trim()
}
