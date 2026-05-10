from sympy import sympify


def evaluate_expr(expr: str) -> str:
    return str(sympify(expr))
