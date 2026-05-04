from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from code_editor.models import Project, Repository, IndexedFile, CodeChunk
from code_editor.services import RetrievalService


class RetrievalFallbackTestCase(TestCase):
    """Tests for retrieval fallback when embeddings are unavailable."""

    def setUp(self) -> None:
        # Create a simple project and repository
        self.project = Project.objects.create(name='Fallback Project', description='Test project')
        self.repository = Repository.objects.create(
            project=self.project,
            name='fallback-repo',
            url='https://example.com/fallback',
            branch='main',
        )
        # Create an indexed file
        self.indexed_file = IndexedFile.objects.create(
            repository=self.repository,
            file_path='src/fallback.py',
            file_hash='fallbackhash',
            file_size=100,
            language='python',
            last_modified=timezone.now(),
        )
        # Create a couple of chunks with symbol names
        self.chunk1 = CodeChunk.objects.create(
            indexed_file=self.indexed_file,
            chunk_index=0,
            content='def foo():\n    pass',
            start_line=1,
            end_line=2,
            chunk_type='function',
            token_count=10,
            symbol_name='foo',
        )
        self.chunk2 = CodeChunk.objects.create(
            indexed_file=self.indexed_file,
            chunk_index=1,
            content='class Bar:\n    pass',
            start_line=3,
            end_line=5,
            chunk_type='class',
            token_count=10,
            symbol_name='Bar',
        )

    @patch('code_editor.services.embeddings_service.EmbeddingsService.generate_embeddings', side_effect=Exception('no embeddings'))
    def test_lexical_fallback_returns_results(self, mocked_embed) -> None:
        """Ensure search_chunks returns results when embeddings fail via lexical fallback."""
        retrieval_service = RetrievalService()
        # Query by function name
        results = retrieval_service.search_chunks(
            query='foo',
            repository_ids=[self.repository.id],
            limit=10,
        )
        self.assertTrue(any(r['chunk_id'] == self.chunk1.id for r in results))
        # Query by class name
        results = retrieval_service.search_chunks(
            query='Bar',
            repository_ids=[self.repository.id],
            limit=10,
        )
        self.assertTrue(any(r['chunk_id'] == self.chunk2.id for r in results))

