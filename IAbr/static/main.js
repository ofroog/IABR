document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ask-form");
    const input = document.getElementById("question");
    const chat = document.getElementById("chat");





    // ===== Toggle do modo "Fato ou Fake" =====
    let chatMode = "normal"; // default
    const askbar = document.querySelector(".askbar"); // pega a barra de digita

    const factcheckToggle = document.createElement("button");
    factcheckToggle.type = "button"; // ⬅️ isso impede que o form seja submetido
    factcheckToggle.textContent = "🕵️ Checar Fatos";
    factcheckToggle.className = "factcheck-toggle";

    // coloca no topo da askbar
    askbar.prepend(factcheckToggle);

    factcheckToggle.addEventListener("click", () => {
        if (chatMode === "normal") {
            chatMode = "fakecheck";
            factcheckToggle.classList.add("active");
            // Mensagem automática no chat
            const message = document.createElement("div");
            message.className = "msg bot system-message"; // classe extra para estilo
            message.innerText = "🕵️ Você entrou no modo Fato ou Fake. As respostas agora indicarão se uma afirmação é verdadeira, falsa ou inconclusiva.";
            chat.appendChild(message);
            scrollChatToBottom();
        } else {
            chatMode = "normal";
            factcheckToggle.classList.remove("active");
            // Mensagem ao sair do modo
            const message = document.createElement("div");
            message.className = "msg bot system-message";
            message.innerText = "🔄 Você saiu do modo Fato ou Fake. As respostas voltam ao modo normal.";
            chat.appendChild(message);
            scrollChatToBottom();
        }
        console.log("Modo do chat:", chatMode);
    });



    // 🔑 Armazena o session_id 
    let sessionId = null;
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;

        gtag('event', 'chat_question', {
            'question_text': question
        });

        addMessage(question, "user");
        updateSidebar(question); // só adiciona a primeira vez
        input.value = "";
        showTyping();

        try {
            const res = await fetch("/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question,
                    session_id: sessionId, // 🔑 manda o session_id junto
                    mode: chatMode   // 👈 manda o modo junto
                })
            });

            const data = await res.json();
            hideTyping();

            if (data.error) {
                addMessage("⚠️ Erro: " + data.error, "bot");
            } else {
                // 🔑 Atualiza session_id se vier um novo do backend
                if (data.session_id && data.session_id !== sessionId) {
                    sessionId = data.session_id;

                }

                addMessage(data.answer, "bot");
                if (chatMode === "fakecheck") {
                    const lastMsg = chat.lastElementChild;
                    const bubble = lastMsg.querySelector(".bubble");

                    lastMsg.classList.add("fakecheck");

                    // adiciona a classe conforme o selo
                    if (data.label) {
                        lastMsg.classList.add(data.label.toLowerCase());
                        // ex: "fato", "fake", "inconclusivo"
                    }

                    // mantém quebra de linha legível
                    bubble.innerHTML = data.answer.replace(/\n/g, "<br>");



                }

                const lastMsg = chat.lastElementChild; // pega o container da resposta
                addExportMenu(lastMsg, data.answer, data.links);

                if (data.images && data.images.length > 0) {
                    const button = document.createElement("button");
                    button.textContent = "Imagens";
                    button.className = "show-images-btn";  // ⬅️ classe CSS
                    chat.appendChild(button);
                    scrollChatToBottom();

                    let imagesShown = false;
                    button.addEventListener("click", () => {
                        if (!imagesShown) {
                            addImages(data.images);
                            imagesShown = true;
                            button.disabled = true;
                        }
                    });
                }


                addLinks(data.links);
                if (data.videos && data.videos.length > 0) {
                    addVideos(data.videos);
                }
            }
        } catch (err) {
            console.error(err);
            hideTyping();
            addMessage("❌ Erro de conexão com o servidor.", "bot");
        }
    });

    // Função para adicionar botão exportar com menu PDF/Word
    function addExportMenu(answerContainer, answerText, links) {
        const container = document.createElement("div");
        container.className = "export-btn-wrapper"; // garante posição relativa

        // Botão principal
        const mainBtn = document.createElement("button");
        mainBtn.textContent = "Exportar ⬇️";
        mainBtn.className = "export-btn";
        container.appendChild(mainBtn);

        // Botão Compartilhe
        const shareBtn = document.createElement("button");
        shareBtn.textContent = "Compartilhe 📤";
        shareBtn.className = "share-btn";
        container.appendChild(shareBtn);

        // Evento de clique para WhatsApp
        shareBtn.addEventListener("click", () => {
            let text = answerText;

            if (links && links.length > 0) {
                text += "\n\nFontes:\n";
                links.forEach(link => {
                    text += `${link.title}: ${link.url}\n`;
                });
            }

            // Adiciona carimbo da plataforma
            text += "\n\n🔗 Resposta gerada por Roog: https://www.roog.com.br";

            const url = `https://api.whatsapp.com/send?text=${encodeURIComponent(text)}`;
            window.open(url, "_blank");
        });






        // Menu escondido
        const menu = document.createElement("div");
        menu.className = "export-menu";
        menu.innerHTML = `
        <div class="export-pdf">Baixar PDF</div>
        <div class="export-word">Baixar Word</div>
    `;
        container.appendChild(menu);

        // --- Eventos das opções ---
        menu.querySelector(".export-pdf").addEventListener("click", () => {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF();
            doc.setFontSize(12);

            // Quebra automática de texto em várias linhas
            const textLines = doc.splitTextToSize(answerText, 180);
            doc.text(textLines, 10, 20);

            // Posição inicial após o texto
            let y = 20 + textLines.length * 6;

            if (links && links.length > 0) {
                doc.setFontSize(10);
                doc.text("Fontes:", 10, y);
                links.forEach(link => {
                    y += 10;
                    doc.text(`${link.title}: ${link.url}`, 10, y);
                });
            }
            doc.save("resposta.pdf");
            menu.style.display = "none";

        });

        menu.querySelector(".export-word").addEventListener("click", () => {
            let content = `
            <html xmlns:o='urn:schemas-microsoft-com:office:office'
                  xmlns:w='urn:schemas-microsoft-com:office:word'
                  xmlns='http://www.w3.org/TR/REC-html40'>
            <head><meta charset="utf-8"></head>
            <body>
                <h2>Resposta:</h2>
                <p>${answerText.replace(/\n/g, "<br>")}</p>
                `;

            if (links && links.length > 0) {
                content += "<h3>Fontes:</h3><ul>";
                links.forEach(link => {
                    content += `<li><a href="${link.url}">${link.title}</a></li>`;
                });
                content += "</ul>";
            }

            content += `</body></html>`;

            const blob = new Blob([content], {
                type: "application/vnd.ms-word;charset=utf-8"
            });
            const url = URL.createObjectURL(blob);

            const a = document.createElement("a");
            a.href = url;
            a.download = "resposta.doc";
            a.click();

            URL.revokeObjectURL(url);
            menu.style.display = "none";
        });

        // Toggle menu
        mainBtn.addEventListener("click", () => {
            menu.style.display = menu.style.display === "none" ? "block" : "none";
        });

        // Fecha menu se clicar fora
        document.addEventListener("click", (e) => {
            if (!container.contains(e.target)) {
                menu.style.display = "none";
            }
        });

        const bubble = answerContainer.querySelector(".bubble");
        bubble.appendChild(container);



    }









































    function addImages(images) {
        if (!images || images.length === 0) return;

        // Cria container das imagens
        const container = document.createElement("div");
        container.className = "chat-images";
        container.style.display = "flex";
        container.style.gap = "10px";
        container.style.flexWrap = "wrap";
        container.style.marginTop = "10px";

        let imagesLoaded = 0; // <-- inicializa o contador

        images.forEach(img => {
            const imageEl = document.createElement("img");
            imageEl.src = img.url;  // url do backend
            imageEl.alt = img.title || "Imagem relacionada";
            imageEl.style.width = "120px";
            imageEl.style.height = "120px";
            imageEl.style.objectFit = "cover";
            imageEl.style.borderRadius = "8px";
            imageEl.style.cursor = "pointer";

            // ao clicar, abre a imagem em nova aba
            imageEl.addEventListener("click", () => window.open(img.url, "_blank"));


            // incrementa contador e rola para baixo quando cada imagem carregar
            imageEl.addEventListener("load", () => {
                imagesLoaded++;
                if (imagesLoaded === images.length) {
                    scrollChatToBottom();
                }
            });
            container.appendChild(imageEl);
        });

        chat.appendChild(container);

    }







    function updateSidebar(userMessage) {
        const sidebar = document.getElementById("chat-history");
        // só cria o item se o sidebar ainda estiver vazio
        if (sidebar.children.length === 0) {
            const li = document.createElement("li");
            li.className = "user";
            li.textContent = userMessage;
            sidebar.appendChild(li);
        }
    }



    // colocar essa função perto do topo, dentro do DOMContentLoaded
    function escapeHtml(str) {
        if (!str && str !== 0) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }








    function addVideos(videos) {
        if (!videos || videos.length === 0) return;

        videos.forEach(video => {
            if (!video.video_id) return; // segurança extra

            const container = document.createElement("div");
            container.className = "chat-video";

            const titleEsc = escapeHtml(video.title || 'Vídeo relacionado');

            container.innerHTML = `
            <div class="video-header">
                <div class="video-title">${titleEsc}</div>
                <!-- reaproveita a classe .trust para visual consistente com os links -->
                <span class="trust">✔️ Confiável</span>
            </div>
            <div class="video-frame">
                <iframe
                    src="https://www.youtube.com/embed/${encodeURIComponent(video.video_id)}"
                    title="${titleEsc}"
                    frameborder="0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen
                    loading="lazy"></iframe>
            </div>
        `;

            chat.appendChild(container);
            scrollChatToBottom();
        });



    }






    function showTyping() {
        const typing = document.createElement("div");
        typing.className = "msg bot typing";
        typing.id = "typing-indicator";

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        bubble.innerHTML = `
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
    `;

        typing.appendChild(bubble);
        chat.appendChild(typing);
        scrollChatToBottom();
    }


    function hideTyping() {
        const typing = document.getElementById("typing-indicator");
        if (typing) typing.remove();
    }






    // ===== substitua por esta função =====
    function scrollChatToBottom() {
        const doScrollElement = () => {
            try {
                chat.scrollTop = chat.scrollHeight;
            } catch (e) {
                // fallback para window se algo falhar
                window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            }
        };

        const doScrollWindow = () => {
            window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
        };

        // verifica se o container é rolável
        const comp = window.getComputedStyle(chat);
        const isContainerScrollable = (comp.overflowY === 'auto' || comp.overflowY === 'scroll' || chat.scrollHeight > chat.clientHeight);

        // se não for rolável, rola a página inteira (fallback)
        if (!isContainerScrollable) {
            requestAnimationFrame(() => doScrollWindow());
            return;
        }

        // Se houver mídias (img, iframe, video) que podem carregar assíncronamente,
        // espera que carreguem (ou aguarda pequenos ticks de render) antes de rolar.
        const media = chat.querySelectorAll('img, iframe, video');
        if (media.length === 0) {
            // sem mídia, rola após próximo frame e reforça com timeout curto
            requestAnimationFrame(() => {
                doScrollElement();
                setTimeout(doScrollElement, 60);
            });
            return;
        }

        // caso contenha mídia, aguarda carregamento das que não estão prontas
        let pending = 0;
        media.forEach(el => {
            if (el.tagName === 'IFRAME') {
                // Iframes não têm 'complete'; escuta 'load' se necessário
                const src = el.getAttribute('src') || '';
                if (!src) {
                    // se não tem src, ignora
                } else {
                    // se já tem altura (renderado), considera pronto; caso contrário, espera load
                    const rect = el.getBoundingClientRect();
                    if (rect.height > 0) {
                        // possivelmente já renderado
                    } else {
                        pending++;
                        el.addEventListener('load', () => {
                            pending--;
                            if (pending === 0) requestAnimationFrame(doScrollElement);
                        }, { once: true });
                    }
                }
            } else if (el.tagName === 'IMG' || el.tagName === 'VIDEO') {
                if (el.complete || (el.readyState && el.readyState >= 2)) {
                    // pronto
                } else {
                    pending++;
                    el.addEventListener('load', () => {
                        pending--;
                        if (pending === 0) requestAnimationFrame(doScrollElement);
                    }, { once: true });
                    el.addEventListener('error', () => {
                        pending--;
                        if (pending === 0) requestAnimationFrame(doScrollElement);
                    }, { once: true });
                }
            }
        });

        // se não ficou nada pendente, rola imediatamente (com pequeno atraso para render)
        if (pending === 0) {
            requestAnimationFrame(() => {
                doScrollElement();
                setTimeout(doScrollElement, 60);
            });
        }
    }

    // ===== logo após const chat = document.getElementById("chat"); cole o MutationObserver: =====
    const chatObserver = new MutationObserver((mutations) => {
        // quando houver nodes adicionados ao chat, tenta rolar para baixo
        for (const m of mutations) {
            if (m.addedNodes && m.addedNodes.length > 0) {
                // garante que a rolagem acontece no próximo ciclo do browser
                requestAnimationFrame(() => {
                    // pequena verificação extra: se o chat tem mídia, a função lida com isso
                    scrollChatToBottom();
                });
                break;
            }
        }
    });

    // observa adições e mudanças internas
    chatObserver.observe(chat, { childList: true, subtree: true });





    function addMessage(text, sender = "bot") {
        const msg = document.createElement("div");
        msg.className = `msg ${sender}`;

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = text;

        msg.appendChild(bubble);
        chat.appendChild(msg);
        scrollChatToBottom();
    }

    function addToSidebar(text) {
        const historyList = document.getElementById("chat-history");
        if (!historyList) return;

        // Pega as primeiras 8 palavras
        let preview = text.split(" ").slice(0, 8).join(" ");
        if (text.split(" ").length > 8) preview += "...";

        const li = document.createElement("li");
        li.textContent = preview;
        li.classList.add("user"); // classe só pra estilizar se quiser
        historyList.appendChild(li);
    }


    function addLinks(links) {
        if (!links || links.length === 0) return;

        const linksDiv = document.createElement("div");
        linksDiv.className = "sources";

        links.forEach(link => {
            const item = document.createElement("div");
            item.className = "source-item";

            item.innerHTML = `
                <img src="${link.favicon}" alt="icon" class="favicon" />
                <a href="${link.url}" target="_blank">${link.title}</a>
                <span class="trust">${link.trust_label}</span>
            `;

            linksDiv.appendChild(item);
        });

        chat.appendChild(linksDiv);
        scrollChatToBottom();  // <- e aqui

        linksDiv.addEventListener("click", (e) => {
            const a = e.target.closest("a");
            if (a) {
                gtag('event', 'chat_link_click', {
                    'link_url': a.href
                });
            }
        });

    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        gtag('event', 'chat_question', {
            'question_text': question
        });

        addMessage(question, "user");
        updateSidebar(question);
        input.value = "";
        showTyping();

        try {
            const res = await fetch("/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question,
                    mode: chatMode
                }),

            });

            const data = await res.json();
            hideTyping();

            if (data.error) {
                addMessage("⚠️ Erro: " + data.error, "bot");
            } else {
                addMessage(data.answer, "bot");
                addLinks(data.links);
                if (data.videos && data.videos.length > 0) {
                    addVideos(data.videos);
                }

            }
        } catch (err) {
            console.error(err);
            hideTyping();
            addMessage("❌ Erro de conexão com o servidor.", "bot");
        }
    });
});