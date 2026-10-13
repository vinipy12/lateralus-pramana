"""Bounded role workers over durable queues; no task-per-case fanout."""

import asyncio
import contextlib
import time
import uuid

from .agents import preflight
from .codex_runtime import RuntimeExecutionError
from .contracts import ROLES, ContractError
from .measurement import unavailable_usage, validate_usage


class Pipeline:
    def __init__(self, store, collector, runtime):
        self.store, self.collector, self.runtime = store, collector, runtime
        self.owner = uuid.uuid4().hex

    async def _heartbeat(self, job, seconds):
        while True:
            await asyncio.sleep(max(0.1, seconds / 3))
            if not await self.store.call("renew", job):
                return

    async def _execute(self, job, config):
        start = time.monotonic()
        usage, output = unavailable_usage(), None
        heartbeat = asyncio.create_task(self._heartbeat(job, config["lease_seconds"]))
        invoked = False
        try:
            role = job["role"]
            if role in ("collection", "supplemental"):
                output = await self.store.call("cached", job) if role == "collection" else None
                if output is not None:
                    await self.store.call("event", job["run"], role, "cache_reused", job=job["id"])
                else:
                    predecessor = None
                    if role == "supplemental":
                        bundle = await self.store.call("_verified_bundle", job["bundle"])
                        predecessor = bundle["bundle_id"]

                    async def record_fetch(phase, fetch):
                        await self.store.call(
                            "event",
                            job["run"],
                            "fetch",
                            phase,
                            job=job["id"],
                            attempt=job["attempt_id"],
                            case=job["case_id"],
                            fetch=fetch,
                        )

                    output = await self.collector.collect(
                        job["target"],
                        predecessor,
                        role == "supplemental",
                        on_attempt=record_fetch,
                        budget_seconds=config["supplemental_seconds"]
                        if role == "supplemental"
                        else None,
                    )
                usage = unavailable_usage("no_model_invoked")
            else:
                task = await self.store.call("task", job)
                invoked = True
                result = await self.runtime.invoke(task)
                output = result.output
                try:
                    usage = validate_usage(result.usage)
                except ValueError:
                    usage = unavailable_usage("invalid_runtime_usage_payload")
                    await self.store.call(
                        "event",
                        job["run"],
                        role,
                        "invalid_usage",
                        job=job["id"],
                        attempt=job["attempt_id"],
                        native_usage=result.usage,
                    )
                    raise
                # Preserve actual model identity independently from configured model names.
                await self.store.call(
                    "event",
                    job["run"],
                    role,
                    "runtime_returned",
                    job=job["id"],
                    attempt=job["attempt_id"],
                    actual_model=result.actual_model,
                    configured_model=task["model"],
                    runtime=self.runtime.capabilities.name,
                    native_receipt=result.native_receipt,
                )
                if (
                    not self.runtime.capabilities.synthetic
                    and result.actual_model is not None
                    and result.actual_model != task["model"]
                ):
                    raise ContractError("Runtime substituted the configured model")
            await self.store.call("complete", job, output, usage, (time.monotonic() - start) * 1000)
        except asyncio.CancelledError:
            await self.store.call(
                "fail",
                job,
                "cancelled" if invoked else "interrupted",
                usage,
                (time.monotonic() - start) * 1000,
                output,
            )
            raise
        except RuntimeExecutionError as exc:
            await self.store.call(
                "event",
                job["run"],
                job["role"],
                "runtime_failed",
                job=job["id"],
                attempt=job["attempt_id"],
                native_receipt=exc.receipt,
            )
            await self.store.call(
                "fail", job, "execution_unknown", exc.usage, (time.monotonic() - start) * 1000
            )
            # Stop admissions on adapter/auth/quota failures instead of launching
            # another subscription session for every remaining dataset row.
            raise
        except (ContractError, ValueError):
            await self.store.call(
                "fail",
                job,
                "invalid_output" if invoked else "invalid_artifact",
                usage,
                (time.monotonic() - start) * 1000,
                output,
            )
        except Exception:
            # Unknown external effects are deliberately not retried automatically.
            await self.store.call(
                "fail",
                job,
                "execution_unknown" if invoked else "internal_failure",
                usage,
                (time.monotonic() - start) * 1000,
                output,
            )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _worker(self, run, role, phase_roles, config):
        next_recovery = time.monotonic() + config["lease_seconds"]
        while True:
            if time.monotonic() >= next_recovery:
                await self.store.call("recover", run)
                next_recovery = time.monotonic() + config["lease_seconds"]
            job = await self.store.call("claim", run, role, self.owner)
            if job:
                await self._execute(job, config)
                continue
            current = await self.store.call("run", run)
            if current["state"] == "cancelled":
                return
            if not await self.store.call("active", run, phase_roles):
                return
            await asyncio.sleep(0.02)

    async def run(self, run, *, collect_only=False):
        config = (await self.store.call("run", run))["config"]
        if not collect_only:
            capability = preflight(self.runtime, config)
            if not capability["ready"]:
                raise ValueError("; ".join(capability["problems"]))
        await self.store.call("verify", run)
        await self.store.call("recover", run)
        workers = []
        try:
            workers = [
                asyncio.create_task(self._worker(run, "collection", ("collection",), config))
                for _ in range(config["concurrency"]["collection"])
            ]
            await asyncio.gather(*workers)
            if not await self.store.call("release_barrier", run):
                return (await self.store.call("run", run))["state"]
            if collect_only:
                return "collected"
            roles = (*ROLES, "judge", "supplemental")
            workers = [
                asyncio.create_task(self._worker(run, role, roles, config))
                for role in roles
                for _ in range(config["concurrency"].get(role, 1))
            ]
            await asyncio.gather(*workers)
            return await self.store.call("finish_run", run)
        except BaseException:
            for worker in workers:
                # gather propagates cancellation already. A second cancel can
                # interrupt the worker while it is persisting its terminal receipt.
                if not worker.done() and not worker.cancelling():
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.store.call("cancel", run)
            raise
