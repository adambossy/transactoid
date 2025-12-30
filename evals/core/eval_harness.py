from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Any

from rich.console import Console
from rich.progress import Progress
from rich.table import Table
import yaml

from evals.core.headless_runner import ConversationResult, HeadlessAgentRunner
from evals.core.llm_judge import JudgeResult, LLMJudge
from evals.data.db_builder import EvalDBBuilder
from evals.data.fixtures import FIXTURES
from transactoid.adapters.cache.file_cache import FileCache
from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import Base, CategoryRow
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db


@dataclass
class EvalRunResult:
    """Result of running one eval."""

    question_id: str
    question: str
    follow_ups: list[str]
    conversation_result: ConversationResult
    judge_result: JudgeResult
    fixture_name: str


class EvalHarness:
    """Main evaluation harness."""

    def __init__(self, questions_path: str, questions: str | None = None) -> None:
        """Initialize harness.

        Args:
            questions_path: Path to questions.yaml file
            questions: Comma-separated question IDs to run (e.g., q001,q003,q005).
                      If None, runs all questions.
        """
        self._questions = self._load_questions(questions_path)
        if questions:
            included_ids = set(questions.split(","))
            self._questions = [q for q in self._questions if q["id"] in included_ids]
        self._cache = FileCache()
        self._console = Console()

    def _load_questions(self, path: str) -> list[dict[str, Any]]:
        """Load questions from YAML.

        Args:
            path: Path to questions.yaml

        Returns:
            List of question dicts
        """
        with open(path) as f:
            data = yaml.safe_load(f)
        questions: list[dict[str, Any]] = data["questions"]
        return questions

    def _create_db(self) -> DB:
        """Create in-memory database."""
        db = DB("sqlite:///:memory:")
        with db.session() as session:
            if session.bind is None:
                raise RuntimeError("Session bind is None")
            Base.metadata.create_all(session.bind)
        return db

    def _load_full_taxonomy(self, db: DB) -> Taxonomy:
        """Load full taxonomy from configs/taxonomy.yaml.

        Args:
            db: Database instance

        Returns:
            Taxonomy instance
        """
        with open("configs/taxonomy.yaml") as f:
            data = yaml.safe_load(f)

        categories = []
        for idx, cat_data in enumerate(data["categories"], start=1):
            categories.append(
                CategoryRow(
                    category_id=idx,
                    parent_id=None,
                    key=cat_data["key"],
                    name=cat_data["name"],
                    description=cat_data.get("description"),
                    parent_key=cat_data.get("parent_key"),
                )
            )

        db.replace_categories_rows(categories)
        return load_taxonomy_from_db(db)

    async def run_eval(self, question_config: dict[str, Any]) -> EvalRunResult:
        """Run single eval: DB setup → agent run → judge.

        Args:
            question_config: Question configuration dict

        Returns:
            EvalRunResult with all data
        """
        # 1. Create temp DB
        db = self._create_db()
        taxonomy = self._load_full_taxonomy(db)

        # 2. Build from fixture
        fixture = FIXTURES[question_config["fixture"]]
        builder = EvalDBBuilder(db, taxonomy)
        builder.build_from_fixture(fixture)

        # 3. Run headless agent
        runner = HeadlessAgentRunner(db, taxonomy)
        conv_result = await runner.run_conversation(
            question_config["question"],
            question_config["follow_ups"],
        )

        # 4. Judge evaluation
        judge = LLMJudge(self._cache)
        judge_result = await judge.evaluate(
            conv_result.full_conversation,
            question_config["ground_truth"],
            question_config["expectations"],
        )

        # 5. Return result
        return EvalRunResult(
            question_id=question_config["id"],
            question=question_config["question"],
            follow_ups=question_config["follow_ups"],
            conversation_result=conv_result,
            judge_result=judge_result,
            fixture_name=question_config["fixture"],
        )

    async def run_all(self) -> list[EvalRunResult]:
        """Run all evals with Rich progress bar.

        Returns:
            List of EvalRunResult
        """
        results = []
        with Progress() as progress:
            task = progress.add_task(
                "[cyan]Running evals...", total=len(self._questions)
            )
            for q in self._questions:
                result = await self.run_eval(q)
                results.append(result)
                progress.update(task, advance=1)
        return results

    def save_results(self, results: list[EvalRunResult], output_path: str) -> None:
        """Save results to JSON file.

        Args:
            results: List of eval results
            output_path: Path to output JSON file
        """
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_evals": len(results),
            "single_turn_count": sum(1 for r in results if not r.follow_ups),
            "multi_turn_count": sum(1 for r in results if r.follow_ups),
            "passed": sum(1 for r in results if r.judge_result.passed),
            "failed": sum(1 for r in results if not r.judge_result.passed),
            "pass_rate": sum(1 for r in results if r.judge_result.passed) / len(results)
            if results
            else 0.0,
            "avg_scores": self._calculate_avg_scores(results),
            "results": [self._result_to_dict(r) for r in results],
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

    def _calculate_avg_scores(self, results: list[EvalRunResult]) -> dict[str, float]:
        """Calculate average scores across all results."""
        if not results:
            return {}

        scores = {
            "numerical_consistency": 0.0,
            "conciseness": 0.0,
            "use_of_tables": 0.0,
            "accurate_formatting": 0.0,
            "snide_personality": 0.0,
            "overall": 0.0,
        }

        for result in results:
            scores["numerical_consistency"] += (
                result.judge_result.numerical_consistency.score
            )
            scores["conciseness"] += result.judge_result.conciseness.score
            scores["use_of_tables"] += result.judge_result.use_of_tables.score
            scores["accurate_formatting"] += (
                result.judge_result.accurate_formatting.score
            )
            scores["snide_personality"] += result.judge_result.snide_personality.score
            scores["overall"] += result.judge_result.overall_score

        count = len(results)
        return {k: round(v / count, 2) for k, v in scores.items()}

    def _result_to_dict(self, result: EvalRunResult) -> dict[str, Any]:
        """Convert EvalRunResult to dict for JSON serialization."""
        return {
            "question_id": result.question_id,
            "question": result.question,
            "follow_ups": result.follow_ups,
            "is_multi_turn": bool(result.follow_ups),
            "fixture": result.fixture_name,
            "conversation": result.conversation_result.full_conversation,
            "duration_seconds": result.conversation_result.total_duration_seconds,
            "turns": [asdict(turn) for turn in result.conversation_result.turns],
            "judge_result": {
                "numerical_consistency": asdict(
                    result.judge_result.numerical_consistency
                ),
                "conciseness": asdict(result.judge_result.conciseness),
                "use_of_tables": asdict(result.judge_result.use_of_tables),
                "accurate_formatting": asdict(result.judge_result.accurate_formatting),
                "snide_personality": asdict(result.judge_result.snide_personality),
                "overall_score": result.judge_result.overall_score,
                "passed": result.judge_result.passed,
            },
        }

    def print_summary(self, results: list[EvalRunResult]) -> None:
        """Print console summary with Rich tables."""
        # Table 1: Per-eval results
        table = Table(title="Evaluation Results", show_lines=True)
        table.add_column("ID", style="cyan")
        table.add_column("Question", style="white")
        table.add_column("Turns", justify="center")
        table.add_column("Status")
        table.add_column("Overall", justify="right")

        for result in results:
            status = "✓ PASS" if result.judge_result.passed else "✗ FAIL"
            status_style = "green" if result.judge_result.passed else "red"
            turns = str(len(result.conversation_result.turns))

            table.add_row(
                result.question_id,
                result.question[:50] + "..."
                if len(result.question) > 50
                else result.question,
                turns,
                f"[{status_style}]{status}[/{status_style}]",
                f"{result.judge_result.overall_score:.2f}",
            )

        self._console.print(table)

        # Summary stats
        passed = sum(1 for r in results if r.judge_result.passed)
        failed = sum(1 for r in results if not r.judge_result.passed)
        total = len(results)

        self._console.print("\n[bold]Summary:[/bold]")
        self._console.print(f"  Total: {total} evals")
        self._console.print(
            f"  [green]Passed: {passed} ({passed / total * 100:.1f}%)[/green]"
        )
        self._console.print(
            f"  [red]Failed: {failed} ({failed / total * 100:.1f}%)[/red]"
        )
