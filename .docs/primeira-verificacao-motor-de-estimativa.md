# Motor de estimativa em Python, sem banco de dados e sem dependências externas. 

A ideia é termos uma base que possamos testar, revisar e evoluir antes de construir a interface do produto.

---

## 1. Baixe o projeto

Motor de estimativa com IA — versão 0.1

Pacote ZIP com código Python, parâmetros, projeto de exemplo, documentação e testes.

Baixar o projeto completo (.zip)

## 2. O que já está implementado

Parâmetros editáveis

O arquivo `parameters.json` contém taxas horárias por papel e senioridade, pesos PERT, premissas de uso de IA e contingência.

Cálculo de esforço e custo

O motor estima horas por atividade, distribui o esforço entre os profissionais e calcula custos de mão de obra.

Comparação com e sem IA

Calcula a redução estimada de esforço, inclui revisão e retrabalho e considera um custo de ferramentas de IA.

Projeto de exemplo

Um portal de solicitações internas, dividido em funcionalidades, tarefas e atividades de desenvolvimento, QA e DevSecOps.

Testes automatizados

Os sete testes passaram, cobrindo a fórmula PERT, validação de alocações, premissas de IA e consistência dos custos.

## 3. Como executar no seu computador

Você precisará do Python 3.10 ou superior. Depois de extrair o ZIP, abra o terminal na pasta do projeto.

Executar a estimativa:

```
python engine.py
```

Salvar o resultado em um arquivo JSON:

```
python engine.py --output resultado.json
```

Executar os testes automatizados:

```
python -m unittest discover -s tests -v
```

O resultado da estimativa será apresentado em JSON, contendo o resumo geral, as horas por atividade, os custos e a comparação entre os cenários.

## 4. A lógica de cálculo utilizada

A estimativa de cada atividade usa três valores:

- O: horas otimistas.
- M: horas mais prováveis.
- P: horas pessimistas.

A estimativa-base segue a fórmula PERT:

\\[ H\_{\text{base}}=\frac{O+4M+P}{6} \\]

O cenário com IA considera a parcela do trabalho elegível para assistência, a redução estimada nessa parcela, o tempo de revisão e o retrabalho:

\\[ H\_{\text{IA}}=H\_{\text{base}}(1-a r)+H\_{\text{base}}v+H\_{\text{base}}t \\]

Em que \\(a\\) representa a parcela elegível, \\(r\\) a redução estimada, \\(v\\) a proporção de esforço para revisão e \\(t\\) a proporção para retrabalho.

Importante: os valores incluídos são hipóteses iniciais para demonstração, não dados de mercado nem ganhos de produtividade comprovados. O motor permite inclusive que o cenário com IA tenha um custo ou esforço maior.

## 5. Minha recomendação para a próxima etapa

Eu seguiria nesta ordem:

1. Validar as regras de negócio: confirmar como estimar, distribuir horas e calcular custos.
2. Revisar os parâmetros: ajustar papéis, senioridades, taxas e premissas de IA à realidade que o produto pretende representar.
3. Ampliar os testes: incluir cenários extremos, atividades não elegíveis para IA e casos em que o uso de IA aumenta o esforço.
4. Construir a interface: permitir que Product Owners e Tech Leaders cadastrem funcionalidades e atividades sem editar arquivos JSON manualmente.

A distinção que eu manteria como princípio arquitetural é esta: a IA ajuda a interpretar requisitos e sugerir atividades; o motor Python calcula horas e custos por regras explícitas e testáveis.

Assim, começamos com um núcleo verificável e deixamos a interface, a persistência em banco de dados e a integração com modelos de IA para as etapas seguintes.