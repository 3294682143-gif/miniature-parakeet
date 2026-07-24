from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from math import gcd, isqrt
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.logging_utils import atomic_text_write


@dataclass(frozen=True)
class HiddenCase:
    question_id: str
    question: str
    answer: str
    domain: str
    problem_type: str
    evaluation_mode: str
    min_proof_score: float | None = None


SOURCE_NOTE = "Synthetic hidden-set-style hard math regression item."


def _factor_int(n: int) -> dict[int, int]:
    factors: dict[int, int] = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] = factors.get(d, 0) + 1
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors[n] = factors.get(n, 0) + 1
    return factors


def _totient(n: int) -> int:
    result = n
    for prime in _factor_int(n):
        result = result // prime * (prime - 1)
    return result


def _divisor_count(n: int) -> int:
    count = 1
    for exponent in _factor_int(n).values():
        count *= exponent + 1
    return count


def _format_sqrt_int(n: int) -> str:
    root = isqrt(n)
    if root * root == n:
        return str(root)
    outside = 1
    inside = n
    factor = 2
    while factor * factor <= inside:
        square = factor * factor
        while inside % square == 0:
            outside *= factor
            inside //= square
        factor += 1
    if outside == 1:
        return f"sqrt({inside})"
    if inside == 1:
        return str(outside)
    return f"{outside}*sqrt({inside})"


def _crt_two(a: int, m: int, b: int, n: int) -> int:
    for value in range(m * n):
        if value % m == a % m and value % n == b % n:
            return value
    raise ValueError("inconsistent CRT input")


def _proof_cases() -> list[HiddenCase]:
    prompts = [
        "Prove that sqrt(2) is irrational.",
        "Prove that there are infinitely many prime numbers.",
        "Prove that the sum of the first n positive odd integers is n^2.",
        "Prove that if n is odd, then n^2 is odd.",
        "Prove that if n^2 is even, then n is even.",
        "Prove that every integer congruent to 1 modulo 4 has an odd square congruent to 1 modulo 8.",
        "Prove that if a and b are coprime integers and a divides bc, then a divides c.",
        "Prove that for any integer n, n^3 - n is divisible by 6.",
        "Prove that the arithmetic mean of two positive real numbers is at least their geometric mean.",
        "Prove that the product of two consecutive integers is even.",
        "Prove that a rational root of a monic integer polynomial is an integer.",
        "Prove that if p is prime and p divides ab, then p divides a or p divides b.",
        "Prove that the square of any integer is congruent to 0 or 1 modulo 4.",
        "Prove that if gcd(a,b)=1, then gcd(a+b,a-b) divides 2.",
        "Prove that the sequence defined by a_1=1 and a_{n+1}=a_n+2n+1 equals n^2.",
        "Prove that a finite set with n elements has exactly 2^n subsets.",
        "Prove that the sum of the interior angles of a triangle is 180 degrees.",
        "Prove that the base angles of an isosceles triangle are equal.",
        "Prove that the medians of a triangle divide it into six equal-area triangles.",
        "Prove that if two chords of a circle are equal, then they are equidistant from the center.",
        "Prove that the perpendicular bisector of a chord passes through the center of the circle.",
        "Prove that a cyclic quadrilateral has opposite angles summing to 180 degrees.",
        "Prove that if two triangles are similar, then their areas are in the square ratio of corresponding sides.",
        "Prove that the altitude to the hypotenuse in a right triangle creates two triangles similar to the original.",
        "Prove that the binomial coefficient C(n,k) equals C(n,n-k).",
        "Prove Pascal's identity C(n,k)=C(n-1,k)+C(n-1,k-1).",
        "Prove by induction that 1+2+...+n=n(n+1)/2.",
        "Prove by induction that 2^n >= n+1 for all nonnegative integers n.",
        "Prove that the harmonic mean of two positive real numbers is at most their arithmetic mean.",
        "Prove that if a positive integer is divisible by 9, then the sum of its decimal digits is divisible by 9.",
        "Prove that among any n+1 integers, two have the same remainder modulo n.",
        "Prove that if p is an odd prime, then p has an inverse modulo 2p+1 whenever gcd(p,2p+1)=1.",
        "Prove that a graph with all vertex degrees at least 2 contains a cycle.",
        "Prove that if x+y and xy are integers, then x^2+y^2 is an integer.",
        "Prove that if real numbers x and y satisfy x^2+y^2=0, then x=0 and y=0.",
        "Prove that for positive real numbers x,y,z, (x+y+z)^2 >= 3(xy+yz+zx).",
        "Prove that if a sequence is increasing and bounded above, then it has at most one limit.",
        "Prove that the composition of two injective functions is injective.",
        "Prove that the inverse image of a union is the union of inverse images.",
        "Prove that if a divides b and b divides c, then a divides c.",
    ]
    return [
        HiddenCase(
            question_id=f"hard_hidden_proof_{idx:03d}",
            question=f"{prompt} Give a rigorous but concise proof.",
            answer="proved",
            domain="proof",
            problem_type="proof",
            evaluation_mode="proof_validity",
        )
        for idx, prompt in enumerate(prompts, start=1)
    ]


