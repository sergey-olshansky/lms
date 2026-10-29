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
