from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


SOURCE_NOTE = (
    "Official-style Synthetic 18-domain regression item; not official benchmark data."
)


@dataclass(frozen=True)
class OfficialStyleCase:
    question_id: str
    question: str
    answer: str
    domain: str
    problem_type: str
    evaluation_mode: str = "short_answer"
    min_proof_score: float | None = None


DOMAIN_COUNTS = {
    "PDE": 7,
    "ComplexAnalysis": 7,
    "Topology": 7,
    "OperationsResearch": 7,
    "Algebra": 6,
    "LinearAlgebra": 6,
    "Calculus": 6,
    "RealAnalysis": 6,
    "Probability": 6,
    "Statistics": 6,
    "Geometry": 6,
    "NumberTheory": 6,
    "Combinatorics": 6,
    "Optimization": 6,
    "DifferentialEquations": 6,
    "DiscreteMath": 6,
    "FunctionalEquations": 6,
    "NumericalAnalysis": 6,
}

# fmt: off
RAW_CASES: dict[str, list[tuple[str, str, str, str, str, float | None]]] = {
    "PDE": [
        ("Classify the PDE u_xx + u_yy = 0.", "elliptic", "classification", "short_answer", None),
        ("Classify the PDE u_t - 4 u_xx = 0.", "parabolic", "classification", "short_answer", None),
        ("Classify the PDE u_tt - 9 u_xx = 0.", "hyperbolic", "classification", "short_answer", None),
        ("For u_t = 3 u_xx, what is the diffusion coefficient?", "3", "coefficient", "short_answer", None),
        ("For the heat equation u_t = k u_xx with k>0, name the equation type.", "parabolic", "classification", "short_answer", None),
        ("For Laplace equation Delta u = 0, what is the standard name for such a function u?", "harmonic", "concept", "short_answer", None),
        ("Prove that the sum of two solutions of a linear homogeneous PDE is again a solution.", "proved", "proof", "proof_quality", 0.68),
    ],
    "ComplexAnalysis": [
        ("Compute the residue of 1/(z-2) at z=2.", "1", "residue", "short_answer", None),
        ("Compute the residue of z/(z-1) at z=1.", "1", "residue", "short_answer", None),
        ("How many isolated singularities does 1/((z-1)(z-2)) have?", "2", "singularity_count", "short_answer", None),
        ("Evaluate the contour integral of 1/z around the unit circle counterclockwise.", "2*pi*I", "contour_integral", "short_answer", None),
        ("If f is entire and bounded, what theorem implies f is constant?", "Liouville", "theorem_name", "short_answer", None),
        ("For f(z)=z^3, compute f'(z).", "3*z**2", "derivative", "short_answer", None),
        ("Prove that if f and g are analytic, then f+g is analytic.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Topology": [
        ("In a metric space, is every open ball open? Answer yes or no.", "yes", "concept", "short_answer", None),
        ("Is every finite subset of R compact? Answer yes or no.", "yes", "compactness", "short_answer", None),
        ("Is the interval (0,1) compact in R with the usual topology? Answer yes or no.", "no", "compactness", "short_answer", None),
        ("Name the property: every open cover has a finite subcover.", "compactness", "definition", "short_answer", None),
        ("Is a continuous image of a compact space compact? Answer yes or no.", "yes", "compactness", "short_answer", None),
        ("In R, is the set [0,1] connected? Answer yes or no.", "yes", "connectedness", "short_answer", None),
        ("Prove that the intersection of two open sets is open.", "proved", "proof", "proof_quality", 0.68),
    ],
    "OperationsResearch": [
        ("Maximize 3x+2y subject to x+y<=4, x>=0, y>=0. What is the optimal value?", "12", "linear_programming", "short_answer", None),
        ("Minimize x+y subject to x>=2 and y>=3. What is the optimal value?", "5", "linear_programming", "short_answer", None),
        ("In a shortest path problem with nonnegative edge weights, which classic algorithm is used?", "Dijkstra", "algorithm", "short_answer", None),
        ("For EOQ with demand D, order cost S, holding cost H, give the optimal order quantity.", "sqrt(2*D*S/H)", "inventory", "short_answer", None),
        ("If a queue has arrival rate lambda=2 and service rate mu=5, what is rho?", "2/5", "queueing", "short_answer", None),
        ("In a max-flow network, what theorem equates max flow with a cut capacity?", "max-flow min-cut", "theorem_name", "short_answer", None),
        ("Prove briefly that a linear program over a nonempty bounded polytope has an optimal solution at an extreme point.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Algebra": [
        ("Solve: x**2 - 5*x + 6 = 0. Give sorted roots.", "[2,3]", "quadratic_equation", "short_answer", None),
        ("Compute the order of the cyclic group Z_12.", "12", "group_order", "short_answer", None),
        ("In a field, what is the multiplicative identity called?", "1", "field_axiom", "short_answer", None),
        ("Factor x**2 - 9 over the integers.", "(x-3)*(x+3)", "factorization", "short_answer", None),
        ("Solve: 3*x + 4 = 19.", "x=5", "linear_equation", "short_answer", None),
        ("Prove that the identity element in a group is unique.", "proved", "proof", "proof_quality", 0.68),
    ],
    "LinearAlgebra": [
        ("Compute the determinant of [[1,2],[3,4]].", "-2", "determinant", "short_answer", None),
        ("What is the trace of [[2,1],[0,5]]?", "7", "trace", "short_answer", None),
        ("What is the rank of the 2x2 identity matrix?", "2", "rank", "short_answer", None),
        ("Find the eigenvalues of diag(2,5). Give sorted values.", "[2,5]", "eigenvalue", "short_answer", None),
        ("If A is invertible, what is rank(A) for a 3x3 matrix?", "3", "rank", "short_answer", None),
        ("Prove that the columns of an invertible matrix are linearly independent.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Calculus": [
        ("Compute the derivative of f(x)=x**3.", "3*x**2", "derivative", "short_answer", None),
        ("Evaluate the limit as x approaches 2 of x**2 + 1.", "5", "limit", "short_answer", None),
        ("Compute the definite integral of 2*x from x=0 to x=3.", "9", "definite_integral", "short_answer", None),
        ("Find the critical point of f(x)=x**2-4*x.", "2", "critical_point", "short_answer", None),
        ("Compute d/dx sin(x).", "cos(x)", "derivative", "short_answer", None),
        ("Prove that if f'(x)=0 on an interval, then f is constant on that interval.", "proved", "proof", "proof_quality", 0.68),
    ],
    "RealAnalysis": [
        ("Does the sequence 1/n converge? Answer yes or no.", "yes", "sequence_convergence", "short_answer", None),
        ("What is the limit of 1/n as n tends to infinity?", "0", "sequence_limit", "short_answer", None),
        ("Is every convergent real sequence bounded? Answer yes or no.", "yes", "sequence_property", "short_answer", None),
        ("State the least upper bound property in one word.", "completeness", "definition", "short_answer", None),
        ("Is the union of two open intervals open in R? Answer yes or no.", "yes", "open_sets", "short_answer", None),
        ("Prove that a monotone increasing sequence bounded above converges.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Probability": [
        ("A fair coin is tossed 3 times. Probability of exactly 2 heads?", "3/8", "binomial_probability", "short_answer", None),
        ("A fair die is rolled. Probability of an even number?", "1/2", "probability", "short_answer", None),
        ("If X is Bernoulli(p), what is E[X]?", "p", "expectation", "short_answer", None),
        ("If X and Y are independent, what is P(A and B) in terms of P(A),P(B)?", "P(A)*P(B)", "independence", "short_answer", None),
        ("For Binomial(n,p), what is the mean?", "n*p", "expectation", "short_answer", None),
        ("Prove that probabilities of complementary events sum to 1.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Statistics": [
        ("Compute the mean of 2, 4, 6, 8.", "5", "mean", "short_answer", None),
        ("What is the sample size of the data set 1,1,2,3,5?", "5", "sample_size", "short_answer", None),
        ("For data 1,2,3, what is the median?", "2", "median", "short_answer", None),
        ("If Var(X)=4, what is the standard deviation?", "2", "standard_deviation", "short_answer", None),
        ("For a normal distribution, what parameter denotes the mean?", "mu", "notation", "short_answer", None),
        ("Prove that adding a constant c to all observations adds c to the mean.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Geometry": [
        ("A rectangle has length 8 and width 5. Compute its area.", "40", "area", "short_answer", None),
        ("A right triangle has legs 3 and 4. Compute the hypotenuse.", "5", "pythagorean", "short_answer", None),
        ("Find the squared distance between (1,2) and (4,6).", "25", "coordinate_geometry", "short_answer", None),
        ("A circle has radius 3. Compute its area in terms of pi.", "9*pi", "area", "short_answer", None),
        ("A triangle has base 10 and height 6. Compute its area.", "30", "area", "short_answer", None),
        ("Prove that base angles of an isosceles triangle are equal.", "proved", "proof", "proof_quality", 0.68),
    ],
    "NumberTheory": [
        ("Compute gcd(48,18).", "6", "gcd", "short_answer", None),
        ("Compute lcm(6,8).", "24", "lcm", "short_answer", None),
        ("Find the least nonnegative residue of 7^5 modulo 19.", "11", "modular_exponent", "short_answer", None),
        ("Compute Euler phi of 12.", "4", "totient", "short_answer", None),
        ("How many positive divisors does 36 have?", "9", "divisor_count", "short_answer", None),
        ("Prove that if n is even, then n^2 is even.", "proved", "proof", "proof_quality", 0.68),
    ],
    "Combinatorics": [
        ("Compute 8 choose 2.", "28", "combination", "short_answer", None),
        ("How many permutations of 3 distinct objects are there?", "6", "permutation", "short_answer", None),
        ("How many subsets does a 4-element set have?", "16", "subsets", "short_answer", None),
        ("How many ways to arrange A,B,C in a row?", "6", "permutation", "short_answer", None),
        ("What is C(5,0)?", "1", "combination", "short_answer", None),
        ("Prove Pascal's identity C(n,k)=C(n-1,k)+C(n-1,k-1).", "proved", "proof", "proof_quality", 0.68),
    ],
    "Optimization": [
        ("Minimize f(x)=(x-3)^2. What is the minimizer?", "3", "unconstrained_optimization", "short_answer", None),
        ("Maximize -x^2+4*x. What is the maximum value?", "4", "quadratic_optimization", "short_answer", None),
        ("For f(x)=x^2, is x=0 a local minimum? Answer yes or no.", "yes", "local_minimum", "short_answer", None),
        ("With constraint x+y=10, maximize xy over nonnegative x,y. What is the maximum?", "25", "constrained_optimization", "short_answer", None),
        ("Name the first-order condition for an unconstrained differentiable optimum.", "gradient zero", "optimality_condition", "short_answer", None),
        ("Prove that a convex function has no strict non-global local minimum.", "proved", "proof", "proof_quality", 0.68),
    ],
    "DifferentialEquations": [
        ("Solve y'=2y with y(0)=1. Give y(1).", "exp(2)", "ode", "short_answer", None),
        ("Solve y'=3 with y(0)=2. Give y(4).", "14", "ode", "short_answer", None),
        ("For y''+y=0, name one fundamental solution.", "sin(x)", "ode", "short_answer", None),
        ("For y'=ky, what is the general solution form?", "C*exp(k*x)", "ode", "short_answer", None),
        ("Is y=0 a solution to y'=y? Answer yes or no.", "yes", "ode", "short_answer", None),
        ("Prove that a linear combination of two homogeneous linear ODE solutions is a solution.", "proved", "proof", "proof_quality", 0.68),
    ],
    "DiscreteMath": [
        ("In a graph with 5 vertices and degrees 2,2,2,2,2, how many edges?", "5", "graph_degree", "short_answer", None),
        ("How many edges are in a tree with 10 vertices?", "9", "tree", "short_answer", None),
        ("Is every tree connected? Answer yes or no.", "yes", "tree", "short_answer", None),
        ("How many truth assignments are there for 3 Boolean variables?", "8", "logic", "short_answer", None),
        ("What is the complement of true in Boolean logic?", "false", "logic", "short_answer", None),
        ("Prove that the sum of degrees in a finite graph is twice the number of edges.", "proved", "proof", "proof_quality", 0.68),
    ],
    "FunctionalEquations": [
        ("If f(x)=2*x+1, compute f(4).", "9", "function_evaluation", "short_answer", None),
        ("If f(x)=x+2 and g(x)=3*x, compute f(g(2)).", "8", "function_composition", "short_answer", None),
        ("If f(x+y)=f(x)+f(y) and f(1)=3 for integer inputs, compute f(4).", "12", "cauchy_discrete", "short_answer", None),
        ("If f(f(x))=x and f(2)=5, what is f(5)?", "2", "involution", "short_answer", None),
        ("If f(x)=x^2, solve f(x)=9 over nonnegative x.", "3", "function_equation", "short_answer", None),
        ("Prove that the composition of two injective functions is injective.", "proved", "proof", "proof_quality", 0.68),
    ],
    "NumericalAnalysis": [
        ("Using Newton's method for f(x)=x^2-2, what is f'(x)?", "2*x", "newton_method", "short_answer", None),
        ("With step h=0.1, forward Euler uses how many steps from t=0 to t=1?", "10", "euler_method", "short_answer", None),
        ("For trapezoidal rule on [0,1] with one panel, what weight multiplies f(0)+f(1)?", "1/2", "quadrature", "short_answer", None),
        ("What is the bisection interval midpoint of [2,6]?", "4", "bisection", "short_answer", None),
        ("If an iterative method has error e_{n+1}=0.5e_n, what is the contraction factor?", "0.5", "convergence", "short_answer", None),
        ("Prove that bisection halves the interval length at each iteration.", "proved", "proof", "proof_quality", 0.68),
    ],
}
# fmt: on


def build_cases() -> list[OfficialStyleCase]:
    cases: list[OfficialStyleCase] = []
    for domain, target_count in DOMAIN_COUNTS.items():
        raw_cases = RAW_CASES[domain]
        if len(raw_cases) != target_count:
            raise ValueError(
                f"{domain} expected {target_count} cases, got {len(raw_cases)}"
            )
        prefix = domain.lower().replace("analysis", "analysis").replace(" ", "_")
        for idx, (question, answer, problem_type, eval_mode, min_score) in enumerate(
            raw_cases, start=1
        ):
            cases.append(
                OfficialStyleCase(
                    question_id=f"os18_{prefix}_{idx:03d}",
                    question=question,
                    answer=answer,
                    domain=domain,
                    problem_type=problem_type,
                    evaluation_mode=eval_mode,
                    min_proof_score=min_score,
                )
            )
    if len(cases) != 112:
        raise ValueError(f"expected 112 cases, got {len(cases)}")
    return cases


def write_cases(
    cases: list[OfficialStyleCase], questions_path: Path, answers_path: Path
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
                    "evaluation_mode": case.evaluation_mode,
                    "source": SOURCE_NOTE,
                    **(
                        {"min_proof_score": case.min_proof_score}
                        if case.min_proof_score is not None
                        else {}
                    ),
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
        description=(
            "Generate a 112-item official-style synthetic suite across 18 math "
            "domains."
        )
    )
    parser.add_argument("--questions", default="data/official_style_18domain_112.jsonl")
    parser.add_argument(
        "--answers",
        default="data/official_style_18domain_112_answers.jsonl",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = build_cases()
    write_cases(cases, Path(args.questions), Path(args.answers))
    print(f"generated={len(cases)}")
    print(f"domains={len(DOMAIN_COUNTS)}")
    print(f"questions={args.questions}")
    print(f"answers={args.answers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
