# Especificação funcional do MVP

## Estimador de esforço e custos de desenvolvimento de software com IA

MVP — versão 1.0

Product Owner + Tech Leader

Estimativa paramétrica

O produto será uma aplicação web para estimar horas de trabalho, composição da equipe e custos de desenvolvimento de software, tanto por funcionalidade quanto por projeto completo, considerando atividades executadas com e sem assistência de IA generativa e vibe coding.

O sistema começará com parâmetros configuráveis, sem depender de histórico de projetos. As estimativas serão transparentes, revisáveis e acompanhadas das premissas que as originaram.

## 1. Objetivo e escopo do produto

### 1.1 Objetivo principal

Permitir que Product Owners e Tech Leaders respondam, antes de iniciar o desenvolvimento:

- Quantas horas de trabalho serão necessárias?
- Quanto custará o desenvolvimento?
- Como distribuir o esforço entre desenvolvimento, QA e DevSecOps?
- Qual será a composição por senioridade: júnior, pleno e sênior?
- Quanto poderá mudar a estimativa com o uso de IA?
- Quais premissas e riscos podem afetar o resultado?

### 1.2 Escopo funcional

### 01

Cadastro do projeto

Nome, objetivo, tecnologias, premissas, moeda e parâmetros de custo.

### 02

Cadastro de funcionalidades

Descrição, critérios de aceite, complexidade, integrações e dependências.

### 03

Decomposição assistida por IA

Sugestão de tarefas e atividades por papel, sujeita à revisão humana.

### 04

Motor de estimativa

Cálculo de horas por atividade, senioridade, papel e cenário.

### 05

Composição de custos

Aplicação de taxas horárias por perfil e custo adicional opcional.

### 06

Consolidação do projeto

Soma das funcionalidades, atividades transversais e contingências.

### 07

Relatório gerencial

Estimativa-base, intervalos, custos, premissas, riscos e comparação de cenários.

### 08

Parâmetros administrativos

Manutenção de fatores, taxas horárias e regras de cálculo.

### 1.3 O que não entra na primeira versão

- Integração automática com Jira, Azure DevOps ou GitHub.
- Cronometragem automática de horas trabalhadas.
- Treinamento de modelos próprios de machine learning.
- Previsão automática de datas de entrega com base em velocidade histórica.
- Benchmark de produtividade entre profissionais.
- Garantia de economia de horas por utilizar IA.

Esses recursos poderão ser avaliados após a validação do modelo básico.

## 2. Perfis de usuário e permissões

| Funcionalidade                      | Product Owner | Tech Leader        | Administrador         |
| ----------------------------------- | ------------- | ------------------ | --------------------- |
| Criar projeto                       | Sim           | Sim                | Sim                   |
| Cadastrar funcionalidades           | Sim           | Sim                | Sim                   |
| Solicitar decomposição por IA       | Sim           | Sim                | Sim                   |
| Revisar tarefas técnicas            | Visualizar    | Editar e aprovar   | Sim                   |
| Alterar parâmetros técnicos         | Consultar     | Conforme permissão | Sim                   |
| Consultar custos e horas            | Sim           | Sim                | Sim                   |
| Aprovar estimativa técnica          | Não           | Sim                | Conforme configuração |
| Administrar taxas e fatores globais | Não           | Não                | Sim                   |
| Consultar histórico de versões      | Sim           | Sim                | Sim                   |

A aprovação técnica deve ser explícita. Uma estimativa gerada pela IA não será considerada aprovada automaticamente.

## 3. Regras de negócio

Estas são as regras que devem orientar a implementação, independentemente da tecnologia escolhida.

RN-01 — Separação entre IA e cálculo

A IA interpreta os requisitos e sugere tarefas. O motor determinístico calcula horas e custos a partir dos parâmetros vigentes.

RN-02 — Estimativa por atividade

Cada tarefa deve ser decomposta, quando aplicável, em implementação, revisão, integração, testes, segurança e outras atividades pertinentes. A estimativa é calculada por atividade, não por um único multiplicador de complexidade aplicado ao projeto inteiro.

RN-03 — Papéis e senioridades

Os papéis iniciais serão desenvolvimento, QA e DevSecOps. Cada atividade será distribuída entre júnior, pleno e sênior por percentuais configuráveis, cuja soma deve ser 100% quando houver alocação por senioridade.

