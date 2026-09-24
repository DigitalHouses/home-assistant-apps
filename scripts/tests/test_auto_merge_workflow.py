from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "auto-merge.yml"


class AutoMergeWorkflowTests(unittest.TestCase):
    # These tests protect the exact-base invariant under concurrent owner PRs.
    def _text(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_stale_validated_base_updates_branch_instead_of_merging(self):
        text = self._text()

        self.assertIn(
            'current_base_sha="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)"',
            text,
        )
        self.assertIn(
            'if [ "$current_base_sha" != "$VALIDATED_BASE_SHA" ]; then',
            text,
        )
        self.assertIn(
            'gh api --method PUT "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/update-branch"',
            text,
        )
        self.assertIn('-f "expected_head_sha=${head_sha}"', text)
        self.assertIn('echo "merged=false" >> "$GITHUB_OUTPUT"', text)
        self.assertLess(
            text.index('if [ "$current_base_sha" != "$VALIDATED_BASE_SHA" ]; then'),
            text.index('gh pr merge "$PR_NUMBER"'),
        )

    def test_release_detection_uses_actual_first_parent_of_merge_commit(self):
        text = self._text()

        self.assertIn(
            "release_base_sha=\"$(gh api \"repos/${GITHUB_REPOSITORY}/git/commits/${merge_sha}\" --jq '.parents[0].sha')\"",
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

    def test_post_merge_steps_run_only_after_an_actual_merge(self):
        text = self._text()

        self.assertIn('echo "merged=true" >> "$GITHUB_OUTPUT"', text)
        for step_name in (
            "Check out exact merged main revision",
            "Set up Python",
            "Detect and validate releases",
            "Publish product releases",
            "Verify published releases",
        ):
            marker = f"- name: {step_name}"
            start = text.index(marker)
            end = text.find("\n      - name:", start + len(marker))
            block = text[start:] if end == -1 else text[start:end]
            self.assertIn("if: steps.merge.outputs.merged == 'true'", block)


if __name__ == "__main__":
    unittest.main()
