#!/usr/bin/env python3
"""
Painel Avança Uberlândia: busca os dados no Notion e monta o site.

O GitHub Actions roda este script sozinho (todo dia e quando alguém clica em
"Run workflow"). Ele:
  1. lê o config.json;
  2. busca as bases do Notion usando o token guardado em NOTION_TOKEN;
  3. escolhe os objetos com a tag do programa e organiza os campos;
  4. grava o site pronto em _site/index.html (modelo index.html + dados).

Se algo der errado (token inválido, base sem acesso, coluna de tag ausente),
o script para com uma mensagem em português e o site anterior continua no ar.

Só usa a biblioteca padrão do Python, então não precisa instalar nada.
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
API = os.environ.get("NOTION_API_URL", "https://api.notion.com/v1").rstrip("/")
VERSAO_API = "2026-03-11"
OUTROS, NAO_INFORMADA = "Outros", "Não informada"
FASES = {"concluida", "andamento", "licitacao", "planejamento"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


class Erro(Exception):
    """Erro com mensagem pronta para mostrar a quem cuida do painel."""


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def normalizar(texto):
    """Minúsculas, sem acentos e sem espaços sobrando (para comparar nomes)."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().casefold()


def chave(texto):
    """Como normalizar, mas também ignora vírgulas e outros sinais (para comparar eixos)."""
    return re.sub(r"[^a-z0-9]+", " ", normalizar(texto)).strip()


def reais(v):
    if v >= 1e9:
        return f"R$ {v / 1e9:.2f} bi".replace(".", ",")
    if v >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    return f"R$ {v:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
def carregar_config():
    caminho = RAIZ / "config.json"
    try:
        cfg = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Erro("Não encontrei o arquivo config.json na raiz do repositório.")
    except json.JSONDecodeError as e:
        raise Erro(f"O config.json tem um erro de digitação na linha {e.lineno}, coluna {e.colno}: {e.msg}. "
                   "Confira vírgulas e aspas perto desse ponto.")
    for chave in ("tag_do_programa", "total_do_programa", "bases", "fontes", "eixos"):
        if chave not in cfg:
            raise Erro(f'O config.json está sem o item "{chave}".')
    for base in cfg["bases"]:
        if base.get("fase") not in FASES:
            raise Erro(f'A base "{base.get("nome")}" tem fase "{base.get("fase")}". Use uma destas: {", ".join(sorted(FASES))}.')
        if "titulo" not in base.get("colunas", {}):
            raise Erro(f'A base "{base.get("nome")}" precisa da coluna "titulo" em "colunas".')
    if OUTROS not in cfg["eixos"]:
        cfg["eixos"] = list(cfg["eixos"]) + [OUTROS]
    return cfg