def _large_proof_cases() -> list[HiddenCase]:
    seed_cases = _proof_cases()
    prompts = [
        case.question.removesuffix(" Give a rigorous but concise proof.")
        for case in seed_cases
    ]
    methods = [
        "Use a direct proof.",
        "Use proof by contradiction where appropriate.",
        "Use induction if it is natural.",
    ]
    extra_templates = [
        "Prove that if a number is divisible by both 4 and 9, then it is divisible by 36.",
        "Prove that if gcd(a,b)=1 and gcd(a,c)=1, then gcd(a,bc)=1.",
        "Prove that the product of three consecutive integers is divisible by 6.",
        "Prove that if a prime p divides a^2, then p divides a.",
        "Prove that every integer square is congruent to 0, 1, or 4 modulo 8.",
        "Prove that if n is even, then n^3 is even.",
        "Prove that if n is odd, then n^3 is odd.",
        "Prove that there is no largest even integer.",
        "Prove that sqrt(3) is irrational.",
        "Prove that log_2(3) is irrational.",
        "Prove that if a divides b, then a divides kb for every integer k.",
        "Prove that if a divides b and a divides c, then a divides b+c.",
        "Prove that if a divides b and a divides c, then a divides b-c.",
        "Prove that every prime greater than 3 is congruent to 1 or 5 modulo 6.",
        "Prove that if p is prime and p>2, then p is odd.",
        "Prove that a polynomial of odd degree with real coefficients has a real root.",
        "Prove that the composition of two surjective functions is surjective.",
        "Prove that the inverse image of an intersection is the intersection of inverse images.",
        "Prove that if A is a subset of B, then A union B equals B.",
        "Prove that if A is a subset of B, then A intersection B equals A.",
        "Prove that if two lines are parallel, alternate interior angles are equal.",
        "Prove that vertical angles are equal.",
        "Prove that the diagonals of a parallelogram bisect each other.",
        "Prove that the diagonals of a rectangle are equal.",
        "Prove that the area of a triangle is half base times height.",
        "Prove that the perpendicular from the center of a circle to a chord bisects the chord.",
        "Prove that equal arcs in a circle subtend equal chords.",
        "Prove that the angle in a semicircle is a right angle.",
        "Prove that similar triangles have proportional medians.",
        "Prove that the centroid divides each median in a 2:1 ratio.",
        "Prove that the binomial theorem holds for nonnegative integer exponents.",
        "Prove that C(n,0)=C(n,n)=1.",
        "Prove that the sum of binomial coefficients in row n is 2^n.",
        "Prove that the alternating sum of binomial coefficients in row n is 0 for n>0.",
        "Prove that if a sequence has two limits, then the two limits are equal.",
        "Prove that every convergent sequence is bounded.",
        "Prove that the sum of two convergent sequences is convergent.",
        "Prove that if 0 <= a_n <= b_n and b_n tends to 0, then a_n tends to 0.",
        "Prove that the intersection of two open sets is open.",
        "Prove that the union of any collection of open sets is open.",
        "Prove that a finite union of closed sets is closed.",
        "Prove that the empty set is a subset of every set.",
        "Prove that set inclusion is transitive.",
        "Prove that equality of sets is equivalent to mutual inclusion.",
        "Prove that if x is rational and y is rational, then x+y is rational.",
        "Prove that if x is rational and y is rational, then xy is rational.",
        "Prove that if x is irrational and r is nonzero rational, then rx is irrational.",
        "Prove that between any two distinct rational numbers there is another rational number.",
        "Prove that if a and b are positive, then a/b is positive.",
        "Prove that if 0<a<b, then 1/b<1/a.",
        "Prove that the maximum of two real numbers is unique.",
        "Prove that absolute value satisfies |xy|=|x||y|.",
        "Prove the triangle inequality for real numbers.",
        "Prove that if |x|<epsilon for every epsilon>0, then x=0.",
        "Prove that the sum of two multiples of 5 is a multiple of 5.",
        "Prove that a decimal integer is divisible by 3 if and only if its digit sum is divisible by 3.",
        "Prove that if a number ends in 0 or 5, then it is divisible by 5.",
        "Prove that if an integer is congruent to 2 modulo 4, then it is not a square.",
        "Prove that if n is composite, then n has a prime divisor at most sqrt(n).",
        "Prove that every integer n>1 has a prime divisor.",
        "Prove that the least positive element of a nonempty set of positive integers exists.",
        "Prove Euclid's lemma using Bezout's identity.",
        "Prove that if ac is congruent to bc modulo m and gcd(a,m)=1, then c is congruent to b modulo m.",
        "Prove that modular congruence is an equivalence relation.",
        "Prove that if a is congruent to b modulo m, then a^k is congruent to b^k modulo m.",
        "Prove that if x is congruent to y modulo m, then x+z is congruent to y+z modulo m.",
        "Prove that if x is congruent to y modulo m, then xz is congruent to yz modulo m.",
        "Prove that the sum of degrees in a finite graph is twice the number of edges.",
        "Prove that a finite tree with n vertices has n-1 edges.",
        "Prove that every finite tree has at least two leaves.",
        "Prove that a connected graph with n vertices and n-1 edges is a tree.",
        "Prove that in any group, the identity element is unique.",
        "Prove that in any group, inverses are unique.",
        "Prove that cancellation holds in a group.",
        "Prove that the inverse of a product in a group is the product of inverses in reverse order.",
        "Prove that the kernel of a homomorphism is a subgroup.",
        "Prove that the image of a subgroup under a homomorphism is a subgroup.",
        "Prove that the intersection of two subgroups is a subgroup.",
        "Prove that the center of a group is a subgroup.",
        "Prove that if H is a subgroup of G, then the identity of H is the identity of G.",
    ]
    prompts.extend(extra_templates)
    cases: list[HiddenCase] = []
    for idx in range(120):
        prompt = prompts[idx % len(prompts)]
        method = methods[idx % len(methods)]
        cases.append(
            HiddenCase(
                question_id=f"hard300_proof_{idx + 1:03d}",
                question=f"{prompt} {method} Give a rigorous but concise proof.",
                answer="proved",
                domain="proof",
                problem_type="proof",
                evaluation_mode="proof_quality",
                min_proof_score=0.68,
            )
        )
    return cases


