"""Regression checks for raster-only printed answer keys (task 40).

The «Полувариант 2. Органика» answers page prints task 14's key only as an
embedded raster image beside a standalone ``[14]`` marker. The AI endpoint is
text-only, so such a key can never be transcribed: the model must return an
empty answer, the importer must verify from the PDF itself that the band holds
just the marker and images (no answer text), and the printed image is preserved
verbatim as the question's key. Any invented answer text for a text-free band
is refused, and any band that does contain text keeps requiring an AI-copied
answer.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe

import lms.lms.chemedge_pdf_import as importer
from lms.lms.chemedge_pdf_import import (
	_answer_image_html,
	_answer_marker_starts,
	_create_answer_images,
	_raster_answer_region,
	_reject_unprinted_answer,
	_validate_ai_tasks,
	_verified_raster_answer,
	AIExtractionInvalid,
)


def word(text, top, bottom, x0, x1):
	return {"text": text, "top": float(top), "bottom": float(bottom), "x0": float(x0), "x1": float(x1)}


def image(top, bottom, x0, x1):
	return {"top": float(top), "bottom": float(bottom), "x0": float(x0), "x1": float(x1)}


class AnswersPage:
	"""pdfplumber-like answers page: ``[N] key`` rows, task 14's key is an image."""

	def __init__(self, words, images, width=780.0, height=540.0):
		self.width, self.height = float(width), float(height)
		self.words, self.images = words, images
		self.chars, self.rects, self.curves = [], [], []

	def extract_words(self, **kwargs):
		return [dict(item) for item in self.words]

	def extract_text_lines(self, strip=True, return_chars=False):
		return []

	def search(self, pattern, regex=True, case=True):
		return []

	def crop(self, bbox):
		return SimpleNamespace(extract_text=lambda: "")


def raster_answer_page():
	"""Rows [13] '1,4', [14] with the printed key only as Im6, [15] '2'."""
	return AnswersPage(
		words=[
			word("[13]", 100, 112, 40, 70),
			word("1,4", 100, 112, 80, 110),
			word("[14]", 140, 152, 40, 70),
			word("[15]", 340, 352, 40, 70),
			word("2", 340, 352, 80, 95),
		],
		images=[image(135, 320, 60, 700)],
	)


def fake_pdf(pages):
	return SimpleNamespace(pages=pages)


def answer_pdf(page):
	"""A five-page PDF whose answer key page is page 5."""
	return SimpleNamespace(pages=[None, None, None, None, page])


class TestRasterAnswerRegion(unittest.TestCase):
	def test_raster_only_answer_band_is_resolved(self):
		region = _raster_answer_region(answer_pdf(raster_answer_page()), [5], 14)
		self.assertEqual(region["page_number"], 5)
		self.assertEqual(region["page_width"], 780.0)
		self.assertEqual(region["page_height"], 540.0)
		x0, top, x1, bottom = region["bbox"]
		self.assertAlmostEqual(x0, 34.0)
		self.assertAlmostEqual(top, 137.0)
		self.assertAlmostEqual(x1, 706.0)
		self.assertAlmostEqual(bottom, 325.0)

	def test_text_answer_band_is_not_raster(self):
		page = raster_answer_page()
		page.words.append(word("C2H5OH", 160, 172, 90, 160))
		self.assertIsNone(_raster_answer_region(answer_pdf(page), [5], 14))

	def test_missing_or_ambiguous_marker_is_rejected(self):
		pages = [raster_answer_page(), raster_answer_page()]
		self.assertIsNone(_raster_answer_region(answer_pdf(pages[0]), [5], 99))
		self.assertIsNone(_raster_answer_region(fake_pdf(pages), [1, 2], 14))

	def test_band_without_image_is_rejected(self):
		page = raster_answer_page()
		page.images = []
		self.assertIsNone(_raster_answer_region(answer_pdf(page), [5], 14))

	def test_glued_marker_words_are_not_answer_markers(self):
		page = raster_answer_page()
		page.words = [word("[14]текст", 140, 152, 40, 160), *page.words[3:]]
		self.assertEqual([marker["number"] for marker in _answer_marker_starts(page)], [15])

	def test_footer_below_the_band_margin_keeps_the_raster_answer(self):
		page = raster_answer_page()
		page.words = page.words[:3] + [word("stepenin.ru", 520, 530, 40, 120)]
		page.images = [image(135, 500, 60, 700)]
		region = _raster_answer_region(answer_pdf(page), [5], 14)
		self.assertAlmostEqual(region["bbox"][3], 505.0)

	def test_image_crossing_the_next_marker_is_rejected(self):
		page = raster_answer_page()
		page.images = [image(135, 360, 60, 700)]
		self.assertIsNone(_raster_answer_region(fake_pdf([page]), [1], 14))

	def test_two_column_answers_page_scopes_the_markers_own_column(self):
		"""The real page-5 layout: [15] with a text solution top-right, [14]'s
		raster key mid-left, tiny formula images bottom-right."""
		page = AnswersPage(
			words=[
				word("[15]", 63, 74, 431, 449),
				word("Найдем", 251.9, 263, 458, 497),
				word("соотношение:", 251.9, 263, 500, 570),
				word("формула", 288.9, 300, 530, 580),
				word("[14]", 248.1, 259.1, 10.8, 29.1),
			],
			images=[
				image(234.1, 480.1, 35.4, 364.4),
				image(494.6, 516.5, 430.6, 452.4),
			],
		)
		pdf = fake_pdf([page])
		region = _raster_answer_region(pdf, [1], 14)
		x0, top, x1, bottom = region["bbox"]
		self.assertAlmostEqual(x0, 4.8)
		self.assertAlmostEqual(top, 245.1)
		self.assertAlmostEqual(x1, 370.4)
		self.assertAlmostEqual(bottom, 485.1)
		# The right column's text key is a different task's printed answer.
		self.assertIsNone(_raster_answer_region(pdf, [1], 15))

	def test_verified_raster_answer_opens_the_pdf_and_passes_source_number(self):
		with patch.object(importer.pdfplumber, "open") as opened:
			opened.return_value.__enter__.return_value = answer_pdf(raster_answer_page())
			region = _verified_raster_answer(Path("trainer.pdf"), {"number": 14, "answer_pages": [5]}, {})
		self.assertEqual(region["page_number"], 5)
		self.assertIsNone(_verified_raster_answer(Path("trainer.pdf"), {"number": 14, "answer_pages": []}, {}))


