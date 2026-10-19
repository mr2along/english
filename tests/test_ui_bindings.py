from __future__ import annotations

import ast
import unittest
from pathlib import Path


class GradioBindingTests(unittest.TestCase):
    def test_callback_argument_counts_match_bound_inputs(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(app_path.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        mismatches = []
        event_methods = {"click", "change", "input", "submit", "then", "load"}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in event_methods or not node.args:
                continue

            callback = node.args[0]
            if isinstance(callback, ast.Constant) and callback.value is None:
                continue
            if isinstance(callback, ast.Name) and callback.id in functions:
                callback_args = functions[callback.id].args.args
                parameter_names = [arg.arg for arg in callback_args]
            elif isinstance(callback, ast.Lambda):
                parameter_names = [arg.arg for arg in callback.args.args]
            else:
                continue

            if len(node.args) < 2 or (
                isinstance(node.args[1], ast.Constant) and node.args[1].value is None
            ):
                input_count = 0
            elif isinstance(node.args[1], (ast.List, ast.Tuple)):
                input_count = len(node.args[1].elts)
            else:
                input_count = 1

            # Gradio supplies its special progress argument automatically.
            parameter_count = sum(name != "progress" for name in parameter_names)
            if parameter_count != input_count:
                mismatches.append(
                    f"line {node.lineno}: {callback.id if isinstance(callback, ast.Name) else '<lambda>'} "
                    f"expects {parameter_count} inputs, bound to {input_count}"
                )

        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
