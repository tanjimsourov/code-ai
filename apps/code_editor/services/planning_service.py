"""Planning service for task decomposition and execution planning."""

from typing import List, Dict, Any, Optional
from ..models import TaskRun, PlanNode
from ..services import ChatService


class PlanningService:
    """Service for intelligent task planning and decomposition."""
    
    def __init__(self):
        self.chat_service = ChatService()
    
    def decompose_task(self, task: TaskRun) -> List[PlanNode]:
        """Decompose a task into a plan of execution nodes."""
        
        # Generate initial plan using LLM
        plan_content = self._generate_initial_plan(task)
        
        # Parse plan into structured nodes
        root_node = PlanNode.objects.create(
            task=task,
            node_key='root',
            title='Root Plan',
            description=plan_content,
            action_type='plan',
            order=0,
            status='planned',
            metadata={'instruction': task.instruction}
        )
        
        # Create sub-nodes based on task type
        sub_nodes = self._create_sub_nodes(task, root_node)
        
        return [root_node] + sub_nodes
    
    def _generate_initial_plan(self, task: TaskRun) -> str:
        """Generate initial plan using LLM."""
        
        system_prompt = self._get_planning_system_prompt(task.task_type)
        
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': task.instruction}
        ]
        
        try:
            response = self.chat_service.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=800
            )
            
            if isinstance(response, dict):
                choices = response.get('choices') or []
                if choices:
                    first_choice = choices[0] or {}
                    message = first_choice.get('message') or {}
                    return message.get('content', '') or ''
            
            return f"Plan could not be generated for: {task.instruction}"
            
        except Exception as exc:
            return f"Failed to generate plan: {exc}"
    
    def _get_planning_system_prompt(self, task_type: str) -> str:
        """Get system prompt for planning based on task type."""
        
        base_prompt = (
            "You are an expert software engineering planner. "
            "Break down the request into specific, actionable steps. "
            "For each step, identify: "
            "1. What files need to be modified "
            "2. What changes are needed "
            "3. Dependencies between steps "
            "4. Validation approach "
        )
        
        type_specific = {
            'feature': base_prompt + " Focus on implementing new functionality safely.",
            'bugfix': base_prompt + " Focus on identifying root cause and minimal fixes.",
            'refactor': base_prompt + " Focus on improving code structure without breaking functionality.",
            'test': base_prompt + " Focus on comprehensive test coverage.",
            'custom': base_prompt
        }
        
        return type_specific.get(task_type, base_prompt)
    
    def _create_sub_nodes(self, task: TaskRun, root_node: PlanNode) -> List[PlanNode]:
        """Create sub-nodes for task execution."""
        
        nodes = []
        
        # Common execution phases
        phases = [
            ('context_retrieval', 'Retrieve Repository Context', 'Gather relevant code context'),
            ('file_selection', 'Select Target Files', 'Identify files to modify'),
            ('patch_generation', 'Generate Patches', 'Create candidate solutions'),
            ('validation', 'Validate Changes', 'Test and verify solutions'),
            ('finalization', 'Finalize Solution', 'Apply best solution')
        ]
        
        for i, (key, title, description) in enumerate(phases, 1):
            node = PlanNode.objects.create(
                task=task,
                parent=root_node,
                node_key=key,
                title=title,
                description=description,
                action_type='execution_phase',
                order=i,
                status='planned',
                depends_on=[root_node.node_key] if i > 1 else [],
                metadata={'phase_order': i}
            )
            nodes.append(node)
        
        return nodes