RN-04 — Uso de IA

O sistema deve permitir cenários sem IA e com modalidades de IA selecionadas por atividade. Os fatores de produtividade serão configuráveis e identificados como hipóteses até serem validados.

RN-05 — Escopo comparável

A comparação entre cenários deve utilizar o mesmo escopo, os mesmos critérios de aceite e o mesmo padrão de qualidade. A IA não pode gerar economia simplesmente omitindo atividades.

RN-06 — Cálculo de custos

O custo de mão de obra será calculado por horas estimadas multiplicadas pelas taxas horárias configuradas. Custos de infraestrutura, licenças, APIs de IA e outros itens serão discriminados separadamente.

RN-07 — Versionamento

Toda estimativa aprovada deve preservar a versão dos requisitos, os parâmetros, as taxas horárias, os fatores de IA e a versão do motor de cálculo utilizados.

RN-08 — Incerteza e contingência

A estimativa deve apresentar uma faixa de esforço e explicitar as premissas. A contingência será configurável, aplicada de forma identificável e nunca escondida dentro das horas-base.

## 4. Telas do aplicativo

A navegação deve ser simples, orientada ao fluxo de estimativa, e compartilhada pelos dois perfis de usuário.

## Tela 1 — Painel de projetos

Obrigatória

### Meus projetos

Projetos ativos

# 03

Estimativas pendentes

# 05

Portal de clientes

12 funcionalidades · Em revisão técnica

Estimada: 240 h

Rascunho

Automação de pedidos

8 funcionalidades · Aprovado

Estimativa-base: 156 h

&#x20;Novo projeto

Os dados exibidos são exemplos fictícios de interface.

## Tela 2 — Cadastro do projeto

Obrigatória

Informações gerais

Nome do projeto

Portal de clientes

Objetivo de negócio

Permitir que clientes consultem pedidos e atualizem seus dados.

Front-end

React

Back-end

Node.js

Moeda

BRL — Real brasileiro

As tecnologias são exemplos. O formulário real permitirá selecionar tecnologias, restrições e premissas.

## Tela 3 — Cadastro de funcionalidade

Obrigatória

Nome da funcionalidade

Consultar pedidos

Descrição e critérios de aceite

O cliente autenticado pode consultar seus pedidos, visualizar status e acessar detalhes.

Critério: mostrar apenas pedidos associados ao cliente autenticado.

Complexidade preliminar

Baixa

Média — selecionada

Alta

Assistência por IA

Geração de código

Vibe coding

QA assistido

Análise assistida por IA

Identificar tarefas, dependências, riscos e dúvidas sobre o escopo. A estimativa só será calculada após a revisão das informações necessárias.

## Tela 4 — Revisão técnica

Obrigatória

Decomposição sugerida

Implementar API de consulta

Desenvolvimento

12 h

Criar interface e estados de tela

Desenvolvimento

10 h

Testar regras de acesso

QA

6 h

Revisar autorização e logs

DevSecOps

4 h

Total preliminar

## 32 h

Exemplo fictício. Os tempos devem ser definidos pelo motor de estimativa, não gerados como fatos pela IA.

## Tela 5 — Resultado e comparação

Obrigatória

Esforço-base

# 32 h

Custo-base

# R$ 3.200

### Distribuição por papel

Esforço por papel

Exemplo ilustrativo de distribuição de horas.

0 h3,75 h7,5 h11,25 h15 hDesenvolvimentoQADevSecOps

### Premissas e alertas

• A taxa horária deve corresponder à composição de equipe definida.

• O custo não inclui infraestrutura ou licenças, salvo se adicionadas.

• Os parâmetros de produtividade ainda não foram calibrados com dados reais.

## Tela 6 — Administração de parâmetros

O administrador poderá configurar:

- Taxas horárias por papel e senioridade.
- Esforços de referência por tipo de atividade.
- Fatores de complexidade e incerteza.
- Reduções de esforço e custos adicionais de IA.
- Percentuais de alocação por senioridade.
- Contingência e regras de arredondamento.
- Versões dos parâmetros e data de vigência.

## 5. Modelo de dados

Sugiro um banco relacional, como PostgreSQL. O modelo abaixo representa as entidades centrais e pode ser implementado sem exigir uma arquitetura excessiva.

