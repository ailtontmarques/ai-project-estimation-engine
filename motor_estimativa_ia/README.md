# Motor inicial de estimativa de esforço e custos com/sem IA

O motor de cálculo é escrito em Python puro, sem dependências externas. Em volta dele há uma API FastAPI com persistência em Postgres, que registra projetos, estimativas versionadas e a aprovação técnica. A autenticação é feita pelo UNE AI SSO.

## Conteúdo
- `engine.py`: motor determinístico de cálculo, só com a biblioteca padrão.
- `parameters.json`: taxas horárias, parâmetros PERT, premissas de IA e contingência. Serve de carga inicial do banco.
- `project_example.json`: projeto fictício dividido em funcionalidades, tarefas e atividades.
- `models.py`: contrato de dados (Pydantic) da entrada e da saída do motor.
- `schemas.py`: contratos HTTP de usuários, parâmetros, projetos e estimativas.
- `db.py`: tabelas (SQLAlchemy) e sessão com o banco.
- `services.py`: regras de fluxo e permissão, como versionamento, registro e aprovação.
- `api.py`: rotas HTTP (FastAPI).
- `migrations/`, `alembic.ini`: migrações do esquema (Alembic).
- `seed.py`: carga inicial do conjunto de parâmetros.
- `sso.py`: integração com o UNE AI SSO (proxy de sessão, validação do token, perfis).
- `ai.py`: decomposição assistida por IA (OpenAI), com saída estruturada validada contra os parâmetros.
- `scripts/sso_setup_dev.sh`, `scripts/sso_bootstrap.py`: bootstrap do domínio, do primeiro admin e das roles do app no SSO.
- `docker-compose.yml`, `docker/`: Postgres local, que lê as credenciais do `.env`.
- `.env.example`: modelo das variáveis de ambiente. O `.env` real não deve ser versionado.
- `tests/`: testes do motor, do contrato e da API, e de persistência.
- `requirements.txt`: dependências da API e da persistência.

## Requisitos
Python 3.10 ou superior.

## Executar o cálculo
Na pasta do projeto:

```bash
python engine.py
```

Ou informe arquivos e grave o resultado:

```bash
python engine.py --parameters parameters.json --project project_example.json --output resultado.json
```

## API HTTP e banco de dados
O motor também é exposto por uma API FastAPI (`api.py`), com persistência em Postgres. O motor continua sem dependências externas; a API e a persistência dependem de `requirements.txt`.

