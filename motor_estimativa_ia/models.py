"""Contrato de dados do motor (Pydantic).

Entrada (Project, Parameters): valida estrutura, tipos e faixas de valores. As regras que cruzam
projeto e parâmetros (tipos de atividade, modalidades, taxas, alocações somando 100%, duplicidade
de transversais) continuam no motor, que é a única fonte das regras de negócio.

Saída (EstimateResult): espelha exatamente o retorno de engine.calculate_project. Como os modelos
proíbem campos extras, qualquer divergência entre motor e contrato falha nos testes.
"""
from __future__ import annotations
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Share = Annotated[float, Field(ge=0, le=1)]
NonNegative = Annotated[float, Field(ge=0)]
ValidationStatus = Literal["hipotese", "em_validacao", "validado"]
CostScenario = Literal["both", "base", "ai"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Projeto

class AIOverrides(Strict):
    eligible_share: Share | None = None
    reduction_rate: Share | None = None
    review_hours_per_base_hour: NonNegative | None = None
    rework_hours_per_base_hour: NonNegative | None = None


class Activity(Strict):
    id: str
    name: str
    activity_type: str
    scope_key: str | None = None
    ai_modality: str | None = None
    ai: AIOverrides | None = None
    optimistic_hours: NonNegative
    most_likely_hours: NonNegative
    pessimistic_hours: NonNegative
    allocations: dict[str, dict[str, Share]]


class Task(Strict):
    id: str
    name: str
    description: str | None = None
    activities: list[Activity]


class Feature(Strict):
    id: str
    name: str
    description: str | None = None
    acceptance_criteria: str | None = None
    complexity: Literal["baixa", "media", "alta"] | None = None
    tasks: list[Task]


class CostItem(Strict):
    id: str
    description: str | None = None
    cost_type: str
    amount: NonNegative | None = None  # None = valor a confirmar ("não contabilizado")
    applies_to: CostScenario | None = None


class ProjectContent(Strict):
    """Escopo estimável do projeto; é o que fica versionado (revision) na persistência."""
    description: str | None = None
    contingency_rate: Share | None = None
    features: list[Feature] = []
    transversal_tasks: list[Task] = []
    cost_items: list[CostItem] = []


class Project(ProjectContent):
    """Entrada do motor: identificação + conteúdo."""
    project_id: str
    name: str


# Parâmetros

class Provenance(Strict):
    validation_status: ValidationStatus
    source: str


class PertConfig(Strict):
    optimistic_weight: NonNegative
    most_likely_weight: NonNegative
    pessimistic_weight: NonNegative
    divisor: Annotated[float, Field(gt=0)]


class AIModality(Strict):
    label: str
    applicable_activity_types: list[str]
    eligible_share: Share
    reduction_rate: Share
    review_hours_per_base_hour: NonNegative
    rework_hours_per_base_hour: NonNegative
    validation_status: ValidationStatus
    source: str


class AIConfig(Strict):
    modalities: dict[str, AIModality]


class CostType(Strict):
    label: str
    applies_to: CostScenario


class Parameters(Strict):
    config_version: str
    currency: str
    provenance: dict[str, Provenance] = {}
    pert: PertConfig
    activity_types: dict[str, str]
    roles: dict[str, dict[str, NonNegative]]
    ai: AIConfig
    cost_types: dict[str, CostType]
    contingency_rate_default: Share


# Resultado

ResolvedStatus = Literal["hipotese", "em_validacao", "validado", "unspecified"]


class ProvenanceEntry(Strict):
    validation_status: ResolvedStatus
    source: str


class AIFactors(Strict):
    eligible_share: float
    reduction_rate: float
    review_hours_per_base_hour: float
    rework_hours_per_base_hour: float


class ModalityUsed(AIFactors):
    validation_status: ResolvedStatus
    source: str


class Assumptions(Strict):
    engine_version: str
    parameters_version: str
    cost_basis: Literal["internal"]
    ai_review_rework_basis: Literal["proportional_to_base_hours"]
    ai_modalities_used: dict[str, ModalityUsed] = Field(description="Modalidades efetivamente aplicadas, com fatores padrão")
    contingency_rate: float
    contingency_source: Literal["project", "parameters"]
    uncounted_costs: list[str] = Field(description="Tipos de custo sem valor informado; não são zero")
    parameter_provenance: dict[str, ProvenanceEntry]
    unvalidated_parameters: list[str] = Field(description="Parâmetros usados que ainda não foram validados")
    note: str


class Summary(Strict):
    activity_count: int
    ai_activity_count: int
    optimistic_hours: float
    pessimistic_hours: float
    uncertainty_range_hours: float = Field(description="Σ(P − O); indicador simples, não intervalo estatístico")
    base_hours: float = Field(description="Subtotal sem IA, antes da contingência")
    ai_hours: float = Field(description="Subtotal com IA, antes da contingência")
    base_contingency_hours: float
    ai_contingency_hours: float
    base_total_hours: float
    ai_total_hours: float
    hours_saved: float = Field(description="Pode ser negativo: a IA aumentou o esforço")
    hours_saved_percent: float
    base_labor_cost: float
    ai_labor_cost: float
    base_contingency: float
    ai_contingency: float
    base_additional_cost: float
    ai_additional_cost: float
    base_total_cost: float
    ai_total_cost: float
    cost_difference_ai_minus_base: float
    cost_savings: float = Field(description="Pode ser negativo: a IA aumentou o custo")
    cost_savings_percent: float


class CostItemResult(Strict):
    id: str | None
    description: str | None
    cost_type: str
    applies_to: CostScenario
    amount: float | None
    counted: bool


class CostPair(Strict):
    base_cost: float
    ai_cost: float


class AdditionalCosts(Strict):
    items: list[CostItemResult]
    by_type: dict[str, CostPair]


class HoursPair(Strict):
    base_hours: float
    ai_hours: float


class RoleSeniorityResult(Strict):
    base_hours: float
    base_labor_cost: float
    ai_hours: float
    ai_labor_cost: float


class AllocationResult(Strict):
    role: str
    seniority: str
    share: float
    hourly_rate: float
    base_hours: float
    ai_hours: float
    base_labor_cost: float
    ai_labor_cost: float


class ActivityResult(Strict):
    scope: Literal["feature", "transversal"]
    feature_id: str | None = Field(description="None para atividades transversais")
    feature: str
    task_id: str
    task: str
    activity_id: str
    activity: str
    activity_type: str
    scope_key: str | None
    optimistic_hours: float
    pessimistic_hours: float
    uncertainty_range_hours: float
    ai_applied: bool
    ai_modality: str = Field(description='Modalidade aplicada ou "sem_ia"')
    ai_factors: AIFactors | None = Field(description="Fatores efetivos (padrão da modalidade + sobrescritas)")
    base_hours: float
    ai_hours: float
    hours_saved: float
    base_labor_cost: float
    ai_labor_cost: float
    allocations: list[AllocationResult]


class EstimateResult(Strict):
    project_id: str | None
    project_name: str | None
    currency: str
    assumptions: Assumptions
    summary: Summary
    additional_costs: AdditionalCosts
    hours_by_scope: dict[str, HoursPair]
    hours_by_activity_type: dict[str, HoursPair]
    hours_by_ai_modality: dict[str, HoursPair]
    hours_and_cost_by_role_seniority: dict[str, RoleSeniorityResult] = Field(description='Chave "papel/senioridade"')
    activities: list[ActivityResult]
