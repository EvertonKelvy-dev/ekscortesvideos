const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, ...filhos) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...filhos);
  return e;
};
const ETAPAS = ["Obter o vídeo", "Transcrever a fala", "Detectar silêncios",
  "Escolher os melhores momentos", "Ajustar pontos de corte", "Exportar os vídeos"];

let fonte = "arquivo", modo = "curto", arquivo = null, jobId = null, timer = null;

// ---------- servidor local: o site é só a tela, o programa roda no seu PC ----------
const LOCAL = ["localhost", "127.0.0.1"].includes(location.hostname);
const HOSPEDADO = location.protocol.startsWith("http") && !LOCAL;  // ex.: GitHub Pages
let API = "";
async function detectarApi() {
  const bases = ["http://localhost:5000", "http://127.0.0.1:5000"];
  if (!HOSPEDADO) bases.unshift("");  // aberto pelo próprio Flask: mesma origem
  for (const base of bases) {
    try {
      const r = await fetch(base + "/api/saude", base ? { targetAddressSpace: "loopback" } : {});
      if ((r.headers.get("content-type") || "").includes("json")) { API = base; return await r.json(); }
    } catch (e) { /* tenta o próximo */ }
  }
  return null;
}
function avisarAmbiente(s) {
  if (!s) return mostrarErro("Não encontrei o programa. Dê dois cliques em iniciar.bat no seu PC, deixe a janela preta aberta e tente de novo.");
  if (s.problemas.length) mostrarErro("Antes de começar:\n• " + s.problemas.join("\n• "));
}
function repoUrl() {  // descobre o repositório pelo endereço do GitHub Pages
  const m = location.hostname.match(/^(.+)\.github\.io$/), repo = location.pathname.split("/")[1];
  return m && repo ? `https://github.com/${m[1]}/${repo}` : "";
}
let tentativa = null;
function atualizarConexao(s) {
  const on = !!s;
  $("#status").className = "status " + (on ? "on" : "off");
  $("#status-txt").textContent = on ? "Programa conectado" : "Programa desligado";
  $("#offline").hidden = on;
  const url = repoUrl();
  $("#baixar-projeto").hidden = !url;
  if (url) $("#baixar-projeto").href = url + "/archive/refs/heads/main.zip";
  clearTimeout(tentativa);
  // no PC tenta sozinho; no site publicado só quando a pessoa clica (o navegador pede permissão)
  if (!on && !HOSPEDADO) tentativa = setTimeout(procurar, 4000);
}
async function procurar(manual = false) {
  const s = await detectarApi();
  atualizarConexao(s);
  const msg = $("#offline-msg");
  msg.hidden = !!s || manual !== true;
  if (!msg.hidden) {
    msg.textContent = location.protocol === "file:"
      ? "Abra o programa pelo endereço http://localhost:5000, e não clicando no arquivo index.html."
      : "Não achei o programa. Confira se a janela preta do iniciar.bat está aberta. Se o navegador perguntou sobre " +
        "acesso à rede local e você negou, clique no cadeado ao lado do endereço, abra as configurações do site, " +
        "permita o acesso à rede local e tente de novo. Se for o seu site no GitHub Pages, confira também a linha " +
        "EKS_ORIGENS_PERMITIDAS no arquivo .env.";
  }
  if (s && s.problemas.length) avisarAmbiente(s);
  return s;
}
$("#conectar").onclick = () => procurar(true);
if (HOSPEDADO) atualizarConexao(null); else procurar();

// ---------- formulário ----------
document.querySelectorAll(".aba").forEach((b) => b.onclick = () => {
  fonte = b.dataset.fonte;
  document.querySelectorAll(".aba").forEach((x) => x.classList.toggle("ativa", x === b));
  $("#area-arquivo").hidden = fonte !== "arquivo";
  $("#area-link").hidden = fonte !== "link";
});
document.querySelectorAll("#modo button").forEach((b) => b.onclick = () => {
  modo = b.dataset.modo;
  document.querySelectorAll("#modo button").forEach((x) => x.classList.toggle("ativa", x === b));
});
function escolher(f) {
  arquivo = f;
  $("#drop-texto").textContent = f ? `${f.name} (${(f.size / 1048576).toFixed(0)} MB)` : "Arraste o vídeo aqui ou clique para escolher";
}
$("#arquivo").onchange = (e) => escolher(e.target.files[0]);
const drop = $("#drop");
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("sobre"); };
drop.ondragleave = () => drop.classList.remove("sobre");
drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("sobre"); escolher(e.dataTransfer.files[0]); };

// sem fala não há o que transcrever: desliga precisão e idioma
$("#fala").onchange = () => {
  const semFala = $("#fala").value === "nao";
  $("#whisper").disabled = semFala;
  $("#idioma").disabled = semFala;
};

function mostrarErro(msg) { $("#erro").textContent = msg; $("#erro").hidden = !msg; }

