"""Candidate scoring and ranking service."""

from typing import List, Dict, Any, Optional
from django.utils import timezone
from ..models import TaskRun, CandidatePatch, CandidateScore, ValidationRun, TestRun


class CandidateScoringService:
    """Service for scoring and ranking candidate patches."""
    
    def __init__(self):
        pass
    
    def score_and_rank_candidates(self, task: TaskRun, candidates: List[CandidatePatch]) -> List[CandidatePatch]:
        """Score and rank all candidates for a task."""
        
        scored_candidates = []
        
        for candidate in candidates:
            score = self._calculate_candidate_score(task, candidate)
            scored_candidates.append((candidate, score))
        
        # Sort by score (descending)
        scored_candidates.sort(key=lambda x: x[1]['final_score'], reverse=True)
        
        # Update ranks and create score records
        for rank, (candidate, score) in enumerate(scored_candidates, 1):
            # Create or update score record
            CandidateScore.objects.update_or_create(
                task=task,
                candidate_patch=candidate,
                defaults={
                    'syntax_score': score['syntax_score'],
                    'validation_score': score['validation_score'],
                    'relevance_score': score['relevance_score'],
                    'risk_score': score['risk_score'],
                    'quality_score': score['quality_score'],
                    'final_score': score['final_score'],
                    'rank': rank,
                    'scoring_metadata': score['metadata']
                }
            )
            
            # Update candidate status
            if rank == 1:
                candidate.status = 'selected'
                candidate.selected_at = timezone.now()
            else:
                candidate.status = 'validated'
            
            candidate.save(update_fields=['status', 'selected_at', 'updated_at'])
        
        # Return sorted candidates
        return [candidate for candidate, _ in scored_candidates]
    
    def _calculate_candidate_score(self, task: TaskRun, candidate: CandidatePatch) -> Dict[str, Any]:
        """Calculate comprehensive score for a candidate."""
        
        # Get validation results
        validation_runs = candidate.validation_runs.all()
        test_runs = TestRun.objects.filter(candidate_patch=candidate)
        
        # Component scores
        syntax_score = self._calculate_syntax_score(candidate)
        validation_score = self._calculate_validation_score(validation_runs, test_runs)
        relevance_score = self._calculate_relevance_score(task, candidate)
        risk_score = self._calculate_risk_score(candidate)
        quality_score = self._calculate_quality_score(candidate, validation_runs)
        
        # Final weighted score
        weights = self._get_scoring_weights(task.task_type)
        final_score = (
            syntax_score * weights['syntax'] +
            validation_score * weights['validation'] +
            relevance_score * weights['relevance'] +
            (1.0 - risk_score) * weights['risk'] +  # Invert risk (lower risk = higher score)
            quality_score * weights['quality']
        )
        
        return {
            'syntax_score': syntax_score,
            'validation_score': validation_score,
            'relevance_score': relevance_score,
            'risk_score': risk_score,
            'quality_score': quality_score,
            'final_score': final_score,
            'metadata': {
                'weights': weights,
                'validation_count': validation_runs.count(),
                'test_count': test_runs.count(),
                'files_touched': len(candidate.touched_files),
                'strategy': candidate.patch_metadata.get('strategy', 'unknown')
            }
        }
    
    def _calculate_syntax_score(self, candidate: CandidatePatch) -> float:
        """Calculate syntax validation score."""
        
        # Check if there are any syntax errors in validation
        validation_runs = candidate.validation_runs.filter(stage_name='syntax_validation')
        
        if not validation_runs.exists():
            # No syntax validation performed, assume good
            return 0.8
        
        for validation in validation_runs:
            try:
                import json
                result = json.loads(validation.output or '{}')
                if result.get('passed', False):
                    return 1.0
                else:
                    # Syntax errors found
                    error_count = len(result.get('errors', []))
                    return max(0.0, 1.0 - (error_count * 0.2))  # Penalize each error
            except (json.JSONDecodeError, KeyError):
                pass
        
        return 0.5  # Unknown result
    
    def _calculate_validation_score(self, validation_runs: List[ValidationRun], test_runs: List[TestRun]) -> float:
        """Calculate validation score based on test results."""
        
        if not validation_runs.exists() and not test_runs.exists():
            return 0.3  # No validation performed
        
        total_score = 0.0
        weight_sum = 0.0
        
        # Test run scores
        for test_run in test_runs:
            weight = 1.0
            
            if test_run.run_type == 'targeted':
                weight = 2.0  # Targeted tests are more important
            elif test_run.run_type == 'regression':
                weight = 1.5  # Regression tests are important
            
            if test_run.status == 'passed':
                score = 1.0
            elif test_run.status == 'failed':
                # Partial credit for running tests
                if test_run.total_tests > 0:
                    score = test_run.passed_tests / test_run.total_tests
                else:
                    score = 0.0
            elif test_run.status == 'skipped':
                score = 0.5  # Neutral for skipped tests
            else:
                score = 0.0  # Error or cancelled
            
            total_score += score * weight
            weight_sum += weight
        
        # Validation run scores (non-test validations)
        for validation in validation_runs.exclude(validation_type='multi_stage'):
            if validation.status == 'passed':
                total_score += 1.0
                weight_sum += 1.0
            elif validation.status == 'failed':
                total_score += 0.0
                weight_sum += 1.0
        
        if weight_sum == 0:
            return 0.3
        
        return total_score / weight_sum
    
    def _calculate_relevance_score(self, task: TaskRun, candidate: CandidatePatch) -> float:
        """Calculate relevance score based on how well candidate addresses the task."""
        
        # Base relevance on strategy appropriateness
        strategy = candidate.patch_metadata.get('strategy', 'unknown')
        task_type = task.task_type
        
        strategy_relevance = {
            ('feature', 'comprehensive'): 0.9,
            ('feature', 'conservative'): 0.7,
            ('feature', 'incremental'): 0.8,
            ('feature', 'alternative'): 0.6,
            
            ('bugfix', 'conservative'): 0.9,
            ('bugfix', 'comprehensive'): 0.6,
            ('bugfix', 'incremental'): 0.8,
            ('bugfix', 'alternative'): 0.5,
            
            ('refactor', 'comprehensive'): 0.9,
            ('refactor', 'conservative'): 0.6,
            ('refactor', 'incremental'): 0.8,
            ('refactor', 'alternative'): 0.7,
            
            ('test', 'comprehensive'): 0.8,
            ('test', 'conservative'): 0.7,
            ('test', 'incremental'): 0.9,
            ('test', 'alternative'): 0.6
        }
        
        base_score = strategy_relevance.get((task_type, strategy), 0.5)
        
        # Adjust based on file coverage
        touched_files = len(candidate.touched_files)
        if touched_files == 0:
            return 0.0
        elif touched_files <= 3:
            return base_score  # Good coverage
        elif touched_files <= 10:
            return base_score * 0.9  # Slightly less focused
        else:
            return base_score * 0.7  # Too many files, less focused
    
    def _calculate_risk_score(self, candidate: CandidatePatch) -> float:
        """Calculate risk score (higher = more risky)."""
        
        risk_factors = []
        
        # File count risk
        file_count = len(candidate.touched_files)
        if file_count > 20:
            risk_factors.append(0.8)
        elif file_count > 10:
            risk_factors.append(0.5)
        elif file_count > 5:
            risk_factors.append(0.3)
        else:
            risk_factors.append(0.1)
        
        # Strategy risk
        strategy = candidate.patch_metadata.get('strategy', 'unknown')
        strategy_risk = {
            'conservative': 0.1,
            'incremental': 0.2,
            'comprehensive': 0.5,
            'alternative': 0.7
        }
        risk_factors.append(strategy_risk.get(strategy, 0.5))
        
        # Validation risk (if validation failed, higher risk)
        validation_runs = candidate.validation_runs.all()
        if validation_runs.filter(status='failed').exists():
            risk_factors.append(0.8)
        elif not validation_runs.exists():
            risk_factors.append(0.5)  # Unknown risk
        else:
            risk_factors.append(0.1)  # Low risk if validated
        
        # Calculate average risk
        if risk_factors:
            return sum(risk_factors) / len(risk_factors)
        
        return 0.5  # Default medium risk
    
    def _calculate_quality_score(self, candidate: CandidatePatch, validation_runs: List[ValidationRun]) -> float:
        """Calculate quality score based on various quality indicators."""
        
        quality_factors = []
        
        # Test coverage quality
        test_runs = TestRun.objects.filter(candidate_patch=candidate)
        if test_runs.exists():
            passed_tests = sum(run.passed_tests for run in test_runs if run.status == 'passed')
            total_tests = sum(run.total_tests for run in test_runs)
            if total_tests > 0:
                quality_factors.append(passed_tests / total_tests)
            else:
                quality_factors.append(0.5)
        else:
            quality_factors.append(0.3)  # No tests
        
        # Validation completeness
        validation_stages = set(validation_runs.values_list('stage_name', flat=True))
        expected_stages = {'syntax_validation', 'comprehensive_validation'}
        completeness = len(validation_stages & expected_stages) / len(expected_stages)
        quality_factors.append(completeness)
        
        # Patch metadata quality
        metadata = candidate.patch_metadata
        if metadata.get('generation_method') == 'llm_based':
            quality_factors.append(0.8)  # LLM-generated patches are generally good quality
        else:
            quality_factors.append(0.5)
        
        # File diversity (too many files might indicate lack of focus)
        file_count = len(candidate.touched_files)
        if file_count <= 5:
            quality_factors.append(0.9)
        elif file_count <= 15:
            quality_factors.append(0.7)
        else:
            quality_factors.append(0.4)
        
        # Calculate average quality
        if quality_factors:
            return sum(quality_factors) / len(quality_factors)
        
        return 0.5  # Default medium quality
    
    def _get_scoring_weights(self, task_type: str) -> Dict[str, float]:
        """Get scoring weights based on task type."""
        
        weights = {
            'feature': {
                'syntax': 0.1,
                'validation': 0.3,
                'relevance': 0.3,
                'risk': 0.2,
                'quality': 0.1
            },
            'bugfix': {
                'syntax': 0.15,
                'validation': 0.4,
                'relevance': 0.25,
                'risk': 0.15,
                'quality': 0.05
            },
            'refactor': {
                'syntax': 0.1,
                'validation': 0.25,
                'relevance': 0.2,
                'risk': 0.25,
                'quality': 0.2
            },
            'test': {
                'syntax': 0.1,
                'validation': 0.4,
                'relevance': 0.3,
                'risk': 0.1,
                'quality': 0.1
            },
            'custom': {
                'syntax': 0.1,
                'validation': 0.25,
                'relevance': 0.25,
                'risk': 0.2,
                'quality': 0.2
            }
        }
        
        return weights.get(task_type, weights['custom'])
    
    def get_best_candidate(self, task: TaskRun) -> Optional[CandidatePatch]:
        """Get the best scoring candidate for a task."""
        
        try:
            best_score = CandidateScore.objects.filter(task=task).order_by('-final_score').first()
            return best_score.candidate_patch if best_score else None
        except Exception:
            return None
    
    def get_candidate_summary(self, candidate: CandidatePatch) -> Dict[str, Any]:
        """Get a summary of candidate scoring."""
        
        try:
            score = CandidateScore.objects.get(candidate_patch=candidate)
            return {
                'candidate_key': candidate.candidate_key,
                'final_score': score.final_score,
                'rank': score.rank,
                'component_scores': {
                    'syntax': score.syntax_score,
                    'validation': score.validation_score,
                    'relevance': score.relevance_score,
                    'risk': score.risk_score,
                    'quality': score.quality_score
                },
                'metadata': score.scoring_metadata
            }
        except CandidateScore.DoesNotExist:
            return {
                'candidate_key': candidate.candidate_key,
                'final_score': 0.0,
                'rank': 999,
                'error': 'Score not calculated'
            }
