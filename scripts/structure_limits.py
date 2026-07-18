#!/usr/bin/env python3
"""Enforce structural limits from .agent/core/PRINCIPLES.md."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("app", "tests", "scripts")
PROD_FILE_HARD = 600
TEST_FILE_HARD = 800
PROD_FUNCTION_HARD = 60
TEST_FUNCTION_HARD = 50
CLASS_HARD = 300
NESTING_HARD = 3
PARAMETER_HARD = 7

BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
)

LEGACY_BASELINE = {
    ("app/bot/handlers/level.py", "nesting", "level_selected"): 4,
    ("app/bot/handlers/profile.py", "nesting", "handle_profile_callback"): 4,
    ("app/bot/handlers/review.py", "function-lines", "handle_review_start"): 84,
    ("app/bot/handlers/review.py", "nesting", "handle_review_entry"): 4,
    ("app/bot/handlers/start.py", "nesting", "_remember_user"): 4,
    ("app/bot/handlers/subscription.py", "nesting", "handle_subscription_callback"): 4,
    ("app/bot/handlers/training.py", "nesting", "handle_next_question"): 4,
    ("app/bot/handlers/training.py", "nesting", "handle_resume_training"): 4,
    ("app/bot/handlers/training.py", "nesting", "handle_start_new_training"): 4,
    ("app/bot/handlers/training_flow.py", "parameters", "persist_quiz_bank_error"): 8,
    ("app/quiz_bank/client.py", "parameters", "QuizBankAsyncClient.__init__"): 10,
    ("app/repositories/answers.py", "parameters", "AnswerRepository.create"): 17,
    ("app/repositories/api_error_logs.py", "parameters", "ApiErrorLogRepository.record"): 10,
    ("app/repositories/mistake_history.py", "parameters", "MistakeHistoryRepository.record"): 9,
    ("app/repositories/mistakes.py", "parameters", "MistakeRepository.create"): 8,
    ("app/repositories/question_references.py", "parameters", "QuestionReferenceRepository.upsert_snapshot"): 10,
    ("app/repositories/quiz_sessions.py", "parameters", "QuizSessionRepository.create"): 8,
    ("app/services/mistakes.py", "function-lines", "MistakeService.record_wrong_answer"): 106,
    ("app/services/mistakes.py", "parameters", "MistakeService._record_history"): 9,
    ("app/services/mistakes.py", "parameters", "MistakeService.record_review_success"): 10,
    ("app/services/mistakes.py", "parameters", "MistakeService.record_wrong_answer"): 12,
    ("app/services/progress.py", "parameters", "ProgressService.record_answer_result"): 14,
    ("app/services/progress_model.py", "parameters", "calculate_topic_scores"): 8,
    ("app/services/progress_model.py", "parameters", "determine_topic_status"): 8,
    ("app/services/training_answer_flow.py", "class-lines", "TrainingAnswerProcessor"): 424,
    ("app/services/training_question_flow.py", "class-lines", "TrainingQuestionProcessor"): 310,
    ("app/services/training_session.py", "parameters", "TrainingSessionService.__init__"): 11,
    (
        "app/services/training_session_lifecycle.py",
        "function-lines",
        "TrainingSessionLifecycleMixin.start_review_session",
    ): 63,
    ("tests/fakes/training_session.py", "parameters", "FakeAnswerRepository.create"): 17,
    ("tests/fakes/training_session.py", "parameters", "FakeSessionRepository.create"): 8,
    ("tests/test_analytics_service.py", "function-lines", "_seed_metrics_data"): 89,
    ("tests/test_mistakes_service.py", "function-lines", "test_record_wrong_answer_reopens_resolved_mistake"): 61,
    ("tests/test_mistakes_service.py", "parameters", "FakeMistakeRepository.create"): 8,
    ("tests/test_progress_service.py", "function-lines", "test_record_answer_result_counts_repeated_item_once_for_coverage"): 53,
    ("tests/test_progress_service.py", "function-lines", "test_record_answer_result_uses_berlin_days_for_stability"): 51,
    ("tests/test_quiz_bank_schemas.py", "function-lines", "test_catalog_and_lookup_schemas_validate"): 64,
    ("tests/test_security_controls.py", "parameters", "FakeRedis.eval"): 8,
    ("tests/test_training_mistakes_integration.py", "parameters", "FakeAnswerRepository.create"): 17,
    ("tests/test_training_mistakes_integration.py", "parameters", "FakeSessionRepository.create"): 8,
    ("tests/test_training_progress_integration.py", "parameters", "FakeAnswerRepository.create"): 17,
    ("tests/test_training_progress_integration.py", "parameters", "FakeSessionRepository.create"): 8,
}


@dataclass(frozen=True)
class Violation:
    path: str
    kind: str
    name: str
    value: int
    limit: int
    line: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.kind, self.name)


class LimitVisitor(ast.NodeVisitor):
    def __init__(self, path: str, is_test: bool) -> None:
        self.path = path
        self.is_test = is_test
        self.stack: list[str] = []
        self.violations: list[Violation] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record("class-lines", node.name, node_length(node), CLASS_HARD, node.lineno)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name = ".".join([*self.stack, node.name])
        function_limit = TEST_FUNCTION_HARD if self.is_test else PROD_FUNCTION_HARD
        self._record("function-lines", name, node_length(node), function_limit, node.lineno)
        self._record("parameters", name, parameter_count(node), PARAMETER_HARD, node.lineno)
        self._record("nesting", name, max_nesting(node), NESTING_HARD, node.lineno)

        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _record(self, kind: str, name: str, value: int, limit: int, line: int) -> None:
        if value > limit:
            self.violations.append(Violation(self.path, kind, name, value, limit, line))


def main() -> int:
    violations = collect_violations()
    current_keys = {violation.key for violation in violations}
    failures = [
        violation
        for violation in violations
        if violation.value > LEGACY_BASELINE.get(violation.key, violation.limit)
    ]
    stale_baseline = sorted(set(LEGACY_BASELINE) - current_keys)

    if failures or stale_baseline:
        print("Structural limit check failed:")
        for violation in failures:
            allowed = LEGACY_BASELINE.get(violation.key, violation.limit)
            print(
                f"{violation.path}:{violation.line}: {violation.kind} "
                f"{violation.name}={violation.value} exceeds allowed {allowed} "
                f"(hard limit {violation.limit})",
            )
        for path, kind, name in stale_baseline:
            print(f"{path}: stale baseline entry can be removed: {kind} {name}")
        return 1

    print(f"Structural limit check passed with {len(violations)} tracked legacy violations.")
    return 0


def collect_violations() -> list[Violation]:
    violations: list[Violation] = []
    for path in python_files():
        relative = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        is_test = relative.startswith("tests/")
        file_limit = TEST_FILE_HARD if is_test else PROD_FILE_HARD
        if len(lines) > file_limit:
            violations.append(Violation(relative, "file-lines", "<module>", len(lines), file_limit, 1))

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        visitor = LimitVisitor(relative, is_test=is_test)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


def python_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        root = ROOT / target
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.py"))
    return sorted(path for path in files if "__pycache__" not in path.parts)


def node_length(node: ast.AST) -> int:
    return getattr(node, "end_lineno", node.lineno) - node.lineno + 1


def parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    count = len(positional) + len(args.kwonlyargs)
    if positional and positional[0].arg in {"self", "cls"}:
        count -= 1
    if args.vararg is not None:
        count += 1
    if args.kwarg is not None:
        count += 1
    return count


def max_nesting(node: ast.AST, depth: int = 0) -> int:
    maximum = depth
    for child in ast.iter_child_nodes(node):
        child_depth = depth + 1 if isinstance(child, BRANCH_NODES) else depth
        maximum = max(maximum, max_nesting(child, child_depth))
    return maximum


if __name__ == "__main__":
    raise SystemExit(main())
