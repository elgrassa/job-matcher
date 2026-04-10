"""Tests for keyword matcher."""

import pytest

from job_matcher.scoring.keyword_matcher import compute_keyword_match

SDET_CV = """
Senior SDET with 15 years of experience in test automation.
Skills: Java, Python, Cypress, Playwright, CI/CD, API testing, Agile.
Built CI/CD pipelines at Noumena for 25+ projects.
Experience with Jenkins, Docker, Kubernetes.
"""

AI_CV = """
AI QA Engineer with 8 years of experience.
Skills: Python, RAG, LLM evaluation, DeepEval, RAGAS, Promptfoo.
Built RAG evaluation pipeline. 8 years in software testing.
"""


class TestExactMatch:
    def test_keyword_present_in_cv(self):
        result = compute_keyword_match(["java"], SDET_CV)
        assert "java" in result.matched

    def test_keyword_missing_from_cv(self):
        result = compute_keyword_match(["rust"], SDET_CV)
        assert "rust" in result.missing

    def test_case_insensitive_match(self):
        result = compute_keyword_match(["JAVA", "python"], SDET_CV)
        assert "JAVA" in result.matched
        assert "python" in result.matched


class TestYearRequirements:
    @pytest.mark.parametrize(
        "required, cv_text, matches",
        [
            ("5+ years", SDET_CV, True),   # CV has 15 years
            ("10 years", SDET_CV, True),    # 15 >= 10
            ("20 years", SDET_CV, False),   # 15 < 20
            ("5+ years", "No experience mentioned.", False),
        ],
    )
    def test(self, required: str, cv_text: str, matches: bool):
        result = compute_keyword_match([required], cv_text)
        if matches:
            assert required in result.matched
        else:
            assert required in result.missing

    def test_ai_cv_8_years(self):
        result = compute_keyword_match(["8 years"], AI_CV)
        assert "8 years" in result.matched

    def test_ai_cv_10_years_fails(self):
        result = compute_keyword_match(["10 years"], AI_CV)
        assert "10 years" in result.missing


class TestNormalization:
    def test_cicd_variants_all_match(self):
        cv = "Experience with CI/CD pipelines."
        for kw in ["ci/cd", "cicd", "CI-CD", "CI_CD"]:
            result = compute_keyword_match([kw], cv)
            assert kw in result.matched, f"{kw} should match"

    def test_ci_cd_matches_cicd_in_cv(self):
        cv = "Built CICD pipelines."
        result = compute_keyword_match(["ci/cd"], cv)
        assert "ci/cd" in result.matched


class TestScore:
    def test_empty_requirements_returns_zero(self):
        result = compute_keyword_match([], SDET_CV)
        assert result.score == 0.0
        assert result.matched == []
        assert result.missing == []

    def test_all_matched_returns_one(self):
        result = compute_keyword_match(["java", "python", "cypress"], SDET_CV)
        assert result.score == 1.0

    def test_half_matched_returns_point_five(self):
        result = compute_keyword_match(["java", "rust"], SDET_CV)
        assert result.score == 0.5

    def test_score_rounds_to_4_decimals(self):
        result = compute_keyword_match(["java", "python", "rust"], SDET_CV)
        assert result.score == pytest.approx(0.6667, abs=0.0001)

    def test_result_lists_are_consistent(self):
        required = ["java", "python", "rust", "go"]
        result = compute_keyword_match(required, SDET_CV)
        assert set(result.matched) | set(result.missing) == set(required)
        assert set(result.matched) & set(result.missing) == set()


class TestEdgeCases:
    def test_empty_cv(self):
        result = compute_keyword_match(["java"], "")
        assert result.score == 0.0
        assert result.missing == ["java"]

    def test_multiword_keyword(self):
        result = compute_keyword_match(["api testing"], SDET_CV)
        assert "api testing" in result.matched

    def test_playwright_match(self):
        result = compute_keyword_match(["playwright"], SDET_CV)
        assert "playwright" in result.matched

    def test_rag_match_in_ai_cv(self):
        result = compute_keyword_match(["rag", "deepeval"], AI_CV)
        assert "rag" in result.matched
        assert "deepeval" in result.matched
