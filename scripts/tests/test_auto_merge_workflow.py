from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "auto-merge.yml"
VALIDATE = ROOT / ".github" / "workflows" / "validate.yml"


class AutoMergeWorkflowTests(unittest.TestCase):
    def _text(self):
        return WORKFLOW.read_text(encoding="utf-8")

    def test_successful_pr_is_resolved_even_when_workflow_run_prs_empty(self):
        text = self._text()
        self.assertIn('gh run download "$VALIDATION_RUN_ID"', text)
        self.assertIn("--name ci-provenance", text)
        self.assertIn('artifact_head" = "$VALIDATED_HEAD_SHA"', text)
        self.assertIn('artifact_attempt" = "$VALIDATION_RUN_ATTEMPT"', text)
        self.assertIn('commits/$VALIDATED_HEAD_SHA/pulls', text)
        self.assertIn('test "$head_repo" = "$GITHUB_REPOSITORY"', text)
        self.assertIn('test "$author" = DigitalHouses', text)
        self.assertIn('test "$head_ref" = "$VALIDATED_HEAD_BRANCH"', text)

    def test_stale_base_dispatches_new_validation_without_branch_update(self):
        text = self._text()
        self.assertIn('current_main" != "$VALIDATED_BASE_SHA"', text)
        self.assertIn('base_sha" != "$VALIDATED_BASE_SHA"', text)
        self.assertIn('actions/workflows/validate.yml/dispatches', text)
        self.assertIn('-f "inputs[expected_head_sha]=$head_sha"', text)
        self.assertIn('-f "inputs[expected_base_sha]=$current_main"', text)
        self.assertNotIn('/update-branch', text)
        self.assertLess(text.index('if [ "$current_main" != "$VALIDATED_BASE_SHA" ]'),
                        text.index('gh pr merge "$PR_NUMBER"'))
        self.assertIn('--match-head-commit "$VALIDATED_HEAD_SHA"', text)
        self.assertIn('else\n              merge_rc=$?\n            fi', text)

    def test_manual_main_push_reconciles_releases(self):
        text = self._text()
        self.assertIn('github.event.workflow_run.event == \'push\'', text)
        self.assertIn('if [ "$VALIDATION_EVENT" = push ]; then', text)
        self.assertIn('if [ "$VALIDATED_HEAD_SHA" != "$current_main" ]; then', text)
        self.assertIn('echo "merge_sha=$current_main" >> "$GITHUB_OUTPUT"', text)
        self.assertIn('--include-pending-existing', text)

    def test_release_source_is_actual_first_parent(self):
        text = self._text()
        self.assertIn('git/commits/$merge_sha" --jq \'.parents[0].sha\'', text)
        self.assertIn('git/commits/$current_main" --jq \'.parents[0].sha\'', text)
        self.assertIn('BASE_SHA: ${{ steps.merge.outputs.release_base_sha }}', text)
        self.assertIn('MERGE_SHA: ${{ steps.merge.outputs.merge_sha }}', text)

    def test_new_validation_dispatch_checks_exact_merge_revision(self):
        text = VALIDATE.read_text()
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('name: Upload validated PR identity', text)
        self.assertIn('name: Validate dispatched PR identity and current main', text)
        self.assertIn('git rev-parse HEAD^1', text)
        self.assertIn('git rev-parse HEAD^2', text)
        self.assertIn('refs/pull/{0}/merge', text)
        self.assertIn("if: github.event_name != 'push'", text)

    def test_native_build_and_publish_gates(self):
        text = self._text()
        self.assertNotIn('setup-qemu-action', text)
        self.assertIn('runs-on: ${{ matrix.runner }}', text)
        self.assertIn('needs: [integrate, build-native]', text)
        self.assertIn("needs.build-native.result == 'success'", text)
        self.assertIn("needs.build-native.result == 'skipped'", text)
        self.assertIn("needs.integrate.outputs.merged == 'true'", text)
        self.assertIn('refs+=("$image@$digest")', text)
        self.assertIn('--cache-to', text)


if __name__ == "__main__":
    unittest.main()
