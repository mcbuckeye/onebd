"""
Unit tests for TreeCache service.

TDD: tests written before implementation.
Uses MagicMock for session — no real DB needed.
"""
import json
import unittest
from unittest.mock import MagicMock, patch, call
from typing import Optional

# Will fail until tree_cache.py is implemented
from unified_api.services.tree_cache import TreeCache


class TestTreeCacheGetTree(unittest.TestCase):
    """Tests for TreeCache.get_tree()"""

    def setUp(self):
        self.mock_session = MagicMock()
        self.session_factory = MagicMock(return_value=self.mock_session)
        self.cache = TreeCache(self.session_factory)

    def test_get_tree_returns_dict_when_found(self):
        """get_tree returns parsed dict when contract exists in cache"""
        tree_data = {"nodes": [{"id": 1, "text": "Section 1"}], "depth": 2}
        mock_row = MagicMock()
        mock_row._mapping = {"tree_json": tree_data}
        self.mock_session.execute.return_value.fetchone.return_value = mock_row

        result = self.cache.get_tree(42)

        self.assertEqual(result, tree_data)
        self.mock_session.close.assert_called_once()

    def test_get_tree_returns_none_when_not_found(self):
        """get_tree returns None when contract not in cache"""
        self.mock_session.execute.return_value.fetchone.return_value = None

        result = self.cache.get_tree(999)

        self.assertIsNone(result)
        self.mock_session.close.assert_called_once()

    def test_get_tree_closes_session_on_exception(self):
        """get_tree closes session even if exception is raised"""
        self.mock_session.execute.side_effect = Exception("DB error")

        with self.assertRaises(Exception):
            self.cache.get_tree(42)

        self.mock_session.close.assert_called_once()

    def test_get_tree_queries_by_contract_id(self):
        """get_tree executes a query with the correct contract_id parameter"""
        self.mock_session.execute.return_value.fetchone.return_value = None

        self.cache.get_tree(123)

        self.mock_session.execute.assert_called_once()
        call_args = self.mock_session.execute.call_args
        # Second arg should be params dict with contract_id
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", call_args[0][1] if len(call_args[0]) > 1 else None)
        # Extract from positional or keyword args
        execute_args = self.mock_session.execute.call_args
        if execute_args.args and len(execute_args.args) > 1:
            params = execute_args.args[1]
        elif execute_args.kwargs:
            params = execute_args.kwargs.get("params", {})
        self.assertEqual(params.get("contract_id"), 123)


class TestTreeCacheGetTreeByDeal(unittest.TestCase):
    """Tests for TreeCache.get_tree_by_deal()"""

    def setUp(self):
        self.mock_session = MagicMock()
        self.session_factory = MagicMock(return_value=self.mock_session)
        self.cache = TreeCache(self.session_factory)

    def test_get_tree_by_deal_returns_dict_when_found(self):
        """get_tree_by_deal returns most recent tree for deal"""
        tree_data = {"nodes": [], "deal": 77}
        mock_row = MagicMock()
        mock_row._mapping = {"tree_json": tree_data}
        self.mock_session.execute.return_value.fetchone.return_value = mock_row

        result = self.cache.get_tree_by_deal(77)

        self.assertEqual(result, tree_data)
        self.mock_session.close.assert_called_once()

    def test_get_tree_by_deal_returns_none_when_not_found(self):
        """get_tree_by_deal returns None when deal not in cache"""
        self.mock_session.execute.return_value.fetchone.return_value = None

        result = self.cache.get_tree_by_deal(404)

        self.assertIsNone(result)

    def test_get_tree_by_deal_closes_session_on_exception(self):
        """get_tree_by_deal closes session even on exception"""
        self.mock_session.execute.side_effect = RuntimeError("connection lost")

        with self.assertRaises(RuntimeError):
            self.cache.get_tree_by_deal(77)

        self.mock_session.close.assert_called_once()