class TestRasterAnswerValidation(unittest.TestCase):
	def candidate(self):
		return {
			"tasks": [{"number": 14, "region_refs": ["body"]}],
			"regions": {"body": {"kind": "task", "page_number": 4, "text": "[14]Из предложенного перечня выберите вещество"}},
		}

	def result(self):
		return {"tasks": [{"number": 14, "reviewed": True, "question": "Задание 14", "answer": "", "options": [], "source_regions": [{"ref": "body"}]}]}

	def test_empty_answer_stays_invalid_without_verified_raster(self):
		with self.assertRaises(frappe.ValidationError):
			_validate_ai_tasks(self.result(), Path("trainer.pdf"), self.candidate())

	def test_empty_answer_is_accepted_with_verified_raster(self):
		title, tasks = _validate_ai_tasks(self.result(), Path("trainer.pdf"), self.candidate(), allow_empty_answer=True)
		self.assertEqual(len(tasks), 1)
		self.assertEqual(tasks[0]["answer"], "")

	def test_invented_answer_text_is_refused_for_a_text_free_band(self):
		result = {"tasks": [{**self.result()["tasks"][0], "answer": "24"}]}
		with self.assertRaises(AIExtractionInvalid):
			_reject_unprinted_answer(result, 14)

	def test_empty_answer_is_not_refused_and_other_tasks_are_ignored(self):
		_reject_unprinted_answer(self.result(), 14)
		_reject_unprinted_answer({"tasks": [{**self.result()["tasks"][0], "answer": "24"}]}, 15)


class TestRasterAnswerArtifacts(unittest.TestCase):
	def test_answer_image_html_is_sanitized(self):
		html = _answer_image_html({"number": 14}, "/private/files/chemedge-answer-0014.png")
		self.assertEqual(
			html,
			'<p><img src="/private/files/chemedge-answer-0014.png" alt="Task 14 printed answer"></p>',
		)

	def test_answer_images_are_rendered_per_raster_task(self):
		tasks = [
			{"number": 13, "answer": "1,4"},
			{"number": 14, "answer": "", "answer_image_region": {"page_number": 5, "bbox": (0, 0, 100, 100), "page_width": 780, "page_height": 540}},
		]
		saved = []

		class FakeImage:
			def save(self, path, **kwargs):
				saved.append(Path(path))

			def close(self):
				pass

		def fake_compose(regions, get_page):
			self.assertEqual(len(regions), 1)
			return FakeImage()

		page = SimpleNamespace(to_image=lambda resolution, antialias: SimpleNamespace(original=SimpleNamespace(convert=lambda mode: object())))
		with patch.object(importer, "compose_source_regions", side_effect=fake_compose):
			with patch.object(importer.pdfplumber, "open") as opened:
				opened.return_value.__enter__.return_value = SimpleNamespace(pages=[None, None, None, None, page])
				import tempfile

				with tempfile.TemporaryDirectory() as work_dir:
					images = _create_answer_images(Path("trainer.pdf"), tasks, Path(work_dir))
		self.assertEqual(list(images), [14])
		self.assertEqual(saved, [images[14]])
		self.assertEqual(saved[0].name, "ai-answer-0014.png")
		self.assertEqual(_create_answer_images(Path("trainer.pdf"), tasks[:1], Path("/tmp")), {})


if __name__ == "__main__":
	unittest.main()