```bash
erDiagram
    USER ||--o{ PROJECT : manages
    PROJECT ||--o{ FEATURE : contains
    PROJECT ||--o{ ESTIMATE : has
    FEATURE ||--o{ TASK : decomposes_into
    TASK ||--o{ ACTIVITY_ESTIMATE : estimates
    ESTIMATE ||--o{ ACTIVITY_ESTIMATE : snapshots
    ACTIVITY_ESTIMATE ||--o{ ROLE_ALLOCATION : distributes
    ROLE ||--o{ ROLE_ALLOCATION : assigned
    SENIORITY ||--o{ ROLE_ALLOCATION : classified
    ACTIVITY_TYPE ||--o{ ACTIVITY_ESTIMATE : categorizes
    ESTIMATE ||--o{ ESTIMATE_COST : calculates
    PARAMETER_SET ||--o{ ESTIMATE : uses
    PROJECT ||--o{ PROJECT_COST_ITEM : includes
    USER ||--o{ ESTIMATE : approves

    USER {
        uuid id PK
        string name
        string email
        string profile
    }
    PROJECT {
        uuid id PK
        string name
        string objective
        string status
        string currency
        datetime created_at
    }
    FEATURE {
        uuid id PK
        uuid project_id FK
        string name
        text description
        text acceptance_criteria
        string complexity
        string status
    }
    TASK {
        uuid id PK
        uuid feature_id FK
        string name
        text description
        string role_hint
        string status
    }
    ACTIVITY_ESTIMATE {
        uuid id PK
        uuid estimate_id FK
        uuid task_id FK
        string activity_type
        decimal base_hours
        decimal ai_reduction
        decimal review_hours
        decimal rework_hours
    }
    ROLE_ALLOCATION {
        uuid id PK
        uuid activity_estimate_id FK
        uuid role_id FK
        uuid seniority_id FK
        decimal allocation_pct
        decimal hourly_rate
        decimal hours
    }
    ROLE {
        uuid id PK
        string name
    }
    SENIORITY {
        uuid id PK
        string name
    }
    ACTIVITY_TYPE {
        uuid id PK
        string name
    }
    ESTIMATE {
        uuid id PK
        uuid project_id FK
        uuid parameter_set_id FK
        int version
        string scenario
        decimal total_hours
        decimal total_cost
        string status
        datetime approved_at
    }
    ESTIMATE_COST {
        uuid id PK
        uuid estimate_id FK
        string cost_type
        decimal amount
    }
    PROJECT_COST_ITEM {
        uuid id PK
        uuid project_id FK
        string description
        string cost_type
        decimal amount
    }
    PARAMETER_SET {
        uuid id PK
        string name
        int version
        json parameters
        datetime effective_at
    }

```

### 5.1 Regras importantes do modelo

- PROJECT: representa o projeto como um todo.
- FEATURE: representa uma funcionalidade ou história de usuário.
- TASK: representa uma tarefa técnica decorrente da decomposição.
- ACTIVITY_ESTIMATE: guarda a estimativa de esforço para uma atividade específica dentro de uma versão da estimativa.
- ROLE_ALLOCATION: distribui as horas entre papel e senioridade e guarda a taxa horária aplicada.
- PARAMETER_SET: preserva os parâmetros utilizados em cada cálculo.
- ESTIMATE_COST: guarda custos calculados e outros custos associados à versão da estimativa.

Os nomes de papéis, tipos de atividade e senioridades devem ser tabelas de referência, e não valores fixos dispersos no código.

Também recomendo que as estimativas aprovadas sejam imutáveis. Uma alteração nos requisitos ou parâmetros gera uma nova versão, mantendo a trilha de auditoria.

## 6. Motor de cálculo

Este é o núcleo do produto. Recomendo que seja implementado como um serviço independente da IA, com fórmulas explícitas, testes automatizados e versionamento.

### 6.1 Etapa A — Estimativa-base por atividade

Para cada atividade, o sistema registra três valores:

- \\(O\\): estimativa otimista.
- \\(M\\): estimativa mais provável.
- \\(P\\): estimativa pessimista.

O MVP pode usar a técnica PERT como ponto de partida:

\\[ H\_{base}=\frac{O+4M+P}{6} \\]

