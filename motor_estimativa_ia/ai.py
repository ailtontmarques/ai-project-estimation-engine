"""Decomposição assistida por IA (Etapa 3): sugere tarefas e atividades técnicas para uma funcionalidade.

RN-01: a IA interpreta os requisitos e propõe; nada é salvo nem calculado aqui. A sugestão volta para a
revisão técnica, onde o Tech Leader ajusta, aplica ao escopo e salva; o motor calcula horas e custos.

A resposta do modelo é estruturada (Pydantic) e depois saneada contra os catálogos dos parâmetros
vigentes (tipos de atividade, modalidades compatíveis, papéis/senioridades, alocações somando 100%).
"""
from __future__ import annotations
import json
import os
from functools import lru_cache
from typing import Any, Protocol

import openai
from pydantic import BaseModel, Field

from services import ServiceError

DEFAULT_MODEL = "gpt-5.5"
NOT_CONFIGURED = "IA não configurada: defina OPENAI_API_KEY no ambiente da API."


class AIUnavailable(ServiceError):
    status_code = 503


class AIRefused(ServiceError):
    status_code = 422


# Formato pedido ao modelo (saída estruturada). Sem restrições numéricas no esquema: o saneamento valida.

class LLMAllocation(BaseModel):
    role: str
    seniority: str
    share: float = Field(description="Fração do esforço da atividade, entre 0 e 1")


class LLMActivity(BaseModel):
    name: str
    activity_type: str
    ai_modality: str | None = Field(description="Chave da modalidade de IA aplicável, ou null para sem IA")
    optimistic_hours: float
    most_likely_hours: float
    pessimistic_hours: float
    allocations: list[LLMAllocation]
    rationale: str = Field(description="Por que a atividade existe e de onde vêm as horas sugeridas")


class LLMTask(BaseModel):
    name: str
    activities: list[LLMActivity]


class LLMDecomposition(BaseModel):
    tasks: list[LLMTask]
    open_questions: list[str] = Field(description="Dúvidas de escopo que podem mudar a estimativa")
    risks: list[str]
    assumptions: list[str]


SYSTEM_PROMPT = """Você apoia a revisão técnica de estimativas de software em uma consultoria brasileira.
Recebe uma funcionalidade (história de usuário) e propõe a decomposição em tarefas técnicas e atividades,
para um Tech Leader revisar antes de qualquer cálculo. Escreva em português do Brasil.

Como decompor:
- Cada tarefa agrupa atividades de um mesmo resultado técnico. Cubra implementação, interface, integração,
  testes e segurança quando forem pertinentes; não omita QA nem segurança para parecer mais barato.
- Use apenas os tipos de atividade, modalidades de IA, papéis e senioridades do catálogo fornecido.
  Uma modalidade de IA só pode ser usada nos tipos de atividade listados para ela; use null quando a IA
  não se aplicar ou for duvidosa.
- Não inclua trabalho que já está coberto pelas atividades transversais do projeto (ex.: pipeline de CI/CD).
- Horas em estimativa de três pontos (otimista <= mais provável <= pessimista), em horas de trabalho sem IA.
  São sugestões iniciais que o Tech Leader vai revisar: seja realista, explique a base em `rationale` e
  amplie a distância entre otimista e pessimista quando o escopo for incerto.
- Distribua cada atividade entre papel e senioridade com frações que somem 1.
- Registre em `open_questions` o que falta saber para estimar melhor, em `risks` o que pode aumentar o
  esforço e em `assumptions` as premissas que você adotou."""


