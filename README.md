# Grade horária com algoritmo genético

Implementação em Python para distribuir as disciplinas do 1º ao 4º período sem conflitos de turma, professor ou pré-requisitos. Usa apenas a biblioteca padrão do Python 3.

## Executar

```bash
python3 grade_genetica.py
```

A configuração padrão usa 200 indivíduos, até 1.000 gerações, no mínimo 500 gerações e tempo máximo de 3.600 segundos. Para uma execução com até uma hora e outra semente:

```bash
python3 grade_genetica.py --tempo-maximo 3600 --seed 42
```

Os principais parâmetros podem ser consultados com:

```bash
python3 grade_genetica.py --help
```

## Arquivos

- `dados/disciplinas.json`: disciplinas, professores, pré-requisitos, dias e horários.
- `grade_genetica.py`: implementação e validação.
- `RELATORIO.md`: relatório do trabalho.
- `Relatorio_Final.pdf`: relatório em PDF para entrega.
- `resultados/grade.html`: grade final visualizada no navegador.
- `resultados/grade.csv`: alocações para planilha.
- `resultados/resultado.json`: configuração e resultados completos.
- `resultados/historico.csv`: fitness por geração.
- `resultados/evolucao.svg`: gráfico da evolução.

A base usa a matriz e os docentes COCIC-SH 2026/2 fornecidos para o trabalho, com Empreendedorismo como optativa. O modelo também inclui disponibilidade docente, capacidade de salas e laboratórios, intervalos e limites diários por categoria. Os pré-requisitos foram inferidos pela sequência curricular e devem ser confirmados com a coordenação.
