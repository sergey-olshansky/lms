import { describe, expect, it } from 'vitest'
import {
	transliterateFileName,
	transliterateText,
} from '@/utils/transliterateFileName'

describe('transliterateFileName', () => {
	it('transliterates cyrillic with digraphs and keeps the extension', () => {
		expect(transliterateFileName('Домашка_Глава1.pdf')).toBe(
			'Domashka_Glava1.pdf'
		)
	})

	it('uses Dz for Дз and Shch for Щ', () => {
		expect(transliterateFileName('Дз_по_алгебре.pdf')).toBe('Dz_po_algebre.pdf')
		expect(transliterateFileName('Щётка.jpg')).toBe('Shchyotka.jpg')
	})

	it('keeps uppercase cyrillic uppercase', () => {
		// Uppercase digraphs keep the table form (Ш → Sh), so an all-caps name
		// maps to DOMAShKA, not DOMASHKA.
		expect(transliterateFileName('ДОМАШКА.PDF')).toBe('DOMAShKA.PDF')
	})

	it('passes latin names through unchanged', () => {
		expect(transliterateFileName('report.pdf')).toBe('report.pdf')
	})

	it('preserves the extension for media types', () => {
		expect(transliterateFileName('Фото.jpg')).toBe('Foto.jpg')
		expect(transliterateFileName('Картинка.png')).toBe('Kartinka.png')
		expect(transliterateFileName('Видео.mp4')).toBe('Video.mp4')
		expect(transliterateFileName('Аудио.mp3')).toBe('Audio.mp3')
	})

	it('falls back to file when the base transliterates to empty', () => {
		expect(transliterateFileName('ъь.pdf')).toBe('file.pdf')
	})

	it('transliterates names without an extension as a whole', () => {
		expect(transliterateFileName('Документ')).toBe('Dokument')
	})

	it('handles ukrainian letters', () => {
		expect(transliterateFileName('Їжак.pdf')).toBe('Yizhak.pdf')
		expect(transliterateFileName('Європа.png')).toBe('Yevropa.png')
		expect(transliterateFileName('Ґрунт.jpg')).toBe('Grunt.jpg')
	})

	it('keeps digits and punctuation in mixed names', () => {
		expect(transliterateFileName('Файл №5 (копия).pdf')).toBe(
			'Fayl №5 (kopiya).pdf'
		)
	})
})

describe('transliterateText', () => {
	it('maps the full cyrillic alphabet', () => {
		expect(transliterateText('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЫЭЮЯ')).toBe(
			'ABVGDEYoZhZIYKLMNOPRSTUFKhTsChShShchYEYuYa'
		)
		expect(transliterateText('абвгдеёжзийклмнопрстуфхцчшщыэюя')).toBe(
			'abvgdeyozhziyklmnoprstufkhtschshshchyeyuya'
		)
	})

	it('leaves non-cyrillic characters alone', () => {
		expect(transliterateText('ABC 123 — ok!')).toBe('ABC 123 — ok!')
	})
})
