from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from code_editor.api.retrieval_serializers import SearchRequestSerializer
from code_editor.models import CodeChunk, IndexedFile, Project, Repository
from code_editor.services import RetrievalService


class RetrievalServiceTestCase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Test Project', description='Test project for retrieval')
        self.repository = Repository.objects.create(
            project=self.project,
            name='test-repo',
            url='https://github.com/test/repo',
            branch='main',
        )
        self.indexed_file = IndexedFile.objects.create(
            repository=self.repository,
            file_path='test.py',
            file_hash='testhash',
            file_size=1000,
            language='python',
            last_modified=timezone.now(),
        )
        self.test_chunks = []
        for i in range(3):
            chunk = CodeChunk.objects.create(
                indexed_file=self.indexed_file,
                chunk_index=i,
                content=f'def test_function_{i}():\n    pass',
                start_line=i * 10 + 1,
                end_line=i * 10 + 3,
                chunk_type='function',
                token_count=20,
            )
            self.test_chunks.append(chunk)

    def test_search_chunks_basic(self):
        retrieval_service = RetrievalService()
        results = retrieval_service.search_chunks(query='test function', repository_ids=[self.repository.id], limit=5)
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 5)
        if results:
            result = results[0]
            self.assertIn('chunk_id', result)
            self.assertIn('content', result)
            self.assertIn('similarity', result)
            self.assertIn('file_path', result)

    def test_search_chunks_with_filters(self):
        retrieval_service = RetrievalService()
        results = retrieval_service.search_chunks(query='test', languages=['python'], repository_ids=[self.repository.id])
        self.assertIsInstance(results, list)
        results = retrieval_service.search_chunks(query='test', chunk_types=['function'], repository_ids=[self.repository.id])
        self.assertIsInstance(results, list)
        if results:
            for result in results:
                self.assertEqual(result['chunk_type'], 'function')

    def test_get_chunk_context(self):
        retrieval_service = RetrievalService()
        chunk_id = self.test_chunks[1].id
        context = retrieval_service.get_context_for_chunk(chunk_id=chunk_id, context_lines=5)
        self.assertIn('chunk_id', context)
        self.assertIn('content', context)
        self.assertIn('before_context', context)
        self.assertIn('after_context', context)
        self.assertEqual(context['chunk_id'], chunk_id)

    def test_search_by_file_path(self):
        retrieval_service = RetrievalService()
        results = retrieval_service.search_by_file_path(file_path_pattern='test.py', repository_ids=[self.repository.id])
        self.assertIsInstance(results, list)
        if results:
            for result in results:
                self.assertIn('test.py', result['file_path'])


class RetrievalAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_search_chunks_endpoint(self):
        data = {'query': 'test function', 'limit': 10, 'similarity_threshold': 0.5}
        response = self.client.post('/api/code-editor/search/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('total', response.data)
        self.assertIn('query', response.data)

    def test_search_chunks_validation(self):
        response = self.client.post('/api/code-editor/search/', {'limit': 10}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post('/api/code-editor/search/', {'query': 'test', 'limit': 200}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_chunk_context_endpoint(self):
        project = Project.objects.create(name='Context Test')
        repository = Repository.objects.create(project=project, name='context-repo', url='https://github.com/test/context')
        indexed_file = IndexedFile.objects.create(
            repository=repository,
            file_path='context.py',
            file_hash='conthash',
            file_size=500,
            last_modified=timezone.now(),
        )
        chunk = CodeChunk.objects.create(
            indexed_file=indexed_file,
            chunk_index=0,
            content='def context_test():\n    pass',
            start_line=1,
            end_line=2,
        )
        response = self.client.post('/api/code-editor/context/', {'chunk_id': chunk.id, 'context_lines': 5}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('chunk_id', response.data)
        self.assertIn('content', response.data)
        self.assertIn('before_context', response.data)
        self.assertIn('after_context', response.data)

    def test_search_files_endpoint(self):
        response = self.client.post('/api/code-editor/files/', {'file_path_pattern': 'test.py', 'limit': 20}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data)
        self.assertIn('total', response.data)

    def test_local_access_without_auth(self):
        response = self.client.post('/api/code-editor/search/', {'query': 'test'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SearchRequestSerializerTestCase(TestCase):
    def test_serializer_defaults(self):
        serializer = SearchRequestSerializer(data={'query': 'test'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['limit'], 10)
        self.assertEqual(serializer.validated_data['similarity_threshold'], 0.7)
        self.assertTrue(serializer.validated_data['use_rerank'])

