import os
import uuid
from flask import Flask, render_template, request, jsonify,send_from_directory,redirect
from dotenv import load_dotenv
from ddgs import DDGS
import tldextract
from openai import OpenAI
from datetime import datetime
import requests  # 🔴 Adicionado para chamar o YouTube API
import isodate
from datetime import datetime, timedelta
import json
import psycopg2
from psycopg2 import pool,OperationalError, extensions
import psycopg2.extras
from factcheck_service import factcheck_answer





# Carrega variáveis do .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")  # 🔴 Nova variável

PG_HOST = os.getenv("PG_HOST", "")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "")

app = Flask(__name__)

# ------------------------
# Redirecionamento do Render para domínio oficial foi importado o redirect, apagar def redirect e importaçao redirect caso der erro
# ------------------------
@app.before_request
def redirect_render_to_roog():
    # Se o host for do Render, redireciona para o domínio oficial
    if request.host == "provejorv1.onrender.com":
        # Mantém o path e query string
        return redirect(f"https://www.roog.com.br{request.full_path}", code=301)



# --- Postgres pool (inicializa se as variáveis existirem) ---
db_pool = None

def init_db_pool():
    global db_pool
    if not (PG_HOST and PG_USER and PG_PASSWORD and PG_DATABASE):
        print("Postgres não configurado - skip DB init")
        return
    try:
        db_pool = pool.ThreadedConnectionPool(
            minconn=1, maxconn=10,
            host=PG_HOST, port=int(PG_PORT),
            database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD,
            sslmode="require",
            keepalives=1,          # ativa keepalive
            keepalives_idle=30,    # segundos antes de testar
            keepalives_interval=10,# intervalo entre testes
            keepalives_count=5     # tentativas antes de derrubar
        )
        print("Postgres pool inicializado")
    except Exception as e:
        print("Erro ao inicializar Postgres pool:", e)
        db_pool = None

def get_conn():

    """Pega uma conexão válida do pool (abre nova se a atual caiu)"""
    if not db_pool:
        return None
    conn = db_pool.getconn()
    try:
        # testa conexão
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close()
        return conn
    except OperationalError:
        print("Conexão inválida, tentando renovar...")
        db_pool.putconn(conn, close=True)
        return db_pool.getconn()






