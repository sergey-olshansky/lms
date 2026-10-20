"""Import lesson.zip metadata and private frames for a video block.

Format: docs/lesson-zip-spec.md. Archive contents are data, never executable HTML.
"""

import io
import json
import math
import re
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from PIL import Image

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_FRAMES = 24


class LessonArchiveError(ValueError):
	pass


def video_url(value):
	if not isinstance(value, str):
		raise LessonArchiveError("Укажите iframe VK Видео.")
	try:
		url = urlsplit(value)
		valid = (
			url.scheme == "https"
			and url.hostname in {"vkvideo.ru", "vk.com"}
			and url.path == "/video_ext.php"
			and not url.username
			and not url.password
			and url.port in (None, 443)
		)
	except ValueError:
		valid = False
	if not valid:
		raise LessonArchiveError("Нужен HTTPS iframe VK Видео с адресом video_ext.php.")
	return value


def _number(value, label):
	if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
		raise LessonArchiveError(f"Некорректное число: {label}.")
	return value


def _text(value, label, *, required=False):
	if not isinstance(value, str) or len(value) > 50000 or (required and not value.strip()):
		raise LessonArchiveError(f"Некорректное текстовое поле: {label}.")
	return value


def _texts(value, label):
	if not isinstance(value, list) or len(value) > 200:
		raise LessonArchiveError(f"Некорректный список: {label}.")
	return [_text(item, label) for item in value]


def _read(archive, name, limit):
	try:
		info = archive.getinfo(name)
		if info.file_size > limit or info.flag_bits & 1:
			raise LessonArchiveError(f"Файл {name} слишком велик или зашифрован.")
		with archive.open(info) as stream:
			data = stream.read(limit + 1)
		if len(data) > limit:
			raise LessonArchiveError(f"Файл {name} слишком велик.")
		return data
	except KeyError:
		raise LessonArchiveError(f"В архиве отсутствует {name}.") from None


def parse_archive(content):
	"""Validate everything before writing any Files; ignore unknown fields/files.

	Only referenced PNG members are read. No member is extracted to a filesystem path.
	Returns normalized metadata and the verified image bytes keyed by archive path.
	"""
	if not isinstance(content, bytes):
		raise LessonArchiveError("Не удалось прочитать ZIP-архив урока.")
	if len(content) > MAX_ARCHIVE_BYTES:
		raise LessonArchiveError("Размер ZIP не должен превышать 100 МБ.")
	try:
		with zipfile.ZipFile(io.BytesIO(content)) as archive:
			members = archive.infolist()
			if len(members) > 512 or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
				raise LessonArchiveError("Архив содержит слишком много данных (максимум 100 МБ).")
			if len({m.filename for m in members}) != len(members):
				raise LessonArchiveError("В архиве повторяются имена файлов.")
			try:
				manifest = json.loads(_read(archive, "manifest.json", MAX_MANIFEST_BYTES))
			except (ValueError, UnicodeError):
				raise LessonArchiveError("Не удалось прочитать manifest.json.") from None
			if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
				raise LessonArchiveError("Поддерживается schema_version 1.0.")
			source = manifest.get("source")
			if not isinstance(source, dict):
				raise LessonArchiveError("В manifest.json нет source.")
			duration = _number(source.get("duration_sec"), "source.duration_sec")
			if duration <= 0:
				raise LessonArchiveError("Длительность видео должна быть больше нуля.")
			sections = manifest.get("sections")
			if not isinstance(sections, list) or not 1 <= len(sections) <= 200:
				raise LessonArchiveError("В архиве должно быть от 1 до 200 разделов.")
			result = {
				"schema_version": "1.0",
				"lecture_title": _text(manifest.get("lecture_title"), "lecture_title", required=True),
				"summary": _text(manifest.get("summary", ""), "summary"),
				"top_tags": _texts(manifest.get("top_tags", []), "top_tags"),
				"source": {"duration_sec": duration},
				"sections": [],
			}
			frames = {}
			frame_count = 0
			previous_end = 0
			for index, section in enumerate(sections, 1):
				if not isinstance(section, dict) or section.get("id") != index:
					raise LessonArchiveError("Идентификаторы разделов должны идти от 1 по порядку.")
				start = _number(section.get("start_sec"), "start_sec")
				end = _number(section.get("end_sec"), "end_sec")
				if not 0 <= previous_end <= start < end <= math.ceil(duration):
					raise LessonArchiveError("Некорректный порядок или таймкоды разделов.")
				previous_end = end
				row = {
					"id": index,
					"title": _text(section.get("title"), "section.title", required=True),
					"start_sec": start,
					"end_sec": end,
					"tags": _texts(section.get("tags", []), "tags"),
					"bullets": _texts(section.get("bullets", []), "bullets"),
					"equations": _texts(section.get("equations", []), "equations"),
					"frames": [],
				}
				section_frames = section.get("frames", [])
				if not isinstance(section_frames, list) or len(section_frames) > 3:
					raise LessonArchiveError("В разделе может быть не больше трёх кадров.")
				for frame in section_frames:
					frame_count += 1
					if frame_count > MAX_FRAMES or not isinstance(frame, dict):
						raise LessonArchiveError("Допускается до 24 кадров на урок.")
					name = frame.get("file")
					if (
						not isinstance(name, str)
						or not re.fullmatch(r"frames/[^/\\\x00]+\.png", name)
						or ".." in PurePosixPath(name).parts
					):
						raise LessonArchiveError("Некорректный путь кадра в архиве.")
					stamp = _number(frame.get("timestamp_sec"), "timestamp_sec")
					if not start <= stamp <= end:
						raise LessonArchiveError("Таймкод кадра выходит за границы раздела.")
					if name not in frames:
						image_bytes = _read(archive, name, MAX_FRAME_BYTES)
						try:
							with Image.open(io.BytesIO(image_bytes)) as image:
								if image.format != "PNG" or image.width * image.height > 40000000:
									raise LessonArchiveError(
										"Кадр должен быть PNG размером до 40 мегапикселей."
									)
								image.verify()
						except (OSError, SyntaxError, Image.DecompressionBombError):
							raise LessonArchiveError(f"Повреждённый PNG-кадр: {name}.") from None
						frames[name] = image_bytes
					row["frames"].append(
						{
							"file": name,
							"timestamp_sec": stamp,
							"caption": _text(frame.get("caption", ""), "caption"),
							"board_text": _text(frame.get("board_text", ""), "board_text"),
						}
					)
				result["sections"].append(row)
			return result, frames
	except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError):
		raise LessonArchiveError("Не удалось прочитать ZIP-архив урока.") from None
