# factcheck_service.py
import os
import re
from datetime import datetime
from openai import OpenAI



OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

client = OpenAI(api_key=OPENAI_API_KEY)

def extract_urls(text: str):
    """Extrai URLs de um texto usando regex"""
    url_pattern = re.compile(r'(https?://[^\s\)\]]+)')
    return url_pattern.findall(text)

def factcheck_answer(session_id: str, question: str):
    from api_search import ddg_images  # import local para quebrar o ciclo
    from api_search import ddg_links  # certifique-se de importar a função de busca
    hoje = datetime.now().strftime("%d/%m/%Y")

    messages = [
        {"role": "system", "content": (
           "Você está em modo de checagem de fatos.\n"
        "Sempre comece a resposta com o cabeçalho: ✅ FATO | ❌ FAKE | ⚠️ INCONCLUSIVO.\n\n"
        "Depois, explique de forma organizada em tópicos numerados (1, 2, 3...).\n"
        "Cada tópico deve ter um título curto e um parágrafo de até 3 frases, "
        "trazendo contexto, exemplos ou referências simples.\n"
        "Não use 'Resumo' ou 'Explicação' como seção, apenas os tópicos.\n"
        "Não seja acadêmico demais — fale de forma acessível, mas clara.\n"
        f"Hoje é {hoje}."
        )},
        {"role": "user", "content": question}
    ]

    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=450
    )

    answer = completion.choices[0].message.content.strip()

    # --- Busca links usando DDG ---
    all_links = ddg_links(question, max_results=4)  # pega 4 fontes confiáveis
    links = [l for l in all_links if l.get("trust_label") == "✔️ Confiável"]

   

    

    return {
        "session_id": session_id,
        "answer": answer,
        "links": links,    # 🔑 aqui é o que o front espera
        
        
    }
