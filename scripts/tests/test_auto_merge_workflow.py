from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "auto-merge.yml"


class AutoMergeWorkflowTests(unittest.TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_merge_refuses_a_validated_pr_when_main_advanced_after_validation(self):
        text = self._text()

        self.assertIn(
            'current_base_sha="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)"',
            text,
        )
        self.assertIn('test "$current_base_sha" = "$VALIDATED_BASE_SHA"', text)
        self.assertLess(
            text.index('test "$current_base_sha" = "$VALIDATED_BASE_SHA"'),
            text.index('gh pr merge "$PR_NUMBER"'),
        )

    def test_release_detection_uses_actual_first_parent_of_merge_commit(self):
        text = self._text()

        self.assertIn(
            'release_base_sha="$(git rev-parse "${MERGE_SHA}^1")"',
            text,
        )
        self.assertIn('echo "release_base_sha=$release_base_sha" >> "$GITHUB_OUTPUT"', text)
        self.assertIn(
            'BASE_SHA: ${{ steps.merge.outputs.release_base_sha }}',
            text,
        )
        self.assertNotIn(
            'BASE_SHA: ${{ steps.merge.outputs.base_sha }}',
            text,
        )


if __name__ == "__main__":
    unittest.main()
