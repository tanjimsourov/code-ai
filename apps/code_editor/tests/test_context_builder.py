"""
Unit tests for the token‑aware ``ContextBuilderService``.

These tests verify that the context builder correctly truncates
messages, prefixes/suffixes and code blocks based on token budgets
rather than raw character counts.  The tests deliberately use small
token budgets and known string lengths to ensure deterministic
behaviour when using the approximate token counter (≈4 characters per
token).  All tests rely on the default approximate backend, so they
should pass in environments where optional tokenizer libraries are
absent.
"""

import unittest

from code_editor.services.context_builder import ContextBuilderService


class ContextBuilderTests(unittest.TestCase):
    """Tests for the ContextBuilderService token truncation logic."""

    def test_build_chat_context_truncates_old_messages(self) -> None:
        """
        Given several messages of identical length, a small token budget
        should cause the builder to drop the oldest messages first.  The
        latest message must always be included even if it exceeds the
        budget by itself.
        """
        # Each message is 50 characters (~13 tokens under the 4 chars/token heuristic)
        messages = [{'role': 'user', 'content': 'a' * 50} for _ in range(5)]
        # Use a very small token budget to force truncation to only the last message
        result = ContextBuilderService.build_chat_context(messages, max_chars=25)
        # Expect only one message (the most recent) because 2 messages (~26 tokens) would exceed 25
        self.assertEqual(len(result), 1)
        # The last message in the original list should be preserved
        self.assertEqual(result[-1]['content'], messages[-1]['content'])

    def test_build_completion_context_truncates_suffix(self) -> None:
        """
        When the combined prefix and suffix exceed the token budget, only
        as many tokens of the suffix as will fit should be retained.
        """
        prefix = 'p' * 50  # ≈13 tokens
        suffix = 's' * 100  # ≈25 tokens
        # Total available tokens: 25.  Prefix uses ~13, so ~12 remain for suffix (≈48 characters)
        ctx = ContextBuilderService.build_completion_context(prefix, suffix, max_chars=25)
        self.assertEqual(ctx['prefix'], prefix)
        # Suffix should be truncated to fit within the remaining token budget
        # It should be no longer than 12 tokens ≈ 48 characters
        self.assertTrue(len(ctx['suffix']) <= 48)

    def test_build_edit_context_truncates_code(self) -> None:
        """
        The edit context should prioritise the instruction and truncate the
        code so that the combined token count does not exceed the budget.
        """
        instruction = 'do something'  # 12 chars ≈3 tokens
        code = 'c' * 200  # ≈50 tokens
        # Total budget of 50 tokens leaves ~47 tokens for code (≈188 characters)
        ctx = ContextBuilderService.build_edit_context(instruction, code, max_chars=50)
        # Ensure instruction is unchanged
        self.assertEqual(ctx['instruction'], instruction)
        # Ensure code is truncated to fit within available token budget
        self.assertTrue(len(ctx['code']) <= 188)

    def test_build_chat_context_includes_last_message_when_exceeds(self) -> None:
        """
        If a single message exceeds the token budget on its own, the
        context should still include that message rather than returning
        an empty list.
        """
        huge_message = {'role': 'user', 'content': 'a' * 5000}  # ≈1250 tokens
        result = ContextBuilderService.build_chat_context([huge_message], max_chars=10)
        self.assertEqual(result, [huge_message])

    def test_build_edit_context_truncates_large_instruction_and_drops_code(self) -> None:
        """
        When the instruction alone exceeds the token budget, it should be
        truncated and the code dropped entirely.
        """
        instruction = 'i' * 200  # ≈50 tokens
        code = 'c' * 50  # ≈13 tokens
        ctx = ContextBuilderService.build_edit_context(instruction, code, max_chars=10)
        # Code should be dropped because there is no room after truncating instruction
        self.assertEqual(ctx['code'], '')
        # Truncated instruction should fit within the 10 token budget (≈40 chars)
        self.assertTrue(len(ctx['instruction']) <= 40)

