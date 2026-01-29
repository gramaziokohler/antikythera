import pytest

from antikythera_orchestrator.conditionals import safe_eval_condition


class TestSafeEvalCondition:
    def test_basic_comparisons(self):
        context = {"a": 10, "b": 20}
        assert safe_eval_condition("a < b", context) is True
        assert safe_eval_condition("a > b", context) is False
        assert safe_eval_condition("a == 10", context) is True
        assert safe_eval_condition("b != 10", context) is True
        assert safe_eval_condition("a <= 10", context) is True
        assert safe_eval_condition("b >= 20", context) is True

    def test_equality_types(self):
        context = {"s": "hello", "n": 1}
        assert safe_eval_condition("s == 'hello'", context) is True
        assert safe_eval_condition('s == "hello"', context) is True
        assert safe_eval_condition("n == 1", context) is True

    def test_logic_operators(self):
        context = {"x": True, "y": False}
        assert safe_eval_condition("x and not y", context) is True
        assert safe_eval_condition("x or y", context) is True
        assert safe_eval_condition("not x", context) is False
        assert safe_eval_condition("True and True", context) is True
        assert safe_eval_condition("False or True", context) is True

    def test_list_and_tuple_membership(self):
        context = {"val": 5, "vals": [1, 2, 3, 4, 5]}
        assert safe_eval_condition("val in vals", context) is True
        assert safe_eval_condition("6 not in vals", context) is True
        assert safe_eval_condition("val in (1, 5)", context) is True
        assert safe_eval_condition("val in [1, 5]", context) is True

    def test_chained_comparisons(self):
        context = {"x": 5}
        assert safe_eval_condition("1 < x < 10", context) is True
        assert safe_eval_condition("1 < x < 3", context) is False
        assert safe_eval_condition("10 > x > 1", context) is True

    def test_access_context_variables(self):
        context = {"name": "Alice", "age": 30}
        assert safe_eval_condition("name == 'Alice'", context) is True
        assert safe_eval_condition("age >= 18", context) is True

    def test_complex_expression(self):
        context = {"status": "OPEN", "count": 5, "user": "admin"}
        expr = "(status == 'OPEN' and count > 0) or user == 'root'"
        assert safe_eval_condition(expr, context) is True

        context["status"] = "CLOSED"
        # left side becomes false, right side is false -> false
        assert safe_eval_condition(expr, context) is False

        context["user"] = "root"
        # left side is false, right side is true -> true
        assert safe_eval_condition(expr, context) is True

    def test_block_unsafe_functions(self):
        context = {}
        # asteval should block __import__
        with pytest.raises(ValueError, match="NameError"):
            safe_eval_condition("__import__('os').system('ls')", context)

    def test_math_operations(self):
        # asteval supports math
        context = {"a": 1, "b": 2}
        assert safe_eval_condition("a + b == 3", context) is True

    def test_attribute_access(self):
        # asteval supports attributes
        context = {"s": "hello"}
        assert safe_eval_condition("s.upper() == 'HELLO'", context) is True

    def test_unknown_identifier(self):
        context = {}
        # asteval collects errors and we raise them as ValueError
        with pytest.raises(ValueError, match="NameError"):
            safe_eval_condition("unknown_var == 1", context)

    def test_empty_logic(self):
        # asteval returns None for empty string, which bool() converts to False
        assert safe_eval_condition("", {}) is False
