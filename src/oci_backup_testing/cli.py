from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import warnings
from typing import Any

from .cleanup import CleanupError, cleanup_from_state
from .compute import ComputePhaseError
from .config import ConfigError, load_config
from .discovery import DiscoveryError
from .oci_clients import build_clients
from .queue import clear_queue, init_queue, load_queue
from .report import publish_report
from .state import load_state, mark_execution_cleaned, prune_state, save_state
from .validation import validate_execution
from .workflow import discover, run


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(message)s")
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        message=r"The 'strict' parameter is no longer needed on Python 3\+.*",
        module=r"urllib3\.poolmanager",
    )

    try:
        config = load_config(args.config)
        state = load_state(config.state_file)

        if args.command == "init-batch":
            queue = init_queue(config.queue_file)
            _print_json(
                {
                    "queue_file": config.queue_file,
                    "batch_id": queue["batch_id"],
                    "created_at": queue["created_at"],
                    "executions": len(queue.get("executions", [])),
                }
            )
            return 0

        if args.command == "close-batch":
            removed = clear_queue(config.queue_file)
            _print_json({"queue_file": config.queue_file, "removed": removed})
            return 0

        if args.command == "status":
            _print_json(_state_status(state, limit=args.limit))
            return 0

        if args.command == "prune-state":
            prune_target = copy.deepcopy(state) if args.dry_run else state
            summary = prune_state(
                prune_target,
                max_executions=config.state_retention.max_executions,
                max_age_days=config.state_retention.max_age_days,
                prune_only_cleaned=config.state_retention.prune_only_cleaned,
            )
            summary["state_file"] = config.state_file
            summary["dry_run"] = args.dry_run
            if not args.dry_run:
                save_state(config.state_file, prune_target)
            _print_json(summary)
            return 0

        clients = build_clients(config)

        if args.command == "discover":
            plans = discover(clients, config)
            _print_json([plan.as_dict() for plan in plans])
            return 0

        if args.command == "run":
            if not args.dry_run and not args.yes:
                raise SystemExit("Refusing to create OCI resources without --yes")
            queue = None if args.dry_run else load_queue(config.queue_file, create_if_missing=True)
            results = run(
                clients,
                config,
                state,
                dry_run=args.dry_run,
                limit=args.limit,
                volume_group_id=args.volume_group_id,
                queue=queue,
            )
            if not args.dry_run:
                _print_run_summary(results)
            _print_json(results)
            return _validation_exit_code(results)

        if args.command == "report":
            queue = _load_existing_queue(config.queue_file)
            report_upload = publish_report(
                clients,
                config,
                queue.get("executions", []),
                batch=queue,
            )
            if report_upload is None:
                raise SystemExit("Report generation requires report.enabled=true in config.json")
            report = report_upload.as_dict()
            _print_report_upload(report)
            _print_json({"batch_id": queue.get("batch_id"), "report": report})
            return 0

        if args.command == "validate":
            validations = []
            for execution in state.get("executions", []):
                validation = validate_execution(clients, execution)
                execution["validation"] = validation
                validations.append(
                    {
                        "run_id": execution.get("run_id"),
                        "validation": validation,
                    }
                )
            save_state(config.state_file, state)
            _print_json(validations)
            return _validation_exit_code(
                [item["validation"] for item in validations],
                already_validation_objects=True,
            )

        if args.command == "cleanup":
            if not args.yes:
                raise SystemExit("Refusing to delete OCI resources without --yes")
            cleanup_state = _filtered_cleanup_state(state, args.run_id, args.latest)
            results = cleanup_from_state(clients, config, cleanup_state)
            for result in results:
                mark_execution_cleaned(state, result, _cleanup_status(config))
            save_state(config.state_file, state)
            _print_json(results)
            return 0

        parser.print_help()
        return 2
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except DiscoveryError as exc:
        raise SystemExit(f"Discovery error: {exc}") from exc
    except ComputePhaseError as exc:
        raise SystemExit(f"Compute phase error: {exc}") from exc
    except CleanupError as exc:
        raise SystemExit(f"Cleanup error: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(f"Execution error: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oci-backup-testing",
        description="Restore tagged OCI volume group backups and launch isolated test instances.",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file. Defaults to config.json.",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init-batch",
        help="Reset the report queue and start a new compliance batch.",
    )

    subparsers.add_parser("discover", help="Print tagged volume groups and latest backups.")

    run_parser = subparsers.add_parser("run", help="Run discovery, restore, launch, attach, and validation.")
    run_parser.add_argument("--dry-run", action="store_true", help="Plan only; do not create OCI resources.")
    run_parser.add_argument("--yes", action="store_true", help="Allow OCI resource creation.")
    run_parser.add_argument("--limit", type=int, default=None, help="Process only the first N volume groups.")
    run_parser.add_argument(
        "--volume-group-id",
        "--volume-group",
        dest="volume_group_id",
        help="Run only one source volume group, matched by source volume group OCID.",
    )

    subparsers.add_parser("validate", help="Re-run control-plane validation for resources in the state file.")

    subparsers.add_parser("report", help="Generate and upload an HTML report from the current queue.")

    status_parser = subparsers.add_parser("status", help="Print local state-file progress without OCI calls.")
    status_parser.add_argument("--limit", type=int, default=10, help="Show the latest N executions.")

    prune_parser = subparsers.add_parser(
        "prune-state",
        help="Prune cleaned executions from the state file using configured retention.",
    )
    prune_parser.add_argument("--dry-run", action="store_true", help="Preview pruning without changing state.")

    cleanup_parser = subparsers.add_parser("cleanup", help="Terminate and delete resources recorded in state.")
    cleanup_parser.add_argument("--yes", action="store_true", help="Allow OCI resource deletion.")
    cleanup_parser.add_argument("--run-id", help="Clean only the matching run_id.")
    cleanup_parser.add_argument("--latest", action="store_true", help="Clean only the latest execution.")

    subparsers.add_parser(
        "close-batch",
        help="Close the current compliance batch by removing the local report queue.",
    )

    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _validation_exit_code(
    values: list[dict[str, Any]],
    already_validation_objects: bool = False,
) -> int:
    for value in values:
        validation = value if already_validation_objects else value.get("validation")
        if validation is not None and validation.get("passed") is False:
            return 1
    return 0