A amplitude \\(P-O\\) também será apresentada como indicador simples de incerteza. Essa amplitude não é, por si só, um intervalo estatístico de confiança.

Exemplo:

| Parâmetro       | Horas  |
| --------------- | ------ |
| Otimista        | 6      |
| Mais provável   | 8      |
| Pessimista      | 14     |
| Estimativa PERT | 8,67 h |

A complexidade baixa, média ou alta pode servir para sugerir valores iniciais, mas não deve substituir a análise das atividades e do escopo.

### 6.2 Etapa B — Distribuição por papel e senioridade

Depois de estimar as horas da atividade, o sistema aplica os percentuais de alocação.

\\[ H\_{r,s}=H\_{base}\times A\_{r,s} \\]

Onde:

- \\(H\_{r,s}\\) é o esforço alocado ao papel \\(r\\) e senioridade \\(s\\).
- \\(A\_{r,s}\\) é o percentual de alocação correspondente.

A soma de todos os percentuais da atividade deve ser 100%.

Exemplo: uma atividade de 20 horas pode ser distribuída em 20% para júnior, 50% para pleno e 30% para sênior. Isso resulta em 4 h, 10 h e 6 h, respectivamente.

Essa distribuição não significa que os três profissionais necessariamente trabalharão em paralelo; ela representa a composição do esforço estimado.

### 6.3 Etapa C — Cálculo do custo de mão de obra

\\[ C\_{base}=\sum\_{r,s}H\_{r,s}\times T\_{r,s} \\]

Onde \\(T\_{r,s}\\) é a taxa horária configurada para aquele papel e senioridade.

O sistema deve permitir taxas diferentes para, por exemplo, um desenvolvedor sênior e um profissional DevSecOps sênior.

É importante distinguir:

- Custo interno: custo-hora da equipe, se conhecido.
- Custo comercial: valor-hora de venda, se utilizado para orçamentos.
- Custos adicionais: licenças, APIs de IA, infraestrutura e serviços externos.

Essas categorias não devem ser misturadas, pois respondem a decisões diferentes.

### 6.4 Etapa D — Estimativa com IA

A redução de esforço deve ser aplicada apenas à parcela da atividade que pode efetivamente se beneficiar da IA.

\\[ H\_{IA}=H\_{base}(1-r)+H\_{rev}+H\_{retr} \\]

Onde:

- \\(r\\): redução estimada de esforço na parcela assistida.
- \\(H\_{rev}\\): horas adicionais de revisão humana.
- \\(H\_{retr}\\): horas adicionais de retrabalho.

Para atividades parcialmente assistidas, o cálculo será:

\\[ H\_{IA}=H\_{base}(1-a r)+H\_{rev}+H\_{retr} \\]

Em que \\(a\\) é a fração do esforço considerada elegível para aceleração por IA, entre 0 e 1.

Exemplo didático: uma atividade exige 20 h sem IA; 70% do esforço é elegível para assistência; o fator hipotético de redução é 30%; revisão e retrabalho adicionais totalizam 3 h.

\\[ H\_{IA}=20(1-0{,}7\times0{,}3)+3 \\]

\\[ H\_{IA}=18{,}8\text{ h} \\]

A economia líquida é de 1,2 h, ou 6%. Embora o fator de redução aplicado à parcela elegível seja de 30%, a economia efetiva da atividade é menor porque nem todo o esforço é acelerado e existem custos adicionais de revisão.

Esse exemplo demonstra por que o aplicativo não deve apresentar o percentual de aceleração de uma ferramenta como se fosse a economia total do projeto.

### 6.5 Etapa E — Custos no cenário com IA

O custo total deve considerar:

\\[ C\_{IA}=C\_{\text{mão de obra IA}}+C\_{\text{ferramentas}}+C\_{\text{infraestrutura}} \\]

Os custos adicionais devem ser incluídos somente quando forem conhecidos ou configurados. Se não forem informados, o sistema deverá identificá-los como não contabilizados, e não presumir que sejam zero.

### 6.6 Etapa F — Consolidação do projeto

O esforço total do projeto será:

\\[ H\_{projeto}=\sum H\_{funcionalidades}+ H\_{transversal}+H\_{contingência} \\]

