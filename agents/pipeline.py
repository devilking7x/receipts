"""Pipeline orchestration: Planner -> 3 parallel Executors
-> Adversarial Evaluator -> Writer.

This module wires the agents together. It is synchronous, except for
the executor stage, which runs under asyncio.run so the three
executors run concurrently. API callers must run orchestrate() in a
worker thread (asyncio.to_thread) to avoid blocking the event loop.
"""

import asyncio
import json
import os
from dataclasses import dataclass

from agents.evaluator import EvaluatorAgent
from agents.executors import run_all
from agents.planner import PlannerAgent
from agents.writer import WriterAgent
from cognition.generator import Tracer, create_injected_generator
from cognition.world_model import EntityNode, WorldModel
from config import load_config
from data_layer import (
    SearchClient,
    ZetarisClient,
    load_sample_fixtures,
)


class VendorNotFoundError(Exception):
    """Raised in SAMPLE_MODE when no fixture exists for a vendor."""


@dataclass
class PipelineResult:
    vendor_name: str
    sample_mode: bool
    score: int
    tier: str
    report_md_path: str
    report_json_path: str
    trace_path: str
    trace_id: str
    report: dict


def orchestrate(vendor_name, procurement_context="", config=None,
                out_dir="output", trace_path="logs/traces.jsonl"):
    """Run the full pipeline and write report.md + report.json."""
    config = config or load_config()
    fixtures = load_sample_fixtures() if config.sample_mode else {}
    if config.sample_mode and vendor_name.lower() not in fixtures:
        raise VendorNotFoundError(
            "No SAMPLE_MODE fixture for vendor '%s'. Available sample "
            "vendors: %s. In live mode any vendor can be investigated "
            "through Zetaris."
            % (vendor_name,
               ", ".join(sorted(f["vendor_name"] for f in
                                 fixtures.values()))))
    os.makedirs(out_dir, exist_ok=True)
    trace_dir = os.path.dirname(trace_path)
    if trace_dir:
        os.makedirs(trace_dir, exist_ok=True)
    tracer = Tracer(trace_path)
    models_used = []

    def make_gen(agent_id):
        base = create_injected_generator(config, tracer, agent_id)

        def wrapped(system_prompt, user_prompt, response_schema=None):
            result = base(system_prompt, user_prompt, response_schema)
            models_used.append(result.get("model"))
            return result

        return wrapped

    generate_fns = {
        "PlannerAgent": make_gen("PlannerAgent"),
        "FinancialExecutor": make_gen("FinancialExecutor"),
        "LegalExecutor": make_gen("LegalExecutor"),
        "ReputationExecutor": make_gen("ReputationExecutor"),
        "EvaluatorAgent": make_gen("EvaluatorAgent"),
        "WriterAgent": make_gen("WriterAgent"),
    }

    zetaris_client = ZetarisClient(
        config,
        sample_rows_by_vendor={
            name: fixture.get("zetaris_rows", [])
            for name, fixture in fixtures.items()})
    search_client = SearchClient(config, zetaris_client, fixtures)

    world = WorldModel(vendor_name)
    world.add_entity(EntityNode(
        entity_id="vendor-1", entity_type="Vendor", name=vendor_name))

    planner = PlannerAgent()
    plan = planner.plan(vendor_name, procurement_context,
                        generate_fns["PlannerAgent"], tracer)
    asyncio.run(run_all(world, plan, vendor_name, generate_fns, tracer,
                        zetaris_client, search_client))
    evaluator = EvaluatorAgent()
    evaluator.evaluate(
        world,
        lambda claim: search_client.fetch_primary(claim, vendor_name),
        tracer)
    model = "sample-mock"
    if not config.sample_mode:
        for used in models_used:
            if used and used != "sample-mock":
                model = used
                break
        else:
            model = config.meterless_model
    writer = WriterAgent()
    markdown, report_data = writer.write(
        world, procurement_context, config.sample_mode, model, trace_path,
        generate_fns["WriterAgent"], tracer)
    md_path = os.path.join(out_dir, "report.md")
    json_path = os.path.join(out_dir, "report.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report_data, fh, indent=2, ensure_ascii=False)
    tracer.log(
        step="pipeline", agent="Pipeline", engine="pipeline",
        model=model, event_type="pipeline_complete",
        action="complete",
        input_summary="vendor=%s" % vendor_name,
        output_summary="score %d/100 %s, reports written"
                       % (report_data["score"], report_data["tier"]),
        handoff_to=None, status="success")
    return PipelineResult(
        vendor_name=vendor_name,
        sample_mode=config.sample_mode,
        score=report_data["score"],
        tier=report_data["tier"],
        report_md_path=md_path,
        report_json_path=json_path,
        trace_path=trace_path,
        trace_id=tracer.trace_id,
        report=report_data)