def _number_theory_cases() -> list[HiddenCase]:
    cases: list[HiddenCase] = []
    modpow_items = [
        (7, 128, 19),
        (11, 97, 31),
        (13, 85, 37),
        (17, 64, 43),
        (19, 123, 55),
        (23, 77, 61),
        (29, 101, 71),
        (31, 89, 97),
    ]
    for idx, (base, exponent, modulus) in enumerate(modpow_items, start=1):
        cases.append(
            HiddenCase(
                f"hard_hidden_nt_modpow_{idx:03d}",
                f"Find the least nonnegative residue of {base}^{exponent} modulo {modulus}. Give the final answer only.",
                str(pow(base, exponent, modulus)),
                "number_theory",
                "modular_exponent",
                "short_answer",
            )
        )

    phi_values = [840, 945, 1008, 1155, 1260, 1728, 2025, 2310]
    for idx, value in enumerate(phi_values, start=1):
        cases.append(
            HiddenCase(
                f"hard_hidden_nt_phi_{idx:03d}",
                f"Compute Euler phi of {value}. Give the final answer only.",
                str(_totient(value)),
                "number_theory",
                "totient",
                "short_answer",
            )
        )

    divisor_values = [756, 900, 1080, 1260, 1440, 1680, 1800, 2016]
    for idx, value in enumerate(divisor_values, start=1):
        cases.append(
            HiddenCase(
                f"hard_hidden_nt_divisors_{idx:03d}",
                f"How many positive divisors does {value} have? Give the final answer only.",
                str(_divisor_count(value)),
                "number_theory",
                "divisor_count",
                "short_answer",
            )
        )

    inverse_items = [
        (17, 43),
        (29, 71),
        (31, 80),
        (37, 97),
        (41, 121),
        (53, 127),
        (64, 101),
        (73, 140),
    ]
    for idx, (value, modulus) in enumerate(inverse_items, start=1):
        if gcd(value, modulus) != 1:
            raise ValueError("modular inverse inputs must be coprime")
        cases.append(
            HiddenCase(
                f"hard_hidden_nt_inverse_{idx:03d}",
                f"Find the least positive inverse of {value} modulo {modulus}. Give the final answer only.",
                str(pow(value, -1, modulus)),
                "number_theory",
                "modular_inverse",
                "short_answer",
            )
        )

    crt_items = [
        (2, 5, 3, 7),
        (4, 9, 5, 11),
        (7, 13, 8, 17),
        (11, 19, 13, 23),
        (5, 16, 9, 25),
        (14, 27, 20, 31),
        (17, 29, 22, 35),
        (19, 37, 6, 41),
    ]
    for idx, (a, m, b, n) in enumerate(crt_items, start=1):
        if gcd(m, n) != 1:
            raise ValueError("CRT moduli must be coprime")
        cases.append(
            HiddenCase(
                f"hard_hidden_nt_crt_{idx:03d}",
                f"Find the least nonnegative solution x to x = {a} mod {m} and x = {b} mod {n}. Give the final answer only.",
                str(_crt_two(a, m, b, n)),
                "number_theory",
                "crt",
                "short_answer",
            )
        )
    return cases