def _state_status(state: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    executions = state.get("executions", [])[-limit:]
    return [
        {
            "run_id": execution.get("run_id"),
            "phase": execution.get("phase"),
            "source_display_name": execution.get("source_display_name"),
            "restored_volume_group_id": execution.get("restored_volume_group_id"),
            "boot_volume_id": execution.get("boot_volume_id"),
            "block_volume_count": len(execution.get("block_volume_ids", [])),
            "subnet_id": execution.get("subnet_id"),
            "instance_id": execution.get("instance_id"),
            "instance_display_name": execution.get("instance_display_name"),
            "volume_attachment_count": len(execution.get("volume_attachment_ids", [])),
            "validation_passed": (
                execution.get("validation", {}).get("passed")
                if execution.get("validation") is not None
                else None
            ),
        }
        for execution in executions
    ]


def _filtered_cleanup_state(
    state: dict[str, Any],
    run_id: str | None,
    latest: bool,
) -> dict[str, Any]:
    if run_id and latest:
        raise SystemExit("Use either --run-id or --latest, not both")
    executions = list(state.get("executions", []))
    if latest:
        selected = executions[-1:] if executions else []
    elif run_id:
        selected = [execution for execution in executions if execution.get("run_id") == run_id]
        if not selected:
            raise SystemExit(f"No execution found for run_id {run_id}")
    else:
        selected = executions

    filtered = dict(state)
    filtered["executions"] = selected
    return filtered


def _print_run_summary(results: list[dict[str, Any]]) -> None:
    print("", file=sys.stderr, flush=True)
    print("Run summary:", file=sys.stderr, flush=True)
    if not results:
        print("  No volume groups were processed.", file=sys.stderr, flush=True)
        return

    for result in results:
        source_name = result.get("source_display_name") or "<unknown source volume group>"
        instance_name = result.get("instance_display_name") or "<no test instance>"
        instance_id = result.get("instance_id") or "<no instance id>"
        status = _test_status(result)
        print(
            f"  - {source_name}: {status} | VM: {instance_name} | {instance_id}",
            file=sys.stderr,
            flush=True,
        )


def _test_status(result: dict[str, Any]) -> str:
    validation = result.get("validation")
    if validation is None:
        return f"NOT_VALIDATED ({result.get('phase', 'unknown')})"
    return "PASSED" if validation.get("passed") else "FAILED"


def _print_report_upload(report: dict[str, Any]) -> None:
    print("", file=sys.stderr, flush=True)
    print("Report uploaded:", file=sys.stderr, flush=True)
    print(f"  Object: {report['object_name']}", file=sys.stderr, flush=True)
    print(f"  Bucket: {report['bucket_name']}", file=sys.stderr, flush=True)
    print(f"  Namespace: {report['namespace']}", file=sys.stderr, flush=True)
    print(f"  URI: {report['uri']}", file=sys.stderr, flush=True)


def _load_existing_queue(path: str) -> dict[str, Any]:
    try:
        return load_queue(path)
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Queue file does not exist: {path}. "
            "Run 'oci-backup-testing --config config.json init-batch' first."
        ) from exc


def _cleanup_status(config: Any) -> str:
    if (
        config.cleanup.terminate_instances
        and config.cleanup.delete_restored_volume_group
        and config.cleanup.delete_restored_volumes
    ):
        return "cleaned"
    return "completed"
