from rest_framework import serializers
from ..models import Project, Repository, IngestionJob


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for Project model"""
    
    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class RepositorySerializer(serializers.ModelSerializer):
    """Serializer for Repository model"""
    
    class Meta:
        model = Repository
        fields = [
            'id', 'name', 'url', 'branch', 'access_type', 
            'indexing_status', 'last_indexed_at', 'file_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'indexing_status', 'last_indexed_at', 'file_count', 'created_at', 'updated_at']


class CreateRepositorySerializer(serializers.ModelSerializer):
    """Serializer for creating a new repository"""
    
    class Meta:
        model = Repository
        fields = ['name', 'url', 'branch', 'access_type']
    
    def validate_url(self, value: str) -> str:
        """
        Validate repository URL. Ensures the URL is provided and uses a supported scheme.

        Supported schemes include HTTP(S), git, and local file URLs. Raises a validation
        error if the value is missing or does not start with one of the allowed prefixes.
        """
        if not value:
            raise serializers.ValidationError("Repository URL is required")

        # Ensure the value is a string and strip whitespace
        url = value.strip()
        allowed_prefixes = ('http://', 'https://', 'git://', 'file://')
        if not any(url.startswith(prefix) for prefix in allowed_prefixes):
            raise serializers.ValidationError(
                "Invalid repository URL format. Must start with one of: "
                + ", ".join(allowed_prefixes)
            )

        return url
    
    def validate_name(self, value):
        """Validate repository name"""
        if not value or not value.strip():
            raise serializers.ValidationError("Repository name is required")
        
        if len(value.strip()) > 255:
            raise serializers.ValidationError("Repository name too long (max 255 characters)")
        
        return value.strip()


class IngestionJobSerializer(serializers.ModelSerializer):
    """Serializer for IngestionJob model"""
    
    class Meta:
        model = IngestionJob
        fields = [
            'id', 'job_id', 'status', 'progress', 'files_processed',
            'chunks_created', 'error_message', 'started_at', 'completed_at', 'created_at'
        ]
        read_only_fields = ['id', 'job_id', 'status', 'progress', 'files_processed', 
                          'chunks_created', 'error_message', 'started_at', 'completed_at', 'created_at']


class ProjectStatsSerializer(serializers.Serializer):
    """Serializer for project statistics"""
    repository_count = serializers.IntegerField(read_only=True)
    total_files = serializers.IntegerField(read_only=True)
    total_size_bytes = serializers.IntegerField(read_only=True)
    languages = serializers.DictField(read_only=True)
    last_indexed = serializers.DateTimeField(read_only=True)


class IngestionStatsSerializer(serializers.Serializer):
    """Serializer for ingestion statistics"""
    repository = RepositorySerializer(read_only=True)
    files = serializers.DictField(read_only=True)
    chunks = serializers.DictField(read_only=True)
