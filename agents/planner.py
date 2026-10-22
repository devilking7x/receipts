"""Planner agent: Chief Due-Diligence Architect.

Turns a vendor name plus procurement context into a structured plan of
three non-overlapping tasks: FINANCIAL_TASK, LEGAL_TASK and
REPUTATION_TASK. The plan itself is deterministic; the injected
generate_fn is called for a short rationale, which is logged in traces
but never decides the task list (so the plan is stable and auditable).
"""

from pydantic import BaseModel

from cognition.generator import Tracer


class Task(BaseModel):
    task_id: str
    task_type: str  # FINANCIAL_TASK | LEGAL_TASK | REPUTATION_TASK
    title: str
    description: str
    owner_agent: str


class InvestigationPlan(BaseModel):
    vendor_name: str
    procurement_context: str
    tasks: list


class PlannerAgent:
    AGENT_ID = "PlannerAgent"

    def plan(self, vendor_name, procurement_context, generate_fn, tracer):
        rationale = generate_fn(
            "You are a chief due-diligence architect. Summarize why "
            "splitting this investigation into financial, legal and "
            "reputation work is the right structure.",
            "Vendor: %s. Procurement context: %s. Give a one sentence "
            "rationale for the three task split."
            % (vendor_name, procurement_context or "general onboarding"))
        tasks = [
            Task(task_id="T1", task_type="FINANCIAL_TASK",
                 title="Financial health check",
                 description="Query Zetaris for %s financial records: "
                             "revenue trend, cash flow and distress "
                             "signals." % vendor_name,
                 owner_agent="FinancialExecutor"),
            Task(task_id="T2", task_type="LEGAL_TASK",
                 title="Legal and news risk scan",
                 description="Collect legal filings and news records for "
                             "%s, then verify severe secondary claims "
                             "against primary court records." % vendor_name,
                 owner_agent="LegalExecutor"),
            Task(task_id="T3", task_type="REPUTATION_TASK",
                 title="Reputation and PR check",
                 description="Collect company PR statements and customer "
                             "reviews for %s, and compare PR claims "
                             "against Zetaris financial reality."
                             % vendor_name,
                 owner_agent="ReputationExecutor"),
        ]
        plan = InvestigationPlan(
            vendor_name=vendor_name,
            procurement_context=procurement_context or "",
            tasks=tasks)
        tracer.log(
            step="planner", agent=self.AGENT_ID, engine="planner",
            model=rationale.get("model", "unknown"),
            event_type="plan_created", action="create_plan",
            input_summary="vendor=%s" % vendor_name,
            output_summary="3 tasks: FINANCIAL_TASK, LEGAL_TASK, "
                           "REPUTATION_TASK",
            handoff_to="FinancialExecutor,LegalExecutor,ReputationExecutor",
            status="success")
        return plan