class TestTreeCacheStoreTree(unittest.TestCase):
    """Tests for TreeCache.store_tree()"""

    def setUp(self):
        self.mock_session = MagicMock()
        self.session_factory = MagicMock(return_value=self.mock_session)
        self.cache = TreeCache(self.session_factory)

    def test_store_tree_executes_upsert(self):
        """store_tree executes an INSERT ... ON CONFLICT DO UPDATE query"""
        tree = {"nodes": [{"id": 1}]}
        self.cache.store_tree(
            contract_id=10, deal_id=20, tree_json=tree, model="gpt-4o", line_count=500
        )

        self.mock_session.execute.assert_called_once()
        # Verify the SQL contains ON CONFLICT
        sql_text = str(self.mock_session.execute.call_args[0][0])
        self.assertIn("ON CONFLICT", sql_text.upper())

    def test_store_tree_commits_session(self):
        """store_tree commits after successful write"""
        tree = {"nodes": []}
        self.cache.store_tree(
            contract_id=10, deal_id=20, tree_json=tree, model="gpt-4o"
        )

        self.mock_session.commit.assert_called_once()
        self.mock_session.close.assert_called_once()

    def test_store_tree_passes_correct_params(self):
        """store_tree passes serialized JSON and correct params"""
        tree = {"nodes": [{"id": 1, "text": "Article 1"}]}
        self.cache.store_tree(
            contract_id=55,
            deal_id=99,
            tree_json=tree,
            model="claude-3-5-sonnet",
            line_count=300,
        )

        execute_args = self.mock_session.execute.call_args
        params = execute_args.args[1] if len(execute_args.args) > 1 else {}
        self.assertEqual(params["contract_id"], 55)
        self.assertEqual(params["deal_id"], 99)
        self.assertEqual(params["model"], "claude-3-5-sonnet")
        self.assertEqual(params["line_count"], 300)
        # tree_json should be serialized as JSON string
        self.assertEqual(params["tree_json"], json.dumps(tree))

    def test_store_tree_handles_none_line_count(self):
        """store_tree works when line_count is not provided (defaults to None)"""
        tree = {"nodes": []}
        # Should not raise
        self.cache.store_tree(contract_id=10, deal_id=20, tree_json=tree, model="gpt-4o")

        execute_args = self.mock_session.execute.call_args
        params = execute_args.args[1] if len(execute_args.args) > 1 else {}
        self.assertIsNone(params.get("line_count"))

    def test_store_tree_rolls_back_on_exception(self):
        """store_tree rolls back and closes session on DB error"""
        self.mock_session.execute.side_effect = Exception("constraint violation")

        with self.assertRaises(Exception):
            self.cache.store_tree(
                contract_id=10, deal_id=20, tree_json={}, model="gpt-4o"
            )

        self.mock_session.rollback.assert_called_once()
        self.mock_session.close.assert_called_once()


class TestTreeCacheHasTree(unittest.TestCase):
    """Tests for TreeCache.has_tree()"""

    def setUp(self):
        self.mock_session = MagicMock()
        self.session_factory = MagicMock(return_value=self.mock_session)
        self.cache = TreeCache(self.session_factory)

    def test_has_tree_returns_true_when_exists(self):
        """has_tree returns True when contract_id is in cache"""
        mock_row = MagicMock()
        mock_row._mapping = {"exists": True}
        # Simulate scalar result
        self.mock_session.execute.return_value.scalar.return_value = 1

        result = self.cache.has_tree(42)

        self.assertTrue(result)
        self.mock_session.close.assert_called_once()

    def test_has_tree_returns_false_when_not_exists(self):
        """has_tree returns False when contract_id not in cache"""
        self.mock_session.execute.return_value.scalar.return_value = 0

        result = self.cache.has_tree(999)

        self.assertFalse(result)

    def test_has_tree_closes_session_on_exception(self):
        """has_tree closes session even on exception"""
        self.mock_session.execute.side_effect = Exception("timeout")

        with self.assertRaises(Exception):
            self.cache.has_tree(42)

        self.mock_session.close.assert_called_once()

    def test_has_tree_queries_by_contract_id(self):
        """has_tree passes correct contract_id to query"""
        self.mock_session.execute.return_value.scalar.return_value = 0

        self.cache.has_tree(77)

        execute_args = self.mock_session.execute.call_args
        params = execute_args.args[1] if len(execute_args.args) > 1 else {}
        self.assertEqual(params.get("contract_id"), 77)


class TestTreeCacheInit(unittest.TestCase):
    """Tests for TreeCache.__init__()"""

    def test_init_stores_session_factory(self):
        """TreeCache stores the session_factory for later use"""
        factory = MagicMock()
        cache = TreeCache(factory)
        self.assertEqual(cache.session_factory, factory)

    def test_session_factory_called_per_method(self):
        """Each method call creates a new session from the factory"""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        factory = MagicMock(return_value=mock_session)
        cache = TreeCache(factory)

        cache.get_tree(1)
        cache.get_tree(2)

        self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
