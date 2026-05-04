"""Unit tests for general helper functions in code_editor.utils."""

from django.test import SimpleTestCase

from code_editor import utils


class UtilsFunctionTests(SimpleTestCase):
    def test_generate_secure_token_unique(self) -> None:
        token1 = utils.generate_secure_token(16)
        token2 = utils.generate_secure_token(16)
        self.assertNotEqual(token1, token2)
        self.assertTrue(len(token1) > 0)

    def test_sanitize_input(self) -> None:
        text = 'hello\x00world'
        sanitized = utils.sanitize_input(text)
        self.assertNotIn('\x00', sanitized)
        long_text = 'a' * 200
        truncated = utils.sanitize_input(long_text, max_length=100)
        self.assertEqual(len(truncated), 100)

    def test_calculate_token_estimate(self) -> None:
        text = 'abcd' * 10
        estimate = utils.calculate_token_estimate(text)
        self.assertEqual(estimate, 10)

    def test_formatters(self) -> None:
        self.assertEqual(utils.format_latency_ms(999), '999ms')
        self.assertEqual(utils.format_file_size(1024), '1.0KB')

    def test_extract_code_language(self) -> None:
        self.assertEqual(utils.extract_code_language('test.py', 'def x():\n    pass'), 'python')
        self.assertEqual(utils.extract_code_language('index.ts', ''), 'typescript')