As atividades transversais podem incluir arquitetura compartilhada, configuração inicial do ambiente, pipeline de CI/CD, observabilidade e preparação de ambientes.

A regra essencial é evitar duplicidade: se o pipeline já foi estimado como atividade transversal, ele não poderá ser novamente contabilizado integralmente em cada funcionalidade.

A contingência será apresentada separadamente:

\\[ H\_{contingência}=H\_{subtotal}\times p \\]

Em que \\(p\\) é o percentual configurado. O subtotal e o percentual aplicado devem continuar visíveis no relatório.

### 6.7 Etapa G — Economia comparativa

O sistema calculará separadamente economia de esforço e economia de custo:

\\[ E_H=\frac{H\_{semIA}-H\_{comIA}}{H\_{semIA}}\times100 \\]

\\[ E_C=\frac{C\_{semIA}-C\_{comIA}}{C\_{semIA}}\times100 \\]

O resultado poderá ser negativo, indicando aumento de esforço ou custo. O sistema não deve limitar artificialmente o resultado a uma economia positiva.

A comparação deverá manter escopo, qualidade, premissas e critérios de aceite equivalentes.

## 7. Parâmetros iniciais configuráveis

Como não há histórico confiável, os valores iniciais serão hipóteses de trabalho, não benchmarks de mercado.

| Parâmetro                 | Configuração inicial                                          |
| ------------------------- | ------------------------------------------------------------- |
| Papéis                    | Desenvolvimento, QA, DevSecOps                                |
| Senioridades              | Júnior, pleno, sênior                                         |
| Complexidade              | Baixa, média, alta                                            |
| Estimativa                | Otimista, mais provável, pessimista                           |
| Taxas horárias            | Informadas pelo usuário                                       |
| Elegibilidade para IA     | Percentual por atividade                                      |
| Redução de esforço por IA | Percentual configurável por atividade e modalidade            |
| Revisão e retrabalho      | Horas adicionais ou fatores configuráveis                     |
| Contingência              | Percentual configurável                                       |
| Custos adicionais         | Valores informados ou itens não contabilizados explicitamente |

Eu não fixaria os fatores de produtividade da resposta original como padrão universal. O administrador poderá cadastrar valores iniciais provisórios, mas o sistema deverá mostrar a origem e o estado de validação de cada parâmetro.

## 8. Critérios de aceite do MVP

A versão estará funcionalmente pronta para um piloto quando atender aos seguintes critérios:

### Checklist de aceite

0 de 10

Cadastrar projetos e funcionalidades com critérios de aceite.

Decompor requisitos com IA e permitir revisão manual.

Calcular horas por atividade, papel e senioridade.

Calcular custos com taxas horárias configuráveis.

Comparar cenários com e sem IA.

Incluir revisão, retrabalho e custos adicionais explicitamente.

Consolidar o projeto sem duplicar atividades transversais.

Preservar versões de requisitos, parâmetros e estimativas aprovadas.

Exibir premissas, incertezas e parâmetros ainda não validados.

Exportar um relatório gerencial de estimativas e custos.

Além desses critérios funcionais, os testes automatizados devem confirmar que os cálculos reproduzem os resultados esperados, que as alocações totalizam 100%, que os valores negativos ou inválidos são rejeitados e que versões antigas continuam reproduzíveis.

## 9. Arquitetura de implementação recomendada

Para manter o MVP simples, eu adotaria uma arquitetura modular, com separação entre interface, lógica de negócio e serviço de IA.

```bash
flowchart TB
    PO["Product Owner"]
    TL["Tech Leader"]
    UI["Aplicação Web"]
    API["API de aplicação"]
    REQ["Módulo de requisitos"]
    AI["Serviço de IA"]
    ENG["Motor determinístico de estimativa"]
    COST["Módulo de custos"]
    DB[("PostgreSQL")]
    REP["Relatórios e exportação"]

    PO --> UI
    TL --> UI
    UI --> API
    API --> REQ
    REQ <--> AI
    API --> ENG
    ENG --> COST
    REQ --> DB
    ENG --> DB
    COST --> DB
    DB --> REP
    REP --> UI

```

### Tecnologias sugeridas