def build_prompt(project: dict, feature: dict, catalog: dict) -> str:
    other_features = [f["name"] for f in project["content"].get("features", []) if f["id"] != feature["id"]]
    transversal = [
        {"atividade": a["name"], "scope_key": a.get("scope_key")}
        for task in project["content"].get("transversal_tasks", [])
        for a in task.get("activities", [])
    ]
    context = {
        "projeto": {"nome": project["name"], "objetivo": project.get("objective")},
        "funcionalidade": {
            "nome": feature["name"],
            "descricao": feature.get("description"),
            "criterios_de_aceite": feature.get("acceptance_criteria"),
            "complexidade_preliminar": feature.get("complexity"),
            "tarefas_ja_cadastradas": [t["name"] for t in feature.get("tasks", [])],
        },
        "outras_funcionalidades": other_features,
        "atividades_transversais_existentes": transversal,
        "catalogo": catalog,
    }
    return ("Proponha a decomposição técnica da funcionalidade abaixo.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2))


def catalog_for_prompt(parameters: dict) -> dict:
    return {
        "tipos_de_atividade": parameters["activity_types"],
        "modalidades_de_ia": {
            key: {"descricao": m["label"], "tipos_de_atividade": m["applicable_activity_types"]}
            for key, m in parameters["ai"]["modalities"].items()
        },
        "papeis_e_senioridades": {role: sorted(rates) for role, rates in parameters["roles"].items()},
    }


def sanitize(raw: LLMDecomposition, parameters: dict) -> tuple[list[dict], list[str]]:
    """Ajusta a sugestão aos catálogos vigentes; devolve tarefas no formato do escopo (sem ids) e avisos."""
    activity_types = parameters["activity_types"]
    modalities = parameters["ai"]["modalities"]
    roles = parameters["roles"]
    warnings: list[str] = []
    tasks: list[dict] = []
    for task in raw.tasks:
        activities = []
        for a in task.activities:
            where = f'"{task.name} › {a.name}"'
            if a.activity_type not in activity_types:
                warnings.append(f"{where}: tipo de atividade desconhecido ({a.activity_type}); atividade descartada.")
                continue
            modality = a.ai_modality
            if modality and (modality not in modalities
                             or a.activity_type not in modalities[modality]["applicable_activity_types"]):
                warnings.append(f"{where}: modalidade de IA {modality} não se aplica; marcada como sem IA.")
                modality = None
            o, m, p = sorted(max(0.0, h) for h in (a.optimistic_hours, a.most_likely_hours, a.pessimistic_hours))
            allocations: dict[str, dict[str, float]] = {}
            for alloc in a.allocations:
                if alloc.role in roles and alloc.seniority in roles[alloc.role] and alloc.share > 0:
                    allocations.setdefault(alloc.role, {})
                    allocations[alloc.role][alloc.seniority] = allocations[alloc.role].get(alloc.seniority, 0) + alloc.share
            total = sum(share for seniorities in allocations.values() for share in seniorities.values())
            if total <= 0:
                warnings.append(f"{where}: alocação inválida; revise a equipe.")
                allocations = {next(iter(roles)): {"pleno": 1.0}}
            elif abs(total - 1) > 1e-6:
                allocations = {r: {s: round(v / total, 4) for s, v in sen.items()} for r, sen in allocations.items()}
                # Arredondamento: o resíduo vai para a primeira alocação, para somar exatamente 1.
                first_role = next(iter(allocations))
                first_seniority = next(iter(allocations[first_role]))
                residue = 1 - sum(v for sen in allocations.values() for v in sen.values())
                allocations[first_role][first_seniority] = round(allocations[first_role][first_seniority] + residue, 4)
            activity = {"name": a.name, "activity_type": a.activity_type, "optimistic_hours": round(o, 1),
                        "most_likely_hours": round(m, 1), "pessimistic_hours": round(p, 1),
                        "allocations": allocations, "rationale": a.rationale}
            if modality:
                activity["ai_modality"] = modality
            activities.append(activity)
        if activities:
            tasks.append({"name": task.name, "activities": activities})
    return tasks, warnings


def api_error_message(exc: openai.APIStatusError) -> str:
    """Mensagem para a tela: traduz os casos conhecidos e, nos demais, repassa o detalhe da API."""
    detail = ""
    if isinstance(exc.body, dict):
        detail = str(exc.body.get("message") or "")
    if exc.code == "insufficient_quota":
        return ("A conta da OpenAI usada pela API está sem créditos ou atingiu o limite de gastos. "
                "Verifique em platform.openai.com (Billing) e tente novamente.")
    if exc.code == "model_not_found":
        return f"Modelo de IA indisponível para esta chave: {detail or 'confira ESTIMATION_AI_MODEL'}"
    suffix = f": {detail}" if detail else "."
    return f"Serviço de IA respondeu com erro {exc.status_code}{suffix}"


def _refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "recusa"
    return None


class Decomposer(Protocol):
    def suggest(self, project: dict, feature: dict, parameters: dict) -> dict: ...


class OpenAIDecomposer:
    def __init__(self, client: openai.OpenAI | None = None, model: str | None = None, effort: str | None = None):
        self._client = client
        self.model = model or os.environ.get("ESTIMATION_AI_MODEL") or DEFAULT_MODEL
        # Esforço de raciocínio (none/minimal/low/medium/high/xhigh); vazio = não envia (modelos sem raciocínio).
        self.effort = os.environ.get("ESTIMATION_AI_EFFORT", "medium") if effort is None else effort

    @property
    def client(self) -> openai.OpenAI:
        # Criado sob demanda: sem chave, só a decomposição fica indisponível (não a API inteira).
        if self._client is None:
            try:
                self._client = openai.OpenAI(timeout=180.0)
            except openai.OpenAIError as exc:
                raise AIUnavailable(NOT_CONFIGURED) from exc
        return self._client

    def suggest(self, project: dict, feature: dict, parameters: dict) -> dict:
        extra: dict[str, Any] = {"reasoning": {"effort": self.effort}} if self.effort else {}
        try:
            response = self.client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=build_prompt(project, feature, catalog_for_prompt(parameters)),
                text_format=LLMDecomposition,
                max_output_tokens=32000,   # inclui os tokens de raciocínio
                store=False,
                **extra,
            )
        except openai.AuthenticationError as exc:
            raise AIUnavailable("Chave da OpenAI inválida: confira OPENAI_API_KEY no ambiente da API.") from exc
        except openai.APIStatusError as exc:
            if isinstance(exc, openai.RateLimitError) and exc.code != "insufficient_quota":
                raise AIUnavailable("Limite de uso da IA atingido; tente novamente em instantes.") from exc
            raise AIUnavailable(api_error_message(exc)) from exc
        except openai.APIConnectionError as exc:
            raise AIUnavailable("Não foi possível conectar ao serviço de IA.") from exc

        incomplete = getattr(getattr(response, "incomplete_details", None), "reason", None)
        if _refusal(response) or incomplete == "content_filter":
            raise AIRefused("A IA recusou esta solicitação; revise o texto da funcionalidade.")
        parsed = response.output_parsed
        if response.status == "incomplete" or parsed is None:
            raise AIUnavailable("A resposta da IA veio incompleta; tente decompor uma funcionalidade menor.")
        tasks, warnings = sanitize(parsed, parameters)
        return {"tasks": tasks, "open_questions": parsed.open_questions, "risks": parsed.risks,
                "assumptions": parsed.assumptions, "warnings": warnings, "model": response.model}


@lru_cache
def get_decomposer() -> Decomposer:
    """Dependência FastAPI (substituível nos testes)."""
    return OpenAIDecomposer()


def find_feature(content: dict[str, Any], feature_id: str) -> dict | None:
    return next((f for f in content.get("features", []) if f["id"] == feature_id), None)