### Subir o ambiente local
1. Copie `.env.example` para `.env` e preencha as credenciais. Na `DATABASE_URL`, caracteres especiais da senha devem ser codificados (`@` vira `%40`).
2. Confirme que o UNE AI SSO está no ar (`curl http://localhost:4000/health`) e que o domínio do app existe (veja [Autenticação](#autenticação-une-ai-sso)).
3. Execute os comandos abaixo:

```bash
docker compose up -d --wait            # Postgres 16 + banco de testes <POSTGRES_DB>_test
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/alembic upgrade head          # cria o esquema
.venv/bin/python seed.py                # importa parameters.json como conjunto de parâmetros
.venv/bin/uvicorn api:app --reload
```

O `seed.py` pode ser executado mais de uma vez sem duplicar nada. Usuários e roles não são criados por ele: ficam no SSO.

A documentação interativa fica em `http://localhost:8000/docs`. Para usá-la autenticado:
1. Chame `POST /auth/login`.
2. Copie o `access_token`.
3. Cole o token no botão **Authorize**.

### Autenticação (UNE AI SSO)
A identificação e a autenticação são feitas pelo **UNE AI SSO** (`SSO_BASE_URL`). A base é a raiz do serviço; `/api` é só o Swagger UI dele. O app cuida apenas da **autorização**, ou seja, dos perfis.

- **Sessão:** `POST /auth/login`, `/auth/refresh` e `/auth/logout` repassam as chamadas ao SSO, sempre no domínio do app (`SSO_DOMAIN_SLUG`). O `domain_id` é resolvido pelo slug e enviado como `x-domain-id`.
- **Validação do Bearer:** as demais rotas exigem `Authorization: Bearer <access_token>`. O token é validado por **introspecção**, com `GET /users/me` no SSO, e guardado em cache por `SSO_CACHE_TTL_SECONDS`, nunca além do `exp` do token.
  - O app **não verifica a assinatura** do JWT. Isso exigiria guardar o segredo HS256 do SSO e não refletiria desativações nem trocas de roles.
  - Antes de chamar o SSO, o app recusa tokens malformados, vencidos ou de outro domínio, e também tokens com vida maior que `SSO_MAX_TOKEN_LIFETIME_SECONDS`. Esse último caso cobre o refresh token usado como Bearer.
- **Perfil:** vem do nome da role no domínio do SSO: `admin`, `tech_leader` ou `product_owner`. Com várias roles, vale a de maior precedência (admin > tech_leader > product_owner). Um usuário sem nenhuma dessas roles recebe **403**.
- **Espelho local:** no primeiro acesso validado, o usuário é gravado em `users` com `id` igual ao `sub` do SSO, nome e e-mail. Isso serve para os vínculos `created_by` e `approved_by`. O perfil não é gravado.
- **Indisponibilidade:** se o SSO estiver fora do ar ou responder 429, a API retorna **503** e nega o acesso.
- **Fora do MVP:** login com MFA (a conta recebe 403 com mensagem explicativa) e login com Google ou Microsoft.

**Bootstrap do domínio no SSO** (uma vez por ambiente), com o `scripts/sso_setup_dev.sh`:

```bash
# A senha precisa seguir a política do SSO: mínimo de 12 caracteres, com maiúscula, minúscula,
# número e um caractere especial entre @$!%*?&. Sem SSO_BOOTSTRAP_PASSWORD, ela é pedida no terminal.
SSO_BOOTSTRAP_PASSWORD='<senha forte>' scripts/sso_setup_dev.sh ailton.marques@une.cx "Nome Completo"
```

O script faz o seguinte:
1. Cria o domínio `SSO_DOMAIN_SLUG`.
2. Registra o primeiro usuário ou, se ele já existir, recupera o id.
3. Gera `scripts/out/sso_first_admin.sql`, que cria as roles `admin`, `tech_leader` e `product_owner` e atribui `admin` ao usuário.
4. Aplica o SQL no Postgres do SSO, se `SSO_DB_USER` e `SSO_DB_NAME` estiverem definidos. `SSO_DB_CONTAINER` tem como padrão `une-ai-sso-postgres`. Sem essas variáveis, o script só imprime o comando para você aplicar.
5. Faz login e confere as roles.

O SQL é necessário porque o SSO não tem seed, e criar ou atribuir roles pela API exige uma role com `domain.roles.write` e `user.roles.write` no próprio domínio, que ainda não existe nesse momento. Ele pode ser executado mais de uma vez sem duplicar nada.

Depois do bootstrap, o dia a dia é feito pela API do SSO, com o `scripts/sso_bootstrap.py`:

```bash
.venv/bin/python scripts/sso_bootstrap.py assign --email <admin> --user-id <id> --role tech_leader
.venv/bin/python scripts/sso_bootstrap.py check  --email <usuário>
```

### Rotas

| Método | Rota | Quem pode | Descrição |
|---|---|---|---|
| GET | `/health` | qualquer um | Status e `engine_version` |
| POST | `/auth/login` | qualquer um | Login com e-mail e senha no SSO; retorna `access_token` e `refresh_token` |
| POST | `/auth/refresh` | qualquer um | Renova o access token. O SSO rotaciona o refresh token, então o antigo deixa de valer |
| POST | `/auth/logout` | autenticado | Encerra a sessão no SSO e descarta o cache local do token |
| POST | `/estimate` | todos | Simulação sem registro; sem `parameters`, usa os vigentes |
| GET | `/users/me` | todos | Usuário autenticado, com perfil e roles |
| GET | `/parameter-sets` | todos | Versões de parâmetros, da vigência mais recente à mais antiga |
| GET | `/parameter-sets/current` | todos | Conjunto vigente (maior `effective_at` já alcançado) |
| POST | `/parameter-sets` | admin | Nova versão; `effective_at` futuro agenda a vigência |
| GET | `/projects` | todos | Painel: projetos com a última estimativa e a última aprovada |
| POST | `/projects` | todos | Cria projeto (`name`, `objective`, `content`) |
| GET / PATCH | `/projects/{id}` | todos | Consulta ou altera; mudar `content` gera nova `revision` |
| GET | `/projects/{id}/estimates` | todos | Versões da estimativa do projeto |
| POST | `/projects/{id}/estimates` | todos | Calcula e registra uma nova versão (rascunho) |
| GET | `/estimates/{id}` | todos | Estimativa com snapshot da entrada e resultado |
| POST | `/estimates/{id}/approve` | Tech Leader, admin | Aprovação técnica explícita |
| GET | `/estimates/{id}/reproduction` | todos | Recalcula o snapshot e confere se o resultado é o mesmo |
| POST | `/projects/{id}/features/{feature_id}/decomposition` | todos | Sugestão de tarefas e atividades por IA, sem salvar nada |
| GET | `/estimates/{id}/actuals` | todos | Horas realizadas registradas na estimativa |
| PUT | `/estimates/{id}/actuals` | Tech Leader, admin | Registra ou atualiza horas realizadas (só em estimativas aprovadas) |
| GET | `/calibration` | todos | Estimado × realizado por tipo de atividade e por modalidade de IA |

Códigos de erro:
- **401:** token ausente, inválido, vencido ou de outro domínio, ou credenciais inválidas.
- **403:** usuário sem role do app, conta com MFA, usuário desativado ou perfil sem permissão para a ação.
- **404:** registro não encontrado.
- **409:** conflito, por exemplo estimativa já aprovada, requisitos alterados desde a estimativa, versão de parâmetros duplicada ou nenhum conjunto vigente.
- **422:** dados inválidos ou regra do motor violada. Neste caso, a resposta traz a mensagem do motor.
- **503:** SSO indisponível, limite de requisições do SSO atingido, domínio do app não encontrado ou IA não configurada ou indisponível.

### Regras de persistência
- **Versão dos requisitos:** cada alteração em `content` incrementa `projects.revision`. Mudar só o nome ou o objetivo não conta como nova revisão.
- **Estimativa registrada:** guarda o snapshot exato da entrada do motor, o conjunto de parâmetros usado, `engine_version` e o resultado completo (RN-07).
- **Aprovação:** só vale para a estimativa calculada sobre a revisão atual dos requisitos. Se os requisitos mudaram, é preciso gerar uma nova estimativa.
- **Revisão técnica:** o Product Owner cadastra e edita funcionalidades (nome, descrição, critérios de aceite, complexidade), os dados do projeto e os custos adicionais.
  - Tarefas, atividades, atividades transversais e contingência só podem ser alteradas pelo Tech Leader ou pelo administrador. Uma tentativa do PO responde **403**.
  - O PO pode criar funcionalidades sem tarefas. Só pode remover uma funcionalidade se ela ainda não tiver tarefas.
- **Imutabilidade garantida por triggers no próprio banco, mesmo para acessos fora da API:**
  - um conjunto de parâmetros não pode ser alterado;
  - o cálculo de uma estimativa não pode ser alterado, nem em rascunho;
  - uma estimativa aprovada não pode ser alterada nem excluída.
- **Esquema:** é versionado por migrações Alembic (`migrations/`). Para alterar o esquema, crie uma nova migração com `alembic revision -m "..."`. Não edite a `0001`.

### Decomposição assistida por IA
`POST /projects/{id}/features/{feature_id}/decomposition` pede à OpenAI (Responses API, saída estruturada) uma proposta de tarefas e atividades para uma funcionalidade **salva** (Etapa 3 do plano).

- **O que a resposta traz:** tipo de atividade, horas otimista, mais provável e pessimista, modalidade de IA, alocação e justificativa de cada atividade, além de dúvidas em aberto, riscos e premissas.
- **Nada é salvo nem calculado (RN-01).** O Tech Leader revisa a sugestão, aplica no editor e salva. O motor só calcula depois disso.
- **Validação:** a resposta é conferida contra os parâmetros vigentes. Atividade com tipo desconhecido é descartada, modalidade incompatível vira "sem IA", horas fora de ordem são reordenadas e a alocação é normalizada para 100%. Cada ajuste aparece em `warnings`.
- **Configuração:**

  | Variável | Uso | Padrão |
  |---|---|---|
  | `OPENAI_API_KEY` | Chave da API da OpenAI | — |
  | `ESTIMATION_AI_MODEL` | Modelo usado | `gpt-5.5` |
  | `ESTIMATION_AI_EFFORT` | Esforço de raciocínio (`none`, `low`, `medium`, `high`…). Vazio = não envia, para modelos sem raciocínio. | `medium` |

  Sem credencial, só essa rota fica indisponível: ela responde 503 com a mensagem "IA não configurada".
- **Recusas e erros:** uma recusa do modelo vira 422; falta de créditos, chave inválida e limite de uso viram 503 com mensagem em português.
- **Custo:** **cada sugestão é uma chamada paga à API da OpenAI. As requisições usam `store: false`.**

### Horas realizadas e calibração
Em estimativas **aprovadas**, o Tech Leader ou o administrador registram as horas realizadas por atividade, com `PUT /estimates/{id}/actuals`.

- **Formato:** cada atividade tem um valor atual, que pode ser corrigido, e um campo `ai_used`, que diz se ela foi feita com IA.
- **Comparação:** `GET /calibration` compara as horas realizadas com o cenário que de fato aconteceu. Se a IA foi usada, a comparação é com as horas com IA; senão, com as horas sem IA. As duas são horas de atividade, sem contingência.
- **Relatório:** agrupa por tipo de atividade e pela modalidade de IA usada, com a razão realizado ÷ estimado e o erro percentual médio (MAPE).
- **Amostra pequena:** com menos de 10 atividades, o relatório marca `small_sample`. Nesse caso, os números servem para levantar hipóteses, não para recalibrar.
- **Ajustes:** um ajuste nos parâmetros é feito cadastrando uma nova versão. As estimativas antigas continuam reproduzíveis.

### Contrato de saída
A resposta de `/estimate` é tipada pelo modelo `EstimateResult` em `models.py`, que espelha exatamente o retorno do motor. Os modelos proíbem campos extras: se o motor ganhar ou perder um campo sem que o contrato seja atualizado, os testes falham e a API retorna 500, em vez de omitir o campo sem aviso.

O front-end (veja [Front-end](#front-end-repositório-separado)) gera os tipos TypeScript a partir deste OpenAPI com `npm run gen:api`. Esse comando chama o `scripts/export_openapi.py`, que exporta o OpenAPI sem precisar subir o servidor, e em seguida roda o `openapi-typescript`.

## Front-end (repositório separado)
A interface web (Next.js) fica no repositório [ai-project-estimation-frontend](https://github.com/ailton-marques-unite/ai-project-estimation-frontend), não neste. Clone-o dentro da raiz deste repositório, na pasta `frontend/`, que já está no `.gitignore`:

```bash
# na raiz de ai-project-estimation-engine
git clone git@github.com:ailton-marques-unite/ai-project-estimation-frontend.git frontend
```

O `npm run gen:api` do front-end chama `../motor_estimativa_ia/.venv/bin/python`, então ele precisa estar nessa posição, lado a lado com `motor_estimativa_ia/`. Commits e PRs do front-end são feitos no repositório dele.

## Executar os testes

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Os testes de persistência usam o banco definido em `DATABASE_URL_TEST`. A cada execução, eles recriam o esquema aplicando as migrações para trás e para frente, e limpam as tabelas entre um teste e outro.

A autenticação é testada com um SSO falso em memória (`tests/fake_sso.py`). Ele imita as rotas, os cabeçalhos de domínio e os tokens do UNE AI SSO e é ligado ao cliente real por `httpx.MockTransport`.

Há também um teste de integração com o SSO real, que é pulado a menos que `SSO_IT_EMAIL` e `SSO_IT_PASSWORD` estejam definidos. O usuário informado precisa ter uma role do app no domínio.

Se o banco ou as dependências não estiverem disponíveis, esses testes são pulados e os testes do motor rodam normalmente.

## Como o cálculo funciona

### Estimativa base (sem IA)
Para cada atividade, usando horas otimistas (O), mais prováveis (M) e pessimistas (P):

`H_base = (O + 4*M + P) / 6`

Os pesos são configuráveis em `parameters.json`.

### Cenário com IA
`H_AI = H_base * (1 - a*r) + H_base*v + H_base*t`

Onde:
- `a`: fração do trabalho elegível para assistência de IA;
- `r`: redução estimada na fração elegível;
- `v`: horas de revisão por hora-base;
- `t`: horas de retrabalho por hora-base.

A IA é escolhida **por atividade**, por meio de `ai_modality`. As modalidades ficam em `parameters.json` → `ai.modalities`:

| Modalidade | Tipos de atividade aplicáveis |
|---|---|
| `geracao_codigo` | implementacao, integracao, interface |
| `vibe_coding` | interface |
| `qa_assistido` | testes |
| `devsecops_assistido` | infraestrutura, seguranca |

- Cada modalidade define `a`, `r`, `v` e `t`, além de `validation_status` e `source`. Os valores iniciais são hipóteses.
- Uma atividade sem `ai_modality` não usa IA.
- Uma modalidade aplicada a um tipo de atividade incompatível é rejeitada.
- Os fatores da modalidade podem ser sobrescritos por atividade com um objeto `ai`, mas só quando há modalidade definida.
- Cada atividade usa no máximo uma modalidade, porque os ganhos de ferramentas diferentes se sobrepõem e não devem ser somados.

A economia pode ser negativa: o modelo não presume que IA sempre reduz esforço.

Revisão e retrabalho são proporcionais às horas-base e só se aplicam quando a IA é usada na atividade. Com `eligible_share = 0`, a atividade não usa IA e `H_AI = H_base`.

### Incerteza e contingência
- A faixa de incerteza é a soma de `P - O` das atividades (`uncertainty_range_hours`). É um indicador simples, não um intervalo estatístico.
- A contingência é calculada em horas e em custo, separada do subtotal: `base_hours` + `base_contingency_hours` = `base_total_hours`.

### Custos
Cada atividade distribui 100% das horas entre papéis e senioridades. O custo de mão de obra é a soma de `horas alocadas * taxa horária`. As taxas são hipóteses ilustrativas, não referências de mercado.

Os custos representam **custo interno**, porque a ferramenta é de planejamento interno (`cost_basis: internal`). O papel `product_owner` existe nos parâmetros com taxa inicial zero: suas horas aparecem na estimativa, mas sem custo.

- Sem IA: mão de obra + contingência + custos adicionais do cenário sem IA.
- Com IA: mão de obra + contingência + custos adicionais do cenário com IA.

A contingência incide sobre a mão de obra, é mostrada separadamente e não representa uma previsão estatística.

### Custos adicionais
Os tipos de custo ficam em `parameters.json` → `cost_types`: `infraestrutura`, `licencas`, `servicos_externos` e `ferramentas_ia`. Cada tipo define em qual cenário entra (`applies_to`):
- `both`: nos dois cenários;
- `base`: só no cenário sem IA;
- `ai`: só no cenário com IA.

Os valores são lançados no projeto, em `cost_items`:

```json
{"id": "C01", "description": "Hospedagem", "cost_type": "infraestrutura", "amount": 400}
```

O cenário padrão do tipo pode ser sobrescrito no item com `applies_to`.

Custo não informado nunca é tratado como zero. O tipo vai para `assumptions.uncounted_costs` em dois casos:
- o item tem `amount: null`, porque o valor ainda vai ser confirmado;
- nenhum item foi declarado para aquele tipo.

Para declarar que um tipo de custo não existe no projeto, lance um item com `amount: 0`. Tipos exclusivos do cenário com IA não geram alerta quando nenhuma atividade usa IA.

### Rastreabilidade dos parâmetros
O resultado registra `engine_version` e `parameters_version` para que cada cálculo possa ser reproduzido.

Cada parâmetro declara sua origem e seu estado de validação: `hipotese`, `em_validacao` ou `validado`.
- Para `pert`, `roles` e `contingency_rate_default`, isso fica em `parameters.json` → `provenance`.
- Cada modalidade de IA declara o seu dentro dela mesma.

O resultado expõe essas informações em `assumptions.parameter_provenance`. Os parâmetros não validados aparecem em `assumptions.unvalidated_parameters`, que é a lista de alertas do relatório. Quando o projeto informa a própria `contingency_rate`, o padrão dos parâmetros não entra nessa lista (`contingency_source: project`).

## Estrutura dos dados
Cada funcionalidade contém tarefas, e cada tarefa contém atividades. Cada atividade tem:
- `activity_type` (obrigatório), que precisa existir em `parameters.json` → `activity_types`;
- horas otimistas, mais prováveis e pessimistas;
- alocação por papel e senioridade, com frações que somam 1.0;
- opcionalmente, `ai_modality` e um objeto `ai` com fatores específicos.

Papéis e senioridades devem existir em `parameters.json`.

### Atividades transversais
Trabalho compartilhado pelo projeto (arquitetura, CI/CD, ambientes, observabilidade) fica em `transversal_tasks`, no nível do projeto, e não dentro das funcionalidades:

`H_projeto = Σ H_funcionalidades + H_transversal + H_contingência`

- Toda atividade transversal tem uma `scope_key` única.
- Uma atividade de funcionalidade que use uma `scope_key` transversal é rejeitada, para que nada seja contado duas vezes.

O resultado traz as horas separadas em `hours_by_scope`, `hours_by_activity_type` e `hours_by_ai_modality`.

## Limitações intencionais desta primeira versão
- Login com MFA e com Google ou Microsoft ainda não é suportado.
- A calibração não altera os parâmetros sozinha. Ela mostra os desvios, e um administrador decide e cadastra uma nova versão.
- Os parâmetros são ilustrativos e devem ser calibrados com especialistas antes de uso comercial.
- A IA só **sugere** a decomposição. Horas e custos vêm sempre do motor, sobre o escopo revisado e salvo.
- A comparação é um cenário de planejamento, não uma garantia de produtividade ou economia.
- Os custos adicionais são valores fixos por projeto. Não há rateio por funcionalidade nem custo por uso, como tokens de API.
