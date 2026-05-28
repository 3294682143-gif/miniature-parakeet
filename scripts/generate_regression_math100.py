from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from fractions import Fraction
from math import comb, gcd
from pathlib import Path


@dataclass(frozen=True)
class RegressionCase:
    question_id: str
    question: str
    answer: str
    domain: str
    problem_type: str
    source: str


SOURCE_NOTE = "OpenStax-style public textbook topic adaptation; synthetic values."


def _case(
    qid: str, question: str, answer: str, domain: str, problem_type: str
) -> RegressionCase:
    return RegressionCase(qid, question, answer, domain, problem_type, SOURCE_NOTE)


def _fmt_fraction(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(value)


def build_cases() -> list[RegressionCase]:
    cases: list[RegressionCase] = []

    for i in range(1, 21):
        a = i % 5 + 1
        x = i - 6
        b = i % 7 - 3
        c = a * x + b
        cases.append(
            _case(
                f"reg100_linear_{i:03d}",
                f"solve: {a}*x + {b} = {c}",
                f"x={x}",
                "algebra",
                "linear_equation",
            )
        )

    roots = [
        (-6, -1),
        (-5, 2),
        (-4, 3),
        (-3, 1),
        (-2, 5),
        (-1, 4),
        (0, 7),
        (1, 6),
        (2, 8),
        (3, 9),
        (-7, 3),
        (-8, 2),
        (-9, 1),
        (4, 10),
        (5, 11),
        (-10, -2),
        (-6, 6),
        (-4, 8),
        (2, 12),
        (3, 13),
    ]
    for i, (r1, r2) in enumerate(roots, start=1):
        b = -(r1 + r2)
        c = r1 * r2
        sign_b = "+" if b >= 0 else "-"
        sign_c = "+" if c >= 0 else "-"
        question = f"solve: x**2 {sign_b} {abs(b)}*x {sign_c} {abs(c)} = 0"
        cases.append(
            _case(
                f"reg100_quad_{i:03d}",
                question,
                f"[{min(r1, r2)},{max(r1, r2)}]",
                "algebra",
                "quadratic_equation",
            )
        )

    for i in range(1, 21):
        a = i + 2
        b = i % 6 + 3
        c = i % 5 + 4
        d = i % 3 + 1
        answer = (a + b) * (c - d)
        cases.append(
            _case(
                f"reg100_arith_{i:03d}",
                f"({a}+{b})*({c}-{d})",
                str(answer),
                "arithmetic",
                "calculation",
            )
        )

    for i in range(1, 13):
        coef = i % 5 + 1
        power = i % 4 + 2
        linear = i % 7
        answer = f"{coef * power}*x"
        if power - 1 != 1:
            answer = f"{coef * power}*x**{power - 1}"
        if linear:
            answer = f"{answer}+{linear}"
        cases.append(
            _case(
                f"reg100_deriv_{i:03d}",
                f"Compute the derivative of f(x)={coef}*x**{power} + {linear}*x. Give the final answer only.",
                answer,
                "calculus",
                "derivative",
            )
        )

    for i in range(1, 9):
        point = i - 3
        b = i % 5 + 1
        answer = point**2 + b * point
        cases.append(
            _case(
                f"reg100_limit_{i:03d}",
                f"Evaluate the limit as x approaches {point} of x**2 + {b}*x. Give the final answer only.",
                str(answer),
                "calculus",
                "limit",
            )
        )

    for i in range(1, 9):
        coef = i % 6 + 1
        upper = i % 5 + 2
        answer = Fraction(coef * upper * upper, 2)
        cases.append(
            _case(
                f"reg100_integral_{i:03d}",
                f"Compute the definite integral of {coef}*x from x=0 to x={upper}. Give the final answer only.",
                _fmt_fraction(answer),
                "calculus",
                "definite_integral",
            )
        )

    for i, base in enumerate([2, 3, 4, 5, 2, 3, 4, 5, 2, 3], start=1):
        exponent = i % 5 + 2
        value = base**exponent
        cases.append(
            _case(
                f"reg100_log_{i:03d}",
                f"Compute log base {base} of {value}. Give the final answer only.",
                str(exponent),
                "precalculus",
                "logarithm",
            )
        )
        cases.append(
            _case(
                f"reg100_exp_{i:03d}",
                f"Solve the exponential equation {base}**x = {value}. Give the final answer only.",
                str(exponent),
                "precalculus",
                "exponential_equation",
            )
        )

    for i in range(1, 11):
        length = i + 3
        width = i % 6 + 2
        cases.append(
            _case(
                f"reg100_rect_{i:03d}",
                f"A rectangle has length {length} and width {width}. Compute its area. Give the final answer only.",
                str(length * width),
                "geometry",
                "area",
            )
        )
        radius = i % 5 + 1
        circle_answer = "pi" if radius == 1 else f"{radius * radius}*pi"
        cases.append(
            _case(
                f"reg100_circle_{i:03d}",
                f"A circle has radius {radius}. Compute its area in terms of pi. Give the final answer only.",
                circle_answer,
                "geometry",
                "area",
            )
        )

    for i in range(1, 11):
        n = i % 5 + 3
        k = min(i % 4 + 1, n)
        probability = Fraction(comb(n, k), 2**n)
        cases.append(
            _case(
                f"reg100_prob_{i:03d}",
                f"A fair coin is tossed {n} times. What is the probability of exactly {k} heads? Give the final answer only.",
                _fmt_fraction(probability),
                "probability",
                "binomial_probability",
            )
        )
        choose_n = i + 5
        choose_k = i % 3 + 2
        cases.append(
            _case(
                f"reg100_choose_{i:03d}",
                f"Compute {choose_n} choose {choose_k}. Give the final answer only.",
                str(comb(choose_n, choose_k)),
                "combinatorics",
                "combination",
            )
        )

    for i in range(1, 21):
        a = 6 * i + 12
        b = 4 * i + 8
        cases.append(
            _case(
                f"reg300_gcd_{i:03d}",
                f"Compute gcd({a}, {b}). Give the final answer only.",
                str(gcd(a, b)),
                "number_theory",
                "gcd",
            )
        )
        x = i + 7
        m = i % 7 + 5
        cases.append(
            _case(
                f"reg300_mod_{i:03d}",
                f"Compute the remainder when {x * m + i} is divided by {m}. Give the final answer only.",
                str(i % m),
                "number_theory",
                "modular_arithmetic",
            )
        )

    for i in range(1, 21):
        x1, y1 = i, i % 5 - 2
        x2, y2 = i + 3, i % 7 + 1
        dist_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        cases.append(
            _case(
                f"reg300_dist2_{i:03d}",
                f"Find the squared distance between ({x1},{y1}) and ({x2},{y2}). Give the final answer only.",
                str(dist_sq),
                "geometry",
                "coordinate_geometry",
            )
        )
        base = i + 4
        height = i % 6 + 3
        cases.append(
            _case(
                f"reg300_tri_area_{i:03d}",
                f"A triangle has base {base} and height {height}. Compute its area. Give the final answer only.",
                _fmt_fraction(Fraction(base * height, 2)),
                "geometry",
                "area",
            )
        )

    for i in range(1, 21):
        first = i % 6 + 1
        diff = i % 5 + 2
        n = i % 8 + 5
        cases.append(
            _case(
                f"reg300_arith_seq_{i:03d}",
                f"An arithmetic sequence has a_1={first} and common difference {diff}. Compute a_{n}. Give the final answer only.",
                str(first + (n - 1) * diff),
                "recurrence",
                "arithmetic_sequence",
            )
        )
        ratio = i % 3 + 2
        cases.append(
            _case(
                f"reg300_geo_seq_{i:03d}",
                f"A geometric sequence has a_1={first} and ratio {ratio}. Compute a_{n}. Give the final answer only.",
                str(first * ratio ** (n - 1)),
                "recurrence",
                "geometric_sequence",
            )
        )

    for i in range(1, 21):
        a = i % 5 + 1
        b = i % 7 - 3
        x = i % 9 - 4
        cases.append(
            _case(
                f"reg300_func_eval_{i:03d}",
                f"If f(x)={a}*x + {b}, compute f({x}). Give the final answer only.",
                str(a * x + b),
                "functions",
                "function_evaluation",
            )
        )
        c = i % 4 + 2
        d = i % 6 - 2
        gx = c * x + d
        cases.append(
            _case(
                f"reg300_func_comp_{i:03d}",
                f"If f(x)={a}*x + {b} and g(x)={c}*x + {d}, compute f(g({x})). Give the final answer only.",
                str(a * gx + b),
                "functions",
                "function_composition",
            )
        )

    proof_templates = [
        ("even_sum", "Prove that the sum of two even integers is even."),
        ("odd_square", "Prove that the square of an odd integer is odd."),
        (
            "divisible_by_3",
            "Prove that if n is divisible by 3, then n^2 is divisible by 3.",
        ),
        ("commutative_add", "Prove that addition of integers is commutative."),
        ("positive_square", "Prove that the square of any real number is nonnegative."),
    ]
    for i in range(1, 31):
        name, prompt = proof_templates[(i - 1) % len(proof_templates)]
        cases.append(
            _case(
                f"reg300_proof_{i:03d}_{name}",
                f"{prompt} Give a concise proof.",
                "proved",
                "proof",
                "proof",
            )
        )

    return cases


def write_cases(
    cases: list[RegressionCase], questions_path: Path, answers_path: Path
) -> None:
    questions_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path.parent.mkdir(parents=True, exist_ok=True)
    questions_path.write_text(
        "\n".join(
            json.dumps(
                {"question_id": case.question_id, "question": case.question},
                ensure_ascii=False,
            )
            for case in cases
        )
        + "\n",
        encoding="utf-8",
    )
    answers_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "question_id": case.question_id,
                    "answer": case.answer,
                    "domain": case.domain,
                    "problem_type": case.problem_type,
                    "source": case.source,
                },
                ensure_ascii=False,
            )
            for case in cases
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic 100+ math regression set."
    )
    parser.add_argument("--questions", default="data/regression_math100.jsonl")
    parser.add_argument("--answers", default="data/regression_math100_answers.jsonl")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = build_cases()
    write_cases(cases, Path(args.questions), Path(args.answers))
    print(f"generated={len(cases)}")
    print(f"questions={args.questions}")
    print(f"answers={args.answers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
