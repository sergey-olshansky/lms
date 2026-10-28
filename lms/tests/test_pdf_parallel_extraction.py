import re
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import frappe
from lms.lms import chemedge_pdf_import as importer


def entry(number):
    return {'number': number, 'question_pages': [1], 'context_pages': [], 'answer_pages': [2]}


def result(number):
    return {'tasks': [{'number': number, 'reviewed': True, 'question': 'Question body', 'answer': '42',
        'source_regions': [{'page': 1, 'start': 'exact first source words', 'end': 'exact last source words', 'kind': 'task'}]}]}


class TestParallelExtraction(unittest.TestCase):
    def setUp(self):
        self.cache = {}
        patches = [
            patch.object(importer, '_', side_effect=lambda text: text),
            patch.object(importer, '_ai_settings', return_value={}),
            patch.object(importer, '_zai_setting', return_value='3'),
            patch.object(importer, '_checkpoint_get', side_effect=lambda prefix, suffix: self.cache.get((prefix, suffix))),
            patch.object(importer, '_checkpoint_set', side_effect=lambda prefix, suffix, value: self.cache.__setitem__((prefix, suffix), value)),
            patch.object(importer, '_resolve_extracted_task', side_effect=lambda task, path: task),
            patch('lms.lms.pdf_trainer_jobs.report_progress'),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def extract(self, count=3):
        return importer._extract_page_plan_tasks(Path('test.pdf'), ['questions', 'answers'],
            [entry(n) for n in range(1, count + 1)], {}, {}, '', 'private-owner-prefix', {'title': 'Trainer'})

    def test_three_http_requests_run_concurrently_but_results_keep_source_order(self):
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        active = 0
        maximum = 0
        def ai(prompt, content, settings):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return result(int(re.search(r'stable import number (\d+)', prompt).group(1)))
        with patch.object(importer, '_ai_json', side_effect=ai):
            _, tasks = self.extract()
        self.assertEqual(maximum, 3)
        self.assertEqual([task['number'] for task in tasks], [1, 2, 3])

    def test_only_task_with_unlocatable_crop_is_retried(self):
        calls = Counter()
        resolutions = Counter()
        def ai(prompt, content, settings):
            number = int(re.search(r'stable import number (\d+)', prompt).group(1))
            calls[number] += 1
            return result(number)
        def resolve(task, path):
            number = task['number']
            resolutions[number] += 1
            if number == 2 and resolutions[number] == 1:
                raise frappe.ValidationError('unlocatable anchor')
            return task
        with patch.object(importer, '_ai_json', side_effect=ai), patch.object(importer, '_resolve_extracted_task', side_effect=resolve):
            _, tasks = self.extract(2)
        self.assertEqual(calls, {1: 1, 2: 2})
        self.assertEqual(len(tasks), 2)
        self.assertIn(('private-owner-prefix', '1'), self.cache)
        self.assertIn(('private-owner-prefix', '2'), self.cache)

    def test_retry_reuses_validated_checkpoint_without_another_request(self):
        cached = {**result(1)['tasks'][0], 'source_regions': [{'page_number': 1, 'bbox': [0, 0, 1, 1], 'kind': 'task'}]}
        self.cache[('private-owner-prefix', '1')] = cached
        with patch.object(importer, '_ai_json', return_value=result(2)) as ai:
            _, tasks = self.extract(2)
        ai.assert_called_once()
        self.assertIn('stable import number 2', ai.call_args.args[0])
        self.assertEqual(tasks[0], cached)

    def test_known_source_regions_are_given_to_ai_and_keep_original_pages(self):
        candidate = {'tasks': [{'number': 1, 'region_refs': ['body']}],
            'regions': {'body': {'page_number': 2, 'kind': 'task', 'text': 'exact source body'}}}
        prompt, content, allowed, scoped = importer._task_extraction_request(entry(1), ['page one', 'page two'], candidate, '')
        self.assertIn('provided source ref', prompt)
        self.assertIn('exact source body', content)
        self.assertEqual(scoped['tasks'][0]['region_refs'], ['body'])
        self.assertEqual(allowed, {1, 2})