$("#gerar").onclick = async () => {
  mostrarErro("");
  if (fonte === "arquivo" && !arquivo) return mostrarErro("Escolha um vídeo primeiro.");
  if (fonte === "link" && !$("#link").value.trim()) return mostrarErro("Cole o link do vídeo.");

  const saude = await detectarApi();  // confere servidor e ambiente ANTES de subir o arquivo
  atualizarConexao(saude);
  if (!saude || saude.problemas.length) return avisarAmbiente(saude);
  if (fonte === "link" && !saude.link_ok) return mostrarErro("Para usar links, instale:  pip install yt-dlp");

  const fd = new FormData();
  if (fonte === "arquivo") fd.append("arquivo", arquivo); else fd.append("link", $("#link").value.trim());
  fd.append("modo", modo);
  fd.append("qtd", $("#qtd").value);
  fd.append("whisper", $("#whisper").value);
  fd.append("idioma", $("#idioma").value);
  fd.append("fala", $("#fala").value);

  $("#gerar").disabled = true;
  mostrarProgresso();
  const xhr = new XMLHttpRequest();
  xhr.open("POST", API + "/api/jobs");
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const p = Math.round((e.loaded / e.total) * 100);
      $("#prog-msg").textContent = `Enviando o vídeo… ${p}%`;
      $("#barra").style.width = p * 0.1 + "%";
    }
  };
  xhr.onload = () => {
    let r = {};
    try { r = JSON.parse(xhr.responseText); } catch (e) { /* resposta não era JSON */ }
    if (xhr.status !== 200) return falhar(r.erro || `O servidor respondeu com erro ${xhr.status}. Veja o terminal onde o app está rodando.`);
    jobId = r.id;
    timer = setInterval(consultar, 1500);
  };
  xhr.onerror = () => falhar("Não consegui falar com o servidor.");
  xhr.send(fd);
};

// ---------- progresso ----------
function mostrarProgresso() {
  $("#formulario").hidden = true;
  $("#resultado").hidden = true;
  $("#progresso").hidden = false;
  $("#prog-titulo").textContent = "Processando…";
  $("#etapas").replaceChildren(...ETAPAS.map((t) => el("li", { textContent: t })));
}
function falhar(msg) {
  clearInterval(timer);
  $("#progresso").hidden = true;
  $("#formulario").hidden = false;
  $("#gerar").disabled = false;
  mostrarErro(msg);
}
async function consultar() {
  let r;
  try { r = await (await fetch(`${API}/api/jobs/${jobId}`)).json(); }
  catch (e) { return; }  // falha momentânea: tenta de novo no próximo ciclo
  if (r.erro) return falhar(r.erro);
  if (r.status === "erro") return falhar(r.mensagem);
  $("#prog-msg").textContent = r.mensagem;
  $("#barra").style.width = Math.max(10, (r.etapa / ETAPAS.length) * 100) + "%";
  [...$("#etapas").children].forEach((li, i) => {
    li.className = i + 1 < r.etapa ? "feito" : i + 1 === r.etapa ? "atual" : "";
  });
  if (r.status === "pronto") { clearInterval(timer); mostrarResultado(r); }
}

// ---------- resultado ----------
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function mostrarResultado(r) {
  $("#progresso").hidden = true;
  $("#resultado").hidden = false;
  $("#res-titulo").textContent = r.cortes.length === 1 ? "1 corte pronto" : `${r.cortes.length} cortes prontos`;
  $("#res-aviso").textContent = r.aviso || "";
  $("#res-aviso").hidden = !r.aviso;
  $("#zip").href = `${API}/api/jobs/${jobId}/zip`;
  $("#cortes").replaceChildren(...r.cortes.map(criarCard));
}

function criarCard(c, i) {
  const video = el("video", { src: `${API}/files/${jobId}/${c.arquivo}`, controls: true, preload: "metadata" });
  const dur = el("span", { className: "suave", textContent: `${(c.fim - c.inicio).toFixed(0)}s · ${mmss(c.inicio)} → ${mmss(c.fim)}` });
  const ini = el("input", { type: "number", step: "0.1", min: "0", value: c.inicio });
  const fim = el("input", { type: "number", step: "0.1", min: "0", value: c.fim });

  const recortar = el("button", { className: "botao", textContent: "✂ Recortar de novo" });
  recortar.onclick = async () => {
    recortar.disabled = true; recortar.textContent = "Cortando…";
    try {
      const resp = await fetch(`${API}/api/jobs/${jobId}/cortes/${i}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inicio: ini.value, fim: fim.value }),
      });
      const r = await resp.json();
      if (!resp.ok) throw new Error(r.erro || "Erro ao recortar.");
      Object.assign(c, r);
      video.src = `${API}/files/${jobId}/${c.arquivo}?v=${Date.now()}`;
      dur.textContent = `${(c.fim - c.inicio).toFixed(0)}s · ${mmss(c.inicio)} → ${mmss(c.fim)}`;
    } catch (e) { alert(e.message); }
    recortar.disabled = false; recortar.textContent = "✂ Recortar de novo";
  };

  const copiar = el("button", { className: "botao", textContent: "📋 Copiar texto" });
  copiar.onclick = async () => {
    await navigator.clipboard.writeText(`${c.titulo}\n\n${c.descricao}\n\n${c.hashtags.join(" ")}`);
    copiar.textContent = "✓ Copiado!";
    setTimeout(() => (copiar.textContent = "📋 Copiar texto"), 1500);
  };
  const baixar = el("a", { className: "botao", textContent: "⬇ Baixar", href: `${API}/files/${jobId}/${c.arquivo}?baixar=1`, download: c.arquivo });

  return el("article", { className: "corte" }, video,
    el("div", { className: "corpo" },
      el("span", { className: "nota", textContent: `Potencial ${c.nota}/100` }),
      el("h3", { textContent: c.titulo }),
      dur,
      el("p", { className: "desc", textContent: c.descricao }),
      el("div", { className: "tags", textContent: c.hashtags.join(" ") }),
      el("p", { className: "desc", textContent: "💡 " + c.justificativa }),
      el("div", { className: "tempos" },
        el("label", {}, "Início (s)", ini), el("label", {}, "Fim (s)", fim)),
      el("div", { className: "acoes" }, recortar, copiar, baixar)));
}

$("#novo").onclick = () => {
  $("#resultado").hidden = true;
  $("#formulario").hidden = false;
  $("#gerar").disabled = false;
  escolher(null);
};
