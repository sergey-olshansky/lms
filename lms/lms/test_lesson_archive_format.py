import copy
import io
import json
import unittest
import zipfile

from PIL import Image

from lms.lms.lesson_archive_format import LessonArchiveError, parse_archive, video_url


def png_bytes():
	out = io.BytesIO()
	Image.new("RGB", (4, 3), "white").save(out, "PNG")
	return out.getvalue()


def manifest():
	return {
		"schema_version": "1.0",
		"lecture_title": "Урок ОВР",
		"summary": "Описание",
		"source": {"duration_sec": 120},
		"top_tags": ["#ОВР"],
		"sections": [
			{
				"id": 1,
				"title": "Раздел",
				"start_sec": 0,
				"end_sec": 120,
				"bullets": ["Тезис"],
				"equations": ["Cr³⁺ → Cr⁶⁺"],
				"tags": [],
				"frames": [
					{
						"file": "frames/01_00-30.png",
						"timestamp_sec": 30,
						"caption": "Кадр",
						"board_text": "Cr",
					}
				],
			}
		],
	}


def archive_bytes(data=None, frames=None):
	out = io.BytesIO()
	with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
		archive.writestr("manifest.json", json.dumps(data or manifest()))
		for path, content in (frames if frames is not None else {"frames/01_00-30.png": png_bytes()}).items():
			archive.writestr(path, content)
	return out.getvalue()


class TestLessonArchiveFormat(unittest.TestCase):
	def test_reads_manifest_and_real_images(self):
		data, frames = parse_archive(archive_bytes())
		self.assertEqual(data["lecture_title"], "Урок ОВР")
		self.assertEqual(data["sections"][0]["equations"], ["Cr³⁺ → Cr⁶⁺"])
		self.assertEqual(len(frames), 1)

	def test_ignores_unknown_fields_and_files(self):
		data = manifest()
		data["future"] = {"instructions": "this is only data"}
		data["sections"][0]["future"] = True
		result, _ = parse_archive(
			archive_bytes(data, {"frames/01_00-30.png": png_bytes(), "extra.txt": b"ignored"})
		)
		self.assertNotIn("future", result)

	def test_rejects_missing_referenced_frame(self):
		with self.assertRaisesRegex(LessonArchiveError, "отсутствует"):
			parse_archive(archive_bytes(frames={}))

	def test_rejects_traversal_frame_and_non_image(self):
		data = manifest()
		data["sections"][0]["frames"][0]["file"] = "frames/../secret.png"
		with self.assertRaises(LessonArchiveError):
			parse_archive(archive_bytes(data))
		with self.assertRaises(LessonArchiveError):
			parse_archive(archive_bytes(frames={"frames/01_00-30.png": b"<script>bad</script>"}))

	def test_rejects_unsupported_schema_and_empty_sections(self):
		for key, value in [("schema_version", "2.0"), ("sections", []), ("sections", "bad")]:
			data = manifest()
			data[key] = value
			with self.subTest(key=key), self.assertRaises(LessonArchiveError):
				parse_archive(archive_bytes(data))

	def test_rejects_frame_outside_section(self):
		data = manifest()
		data["sections"][0]["frames"][0]["timestamp_sec"] = 121
		with self.assertRaises(LessonArchiveError):
			parse_archive(archive_bytes(data))

	def test_rejects_overlapping_sections_and_non_finite_duration(self):
		data = manifest()
		second = copy.deepcopy(data["sections"][0])
		second.update(id=2, start_sec=110)
		data["sections"].append(second)
		with self.assertRaises(LessonArchiveError):
			parse_archive(archive_bytes(data))
		data = manifest()
		data["source"]["duration_sec"] = float("nan")
		with self.assertRaises(LessonArchiveError):
			parse_archive(archive_bytes(data))

	def test_rejects_corrupt_zip(self):
		for content in [b"not a zip", "text renamed to lesson.zip"]:
			with self.subTest(content=content), self.assertRaises(LessonArchiveError):
				parse_archive(content)

	def test_video_url_requires_vk_https_embed(self):
		self.assertEqual(
			video_url("https://vkvideo.ru/video_ext.php?oid=-1&id=2"),
			"https://vkvideo.ru/video_ext.php?oid=-1&id=2",
		)
		for url in [
			"javascript:alert(1)",
			"http://vkvideo.ru/video_ext.php",
			"https://example.com/video_ext.php",
			"https://vkvideo.ru:8080/video_ext.php",
			"https://x@vkvideo.ru/video_ext.php",
		]:
			with self.subTest(url=url), self.assertRaises(LessonArchiveError):
				video_url(url)
