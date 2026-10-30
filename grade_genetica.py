#!/usr/bin/env python3
"""Alocacao de horarios com algoritmo genetico, sem dependencias externas."""

import argparse
import csv
import html
import json
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Evento:
    disciplina: int
    encontro: int
    duracao: int


@dataclass
class Avaliacao:
    conflitos_periodo: int
    conflitos_professor: int
    conflitos_pre_requisito: int
    encontros_mesmo_dia: int
    sequencias_longas: int
    conflitos_sala: int
    excesso_categoria: int
    janelas: int
    atraso: int

    @property
    def conflitos(self):
        return (self.conflitos_periodo + self.conflitos_professor
                + self.conflitos_pre_requisito + self.encontros_mesmo_dia
                + self.sequencias_longas + self.conflitos_sala + self.excesso_categoria
                + self.janelas)

    @property
    def fitness(self):
        return 1000 * self.conflitos + self.atraso


class Problema:
    def __init__(self, caminho):
        with open(caminho, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        self.dados = dados
        self.dias = dados["dias"]
        self.horarios = dados["horarios"]
        self.disciplinas = dados["disciplinas"]
        self.recursos = dados["recursos"]
        self.indice = {d["codigo"]: i for i, d in enumerate(self.disciplinas)}
        self._validar_dados()
        self.eventos = []
        for i, disciplina in enumerate(self.disciplinas):
            aulas_restantes = disciplina["aulas_semanais"]
            encontro = 0
            while aulas_restantes:
                duracao = 1 if disciplina.get("online", False) else min(2, aulas_restantes)
                self.eventos.append(Evento(i, encontro, duracao))
                aulas_restantes -= duracao
                encontro += 1
        self.blocos_por_dia = len(self.horarios)
        self.total_slots = len(self.dias) * self.blocos_por_dia
        self.dependentes = self._calcular_dependentes()

    def posicoes(self, gene):
        evento = self.eventos[gene]
        disciplina = self.disciplinas[evento.disciplina]
        dias_permitidos = self.dados["disponibilidade_professores"].get(disciplina["professor"])
        if disciplina.get("online", False):
            if evento.encontro < 5:
                return [evento.encontro * self.blocos_por_dia + 11]
            return [5 * self.blocos_por_dia + evento.encontro - 5]
        posicoes = []
        for slot in range(self.total_slots):
            bloco = slot % self.blocos_por_dia
            dia = slot // self.blocos_por_dia
            if dia >= 5 or (dias_permitidos is not None and dia not in dias_permitidos):
                continue
            tarde = disciplina["periodo"] in (1, 3) or disciplina.get("optativa", False)
            turno_valido = (6 <= bloco and bloco + evento.duracao <= 11) if tarde else (
                bloco + evento.duracao <= 6)
            if turno_valido:
                posicoes.append(slot)
        return posicoes

    def _validar_dados(self):
        codigos = [d["codigo"] for d in self.disciplinas]
        if len(codigos) != len(set(codigos)):
            raise ValueError("Ha codigos de disciplinas duplicados")
        for d in self.disciplinas:
            if d["aulas_semanais"] <= 0:
                raise ValueError(f"Carga horaria invalida em {d['codigo']}")
            for requisito in d["pre_requisitos"]:
                if requisito not in self.indice:
                    raise ValueError(f"Pre-requisito desconhecido: {requisito}")
                if self.disciplinas[self.indice[requisito]]["periodo"] >= d["periodo"]:
                    raise ValueError(f"Pre-requisito fora de periodo anterior: {requisito}")

    def _calcular_dependentes(self):
        pares = set()
        for i, disciplina in enumerate(self.disciplinas):
            vistos = set()
            pendentes = list(disciplina["pre_requisitos"])
            while pendentes:
                codigo = pendentes.pop()
                if codigo in vistos:
                    continue
                vistos.add(codigo)
                anterior = self.indice[codigo]
                pares.add((i, anterior))
                pendentes.extend(self.disciplinas[anterior]["pre_requisitos"])
        return pares

    def tipo_sala(self, disciplina):
        if disciplina.get("online", False):
            return "online"
        if "tipo_sala" in disciplina:
            return disciplina["tipo_sala"]
        codigo = disciplina["codigo"]
        return "laboratorio" if codigo in {
            "CC1AED1", "CC2AED2", "CC3AED3", "CC2POO", "CC4PO",
            "CC4LBD", "CC3PI1", "CC2CLD", "CC3AOC"
        } else "aula"

    def categoria(self, disciplina):
        if self.tipo_sala(disciplina) == "laboratorio":
            return "laboratorio"
        return "matematica" if disciplina["codigo"].startswith("MA") else "teorica"

    def intervalo(self, slot, duracao):
        return range(slot, slot + duracao)

    def avaliar(self, cromossomo):
        ocupacao_periodo = defaultdict(list)
        ocupacao_professor = defaultdict(list)
        ocupacao_sala = defaultdict(int)
        aulas_categoria = defaultdict(int)
        dias_evento = defaultdict(set)
        for gene, slot in enumerate(cromossomo):
            evento = self.eventos[gene]
            disciplina = self.disciplinas[evento.disciplina]
            dia = slot // self.blocos_por_dia
            if dia in dias_evento[evento.disciplina]:
                dias_evento[("repetido", evento.disciplina)].add(dia)
            dias_evento[evento.disciplina].add(dia)
            categoria = self.categoria(disciplina)
            aulas_categoria[(disciplina["periodo"], dia, categoria)] += evento.duracao
            for tempo in self.intervalo(slot, evento.duracao):
                ocupacao_periodo[(disciplina["periodo"], tempo)].append(gene)
                ocupacao_professor[(disciplina["professor"], tempo)].append(gene)
                if not disciplina.get("online", False):
                    ocupacao_sala[(self.tipo_sala(disciplina), tempo)] += 1

        def colisoes(ocupacao):
            return sum(len(genes) - 1 for genes in ocupacao.values() if len(genes) > 1)

        periodo = colisoes(ocupacao_periodo)
        professor = colisoes(ocupacao_professor)
        requisito = 0
        for posterior, anterior in self.dependentes:
            for tempo in range(self.total_slots):
                a = ocupacao_periodo.get((self.disciplinas[posterior]["periodo"], tempo), [])
                b = ocupacao_periodo.get((self.disciplinas[anterior]["periodo"], tempo), [])
                if any(self.eventos[g].disciplina == posterior for g in a) and any(
                        self.eventos[g].disciplina == anterior for g in b):
                    requisito += 1

        janelas = 0
        atraso = 0
        sequencias_longas = 0
        for periodo_turma in range(1, 5):
            for dia in range(len(self.dias)):
                tempos = [tempo for (p, tempo), genes in ocupacao_periodo.items()
                          if p == periodo_turma and genes and tempo // self.blocos_por_dia == dia
                          and tempo % self.blocos_por_dia < 11]
                for inicio_turno, tamanho_turno in ((0, 6), (6, 5)):
                    blocos_turno = [tempo % self.blocos_por_dia for tempo in tempos
                                    if inicio_turno <= tempo % self.blocos_por_dia < inicio_turno + tamanho_turno]
                    if blocos_turno:
                        atraso += sum(bloco - inicio_turno for bloco in blocos_turno)
                        janelas += sum(1 for bloco in range(min(blocos_turno), max(blocos_turno) + 1)
                                       if bloco not in blocos_turno)
                for i, disciplina in enumerate(self.disciplinas):
                    if disciplina["periodo"] != periodo_turma or disciplina.get("online", False):
                        continue
                    aulas = sum(e.duracao for g, e in enumerate(self.eventos)
                                if e.disciplina == i and cromossomo[g] // self.blocos_por_dia == dia)
                    sequencias_longas += max(0, aulas - 3)
        repetidos = 0
        for i in range(len(self.disciplinas)):
            genes = [g for g, e in enumerate(self.eventos) if e.disciplina == i]
            dias_disponiveis = len({slot // self.blocos_por_dia for g in genes
                                    for slot in self.posicoes(g)})
            ocorrencias = sum(len(dias) for chave, dias in dias_evento.items()
                              if chave == ("repetido", i))
            repetidos += max(0, ocorrencias - max(0, len(genes) - dias_disponiveis))
        alunos = self.recursos["alunos_por_turma"]
        capacidades = {"aula": sum(c >= alunos for c in self.recursos["salas_aula"]),
                       "laboratorio": sum(c >= alunos for c in self.recursos["laboratorios"])}
        salas = sum(max(0, quantidade - capacidades[tipo])
                    for (tipo, _), quantidade in ocupacao_sala.items())
        excesso_categoria = 0
        for (_, _, categoria), quantidade in aulas_categoria.items():
            limite = self.recursos.get(f"max_aulas_{categoria}_dia")
            if limite is not None:
                excesso_categoria += max(0, quantidade - limite)
        return Avaliacao(periodo, professor, requisito, repetidos, sequencias_longas,
                         salas, excesso_categoria, janelas, atraso)

    def detalhar_conflitos(self, cromossomo):
        mensagens = []
        for gene, slot in enumerate(cromossomo):
            evento = self.eventos[gene]
            atual = self.disciplinas[evento.disciplina]
            for outro_gene in range(gene):
                outro_evento = self.eventos[outro_gene]
                outro = self.disciplinas[outro_evento.disciplina]
                if set(self.intervalo(slot, evento.duracao)).isdisjoint(
                        self.intervalo(cromossomo[outro_gene], outro_evento.duracao)):
                    continue
                if atual["periodo"] == outro["periodo"]:
                    mensagens.append(f"Turma {atual['periodo']}: {atual['codigo']} x {outro['codigo']}")
                if atual["professor"] == outro["professor"]:
                    mensagens.append(f"Professor {atual['professor']}: {atual['codigo']} x {outro['codigo']}")
                par = (evento.disciplina, outro_evento.disciplina)
                if par in self.dependentes or par[::-1] in self.dependentes:
                    mensagens.append(f"Pre-requisito: {atual['codigo']} x {outro['codigo']}")
            genes_disciplina = [g for g, e in enumerate(self.eventos)
                                if e.disciplina == evento.disciplina]
            dias_disponiveis = len({s // self.blocos_por_dia for g in genes_disciplina
                                    for s in self.posicoes(g)})
            if (len(genes_disciplina) <= dias_disponiveis
                    and sum(cromossomo[g] // self.blocos_por_dia == slot // self.blocos_por_dia
                            for g, e in enumerate(self.eventos)
                            if e.disciplina == evento.disciplina) > 1):
                mensagens.append(f"Dois encontros no mesmo dia: {atual['codigo']}")
        return sorted(set(mensagens))


class AlgoritmoGenetico:
    def __init__(self, problema, args):
        self.problema = problema
        self.args = args
        self.rng = random.Random(args.seed)

    def individuo(self):
        return [self.rng.choice(self.problema.posicoes(gene))
                for gene in range(len(self.problema.eventos))]

    def selecionar(self, avaliados):
        candidatos = self.rng.sample(avaliados, self.args.torneio)
        return min(candidatos, key=lambda item: item[0].fitness)[1]

    def cruzar(self, pai, mae):
        if self.rng.random() >= self.args.taxa_cruzamento:
            return pai[:], mae[:]
        return ([a if self.rng.random() < 0.5 else b for a, b in zip(pai, mae)],
                [b if self.rng.random() < 0.5 else a for a, b in zip(pai, mae)])

    def mutar(self, cromossomo):
        for gene in range(len(cromossomo)):
            if self.rng.random() < self.args.taxa_mutacao:
                cromossomo[gene] = self.rng.choice(self.problema.posicoes(gene))

    def compactar(self, cromossomo, avaliacao):
        melhorou = True
        while melhorou:
            melhorou = False
            for gene in range(len(cromossomo)):
                original = cromossomo[gene]
                melhor_slot = original
                for slot in self.problema.posicoes(gene):
                    cromossomo[gene] = slot
                    candidata = self.problema.avaliar(cromossomo)
                    if candidata.fitness < avaliacao.fitness:
                        avaliacao = candidata
                        melhor_slot = slot
                        melhorou = True
                cromossomo[gene] = melhor_slot
        for gene in range(len(cromossomo)):
            for outro in range(gene):
                if (cromossomo[outro] not in self.problema.posicoes(gene)
                        or cromossomo[gene] not in self.problema.posicoes(outro)):
                    continue
                cromossomo[gene], cromossomo[outro] = cromossomo[outro], cromossomo[gene]
                candidata = self.problema.avaliar(cromossomo)
                if candidata.fitness < avaliacao.fitness:
                    avaliacao = candidata
                else:
                    cromossomo[gene], cromossomo[outro] = cromossomo[outro], cromossomo[gene]
        return cromossomo, avaliacao

    def executar(self):
        inicio = time.monotonic()
        populacao = [self.individuo() for _ in range(self.args.populacao)]
        melhor_global = None
        melhor_avaliacao = None
        historico = []
        geracao_melhor = 0
        geracoes_executadas = 0
        motivo = "limite de geracoes"

        for geracao in range(1, self.args.geracoes + 1):
            avaliados = [(self.problema.avaliar(c), c) for c in populacao]
            avaliados.sort(key=lambda item: item[0].fitness)
            avaliacao, melhor = avaliados[0]
            if melhor_global is None or avaliacao.fitness < melhor_avaliacao.fitness:
                melhor_global = melhor[:]
                melhor_avaliacao = avaliacao
                geracao_melhor = geracao
            historico.append({"geracao": geracao, "melhor_fitness": avaliacao.fitness,
                              "melhor_conflitos": avaliacao.conflitos,
                              "media_fitness": sum(a.fitness for a, _ in avaliados) / len(avaliados)})
            geracoes_executadas = geracao
            if geracao % 100 == 0 or geracao == 1:
                print(f"Geracao {geracao:4d} | conflitos: {melhor_avaliacao.conflitos} "
                      f"| fitness: {melhor_avaliacao.fitness}", flush=True)

            if (geracao >= self.args.min_geracoes and melhor_avaliacao.conflitos == 0
                    and geracao - geracao_melhor >= self.args.paciencia):
                motivo = "solucao sem conflitos e convergencia"
                break
            if time.monotonic() - inicio >= self.args.tempo_maximo:
                motivo = "limite de tempo"
                break

            elite = [c[:] for _, c in avaliados[:self.args.elitismo]]
            nova = elite
            while len(nova) < len(populacao):
                filho1, filho2 = self.cruzar(self.selecionar(avaliados), self.selecionar(avaliados))
                self.mutar(filho1)
                self.mutar(filho2)
                nova.extend((filho1, filho2))
            populacao = nova[:len(populacao)]
        melhor_global, melhor_avaliacao = self.compactar(melhor_global, melhor_avaliacao)
        return melhor_global, melhor_avaliacao, historico, {
            "geracoes_executadas": geracoes_executadas,
            "geracao_melhor_solucao": geracao_melhor,
            "tempo_segundos": round(time.monotonic() - inicio, 3),
            "motivo_parada": motivo
        }


def nome_horario(problema, slot):
    dia = slot // problema.blocos_por_dia
    bloco = slot % problema.blocos_por_dia
    return problema.dias[dia], problema.horarios[bloco]


def salvar_resultados(problema, cromossomo, avaliacao, historico, execucao, args, pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    alocacoes = []
    for gene, slot in enumerate(cromossomo):
        evento = problema.eventos[gene]
        d = problema.disciplinas[evento.disciplina]
        dia, horario = nome_horario(problema, slot)
        alocacoes.append({"periodo": d["periodo"], "codigo": d["codigo"], "disciplina": d["nome"],
                          "professor": d["professor"], "encontro": evento.encontro + 1,
                          "dia": dia, "horario": horario, "slot": slot, "duracao": evento.duracao})
    alocacoes.sort(key=lambda a: (a["periodo"], a["slot"], a["codigo"]))
    conflitos = problema.detalhar_conflitos(cromossomo)
    configuracao = {chave: valor for chave, valor in vars(args).items() if chave != "saida"}
    resultado = {"gerado_em": datetime.now().isoformat(timespec="seconds"),
                 "fonte_dados": problema.dados["descricao"], "configuracao": configuracao,
                 "execucao": execucao, "avaliacao": asdict(avaliacao),
                 "conflitos_totais": avaliacao.conflitos, "conflitos_detalhados": conflitos,
                 "alocacoes": alocacoes, "historico": historico}
    (pasta / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(pasta / "grade.csv", "w", newline="", encoding="utf-8-sig") as arquivo:
        campos = ["periodo", "codigo", "disciplina", "professor", "encontro", "dia", "horario"]
        escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(alocacoes)
    with open(pasta / "historico.csv", "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(historico[0]))
        escritor.writeheader()
        escritor.writerows(historico)
    (pasta / "grade.html").write_text(gerar_html(problema, alocacoes, avaliacao, execucao), encoding="utf-8")
    (pasta / "evolucao.svg").write_text(gerar_grafico(historico), encoding="utf-8")


def gerar_html(problema, alocacoes, avaliacao, execucao):
    partes = ["<!doctype html><html lang='pt-BR'><meta charset='utf-8'>",
              "<title>Grade horaria</title><style>body{font-family:Arial,sans-serif;margin:30px;color:#222}",
              "table{border-collapse:collapse;margin:20px 0;width:100%}th,td{border:1px solid #bbb;padding:8px;text-align:left}",
              "th{background:#e8eef5}.disciplina{display:block;font-weight:bold}.prof{font-size:.85em;color:#555}</style>",
              "<h1>Grade horaria - Ciencia da Computacao</h1>",
              f"<p>Conflitos: <b>{avaliacao.conflitos}</b> | Janelas: {avaliacao.janelas} | ",
              f"Geracoes: {execucao['geracoes_executadas']} | Tempo: {execucao['tempo_segundos']} s</p>",
              "<p>Matriz e docentes COCIC-SH 2026/2. Optativa selecionada: Empreendedorismo.</p>",
              "<p>Intervalos: 10:00-10:20 e 15:30-15:50. Almoco: 12:50-13:00. "
              "Cada disciplina tem no maximo tres aulas no mesmo dia.</p>"]
    for periodo in range(1, 5):
        partes.append(f"<h2>{periodo}o periodo</h2><table><tr><th>Horario</th>")
        partes.extend(f"<th>{html.escape(dia)}</th>" for dia in problema.dias)
        partes.append("</tr>")
        for bloco, horario in enumerate(problema.horarios):
            partes.append(f"<tr><th>{html.escape(horario)}</th>")
            for dia in range(len(problema.dias)):
                slot = dia * problema.blocos_por_dia + bloco
                aulas = [a for a in alocacoes if a["periodo"] == periodo
                         and slot in range(a["slot"], a["slot"] + a["duracao"])]
                conteudo = "".join(f"<span class='disciplina'>{html.escape(a['codigo'])} - {html.escape(a['disciplina'])}</span>"
                                   f"<span class='prof'>{html.escape(a['professor'])}</span>" for a in aulas)
                partes.append(f"<td>{conteudo}</td>")
            partes.append("</tr>")
        partes.append("</table>")
    partes.append("</html>")
    return "".join(partes)


def gerar_grafico(historico):
    largura, altura, margem = 900, 400, 55
    valores = [h["melhor_fitness"] for h in historico]
    maximo = max(valores) or 1
    pontos = []
    for i, valor in enumerate(valores):
        x = margem + i * (largura - 2 * margem) / max(1, len(valores) - 1)
        y = altura - margem - (math.log1p(valor) / math.log1p(maximo)) * (altura - 2 * margem)
        pontos.append(f"{x:.2f},{y:.2f}")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{largura}' height='{altura}' viewBox='0 0 {largura} {altura}'>"
            "<rect width='100%' height='100%' fill='white'/><text x='20' y='25' font-family='Arial' font-size='18'>Evolucao do melhor fitness (escala logaritmica)</text>"
            f"<line x1='{margem}' y1='{altura-margem}' x2='{largura-margem}' y2='{altura-margem}' stroke='black'/>"
            f"<line x1='{margem}' y1='{margem}' x2='{margem}' y2='{altura-margem}' stroke='black'/>"
            f"<polyline fill='none' stroke='#2463a5' stroke-width='2' points='{' '.join(pontos)}'/>"
            f"<text x='{largura//2}' y='{altura-10}' font-family='Arial'>Geracoes</text>"
            f"<text x='5' y='{margem}' font-family='Arial' font-size='12'>{maximo}</text>"
            f"<text x='25' y='{altura-margem}' font-family='Arial' font-size='12'>0</text></svg>")


def argumentos():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", default="dados/disciplinas.json")
    parser.add_argument("--saida", default="resultados")
    parser.add_argument("--populacao", type=int, default=200)
    parser.add_argument("--geracoes", type=int, default=1000)
    parser.add_argument("--min-geracoes", type=int, default=500)
    parser.add_argument("--taxa-mutacao", type=float, default=0.04)
    parser.add_argument("--taxa-cruzamento", type=float, default=0.9)
    parser.add_argument("--torneio", type=int, default=3)
    parser.add_argument("--elitismo", type=int, default=2)
    parser.add_argument("--paciencia", type=int, default=150)
    parser.add_argument("--tempo-maximo", type=float, default=3600)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.populacao < 4 or args.elitismo >= args.populacao:
        parser.error("Use populacao >= 4 e elitismo menor que a populacao")
    if args.geracoes < 500 or args.min_geracoes < 500:
        parser.error("O trabalho exige no minimo 500 geracoes")
    if not 0 <= args.taxa_mutacao <= 1 or not 0 <= args.taxa_cruzamento <= 1:
        parser.error("As taxas devem estar entre 0 e 1")
    if args.torneio < 2 or args.torneio > args.populacao:
        parser.error("O torneio deve ter entre 2 e o tamanho da populacao")
    if args.tempo_maximo <= 0:
        parser.error("O tempo maximo deve ser positivo")
    return args


def main():
    args = argumentos()
    problema = Problema(args.dados)
    print(f"{len(problema.disciplinas)} disciplinas, {len(problema.eventos)} encontros, "
          f"{problema.total_slots} posicoes por encontro")
    melhor, avaliacao, historico, execucao = AlgoritmoGenetico(problema, args).executar()
    salvar_resultados(problema, melhor, avaliacao, historico, execucao, args, Path(args.saida))
    print(f"Final: {avaliacao.conflitos} conflitos, fitness {avaliacao.fitness}, "
          f"{execucao['tempo_segundos']} s. Arquivos em {args.saida}/")


if __name__ == "__main__":
    main()
