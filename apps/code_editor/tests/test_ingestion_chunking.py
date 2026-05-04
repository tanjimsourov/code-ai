from django.test import TestCase

from code_editor.services import IngestionService


class IngestionChunkingTestCase(TestCase):
    """Tests for improved chunking and symbol name extraction."""

    def test_chunk_content_symbol_names(self) -> None:
        ingestion_service = IngestionService()
        # Simple Python content with a function and a class
        content = (
            """# Test module
def func1():
    return 42

class MyClass:
    def method(self):
        pass
"""
        )
        chunks = ingestion_service._chunk_content(content, 'test.py')
        # Extract symbol names from chunk data
        symbol_names = [c.get('symbol_name') for c in chunks if c.get('symbol_name')]
        self.assertIn('func1', symbol_names)
        self.assertIn('MyClass', symbol_names)

