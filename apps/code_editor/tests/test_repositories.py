from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from code_editor.models import Project, Repository
from code_editor.services import IngestionService, RepositoryService


class RepositoryServiceTestCase(TestCase):
    def test_create_project(self):
        project = RepositoryService.create_project(name='Test Project', description='A test project')
        self.assertIsInstance(project, Project)
        self.assertEqual(project.name, 'Test Project')
        self.assertEqual(project.description, 'A test project')
        self.assertTrue(project.is_active)

    def test_add_repository(self):
        project = RepositoryService.create_project(name='Test Project')
        repository = RepositoryService.add_repository(
            project=project,
            name='test-repo',
            url='https://github.com/test/repo',
            access_type='public',
            branch='main',
        )
        self.assertIsInstance(repository, Repository)
        self.assertEqual(repository.project, project)
        self.assertEqual(repository.name, 'test-repo')
        self.assertEqual(repository.url, 'https://github.com/test/repo')
        self.assertEqual(repository.branch, 'main')
        self.assertEqual(repository.access_type, 'public')

    def test_list_projects(self):
        projects = [RepositoryService.create_project(name=f'Test Project {i}') for i in range(3)]
        listed_projects = list(RepositoryService.list_projects())
        self.assertEqual(len(listed_projects), 3)
        for project in listed_projects:
            self.assertIn(project, projects)

    def test_get_project_stats(self):
        project = RepositoryService.create_project(name='Stats Test')
        RepositoryService.add_repository(project=project, name='stats-repo', url='https://github.com/test/stats')
        stats = RepositoryService.get_project_stats(project)
        self.assertEqual(stats['repository_count'], 1)
        self.assertIn('total_files', stats)
        self.assertIn('languages', stats)
        self.assertIn('last_indexed', stats)


class IngestionServiceTestCase(TestCase):
    def setUp(self):
        self.project = RepositoryService.create_project(name='Ingestion Test')
        self.repository = RepositoryService.add_repository(
            project=self.project,
            name='ingest-repo',
            url='https://github.com/test/ingest',
        )

    @patch('code_editor.services.ingestion_service.RepositoryService.get_repository_files')
    def test_ingest_repository(self, mock_get_files):
        mock_get_files.return_value = [
            {
                'path': 'test.py',
                'content': 'def test_function():\n    pass\n',
                'size': 30,
                'last_modified': timezone.now(),
                'language': 'python',
            }
        ]
        ingestion_service = IngestionService()
        job = RepositoryService.start_ingestion_job(self.repository)
        result = ingestion_service.ingest_repository(job.job_id)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['files_processed'], 1)
        self.assertGreater(result['chunks_created'], 0)

    def test_chunk_content(self):
        ingestion_service = IngestionService()
        content = """# Test function\ndef test_function():\n    '''This is a docstring'''\n    return 'test'\n"""
        chunks = ingestion_service._chunk_content(content, 'test.py')
        self.assertGreater(len(chunks), 0)
        chunk_types = [chunk['type'] for chunk in chunks]
        self.assertIn('docstring', chunk_types)
        self.assertIn('code', chunk_types)

    def test_should_reindex(self):
        self.assertTrue(RepositoryService.should_reindex(self.repository))
        self.repository.last_indexed_at = timezone.now()
        self.repository.save()
        self.assertFalse(RepositoryService.should_reindex(self.repository))


class RepositoryAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='repo-user', password='secret123')
        self.client.force_login(self.user)

    def test_list_projects_endpoint(self):
        response = self.client.get('/api/code-editor/projects/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data)
        self.assertEqual(response.data['object'], 'list')

    def test_create_project_endpoint(self):
        data = {'name': 'New Test Project', 'description': 'A new test project'}
        response = self.client.post('/api/code-editor/projects/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['object'], 'project')
        self.assertIn('data', response.data)

    def test_project_detail_endpoint(self):
        project = RepositoryService.create_project(name='Detail Test')
        response = self.client.get(f'/api/code-editor/projects/{project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['object'], 'project')
        self.assertEqual(response.data['data']['name'], 'Detail Test')

    def test_add_repository_endpoint(self):
        project = RepositoryService.create_project(name='Repo Test')
        data = {
            'name': 'test-repo',
            'url': 'https://github.com/test/repo',
            'branch': 'main',
            'access_type': 'public',
        }
        response = self.client.post(f'/api/code-editor/projects/{project.id}/repositories/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['object'], 'repository')

    def test_start_ingestion_endpoint(self):
        project = RepositoryService.create_project(name='Ingestion Test')
        repository = RepositoryService.add_repository(project=project, name='ingest-repo', url='https://github.com/test/ingest')
        response = self.client.post(f'/api/code-editor/projects/{project.id}/repositories/{repository.id}/jobs/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['object'], 'ingestion_job')
        self.assertIn('job_id', response.data['data'])

    def test_ingestion_job_detail_endpoint(self):
        project = RepositoryService.create_project(name='Job Test')
        repository = RepositoryService.add_repository(project=project, name='job-repo', url='https://github.com/test/job')
        job = RepositoryService.start_ingestion_job(repository)
        response = self.client.get(f'/api/code-editor/projects/{project.id}/repositories/{repository.id}/jobs/{job.job_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['object'], 'ingestion_job')
        self.assertEqual(response.data['data']['job_id'], job.job_id)

    def test_project_stats_endpoint(self):
        project = RepositoryService.create_project(name='Stats Test')
        response = self.client.get(f'/api/code-editor/projects/{project.id}/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['object'], 'project_stats')
        self.assertIn('repository_count', response.data['data'])

    def test_projects_endpoint_requires_authentication(self):
        anonymous_client = APIClient()
        response = anonymous_client.get('/api/code-editor/projects/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

