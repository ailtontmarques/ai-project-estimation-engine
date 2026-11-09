"""Motor determinístico de estimativa de esforço e custo.

Uso:
  python engine.py --parameters parameters.json --project project_example.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

ENGINE_VERSION = "0.4.0"
AI_KEYS = ("eligible_share", "reduction_rate", "review_hours_per_base_hour", "rework_hours_per_base_hour")
TRANSVERSAL_GROUP = {"id": None, "name": "Transversal"}
NO_AI = "sem_ia"
COST_SCENARIOS = ("both", "base", "ai")
VALIDATION_STATUSES = ("hipotese", "em_validacao", "validado")
TRACKED_PARAMETERS = ("pert", "roles", "contingency_rate_default")


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pert_hours(activity: dict[str, Any], parameters: dict[str, Any], name: str | None = None) -> float:
    """Estimativa PERT: (O + 4*M + P) / 6, usando pesos configuráveis.

    `name` identifica a atividade nas mensagens de erro (o usuário não vê os ids internos)."""
    label = name or activity.get("name") or activity.get("id")
    o = float(activity["optimistic_hours"])
    m = float(activity["most_likely_hours"])
    p = float(activity["pessimistic_hours"])
    if min(o, m, p) < 0:
        raise ValueError(f"Horas não podem ser negativas em {label}")
    if not (o <= m <= p):
        raise ValueError(f"Esperado otimista <= mais provável <= pessimista em {label}")
    cfg = parameters["pert"]
    divisor = float(cfg["divisor"])
    if divisor <= 0:
        raise ValueError("O divisor PERT precisa ser positivo.")
    return (o * float(cfg["optimistic_weight"]) +
            m * float(cfg["most_likely_weight"]) +
            p * float(cfg["pessimistic_weight"])) / divisor


def validate_allocations(allocations: dict[str, Any], activity_name: str, tolerance: float = 1e-6) -> None:
    if not allocations:
        raise ValueError(f"Atividade sem alocação de equipe: {activity_name}")
    total = 0.0
    for role, seniorities in allocations.items():
        if not isinstance(seniorities, dict) or not seniorities:
            raise ValueError(f"Alocação inválida para o papel {role} em {activity_name}")
        for seniority, share in seniorities.items():
            share = float(share)
            if share < 0 or share > 1:
                raise ValueError(f"Percentual deve estar entre 0 e 1: {activity_name}/{role}/{seniority}")
            total += share
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"Alocações devem somar 100% em {activity_name}; total atual: {total:.4f}")


def iter_activities(project: dict[str, Any]):
    """Percorre as atividades das funcionalidades e, depois, das tarefas transversais do projeto."""
    for feature in project.get("features", []):
        for task in feature.get("tasks", []):
            for activity in task.get("activities", []):
                yield "feature", feature, task, activity
    for task in project.get("transversal_tasks", []):
        for activity in task.get("activities", []):
            yield "transversal", TRANSVERSAL_GROUP, task, activity


def validate_transversal_scope(project: dict[str, Any]) -> None:
    """Impede que algo estimado como transversal seja contabilizado de novo em uma funcionalidade."""
    transversal_keys: set[str] = set()
    for scope, _, _, activity in iter_activities(project):
        if scope != "transversal":
            continue
        key = activity.get("scope_key")
        if not key:
            raise ValueError(f"Atividade transversal sem scope_key: {activity.get('id', activity.get('name'))}")
        if key in transversal_keys:
            raise ValueError(f"scope_key transversal duplicado: {key}")
        transversal_keys.add(key)
    for scope, feature, _, activity in iter_activities(project):
        if scope == "feature" and activity.get("scope_key") in transversal_keys:
            raise ValueError(
                f'{feature["name"]} / {activity["name"]} duplica a atividade transversal "{activity["scope_key"]}"')


def validate_activity_type(activity: dict[str, Any], parameters: dict[str, Any], name: str) -> str:
    activity_type = activity.get("activity_type")
    if activity_type not in parameters["activity_types"]:
        raise ValueError(f"Tipo de atividade ausente ou não configurado em {name}: {activity_type}")
    return activity_type


def resolve_ai(activity: dict[str, Any], activity_type: str, parameters: dict[str, Any],
               name: str) -> tuple[str | None, dict[str, float] | None]:
    """Retorna a modalidade de IA da atividade e seus fatores; (None, None) quando não há IA."""
    modality = activity.get("ai_modality")
    overrides = activity.get("ai") or {}
    if modality is None:
        if overrides:
            raise ValueError(f"Fatores de IA informados sem ai_modality em {name}")
        return None, None
    modalities = parameters["ai"]["modalities"]
    if modality not in modalities:
        raise ValueError(f"Modalidade de IA não configurada em {name}: {modality}")
    cfg = modalities[modality]
    if activity_type not in cfg["applicable_activity_types"]:
        raise ValueError(f"Modalidade {modality} não se aplica ao tipo {activity_type} em {name}")
    factors = {key: float(cfg[key] if overrides.get(key) is None else overrides[key]) for key in AI_KEYS}
    for key in ("eligible_share", "reduction_rate"):
        if not 0 <= factors[key] <= 1:
            raise ValueError(f"{key} deve estar entre 0 e 1 em {name}")
    if factors["review_hours_per_base_hour"] < 0 or factors["rework_hours_per_base_hour"] < 0:
        raise ValueError(f"Revisão e retrabalho não podem ser negativos em {name}")
    return modality, factors


def calculate_additional_costs(project: dict[str, Any], parameters: dict[str, Any], ai_used: bool) -> dict[str, Any]:
    """Soma custos adicionais por tipo e cenário; valor não informado é "não contabilizado", nunca zero."""
    cost_types = parameters["cost_types"]
    items = []
    by_type: dict[str, dict[str, float]] = {}
    uncounted: set[str] = set()
    for item in project.get("cost_items", []):
        cost_type = item.get("cost_type")
        if cost_type not in cost_types:
            raise ValueError(f"Tipo de custo não configurado no item {item.get('id')}: {cost_type}")
        applies_to = item.get("applies_to") or cost_types[cost_type]["applies_to"]
        if applies_to not in COST_SCENARIOS:
            raise ValueError(f"applies_to deve ser um de {COST_SCENARIOS} no item {item.get('id')}")
        amount = item.get("amount")
        if amount is None:
            uncounted.add(cost_type)
        else:
            amount = float(amount)
            if amount < 0:
                raise ValueError(f"Custo adicional não pode ser negativo no item {item.get('id')}")
            bucket = by_type.setdefault(cost_type, {"base_cost": 0.0, "ai_cost": 0.0})
            if applies_to in ("both", "base"):
                bucket["base_cost"] += amount
            if applies_to in ("both", "ai"):
                bucket["ai_cost"] += amount
        items.append({"id": item.get("id"), "description": item.get("description"), "cost_type": cost_type,
                      "applies_to": applies_to, "amount": amount, "counted": amount is not None})

    declared = {i["cost_type"] for i in items}
    for cost_type, cfg in cost_types.items():
        if cfg["applies_to"] == "ai" and not ai_used:
            continue
        if cost_type not in declared:
            uncounted.add(cost_type)

    return {
        "items": items,
        "by_type": by_type,
        "base_total": sum(b["base_cost"] for b in by_type.values()),
        "ai_total": sum(b["ai_cost"] for b in by_type.values()),
        "uncounted": sorted(uncounted),
    }


def collect_provenance(parameters: dict[str, Any], project: dict[str, Any],
                       modalities_used: set[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Origem e estado de validação dos parâmetros usados no cálculo, com a lista dos ainda não validados."""
    provenance = parameters.get("provenance", {})
    project_contingency = project.get("contingency_rate") is not None
    keys = [k for k in TRACKED_PARAMETERS if not (k == "contingency_rate_default" and project_contingency)]
    entries = {k: provenance.get(k, {}) for k in keys}
    entries.update({f"ai.modalities.{m}": parameters["ai"]["modalities"][m] for m in sorted(modalities_used)})
    result = {}
    for key, info in entries.items():
        status = info.get("validation_status", "unspecified")
        if status not in VALIDATION_STATUSES + ("unspecified",):
            raise ValueError(f"validation_status inválido em {key}: {status}")
        result[key] = {"validation_status": status, "source": info.get("source", "unspecified")}
    unvalidated = [k for k, v in result.items() if v["validation_status"] != "validado"]
    return result, unvalidated


