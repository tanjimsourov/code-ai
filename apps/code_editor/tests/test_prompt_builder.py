"""
Unit tests for PromptBuilderService in code_editor.services.prompt_builder.

These tests verify that the prompt builder constructs the appropriate
messages or strings based on the provided parameters.
"""

from django.test import SimpleTestCase

from code_editor.services.prompt_builder import PromptBuilderService


class PromptBuilderTests(SimpleTestCase):
    def test_build_chat_prompt_inserts_system_prompt(self) -> None:
        messages = [{'role': 'user', 'content': 'hello'}]
        system_prompt = 'you are helpful'
        result = PromptBuilderService.build_chat_prompt(messages, system_prompt)
        # Should have system prompt inserted at start
        self.assertEqual(result[0]['role'], 'system')
        self.assertEqual(result[0]['content'], system_prompt)
        # Original user message should follow
        self.assertEqual(result[1], messages[0])

    def test_build_completion_prompt_includes_all_parts(self) -> None:
        prompt = PromptBuilderService.build_completion_prompt(
            prefix='print("hi")', suffix='return x', language='python', filename='test.py', cursor_context='ctx'
        )
        # Check that all provided sections are present in the string
        self.assertIn('Language: python', prompt)
        self.assertIn('File: test.py', prompt)
        self.assertIn('Context: ctx', prompt)
        self.assertIn('Code to complete:\nprint("hi")', prompt)
        self.assertIn('Expected suffix:\nreturn x', prompt)

    def test_build_edit_prompt_structures_messages(self) -> None:
        messages = PromptBuilderService.build_edit_prompt(
            instruction='change', code='print("hi")', language='python', filename='test.py'
        )
        self.assertEqual(messages[0]['role'], 'system')
        self.assertIn('code editing assistant', messages[0]['content'])
        self.assertIn('python', messages[0]['content'])
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('Instruction: change', messages[1]['content'])
        self.assertIn('print("hi")', messages[1]['content'])
        self.assertIn('File: test.py', messages[1]['content'])