def _large_number_theory_cases() -> list[HiddenCase]:
    cases: list[HiddenCase] = []
    primes = [19, 31, 37, 43, 55, 61, 71, 97, 101, 109, 127, 131]

    for idx in range(24):
        base = 7 + 2 * idx
        exponent = 73 + 11 * idx
        modulus = primes[idx % len(primes)] + 2 * (idx // len(primes))
        if modulus % 2 == 0:
            modulus += 1
        cases.append(
            HiddenCase(
                f"hard300_nt_modpow_{idx + 1:03d}",
                f"Find the least nonnegative residue of {base}^{exponent} modulo {modulus}. Give the final answer only.",
                str(pow(base, exponent, modulus)),
                "number_theory",
                "modular_exponent",
                "short_answer",
            )
        )

    for idx in range(24):
        value = (idx + 5) * (idx + 7) * (idx % 9 + 8)
        value *= 6 if idx % 2 == 0 else 10
        cases.append(
            HiddenCase(
                f"hard300_nt_phi_{idx + 1:03d}",
                f"Compute Euler phi of {value}. Give the final answer only.",
                str(_totient(value)),
                "number_theory",
                "totient",
                "short_answer",
            )
        )

    for idx in range(24):
        value = (idx + 6) * (idx + 8) * (idx % 11 + 9) * 4
        cases.append(
            HiddenCase(
                f"hard300_nt_divisors_{idx + 1:03d}",
                f"How many positive divisors does {value} have? Give the final answer only.",
                str(_divisor_count(value)),
                "number_theory",
                "divisor_count",
                "short_answer",
            )
        )

    inverse_count = 0
    candidate = 17
    while inverse_count < 24:
        modulus = 43 + 4 * inverse_count
        if modulus % 2 == 0:
            modulus += 1
        value = candidate + 3 * inverse_count
        if gcd(value, modulus) != 1:
            candidate += 1
            continue
        inverse_count += 1
        cases.append(
            HiddenCase(
                f"hard300_nt_inverse_{inverse_count:03d}",
                f"Find the least positive inverse of {value} modulo {modulus}. Give the final answer only.",
                str(pow(value, -1, modulus)),
                "number_theory",
                "modular_inverse",
                "short_answer",
            )
        )

    crt_count = 0
    a = 2
    seed = 0
    while crt_count < 24:
        m = 5 + 2 * seed
        n = 7 + 4 * seed
        seed += 1
        if gcd(m, n) != 1:
            a += 1
            continue
        b = (3 * crt_count + 4) % n
        crt_count += 1
        cases.append(
            HiddenCase(
                f"hard300_nt_crt_{crt_count:03d}",
                f"Find the least nonnegative solution x to x = {a % m} mod {m} and x = {b} mod {n}. Give the final answer only.",
                str(_crt_two(a % m, m, b, n)),
                "number_theory",
                "crt",
                "short_answer",
            )
        )
        a += 3

    return cases


def _geometry_cases() -> list[HiddenCase]:
    cases: list[HiddenCase] = []
    right_triangles = [
        (9, 12),
        (12, 16),
        (15, 20),
        (20, 21),
        (28, 45),
        (33, 56),
        (36, 77),
        (39, 80),
        (48, 55),
        (65, 72),
        (84, 187),
        (119, 120),
        (140, 171),
        (160, 231),
    ]
    for idx, (a, b) in enumerate(right_triangles, start=1):
        hyp = isqrt(a * a + b * b)
        cases.append(
            HiddenCase(
                f"hard_hidden_geo_inradius_{idx:03d}",
                f"A right triangle has legs {a} and {b}. Compute its inradius. Give the final answer only.",
                str((a + b - hyp) // 2),
                "geometry",
                "inradius",
                "short_answer",
            )
        )

    heron_items = [
        (13, 14, 15),
        (5, 5, 6),
        (4, 13, 15),
        (10, 13, 13),
        (7, 15, 20),
        (9, 10, 17),
        (15, 20, 25),
        (8, 15, 17),
        (6, 8, 10),
        (17, 25, 26),
        (25, 39, 56),
        (20, 21, 29),
        (11, 13, 20),
    ]
    for idx, (a, b, c) in enumerate(heron_items, start=1):
        s2 = a + b + c
        area_sq_num = s2 * (s2 - 2 * a) * (s2 - 2 * b) * (s2 - 2 * c)
        cases.append(
            HiddenCase(
                f"hard_hidden_geo_heron_{idx:03d}",
                f"A triangle has side lengths {a}, {b}, {c}. Compute its area. Give the final answer only.",
                _format_sqrt_int(area_sq_num // 16),
                "geometry",
                "heron_area",
                "short_answer",
            )
        )

    chord_items = [
        (13, 5),
        (25, 7),
        (10, 6),
        (17, 8),
        (29, 20),
        (41, 9),
        (50, 14),
        (65, 33),
        (37, 12),
        (20, 3),
        (30, 11),
        (26, 10),
        (34, 16),
    ]
    for idx, (radius, distance) in enumerate(chord_items, start=1):
        root = _format_sqrt_int(radius * radius - distance * distance)
        answer = str(2 * int(root)) if root.isdigit() else f"2*{root}"
        cases.append(
            HiddenCase(
                f"hard_hidden_geo_chord_{idx:03d}",
                f"A circle has radius {radius}, and a chord is {distance} from the center. Compute the chord length. Give the final answer only.",
                answer,
                "geometry",
                "chord_length",
                "short_answer",
            )
        )
    return cases


def _pythagorean_pairs(limit: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    m = 2
    while len(pairs) < limit:
        for n in range(1, m):
            a = m * m - n * n
            b = 2 * m * n
            if a <= 0 or b <= 0:
                continue
            for scale in range(1, 4):
                leg_a = a * scale
                leg_b = b * scale
                pairs.append((min(leg_a, leg_b), max(leg_a, leg_b)))
                if len(pairs) >= limit:
                    return pairs
        m += 1
    return pairs


def _large_geometry_cases() -> list[HiddenCase]:
    cases: list[HiddenCase] = []
    triples = _pythagorean_pairs(80)

    for idx, (a, b) in enumerate(triples[:40], start=1):
        hyp = isqrt(a * a + b * b)
        cases.append(
            HiddenCase(
                f"hard300_geo_inradius_{idx:03d}",
                f"A right triangle has legs {a} and {b}. Compute its inradius. Give the final answer only.",
                str((a + b - hyp) // 2),
                "geometry",
                "inradius",
                "short_answer",
            )
        )

    for idx, (a, b) in enumerate(triples[40:80], start=1):
        c = isqrt(a * a + b * b)
        cases.append(
            HiddenCase(
                f"hard300_geo_heron_{idx:03d}",
                f"A triangle has side lengths {a}, {b}, {c}. Compute its area. Give the final answer only.",
                str(a * b // 2) if (a * b) % 2 == 0 else f"{a * b}/2",
                "geometry",
                "heron_area",
                "short_answer",
            )
        )

    chord_count = 0
    radius = 17
    while chord_count < 40:
        distance = 3 + (chord_count * 5) % (radius - 2)
        if distance >= radius:
            radius += 3
            continue
        root_value = radius * radius - distance * distance
        if root_value <= 0:
            radius += 2
            continue
        root = _format_sqrt_int(root_value)
        answer = str(2 * int(root)) if root.isdigit() else f"2*{root}"
        chord_count += 1
        cases.append(
            HiddenCase(
                f"hard300_geo_chord_{chord_count:03d}",
                f"A circle has radius {radius}, and a chord is {distance} from the center. Compute the chord length. Give the final answer only.",
                answer,
                "geometry",
                "chord_length",
                "short_answer",
            )
        )
        radius += 2

    return cases


def build_cases(profile: str = "compact") -> list[HiddenCase]:
    if profile == "compact":
        proof = _proof_cases()
        number_theory = _number_theory_cases()
        geometry = _geometry_cases()
    elif profile == "large":
        proof = _large_proof_cases()
        number_theory = _large_number_theory_cases()
        geometry = _large_geometry_cases()
    else:
        raise ValueError("profile must be one of: compact, large")
    if not (len(proof) == len(number_theory) == len(geometry)):
        raise ValueError("hard hidden domains must be balanced")

    cases: list[HiddenCase] = []
    for idx in range(len(proof)):
        cases.extend([proof[idx], number_theory[idx], geometry[idx]])
    return cases


def write_cases(
    cases: list[HiddenCase], questions_path: Path, answers_path: Path
) -> None:
    questions_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text_write(
        "\n".join(
            json.dumps(
                {"question_id": case.question_id, "question": case.question},
                ensure_ascii=False,
            )
            for case in cases
        )
        + "\n",
        questions_path,
    )
    atomic_text_write(
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
        answers_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a balanced hard hidden-style math regression set."
    )
    parser.add_argument("--questions", default="data/synthetic_hard_math.jsonl")
    parser.add_argument("--answers", default="data/synthetic_hard_math_answers.jsonl")
    parser.add_argument("--profile", choices=["compact", "large"], default="compact")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = build_cases(profile=args.profile)
    write_cases(cases, Path(args.questions), Path(args.answers))
    print(f"generated={len(cases)}")
    print(f"questions={args.questions}")
    print(f"answers={args.answers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