| Camada             | Opção para o MVP                                  |
| ------------------ | ------------------------------------------------- |
| Front-end          | Next.js com React e TypeScript                    |
| Back-end           | API em Python com FastAPI                         |
| Banco de dados     | PostgreSQL                                        |
| IA generativa      | Provedor de modelo via API, com saída estruturada |
| Validação de dados | Pydantic no back-end                              |
| Gráficos           | Biblioteca de visualização compatível com React   |
| Testes             | Pytest para cálculo e testes de interface         |
| Implantação        | Serviço de hospedagem gerenciada                  |

Essa é uma proposta inicial, não uma exigência tecnológica. O motor de estimativa deve poder ser testado e utilizado sem depender de chamadas ao modelo de IA.

## 10. Plano de desenvolvimento

Eu dividiria o trabalho em quatro etapas, com entregas verificáveis em vez de definir um prazo sem conhecer a equipe e as tecnologias disponíveis.

1. Etapa 1 — Motor de cálculo

   Implementar fórmulas, parâmetros, taxas horárias, alocação de equipe, custos e testes unitários. Validar os resultados com exemplos controlados.
2. Etapa 2 — Projetos e funcionalidades

   Implementar cadastro, decomposição manual, tarefas, atividades e consolidação do esforço.
3. Etapa 3 — Assistência por IA

   Integrar a interpretação de requisitos, a sugestão de tarefas e a identificação de dúvidas e riscos, sempre com possibilidade de revisão humana.
4. Etapa 4 — Dashboard e piloto

   Implementar comparação de cenários, relatórios, versionamento e validação com funcionalidades reais.

## 11. Recomendação final

O ponto mais importante desta especificação é manter três conceitos separados:

1. Estimativa de esforço: quantas horas de trabalho são necessárias.
2. Estimativa de custo: quanto essas horas e os recursos adicionais custam.
3. Impacto da IA: quanto o esforço e o custo podem mudar, considerando os ganhos e os trabalhos adicionais.

Com essa separação, o aplicativo poderá começar com regras configuráveis e evoluir para um estimador calibrado por dados reais, sem precisar ser reconstruído.

O próximo passo recomendado é implementar primeiro o motor de cálculo e sua tabela de parâmetros. Antes de investir na interface ou na integração com IA, precisamos conseguir demonstrar que uma mesma entrada, com os mesmos parâmetros e a mesma versão do motor, sempre produz os mesmos resultados. Essa será a fundação técnica e gerencial do produto.

Existem três opções:

| Abordagem                   | Vantagens                                                            | Limitações                                                          |
| --------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Python + parâmetros em JSON | Simples, rápido, ótimo para validar fórmulas                         | Persistência e edição dos parâmetros exigem implementação adicional |
| SQLite                      | Banco local, consultas SQL e persistência                            | Menos adequado para acesso concorrente em uma aplicação corporativa |
| PostgreSQL                  | Multiusuário, controle de acesso, histórico e integridade relacional | Exige configuração e administração adicionais                       |

## Minha recomendação: começar com Python + JSON

Podemos construir o primeiro protótipo com quatro componentes:

Tabela de parâmetros — JSON

Taxas horárias, atividades, fatores de complexidade, IA e contingência

Motor de cálculo — Python

PERT, alocação por senioridade, custos e cenários

Testes automatizados

Reproduzibilidade, validação das fórmulas e tratamento de erros

Resultado da estimativa

Horas por papel, senioridade e atividade; custos e comparação de cenários

O arquivo JSON seria a fonte inicial dos parâmetros, com uma versão identificada. O motor não dependeria de IA nem de conexão com banco de dados para calcular.

### Quando migrar para PostgreSQL?

Quando precisarmos de cadastro simultâneo de usuários, vários projetos persistidos, histórico de estimativas, aprovação pelo Tech Leader, controle de permissões e auditoria, o PostgreSQL passa a fazer sentido.

Se separarmos desde o início a lógica de cálculo do armazenamento dos dados, a migração será muito mais simples.

Minha sugestão para o próximo passo: construir um primeiro motor em Python com:

- Arquivo de parâmetros JSON editável.
- Fórmulas de estimativa e cálculo de custos.
- Comparação entre cenário sem IA e com IA.
- Um projeto de exemplo com funcionalidades, tarefas e atividades.
- Testes automatizados para verificar os resultados.

Assim, validamos primeiro a lógica econômica do produto, antes de investir na infraestrutura.