def create_tables():
    """Cria tabela logs se não existir"""
    if not db_pool:
        return
    conn = None
    try:
        conn = get_conn()
       
        cur = conn.cursor()
        cur.execute("""
        CREATE EXTENSION IF NOT EXISTS "pgcrypto";

        CREATE TABLE IF NOT EXISTS logs (
        id BIGSERIAL PRIMARY KEY,
        session_id UUID DEFAULT gen_random_uuid(),
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        links JSONB,
        topic TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)  
        conn.commit()
        cur.close()
    except Exception as e:
        print("Erro ao criar tabelas:", e)
    finally:
        if conn:
            db_pool.putconn(conn)

# chamar init imediatamente (também chamamos create_tables antes da primeira request)
init_db_pool()
create_tables()


def save_log(session_id, question, answer, links=None, topic=None):
    """Insere um registro na tabela logs. Retorna True se ok."""
    if not db_pool:
        return False
    conn = None
    try:
        conn = get_conn()
        
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO logs (session_id, question, answer, links, topic) VALUES (%s, %s, %s, %s, %s)",
            (session_id, question, answer, json.dumps(links) if links else None, topic)
        )
        conn.commit()
        cur.close()
        db_pool.putconn(conn)
        return True
    except Exception as e:
        print("Erro ao salvar log no DB:", e)
        try:
            if conn:
                db_pool.putconn(conn,close=True)
        except:
            pass
        return False


@app.route("/api/save_cache", methods=["POST"])
def api_save_cache():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    question = data.get("question")
    answer = data.get("answer")
    links = data.get("links")
    topic = data.get("topic")
    ok = save_log(session_id, question, answer, links, topic)
    return jsonify({"ok": ok})






# ------------------------
# Configuração de domínios confiáveis
# ------------------------
TRUSTED_DOMAINS = {
    "wikipedia.org", "gov.br", "ibge.gov.br", "who.int", "un.org",
    "bbc.com", "reuters.com", "nytimes.com", "nature.com", "acm.org",
    "scielo.br", "uol.com.br", "g1.globo.com", "estadao.com.br", "folha.uol.com.br","veja.abril.com.br",
    "cnnbrasil.com.br","gazetadopovo.com.br","infomoney.com.br","correiobraziliense.com.br","agenciabrasil.ebc.com.br"
}

BLACKLIST_PARTIALS = [
    "pinterest.", "linktr.ee", "blogspot.", "medium.com/@",
    "reddit.com/r/", "tiktok.com", "instagram.com", "facebook.com", "youtube.com/shorts"
]


# ------------------------
# Cache de conversas em memória
# ------------------------
conversation_cache = {}  # { session_id: [ {role, content}, ... ] }
MAX_HISTORY = 20
SESSION_EXPIRATION = timedelta(minutes=30)  # expira após 30 min sem uso









def cleanup_sessions():
    """Remove sessões inativas do cache."""
    now = datetime.now()
    expired_keys = []
    for sid, session in conversation_cache.items():
        last_active = session.get("last_active")
        if last_active and now - last_active > SESSION_EXPIRATION:
            expired_keys.append(sid)
    for sid in expired_keys:
        del conversation_cache[sid]






@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory("static", "sitemap.xml")

# ------------------------
# Funções auxiliares
# ------------------------
def extract_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if not ext.domain:
        return ""
    return f"{ext.domain}.{ext.suffix}".lower()

def score_trust(url: str) -> int:
    score = 50
    u = url.lower()

    if u.startswith("https://"):
        score += 10

    dom = extract_domain(u)
    if any(dom.endswith(td) for td in TRUSTED_DOMAINS):
        score += 30

    if any(p in u for p in BLACKLIST_PARTIALS):
        score -= 25

    if len(u) > 120:
        score -= 5

    return max(0, min(100, score))

def label_trust(score: int) -> str:
    if score >= 80:
        return "✔️ Confiável"
    if score >= 60:
        return "🟡 Ok"
    return "⚠️ Desconfiar"

def get_favicon(url: str) -> str:
    dom = extract_domain(url)
    if not dom:
        return ""
    return f"https://www.google.com/s2/favicons?domain={dom}&sz=64"

# ------------------------
# Busca no DuckDuckGo
# ------------------------
def ddg_links(query: str, max_results: int = 8):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, region="br-pt", safesearch="moderate", max_results=max_results):
            url = r.get("href") or r.get("link") or r.get("url")
            if not url:
                continue

            title = r.get("title") or r.get("text") or extract_domain(url)
            dom = extract_domain(url)

            # Bloquear domínios indesejados
            if dom.endswith(".cn") or dom.endswith(".ru") or dom.endswith(".jp"):
                continue
            if any("\u4e00" <= ch <= "\u9fff" for ch in title):  # caracteres chineses
                continue
            if any("\u3040" <= ch <= "\u30ff" for ch in title):  # japonês
                continue
            if any("\u0400" <= ch <= "\u04ff" for ch in title):  # russo
                continue

            s = score_trust(url)

            # 🔴 NOVO: só aceita links com trust_score ≥ 80 (✔️ Confiável)
            if s < 80:
                continue

            results.append({
                "title": title,
                "url": url,
                "site": dom,
                "trust_score": s,
                "trust_label": label_trust(s),
                "favicon": get_favicon(url)
            })

    # Ordena pelo score (opcional, mas mantive)
    results.sort(key=lambda x: x["trust_score"], reverse=True)
    return results


# ------------------------
# Busca de imagens no DuckDuckGo
# ------------------------
def ddg_images(query: str, max_results: int = 3):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.images(query, region="br-pt", safesearch="moderate", max_results=max_results):
            url = r.get("image")
            thumb = r.get("thumbnail")
            title = r.get("title") or query
            if not url:
                continue

            results.append({
                "url": url,
                "thumbnail": thumb or url,
                "title": title
            })

            if len(results) >= max_results:
                break

    return results








# ------------------------
# Busca no YouTube API
# ------------------------
def youtube_videos(query: str, max_results: int = 2):
    if not YOUTUBE_API_KEY:
        return []

    # 1) Pesquisa vídeos
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results * 3,  # pegar mais resultados para filtro
        "key": YOUTUBE_API_KEY
    }

    search_res = requests.get(search_url, params=search_params).json()
    if "items" not in search_res:
        return []

    video_ids = [item["id"]["videoId"] for item in search_res["items"]]

    if not video_ids:
        return []

    # 2) Verifica vídeos disponíveis e pega detalhes
    videos_url = "https://www.googleapis.com/youtube/v3/videos"
    videos_params = {
        "part": "status,snippet,contentDetails",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY
    }

    videos_res = requests.get(videos_url, params=videos_params).json()
    results = []

    for item in videos_res.get("items", []):
        status = item["status"]
        snippet = item["snippet"]
        details = item["contentDetails"]

        # Só vídeos públicos e processados
        if status.get("uploadStatus") != "processed" or status.get("privacyStatus")  not in ["public", "unlisted"]:
            continue

        # Filtro de duração (apenas vídeos curtos < 10 min)
        duration = details.get("duration", "PT0S")
        # Convertendo ISO 8601 para segundos
        
        duration_sec = isodate.parse_duration(duration).total_seconds()
        if duration_sec > 1200:  # 10 minutos
            continue

        # Filtro de palavras-chave: remover vídeos com tags ou título não educativos
        forbidden_words = ["jogo", "gameplay", "porno",  "trailer"]
        title_lower = snippet["title"].lower()
        tags = [t.lower() for t in snippet.get("tags", [])]
        if any(word in title_lower for word in forbidden_words) or any(word in tags for word in forbidden_words):
            continue

        results.append({
            "title": snippet["title"],
            "video_id": item["id"],
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "thumbnail": snippet["thumbnails"]["default"]["url"],
            "trust_score": 80,
            "trust_label": "✔️ Confiável"
        })

        if len(results) >= max_results:
            break

    return results















# ------------------------
# OpenAI — geração de resposta
# ------------------------
def ai_answer(session_id: str,question: str, sources=None) -> str:
    if not OPENAI_API_KEY:
        return f"[Erro] Falta configurar OPENAI_API_KEY no .env.\nPergunta: {question}"

    hoje = datetime.now().strftime("%d/%m/%Y")
    
    if session_id not in conversation_cache:
        conversation_cache[session_id] = {"history": [], "topic": None}

    history = conversation_cache[session_id]["history"][-MAX_HISTORY:]


    
   

    messages=[
        {"role": "system", "content": (

            "Você é um assistente confiável e didático. "
            "Explique de forma clara, organizada e completa, mas sem ser excessivamente acadêmico. "
            "Sempre desenvolva cada ponto em 2 a 4 frases, trazendo contexto histórico, exemplos e consequências. "
            "Nunca entregue apenas listas secas: cada item deve ser explicado em parágrafos curtos. "
            "Organize a resposta em tópicos numerados (1, 2, 3...), dando um título curto e relevante para cada um.  "
            "Em cada tópico, escreva um parágrafo explicativo de 2 a 4 frases."
            "Se o tema for mais amplo, sinta-se livre para criar 4 ou mais tópicos. "
            "Não use negrito, itálico ou Markdown pesado. "
            "IMPORTANTE: Você deve sempre levar em conta o histórico recente da conversa. "
            "Se a nova pergunta for vaga (como 'e quem venceu?', 'e quando foi?', 'e onde?'), "
            "responda em relação ao mesmo tema da conversa atual. "
            "Só mude de assunto se a nova pergunta introduzir claramente um tema diferente. "
            "Nunca comece um novo assunto sem que o usuário tenha mudado explicitamente o tema."


            "Separe sempre cada item com uma quebra de linha dupla (\\n\\n). "
                        
            f"Hoje é {hoje}. "
            "Se a pergunta for sobre a data ou 'que dia é hoje', sempre responda com essa data."
        )}] 
    
    # 🔧 converte o histórico salvo para o formato que a API entende
    for turn in history:

        if "q" in turn:
            messages.append({"role": "user", "content": turn["q"]})
        if "a" in turn:
            messages.append({"role": "assistant", "content": turn["a"]})

    # adiciona a pergunta atual
    user_message = {"role": "user", "content": question}
    messages.append(user_message)
    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(

            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=450
    )
    answer = completion.choices[0].message.content.strip()
    # 🔧 mantém histórico no mesmo formato (q/a)
    conversation_cache[session_id]["history"].append({"q": question, "a": answer})
    conversation_cache[session_id]["history"] = conversation_cache[session_id]["history"][-MAX_HISTORY:]

    return answer
    

def ai_fallback_source(answer: str) -> dict:
    """Pede para a IA sugerir uma fonte quando DDG não retorna nada confiável"""
    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Você é um assistente que sugere fontes confiáveis."},
            {"role": "user", "content": f"Baseado nessa resposta: {answer}\nIndique um link confiável como fonte oficial."}
        ],
        temperature=0.3,
        max_tokens=200
    )
    url = completion.choices[0].message.content.strip()
    if not url.startswith("http"):
        return None
    return {
        "title": extract_domain(url),
        "url": url,
        "site": extract_domain(url),
        "trust_score": 70,
        "trust_label": "🟡 Ok",
        "favicon": get_favicon(url)
    }

def detect_topic(question: str, answer: str, history: list, old_topic: str = None) -> str:
    """Detecta o tema principal da conversa atual com base na pergunta, resposta e histórico recente.
    Retorna um rótulo curto (até 5 palavras) representando o tema."""
    # monta histórico recente de forma segura (só itens dict com role/content)
    recent_items = []
    if history:
        for msg in history[-6:]:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                recent_items.append(f"{msg['role']}: {msg['content']}")
    recent_history = "\n".join(recent_items)

    topic_context = (
        f"Histórico recente:\n{recent_history}\n\n"
        f"Pergunta atual: {question}\nResposta atual: {answer}\n\n"
        f"Tema anterior: {old_topic or 'nenhum'}"
    )

    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é responsável por identificar o tema principal de uma conversa. "
                    "Responda com até 5 palavras específicas e concisas (ex.: 'Segunda Guerra Mundial', "
                    "'Eleições EUA 2024', 'MasterChef Brasil'). "
                    "Se a pergunta atual for continuação do mesmo assunto do histórico, mantenha exatamente o mesmo tema. "
                    "Só crie um novo tema se houver mudança clara de assunto. "
                    "Evite termos vagos como 'vitórias', 'eventos' ou 'disputas'."
                ),
            },
            {"role": "user", "content": topic_context},
        ],
        temperature=0.0,
        max_tokens=100,
    )


    
    
    return completion.choices[0].message.content.strip()

# ------------------------
# Rotas Flask
# ------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    mode = data.get("mode", "normal")  # 👈 novo
    session_id = data.get("session_id") or str(uuid.uuid4())  # ← garante ID único por usuário
    # Limpa sessões antigas antes de continuar
    cleanup_sessions()
    if not question:
        return jsonify({"error": "Pergunta vazia"}), 400
     
     # 👇 DESVIO PARA O MODO FATO OU FAKE
    if mode == "fakecheck":
        result = factcheck_answer(session_id, question)
        # 🔎 Puxa links confiáveis via DGS/DDG (igual ao modo normal)
        all_links = ddg_links(question, max_results=8)
        links = [l for l in all_links if l["trust_label"] == "✔️ Confiável"]
        
        # 🔗 Monta resposta no mesmo formato do normal
        response = {
        "session_id": session_id,
        "answer": result["answer"],   # só o texto do fact-check
        "label": result.get("label"), # "fato", "fake" ou "inconclusivo"
        "links": links,
        }
        try:
            save_log(session_id, question, result["answer"], links=links,  topic="fato_ou_fake")
        except Exception as e:
            print("save_log falhou:", e)
        return jsonify(result)
    
    # garante que a sessão existe
    if session_id not in conversation_cache:
        conversation_cache[session_id] = {"history": [], "topic": None}

    
    # Atualiza timestamp de atividade da sessão
    conversation_cache[session_id]["last_active"] = datetime.now()

    # 1) Gerar resposta da IA primeiro
    answer = ai_answer(session_id, question)

    # 2) Remove "Fontes:" caso tenha
    if "Fontes:" in answer:
        answer = answer.split("Fontes:")[0].strip()

    # 3) Detecta o tópico atual usando a pergunta + resposta + histórico
    history_list = conversation_cache[session_id]["history"]
    old_topic = conversation_cache[session_id].get("topic")
    new_topic = detect_topic(question, answer, history_list, old_topic)

    # 4) Só buscar links e vídeos se houver mudança de tópico
    if new_topic and new_topic.lower() != (old_topic or "").lower():
        all_links = ddg_links(new_topic, max_results=8)
        links = [l for l in all_links if l["trust_label"] == "✔️ Confiável"]
        videos = youtube_videos(new_topic, max_results=1)
        images = ddg_images(new_topic, max_results=5)


        conversation_cache[session_id]["topic"] = new_topic
        conversation_cache[session_id]["links"] = links
    else:
        links = conversation_cache[session_id].get("links", [])
        videos = []



    # Atualiza histórico
    conversation_cache[session_id]["history"].append({"q": question, "a": answer})
    conversation_cache[session_id]["history"] = conversation_cache[session_id]["history"][-MAX_HISTORY:]

    # Tenta salvar no banco (não atrapalha fluxo mesmo que falhe)
    try:
        links_for_save = conversation_cache[session_id].get("links", [])
        topic_for_save = conversation_cache[session_id].get("topic")
        save_log(session_id, question, answer, links=links_for_save, topic=topic_for_save)
    except Exception as e:
        print("save_log falhou:", e)


     

    return jsonify({
        "session_id": session_id,
        "answer": answer,
        "links": links,
        "videos": videos, 
        "images": images
    })





if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