def extrair_id(link_ou_id):
    """Aceita o link da base copiado do navegador ou só o ID."""
    s = str(link_ou_id or "").strip().split("?")[0].split("#")[0]
    com_hifens = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s, re.I)
    if com_hifens:
        bruto = com_hifens[-1].replace("-", "")
    else:
        sem_hifens = re.findall(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", s, re.I)
        if not sem_hifens:
            return None
        bruto = sem_hifens[-1]
    b = bruto.lower()
    return f"{b[:8]}-{b[8:12]}-{b[12:16]}-{b[16:20]}-{b[20:]}"


# ---------------------------------------------------------------------------
# Acesso à API do Notion
# ---------------------------------------------------------------------------
class Notion:
    def __init__(self, token):
        self.token = token

    def chamar(self, metodo, caminho, corpo=None):
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        for tentativa in range(6):
            req = urllib.request.Request(API + caminho, data=dados, method=metodo, headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": VERSAO_API,
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                try:
                    detalhe = json.loads(e.read().decode("utf-8"))
                except Exception:
                    detalhe = {}
                if e.code == 429 or e.code >= 500:           # limite de uso ou instabilidade: espera e tenta de novo
                    espera = float(e.headers.get("Retry-After") or 2 ** tentativa)
                    time.sleep(min(espera, 30))
                    continue
                raise ErroNotion(e.code, detalhe.get("code", ""), detalhe.get("message", ""))
            except urllib.error.URLError as e:
                if tentativa < 5:
                    time.sleep(2 ** tentativa)
                    continue
                raise Erro(f"Não consegui falar com o Notion ({e.reason}). Tente rodar de novo mais tarde.")
        raise Erro("O Notion recusou as chamadas várias vezes seguidas (limite de uso). Tente rodar de novo em alguns minutos.")

    def fontes_de_dados(self, id_informado):
        """Devolve a lista de 'data sources' (tabelas) de uma base, aceitando ID de base ou de data source."""
        try:
            base = self.chamar("GET", f"/databases/{id_informado}")
            return [f["id"] for f in base.get("data_sources", [])], base
        except ErroNotion as e:
            if e.status not in (400, 404):
                raise
        try:
            fonte = self.chamar("GET", f"/data_sources/{id_informado}")
            return [fonte["id"]], fonte
        except ErroNotion as e:
            if e.status in (400, 404):
                return [], None
            raise

    def esquema(self, id_fonte):
        return self.chamar("GET", f"/data_sources/{id_fonte}").get("properties", {})

    def linhas(self, id_fonte):
        resultado, cursor = [], None
        while True:
            corpo = {"page_size": 100}
            if cursor:
                corpo["start_cursor"] = cursor
            resp = self.chamar("POST", f"/data_sources/{id_fonte}/query", corpo)
            resultado += [p for p in resp.get("results", []) if p.get("object") == "page"]
            if not resp.get("has_more"):
                return resultado
            cursor = resp.get("next_cursor")


class ErroNotion(Erro):
    def __init__(self, status, codigo, mensagem):
        self.status, self.codigo = status, codigo
        super().__init__(f"{status} {codigo}: {mensagem}")


# ---------------------------------------------------------------------------
# Leitura dos valores das colunas do Notion
# ---------------------------------------------------------------------------
def ler(prop):
    """Converte uma propriedade do Notion em (valor, links)."""
    if not prop:
        return None, []
    tipo = prop.get("type")
    v = prop.get(tipo)
    if tipo in ("title", "rich_text"):
        partes = v or []
        return "".join(p.get("plain_text", "") for p in partes), [p["href"] for p in partes if p.get("href")]
    if tipo in ("select", "status"):
        return (v or {}).get("name"), []
    if tipo == "multi_select":
        return [o.get("name", "") for o in v or []], []
    if tipo == "date":
        return (v or {}).get("start"), []
    if tipo in ("number", "checkbox", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return v, ([v] if tipo == "url" and v else [])
    if tipo == "formula":
        v = v or {}
        interno = v.get(v.get("type"))
        return (interno.get("start") if isinstance(interno, dict) else interno), []
    if tipo == "rollup":
        v = v or {}
        if v.get("type") == "array":
            valores = [ler(item)[0] for item in v.get("array", [])]
            planos = []
            for x in valores:
                planos += x if isinstance(x, list) else ([x] if x not in (None, "") else [])
            return planos, []
        interno = v.get(v.get("type"))
        return (interno.get("start") if isinstance(interno, dict) else interno), []
    if tipo in ("people", "created_by", "last_edited_by"):
        pessoas = v if isinstance(v, list) else [v]
        return [p.get("name", "") for p in pessoas if p], []
    if tipo == "files":
        return [f.get("name", "") for f in v or []], []
    if tipo == "unique_id":
        v = v or {}
        return "-".join(str(x) for x in (v.get("prefix"), v.get("number")) if x), []
    if tipo == "place":
        if not v:
            return None, []
        link = f"https://www.google.com/maps?q={v['lat']},{v['lon']}" if v.get("lat") is not None and v.get("lon") is not None else ""
        return v.get("address") or v.get("name") or "", ([link] if link else [])
    return None, []   # relation, button, unsupported e outros tipos sem valor útil aqui


def como_texto(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, list):
        return ", ".join(como_texto(x) for x in v if como_texto(x))
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def como_lista(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [como_texto(x) for x in v if como_texto(x)]
    return [p.strip() for p in str(v).split(",") if p.strip()]


def como_numero(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        numeros = [como_numero(x) for x in v]
        numeros = [x for x in numeros if x is not None]
        return sum(numeros) if numeros else None
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    if not s:
        return None
    if "," in s:                                   # formato brasileiro: 1.234.567,89
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:                         # 1.234.567
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def como_data(v):
    if not v:
        return ""
    s = str(v[0] if isinstance(v, list) else v).strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.match(r"(\d{1,2}) de (\w+) de (\d{4})", s, re.I)
    if m and normalizar(m[2]) in [normalizar(x) for x in MESES]:
        mes = [normalizar(x) for x in MESES].index(normalizar(m[2])) + 1
        return f"{m[3]}-{mes:02d}-{int(m[1]):02d}"
    return ""


def como_sim_nao(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, list):
        return any(como_sim_nao(x) for x in v)
    return normalizar(v) in ("sim", "s", "yes", "true", "x", "ok", "pronto", "concluido")


# ---------------------------------------------------------------------------
# Regras do painel
# ---------------------------------------------------------------------------
PROCESSO = re.compile(r"^(CP|PE|PD|PI|RDC|TP|CC|DL|IN|PP)\s*\d", re.I)
EMPRESA = re.compile(r"(ltda|construtora|engenharia|consórcio|consorcio|service|servi[cç]os|comércio|comercio|"
                     r"evolução|evolucao|barros|sete|s\.a\.|eireli|\bme\b|\bepp\b)", re.I)


def parece_empresa(parte, empresa):
    if EMPRESA.search(parte):
        return True
    p, e = normalizar(parte), normalizar(empresa)
    return bool(p and e and (p in e or p.split()[0] in e.split()))


def separar_titulo(bruto, empresa=""):
    """'Obra X - Empresa Y - CP 123/2025' vira ('Obra X', 'CP 123/2025')."""
    partes = [p.strip().rstrip("=") for p in re.split(r"\s+-\s+", como_texto(bruto)) if p.strip()]
    processo = next((p for p in partes if PROCESSO.match(p)), "")
    resto = [p for p in partes if not PROCESSO.match(p)]
    if len(resto) > 1 and parece_empresa(resto[-1], empresa):
        resto = resto[:-1]
    nome = re.sub(r"\s+", " ", " – ".join(resto)).strip()
    return (nome[:1].upper() + nome[1:]) if nome else "(sem título)", processo


URL = re.compile(r"https?://\S+")


def montar_local(texto, links, endereco, links_endereco):
    """Texto curto do local e um link de mapa (se houver)."""
    todos_links = URL.findall(texto or "") + links + links_endereco
    link = todos_links[0] if todos_links else ""
    if endereco:
        return {"texto": re.split(r",\s*Uberl[âa]ndia", endereco)[0].strip(), "link": link}
    rotulos = []
    for linha in str(texto or "").split("\n"):
        sem_link = URL.sub("", linha).strip()
        sem_link = re.sub(r"\s*\(.*?\)$", "", sem_link).strip().rstrip(":.").strip()
        if sem_link:
            rotulos.append(sem_link)
    txt = ", ".join(rotulos)
    if normalizar(txt) == "nao se aplica":
        txt = ""
    if not txt and link:
        txt = "Ver no mapa"
    return {"texto": txt, "link": link}


class Regras:
    def __init__(self, cfg):
        self.cfg = cfg
        self.eixos = cfg["eixos"]
        self.eixo_por_nome = {chave(e): e for e in self.eixos}
        self.fonte_por_nome = {}
        for f in cfg["fontes"]:
            for n in [f["nome"]] + list(f.get("nomes_no_notion", [])):
                self.fonte_por_nome[normalizar(n)] = f["nome"]
        self.sem_fonte = {normalizar(x) for x in cfg.get("dotacoes_sem_fonte", [])} | {""}
        self.grupos_outros = [(g["nome"], [normalizar(x) for x in g.get("quando_contem", [])])
                              for g in cfg.get("agrupar_em_outros", [])]
        deducao = cfg.get("deducao_de_eixo", {})
        self.regras_eixo = []
        for r in deducao.get("palavras_chave", []):
            palavras = [normalizar(p) for p in r.get("palavras", []) if p]
            eixo = self.eixo_por_nome.get(chave(r.get("eixo")))
            if palavras and eixo:
                padrao = "|".join(r"(?<![a-z0-9])" + re.escape(p) for p in palavras)
                self.regras_eixo.append((eixo, re.compile(padrao)))
        self.eixo_por_secretaria = {normalizar(k): self.eixo_por_nome[chave(v)]
                                    for k, v in deducao.get("por_secretaria", {}).items() if chave(v) in self.eixo_por_nome}
        self.tag = normalizar(cfg["tag_do_programa"])
        self.tags_prioridade = {normalizar(t) for t in cfg.get("tags_de_prioridade", [])}
        self.situacoes_ignoradas = [normalizar(s) for s in cfg.get("ignorar_situacao_com", []) if s]

    def fontes(self, dotacoes):
        """Converte as dotações do Notion nas fontes oficiais do programa."""
        brutas = dotacoes or [""]
        fontes, outros = [], []
        for d in brutas:
            n = normalizar(d)
            if n in self.fonte_por_nome:
                f = self.fonte_por_nome[n]
            elif n in self.sem_fonte:
                f = NAO_INFORMADA
            else:
                f = OUTROS
                apelido = next((nome for nome, trechos in self.grupos_outros if any(t in n for t in trechos)), d.strip())
                if apelido not in outros:
                    outros.append(apelido)
            if f not in fontes:
                fontes.append(f)
        return fontes, outros

    def eixo(self, valor_notion, titulo, descricao, secretaria, avisos, nome_obj):
        if valor_notion:
            e = self.eixo_por_nome.get(chave(valor_notion))
            if e:
                return e, "notion"
            avisos.append(f'"{nome_obj}": o eixo "{valor_notion}" não está na lista de eixos do config.json; entrou como "{OUTROS}".')
            return OUTROS, "notion"
        for texto in (titulo, descricao):
            n = normalizar(texto)
            for eixo, padrao in self.regras_eixo:
                if padrao.search(n):
                    return eixo, "deduzido"
        primeira = normalizar(str(secretaria or "").split(",")[0])
        return self.eixo_por_secretaria.get(primeira, OUTROS), "deduzido"


# ---------------------------------------------------------------------------
# Leitura de uma base
# ---------------------------------------------------------------------------
OPCIONAIS = {"eixo", "aditivo", "conclusao", "endereco", "descricao", "secretaria", "avanco", "inicio",
             "termino", "empresa", "situacao", "localizacao"}


def ler_base(notion, regras, base, avisos):
    nome_base = base.get("nome") or base["fase"]
    id_base = extrair_id(base.get("link_ou_id"))
    if not base.get("link_ou_id"):
        avisos.append(f'Base "{nome_base}": sem link no config.json, então ficou de fora por enquanto.')
        return [], {"base": nome_base, "linhas": 0, "no_painel": 0, "valor": 0, "pulada": True}
    if not id_base:
        raise Erro(f'Base "{nome_base}": não reconheci o link "{base["link_ou_id"]}". Cole o link copiado do navegador '
                   'com a base aberta em página inteira, ou só o código de 32 letras e números.')

    try:
        ids_fontes, _ = notion.fontes_de_dados(id_base)
    except ErroNotion as e:
        if e.status == 401:
            raise Erro("O Notion recusou o token (401). Confira o segredo NOTION_TOKEN no GitHub: "
                       "ele pode ter sido digitado errado, expirado ou revogado.")
        if e.status == 403:
            raise Erro(f'Base "{nome_base}": a conexão não tem permissão de leitura. '
                       'Nas configurações da conexão no Notion, marque "Ler conteúdo".')
        raise
    if not ids_fontes:
        raise Erro(f'Base "{nome_base}": o Notion não encontrou essa base. Duas causas comuns: (1) a página onde a base '
                   'está não foi conectada à conexão (no Notion: "..." > Conexões > escolher a conexão); '
                   '(2) o link aponta para uma visualização vinculada, e não para a base original.')
    if len(ids_fontes) > 1:
        avisos.append(f'Base "{nome_base}": tem {len(ids_fontes)} fontes de dados; li todas.')

    colunas_cfg = dict(base.get("colunas", {}))
    ignorados = []
    objetos, total_linhas = [], 0

    for id_fonte in ids_fontes:
        esquema = notion.esquema(id_fonte)
        por_nome = {normalizar(n): n for n in esquema}

        def achar(apelidos):
            for a in apelidos if isinstance(apelidos, list) else [apelidos]:
                if normalizar(a) in por_nome:
                    return por_nome[normalizar(a)]
            return None

        mapa = {campo: achar(nomes) for campo, nomes in colunas_cfg.items()}
        faltando = [nomes if isinstance(nomes, str) else " / ".join(nomes)
                    for campo, nomes in colunas_cfg.items() if mapa[campo] is None and campo not in ("eixo", "conclusao")]
        if faltando:
            importantes = [colunas_cfg[c] for c in colunas_cfg if mapa[c] is None and c not in OPCIONAIS]
            alerta = " Atenção: entre elas há coluna essencial (título, valor, dotação ou tags)." if importantes else ""
            avisos.append(f'Base "{nome_base}": não achei estas colunas: {", ".join(chr(34) + f + chr(34) for f in faltando)}.{alerta} '
                          f'Colunas que existem nessa base: {", ".join(n.strip() for n in sorted(esquema))}.')
        if mapa.get("titulo") is None:
            titulo = next((n for n, p in esquema.items() if p.get("type") == "title"), None)
            mapa["titulo"] = titulo
        if base.get("exigir_tag", True) and mapa.get("tags") is None:
            raise Erro(f'Base "{nome_base}": não achei a coluna de tags "{colunas_cfg.get("tags")}", então não sei quais '
                       'objetos são do programa. Corrija o nome em "colunas" > "tags" no config.json.')
        formato_avanco = ((esquema.get(mapa.get("avanco") or "", {}).get("number") or {}).get("format"))

        for pagina in notion.linhas(id_fonte):
            total_linhas += 1
            props = pagina.get("properties", {})

            def valor(campo):
                return ler(props.get(mapa.get(campo) or "", {}))

            tags = como_lista(valor("tags")[0])
            tags_norm = {normalizar(t) for t in tags}
            if base.get("exigir_tag", True) and regras.tag not in tags_norm:
                continue

            titulo_bruto = como_texto(valor("titulo")[0])
            empresa = como_texto(valor("empresa")[0])
            nome, processo = separar_titulo(titulo_bruto, empresa)
            situacao = como_texto(valor("situacao")[0])
            if any(s in normalizar(situacao) for s in regras.situacoes_ignoradas):
                ignorados.append(f"{nome} ({situacao})")
                continue
            descricao = como_texto(valor("descricao")[0])
            texto_local, links_local = valor("localizacao")
            texto_end, links_end = valor("endereco")
            dotacao = como_lista(valor("dotacao")[0])
            fontes, outros = regras.fontes(dotacao)
            eixo, origem = regras.eixo(como_texto(valor("eixo")[0]), titulo_bruto, descricao,
                                       como_texto(valor("secretaria")[0]), avisos, nome)
            avanco = como_numero(valor("avanco")[0])
            if avanco is not None and formato_avanco == "percent":
                avanco *= 100

            o = {
                "status": base["fase"],
                "nome": nome,
                "processo": processo,
                "empresa": empresa,
                "eixo": eixo,
                "eixoOrigem": origem,
                "valor": round(como_numero(valor("valor")[0]) or 0.0, 2),
                "situacao": situacao,
                "dotacao": dotacao,
                "fontes": fontes,
                "outros": outros,
                "local": montar_local(como_texto(texto_local), links_local, como_texto(texto_end), links_end),
                "prioridade": bool(tags_norm & regras.tags_prioridade),
            }
            if base["fase"] in ("andamento", "concluida"):
                o.update({
                    "aditivo": round(como_numero(valor("aditivo")[0]) or 0.0, 2),
                    "inicio": como_data(valor("inicio")[0]),
                    "termino": como_data(valor("termino")[0]),
                    "avanco": round(avanco, 2) if avanco is not None else None,
                })
            if base["fase"] == "concluida":
                o["conclusao"] = como_data(valor("conclusao")[0])
            objetos.append(o)

    if ignorados:
        avisos.append(f'Base "{nome_base}": {len(ignorados)} objeto(s) com rescisão ficaram de fora: {"; ".join(ignorados)}.')
    resumo = {"base": nome_base, "linhas": total_linhas, "no_painel": len(objetos),
              "valor": sum(o["valor"] for o in objetos), "pulada": False}
    return objetos, resumo


# ---------------------------------------------------------------------------
# Montagem do site
# ---------------------------------------------------------------------------
def para_script(obj):
    """JSON seguro para colocar dentro de uma tag <script>."""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def montar_site(cfg, dados, pasta_saida):
    modelo = (RAIZ / "index.html").read_text(encoding="utf-8")
    for marcador in ("/*__CONFIG__*/null", "/*__DADOS__*/null"):
        if modelo.count(marcador) != 1:
            raise Erro(f"O index.html não tem o marcador {marcador} (ou tem mais de um). Use o index.html original do pacote.")
    publico = {k: v for k, v in cfg.items() if k in ("aviso_no_topo", "total_do_programa", "eixos")}
    publico["fontes"] = [{"nome": f["nome"], "disponivel": f["disponivel"], "detalhe": f.get("detalhe", ""), "nota": f.get("nota", "")}
                         for f in cfg["fontes"]]
    html = (modelo.replace("/*__CONFIG__*/null", para_script(publico))
                  .replace("/*__DADOS__*/null", para_script(dados)))
    pasta_saida.mkdir(parents=True, exist_ok=True)
    (pasta_saida / "index.html").write_text(html, encoding="utf-8")


def agora_brasilia():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=-3)))


def escrever_resumo(texto):
    """Mostra o resumo na página da execução no GitHub (e no terminal)."""
    print(texto)
    caminho = os.environ.get("GITHUB_STEP_SUMMARY")
    if caminho:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def principal():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise Erro("Falta o token do Notion. No GitHub, crie o segredo NOTION_TOKEN em "
                   "Settings > Secrets and variables > Actions.")
    cfg = carregar_config()
    regras = Regras(cfg)
    notion = Notion(token)

    objetos, resumos, avisos = [], [], []
    for base in cfg["bases"]:
        lidos, resumo = ler_base(notion, regras, base, avisos)
        objetos += lidos
        resumos.append(resumo)

    momento = agora_brasilia()
    dados = {"atualizadoEm": momento.strftime("%Y-%m-%d"), "atualizadoHora": momento.strftime("%H:%M"), "objetos": objetos}
    saida = RAIZ / os.environ.get("PASTA_SITE", "_site")
    montar_site(cfg, dados, saida)

    deduzidos = sum(1 for o in objetos if o["eixoOrigem"] == "deduzido")
    linhas = ["## Painel atualizado", "",
              f"Dados do Notion de {momento.strftime('%d/%m/%Y às %H:%M')} (horário de Brasília).", "",
              "| Base | Linhas no Notion | Entraram no painel | Valor |", "|---|---:|---:|---:|"]
    for r in resumos:
        if r["pulada"]:
            linhas.append(f"| {r['base']} | sem link | — | — |")
        else:
            linhas.append(f"| {r['base']} | {r['linhas']} | {r['no_painel']} | {reais(r['valor'])} |")
    linhas.append("")
    if deduzidos:
        linhas += [f"{deduzidos} de {len(objetos)} objetos estão sem o campo Eixo temático no Notion; "
                   "o eixo deles foi deduzido pelo nome.", ""]
    if avisos:
        linhas += ["### Avisos", ""] + [f"- {a}" for a in avisos]
    escrever_resumo("\n".join(linhas))


if __name__ == "__main__":
    try:
        principal()
    except Erro as e:
        escrever_resumo(f"## O painel não foi atualizado\n\n{e}\n\nO site continua com a versão anterior.")
        print(f"::error::{e}")
        sys.exit(1)