def calculate_project(project: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Calcula baseline sem IA e cenário com IA, preservando custos por papel/senioridade."""
    validate_transversal_scope(project)
    rows = []
    role_hours: dict[str, float] = {}
    role_costs: dict[str, float] = {}
    role_ai_hours: dict[str, float] = {}
    role_ai_costs: dict[str, float] = {}
    breakdowns: dict[str, dict[str, dict[str, float]]] = {"scope": {}, "activity_type": {}, "ai_modality": {}}
    modalities_used: set[str] = set()
    base_hours_total = 0.0
    ai_hours_total = 0.0
    optimistic_total = 0.0
    pessimistic_total = 0.0
    base_labor_cost = 0.0
    ai_labor_cost = 0.0
    ai_cfg = parameters["ai"]

    for scope, group, task, activity in iter_activities(project):
        name = f'{group["name"]} / {task["name"]} / {activity["name"]}'
        validate_allocations(activity.get("allocations", {}), name)
        activity_type = validate_activity_type(activity, parameters, name)
        base_hours = pert_hours(activity, parameters, name)
        modality, factors = resolve_ai(activity, activity_type, parameters, name)

        # Revisão e retrabalho só existem quando a IA é aplicada à atividade (parcela elegível > 0).
        ai_applied = factors is not None and factors["eligible_share"] > 0
        if ai_applied:
            ai_hours = (base_hours * (1 - factors["eligible_share"] * factors["reduction_rate"])
                        + base_hours * factors["review_hours_per_base_hour"]
                        + base_hours * factors["rework_hours_per_base_hour"])
            modalities_used.add(modality)
        else:
            ai_hours = base_hours
        activity_base_cost = 0.0
        activity_ai_cost = 0.0
        allocation_rows = []
        for role, seniorities in activity["allocations"].items():
            for seniority, share in seniorities.items():
                try:
                    rate = float(parameters["roles"][role][seniority])
                except KeyError as exc:
                    raise ValueError(f"Taxa horária não configurada para {role}/{seniority}") from exc
                if rate < 0:
                    raise ValueError(f"Taxa horária não pode ser negativa: {role}/{seniority}")
                h_base = base_hours * float(share)
                h_ai = ai_hours * float(share)
                c_base = h_base * rate
                c_ai = h_ai * rate
                allocation_rows.append({
                    "role": role, "seniority": seniority, "share": float(share),
                    "hourly_rate": rate, "base_hours": h_base, "ai_hours": h_ai,
                    "base_labor_cost": c_base, "ai_labor_cost": c_ai
                })
                key = f"{role}/{seniority}"
                role_hours[key] = role_hours.get(key, 0.0) + h_base
                role_costs[key] = role_costs.get(key, 0.0) + c_base
                role_ai_hours[key] = role_ai_hours.get(key, 0.0) + h_ai
                role_ai_costs[key] = role_ai_costs.get(key, 0.0) + c_ai
                activity_base_cost += c_base
                activity_ai_cost += c_ai

        modality_key = modality if ai_applied else NO_AI
        for dimension, key in (("scope", scope), ("activity_type", activity_type), ("ai_modality", modality_key)):
            bucket = breakdowns[dimension].setdefault(key, {"base_hours": 0.0, "ai_hours": 0.0})
            bucket["base_hours"] += base_hours
            bucket["ai_hours"] += ai_hours

        rows.append({
            "scope": scope,
            "feature_id": group["id"], "feature": group["name"],
            "task_id": task["id"], "task": task["name"],
            "activity_id": activity["id"], "activity": activity["name"],
            "activity_type": activity_type,
            "scope_key": activity.get("scope_key"),
            "optimistic_hours": float(activity["optimistic_hours"]),
            "pessimistic_hours": float(activity["pessimistic_hours"]),
            "uncertainty_range_hours": float(activity["pessimistic_hours"]) - float(activity["optimistic_hours"]),
            "ai_applied": ai_applied,
            "ai_modality": modality_key,
            "ai_factors": factors if ai_applied else None,
            "base_hours": base_hours, "ai_hours": ai_hours,
            "hours_saved": base_hours - ai_hours,
            "base_labor_cost": activity_base_cost, "ai_labor_cost": activity_ai_cost,
            "allocations": allocation_rows
        })
        base_hours_total += base_hours
        ai_hours_total += ai_hours
        optimistic_total += float(activity["optimistic_hours"])
        pessimistic_total += float(activity["pessimistic_hours"])
        base_labor_cost += activity_base_cost
        ai_labor_cost += activity_ai_cost

    if not rows:
        raise ValueError("O escopo não tem atividades: cadastre ao menos uma atividade antes de estimar.")

    # null equivale a ausente: vale a contingência padrão dos parâmetros.
    project_contingency = project.get("contingency_rate")
    contingency_rate = float(parameters["contingency_rate_default"] if project_contingency is None else project_contingency)
    if not 0 <= contingency_rate <= 1:
        raise ValueError("A contingência deve estar entre 0 e 1.")

    additional = calculate_additional_costs(project, parameters, ai_used=bool(modalities_used))
    provenance, unvalidated = collect_provenance(parameters, project, modalities_used)

    base_contingency_hours = base_hours_total * contingency_rate
    ai_contingency_hours = ai_hours_total * contingency_rate
    base_total_hours = base_hours_total + base_contingency_hours
    ai_total_hours = ai_hours_total + ai_contingency_hours

    base_contingency = base_labor_cost * contingency_rate
    ai_contingency = ai_labor_cost * contingency_rate
    base_total_cost = base_labor_cost + base_contingency + additional["base_total"]
    ai_total_cost = ai_labor_cost + ai_contingency + additional["ai_total"]

    def money(n: float | None) -> float | None:
        return None if n is None else round(n, 2)
    def hours(n: float) -> float:
        return round(n, 2)
    def percent(saved: float, reference: float) -> float:
        return round(saved / reference * 100, 2) if reference else 0
    def rounded(buckets: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        return {k: {m: hours(v) for m, v in b.items()} for k, b in sorted(buckets.items())}

    return {
        "project_id": project.get("project_id"),
        "project_name": project.get("name"),
        "currency": parameters.get("currency", "BRL"),
        "assumptions": {
            "engine_version": ENGINE_VERSION,
            "parameters_version": parameters.get("config_version", "unspecified"),
            "cost_basis": "internal",
            "ai_review_rework_basis": "proportional_to_base_hours",
            "ai_modalities_used": {
                m: {**{k: ai_cfg["modalities"][m][k] for k in AI_KEYS},
                    "validation_status": ai_cfg["modalities"][m].get("validation_status", "unspecified"),
                    "source": ai_cfg["modalities"][m].get("source", "unspecified")}
                for m in sorted(modalities_used)
            },
            "contingency_rate": contingency_rate,
            "contingency_source": "parameters" if project_contingency is None else "project",
            "uncounted_costs": additional["uncounted"],
            "parameter_provenance": provenance,
            "unvalidated_parameters": unvalidated,
            "note": "Parâmetros iniciais ilustrativos; substitua por dados calibrados da organização."
        },
        "summary": {
            "activity_count": len(rows),
            "ai_activity_count": sum(1 for r in rows if r["ai_applied"]),
            "optimistic_hours": hours(optimistic_total),
            "pessimistic_hours": hours(pessimistic_total),
            "uncertainty_range_hours": hours(pessimistic_total - optimistic_total),
            "base_hours": hours(base_hours_total),
            "ai_hours": hours(ai_hours_total),
            "base_contingency_hours": hours(base_contingency_hours),
            "ai_contingency_hours": hours(ai_contingency_hours),
            "base_total_hours": hours(base_total_hours),
            "ai_total_hours": hours(ai_total_hours),
            "hours_saved": hours(base_hours_total - ai_hours_total),
            "hours_saved_percent": percent(base_hours_total - ai_hours_total, base_hours_total),
            "base_labor_cost": money(base_labor_cost),
            "ai_labor_cost": money(ai_labor_cost),
            "base_contingency": money(base_contingency),
            "ai_contingency": money(ai_contingency),
            "base_additional_cost": money(additional["base_total"]),
            "ai_additional_cost": money(additional["ai_total"]),
            "base_total_cost": money(base_total_cost),
            "ai_total_cost": money(ai_total_cost),
            "cost_difference_ai_minus_base": money(ai_total_cost-base_total_cost),
            "cost_savings": money(base_total_cost-ai_total_cost),
            "cost_savings_percent": percent(base_total_cost - ai_total_cost, base_total_cost)
        },
        "additional_costs": {
            "items": additional["items"],
            "by_type": {k: {m: money(v) for m, v in b.items()} for k, b in sorted(additional["by_type"].items())},
        },
        "hours_by_scope": rounded(breakdowns["scope"]),
        "hours_by_activity_type": rounded(breakdowns["activity_type"]),
        "hours_by_ai_modality": rounded(breakdowns["ai_modality"]),
        "hours_and_cost_by_role_seniority": {
            key: {
                "base_hours": hours(value), "base_labor_cost": money(role_costs[key]),
                "ai_hours": hours(role_ai_hours[key]), "ai_labor_cost": money(role_ai_costs[key])
            }
            for key, value in sorted(role_hours.items())
        },
        "activities": rows
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor de estimativa de esforço e custos")
    parser.add_argument("--parameters", default="parameters.json")
    parser.add_argument("--project", default="project_example.json")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = calculate_project(load_json(args.project), load_json(args.parameters))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"Resultado salvo em: {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
