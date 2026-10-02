# Sensewright v2

**Companheiro de IA & Diretor de Mundo para The Sims 4** — Um mod de arquitetura dual-process que dá a cada Sim uma vida interior: sonhos, memórias, personalidade em evolução e um confidente digital oculto com quem você pode conversar. Um Diretor de Mundo molda a vizinhança através de influência suave e NPCs catalisadores, tudo sem custo obrigatório de API.

---

## O Que Faz

- **Confidente Digital Oculto**: Um `SimInfo` nativo em uma household oculta aparece no painel de Relacionamentos. Converse via Celular (SMS) ou Computador (Chat/Email). Conversas aumentam as necessidades Social/Diversão, geram Desejos nativos e produzem Sentimentos nativos (Adoração, Magoado, Rancor, etc.).
- **Vida Interior Autônoma**: Cada Sim com assento roda `sim.impulse` (pensamentos ociosos), `sim.reaction` (a eventos salientes), `sim.dream` (surrealismo noturno alimentando impulsos do dia seguinte), `sim.cognition` (plano diário viesado por sonhos e deveres) e `sim.evolve` (mudanças de postura, atualização de Gostos/Desgostos nativos, propostas de troca de traço).
- **Memória & Narrativa**: Armazenamento SQLite + FTS5 (BM25) com decaimento gradual, consolidação, compactação e memórias legadas imunes a poda. Shadow DB (working/committed/ring-buffer) sincroniza transacionalmente com saves do TS4.
- **Diretor de Mundo (God Director)**: Cria arcos narrativos, gerencia Zeitgeist, sussurra nos sonhos (influência suave) e marioneteia NPCs catalisadores (`god.puppeteer`) que visitam lotes, tocam campainhas e provocam reações genuínas dos seus Sims soberanos. Três modos: `AUTONOMOUS`, `CO_DIRECTOR`, `SANDBOX`.
- **UI Dual**: **Menu Rápido** no jogo (menu de torta em qualquer Sim + painel Shift-clique) e **Web Studio** baseado em navegador (`/ui`) para painéis Inspector, Roteiro e Configuração.
- **Operação Zero-Key**: Todos os 33 propósitos têm fallbacks determinísticos localizados. O mod funciona totalmente sem nenhuma chave de API.

---

## Arquitetura Dual-Process

```
┌─ The Sims 4 (Processo do Jogo — Python 3.7) ────────────────────┐     ┌─ Sidecar (FastAPI — Python 3.10+/3.12+) ──────────────┐
│ Main Thread (GAME_TICK via Lot 51 Core):                        │     │  Routers: lifecycle / chat / autonomy / god / memory    │
│  ├─ state_collector  (deltas de pulso, census, eventos)         │     │  LLMScheduler   → fila única, tiers, SLOs, deep win   │
│  ├─ tool_executor    (GameLever, ArchetypeResolver)             │     │  ContextAssembler → fatiamento de perfil, teto de TPM │
│  ├─ native_hooks     (SimInfo Oculto, Diário, Sentimentos)      │     │  ModelRouter    → propósito → RoutePlan             │
│  ├─ ui_manager       (4 canais visuais, chat encadeado)         │     │  ProviderChain  → RPM/RPD/TPM, circuit breaker, swap  │
│  └─ filas em RAM     (outbound_q / inbound_intents_q)           │     │  SaveVault      → Working DB ↔ Committed DB + FTS5    │
│         │▲ (lock-free, < 0.1 ms)                                │     │  Web Studio     → Inspector SPA, Roteiro, Setup       │
│ Worker Thread (daemon, urllib.request):                         │ HTTP│                                                         │
│  └─ HTTP I/O ───────────────────────────────────────────────────┼────▶│                                                         │
└──────────────────────────────────────────────────────────────────┘     └─────────────────────────────────────────────────────────┘
```

**Regras Arquiteturais Principais**
- **Isolamento de Thread**: Main thread apenas enfileira em `outbound_q` e drena `inbound_intents_q`. Todo I/O HTTP roda em uma única worker thread daemon.
- **Restrições Python 3.7**: Sem walrus (`:=`), sem `match/case`, sem union types, sem `from __future__ import annotations`, sem deps de terceiros além de S4CL e Lot 51 Core.
- **Relógios Duplos**: Wall-clock (segundos reais) para timeouts HTTP, rate limits, SLOs. Sim-clock (`world_sim_tick`, minutos-sim) para toda gameplay: atrasos de intents, cooldowns sociais, decaimento de memória, agendamento de sonhos. Quando `clock_speed == 0` (pausado), despacho de intents congela.

---

## Requisitos

| Componente | Versão | Notas |
|------------|---------|-------|
| The Sims 4 | 1.90+ (patch atual) | Apenas jogo base; DLC não obrigatório |
| S4CL (Sims 4 Community Library) | Release mais recente | Dependência obrigatória — instale separadamente |
| Lot 51 Core Library | Release mais recente | Dependência obrigatória — instale separadamente |
| Python (sidecar) | 3.10+ (3.12 recomendado) | Sidecar roda em 3.10+; 3.12+ preferido para performance |
| Python (build do mod) | 3.7.9 exatamente | `.ts4script` deve ser compilado com bytecode Python 3.7 |

---

## Instalação

### 1. Instale as Dependências (Pasta Mods)
Baixe e coloque em `Documentos/Electronic Arts/The Sims 4/Mods/`:
- **S4CL** — em [GitHub Releases](https://github.com/DeviantGameMods/Sims4CommunityLibrary/releases)
- **Lot 51 Core** — em [GitHub Releases](https://github.com/lot51/lot51_core/releases)

Ative **Modos de Script Permitidos** em Opções de Jogo → Outro.

### 2. Compile e Instale o Sensewright
```bash
# Na raiz do repo (requer Python 3.7 no PATH como `py -3.7` e Python 3.10+ como `python`)
make all          # compila .ts4script + .package
make install      # copia ambos para sua pasta Mods
```

Ou use o helper PowerShell:
```powershell
.\scripts\dev.ps1 build
.\scripts\dev.ps1 install
```

### 3. Configure e Rode o Sidecar
```bash
cd sidecar
cp config.example.toml config.toml
# Edite config.toml — no mínimo defina chaves de API se quiser recursos LLM
python main.py
```
O sidecar serve:
- API REST em `http://127.0.0.1:8765/v1/...`
- Web Studio em `http://127.0.0.1:8765/ui`

**Autoboot**: A worker thread do mod auto-inicia o sidecar se detectar `sidecar/python.txt` apontando para um executável Python 3.10+. Crie esse arquivo em `sidecar/python.txt` com o caminho completo (ex: `C:\Python312\python.exe`) para startup zero-clique.

**Fallback 0-Key**: Se nenhum provedor estiver habilitado ou todas as chaves estiverem vazias, todo propósito retorna um fallback determinístico localizado. O mod é totalmente jogável offline.

---

## Início Rápido

1. Inicie The Sims 4, carregue um save.
2. O mod inicializa no `HOUSEHOLDS_AND_SIMS_LOADED`: cria o Confidente Oculto, envia census, inicia pulsos de autonomia.
3. Clique em qualquer Sim → **Sensewright** no menu de torta → **Chat (Celular)** ou **Chat (PC)**.
4. Digite uma mensagem. O Sim responde em uma notificação com botão **[Responder Agora]** — clique para continuar a conversa sem reabrir o menu.
5. Abra `http://127.0.0.1:8765/ui` no navegador para o Web Studio (Inspector, Roteiro, Configuração).

---

## Configuração (Duas Camadas `config.toml`)

**Camada 1 — Provedores & Limites Técnicos** (`[llm.providers.*]`)
```toml
[llm.providers.openrouter]
enabled = true
base_url = "https://openrouter.ai/api/v1"
api_key = "sk-..."
models = ["openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct:free"]
rpm = 20        # requisições/minuto
rpd = 200       # requisições/dia
tpm = 40000     # tokens/minuto
```
Provedores suportados: `openrouter`, `gemini`, `groq`, `deepseek`, `ollama`. Defina `free_only = true` para bloquear modelos pagos no cliente.

**Camada 2 — Roteamento & Orçamentos** (`[llm.routes.*]`, `[llm.tiers.*]`)
```toml
[llm.routes.default]
provider = "openrouter"
model = "openai/gpt-4o-mini"

[llm.tiers.interactive]
slo_seconds = 3.0
max_input_tokens = 1500
max_output_tokens = 250
concurrency = 4

[llm.tiers.realtime]
slo_seconds = 12.0
max_input_tokens = 700
max_output_tokens = 220
concurrency = 2
thinking_budget = 0

[llm.tiers.bg]
slo_seconds = 60.0
max_input_tokens = 1500
max_output_tokens = 400
concurrency = 1

[llm.tiers.deep]
slo_seconds = 300.0
max_input_tokens = 4000
max_output_tokens = 600
concurrency = 1
```

**Ajustes de Gameplay** (`[gameplay]`, `[god]`) — editáveis no jogo via Menu Rápido / Web Studio:
```toml
[gameplay]
agent_seats = 12
lease_min_sim_minutes = 60
hearing_radius_m = 20.0
max_lines_per_minute = 12
min_interval_between_lines_seconds = 30
player_lock_seconds = 15

[god]
director_mode = "AUTONOMOUS"   # AUTONOMOUS | CO_DIRECTOR | SANDBOX
preset = "novela"              # novela|sitcom|drama|caos|terror|romance|filme_adolescente
intervention_frequency = 0.5
intensity = 0.5
mood_influence = 0.5
autonomy_degree = 0.5
chaos_degree = 0.5
```

---

## Web Studio (`/ui`) & Menu Rápido

| UI | Acesso | Finalidade |
|----|--------|------------|
| **Menu Rápido (Torta)** | Clique em qualquer Sim → Sensewright | Chat (Celular/PC), Provocar, Painel, Controles do Diretor |
| **Menu Rápido (Shift+Clique)** | Shift+Clique em qualquer Sim → Sensewright | Avançado: Perfil, Memória, Assento, Controles do God |
| **Web Studio — Inspector** | `http://127.0.0.1:8765/ui` → Inspector | Estado vivo do Sim, intent bus, memória, psique, relacionamentos |
| **Web Studio — Roteiro** | `http://127.0.0.1:8765/ui` → Roteiro | Invocação manual de propósitos, preview de prompt, trace viewer |
| **Web Studio — Configuração** | `http://127.0.0.1:8765/ui` → Configuração | Editor de config, status de provedores, gerenciador de locale, compilador STBL |

---

## Os 33 Propósitos (Catálogo Canônico)

Cada propósito tem ID estável, tier (definindo SLO + orçamento de tokens + concorrência), orçamentos de tokens de entrada/saída, gatilho, artefato SQLite e consumidor no jogo. Todos têm fallbacks 0-key.

### Domínio: `sim` (13)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `sim.chat` | interactive | Celular / PC (`sw.chat`) | memória thought + fala + intents | Card de chat + Hidden SimInfo |
| `sim.profile` | bg / interactive | Novo assento (bg) / chat (int) | `sims.profile` (PROFILE_SHAPE) | Todos prompts do Sim + GetToKnow |
| `sim.impulse` | realtime | Pulso de zona (tier full) | memória thought + 1 intent não-verbal | Humor/ação do Sim no lote |
| `sim.reaction` | realtime | Evento salience ≥ 1.5 | memória thought + intent speak | Reação imediata ao causador |
| `sim.social` | realtime | Par em conversa (pre-flight ok) | `{a_line, b_line, topic, impact}` | Card compacto de diálogo |
| `sim.social.close` | bg | Fim de ConversationSession | memória social + contágio de rumor | Histórico social + world.gossip |
| `sim.dream` | deep | Início do sono (1×/noite) | memória de sonho + dream_urge | Balões de sono + tooltip moodlet matinal |
| `sim.cognition` | deep | Pós-sonho / bootstrap | `profile.daily_plan` + biases | Commodity buffs + Web Studio |
| `sim.sleep` | deep | Sono (se evento saliente) | `profile.psyche_blocks` | Prompts do Sim + gatilho evo.trait |
| `sim.diary` | bg | Escrever diário / fim do dia | memória diário (1ª pessoa) | Tooltip diário + Bisbilhotar |
| `sim.lifestory` | deep | A cada 7 dias-sim / mem.legacy | `profile.life_story` | ContextAssembler + livro físico |
| `sim.aspiration` | deep | Mudança/marco de aspiração | `profile.ambition` | Metas de médio prazo na cognição |
| `sim.background.expand` | bg | 1× para família/amigos próximos | 3 memórias de background | Reveladas via GetToKnow |

### Domínio: `god` (8)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `god.zeitgeist` | bg | Onboarding / edição no painel | `neighborhoods.zeitgeist` | Sonhos, clima, god.plan |
| `god.plan` | deep | Sem arco / fim de arco | `arcs` (beats + god_whisper_hint) | god.scene + sussurros de sonho |
| `god.cast` | bg | Beat precisa de NPC catalisador | `arcs.cast` (NpcSheet) | spawn_npc lever (VisitSituation) |
| `god.scene` | bg | Beat entra armado | `beat.scene_draft` + scene_subtext | Prepara objetivo do catalisador p/ P18 |
| `god.puppeteer` | realtime | NPC catalisador + alvo no lote | lease + abordagem + objetivo | Controla catalisador + subtexto |
| `god.react` | realtime | Fim de interação do beat | próximo beat ramificado (pivot) | Adapta arco à escolha do agente |
| `god.narration` | realtime | Início de beat / intervenção | 1 linha atmosférica (≤80 tok) | Banner SPECIAL_MOMENT |
| `god.background` | bg | Fila do BackgroundScheduler | `sims.background` | Contexto de cena + crônicas |

### Domínio: `world` (4)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `world.npc.backstory` | bg | Townie recorrente sem história | `sims.background` (NPC) | Semente para profile + god.cast |
| `world.household.chronicle` | bg | Fim do dia-sim | `neighborhoods.chronicles` | Caixa de correio + ops.recap + god.plan |
| `world.gossip` | bg | Evento saliente público / bisbilhotar | RumorNode em neighborhoods | Diálogos sociais + SMS no celular |
| `world.aftermath` | bg | Pós-clímax (salience ≥ 2.0) | intents duráveis + shift zeitgeist | Altera relacionamentos e clima |

### Domínio: `mem` (4)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `mem.consolidate` | bg | 300s silêncio chat / troca de zona | memória consolidada + player_facts | Índice FTS5 + vínculo jogador |
| `mem.compact` | deep | ≥ 20 memórias consolidadas | memória compacta (arquiva 15) | Mantém janela de contexto enxuta |
| `mem.legacy` | deep | Morte, casamento, nascimento | memória legada (imune a decaimento) | sim.lifestory + epitáfio |
| `mem.relationship.review` | deep | Janela deep (arestas ativas) | `relationships.qualitative_note` | Sentimentos nativos + chat/social |

### Domínio: `evo` (2)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `evo.reflect` | deep | Sono (≥8 ev) / espelho | atualiza `current_demeanor` | Mudança de fase preservando `core_personality` |
| `evo.trait` | deep | Trauma/crença > 0.85 / hábito | gostos/desgostos / troca de traço | trait_tracker + banner Aceitar |

### Domínio: `ops` (2)
| ID | Tier | Gatilho | Artefato | Consumidor |
|----|------|---------|----------|------------|
| `ops.recap` | bg | `lifecycle/session-start` | `{headline, recap_text}` | Banner "Anteriormente..." |
| `ops.panel.summary` | bg | Mudança de estado / painel aberto | resumo diagnóstico de 2 linhas | Cabeçalho Menu Rápido + Web Studio |

---

## Localização & Contribuição de Tradução

Sensewright usa um **motor i18n guiado por manifesto, zero-hardcode** com cascata de 4 camadas:

```
Overlay do Usuário (data/locales/) → Locale Ativo (sidecar/locales/) → Subtag Base (ex: pt) → Default do Manifesto (en-US)
```

### Topologia de Arquivos
```
PlaintextMods/Sensewright/
├── Sensewright.ts4script          # Locales fallback embutidos
├── Sensewright.package            # STBLs compilados de locales/stbl/
├── data/
│   └── locales/                   # [CAMADA 1 — OVERLAY USUÁRIO/COMUNIDADE]
│       ├── manifest.override.json # Opcional: registrar novos idiomas
│       ├── ui/                    # Drop-in: <locale>.json (sobrescreve UI do Mod)
│       └── content/               # Drop-in: <locale>.json (sobrescreve Prompts/Fallbacks)
└── sidecar/
    └── locales/                   # [CAMADA 2 — BUNDLE OFICIAL]
        ├── manifest.json          # Fonte única da verdade
        ├── ui/
        │   ├── en-US.json
        │   └── pt-BR.json
        └── content/
            ├── en-US.json
            └── pt-BR.json
```

### Contrato do Manifesto (`manifest.json`)
```json
{
  "schema_version": 2,
  "default_locale": "en-US",
  "locales": [
    {
      "code": "en-US",
      "base_subtag": "en",
      "display_name": "English (US)",
      "llm_language_name": "English",
      "ts4_stbl_byte": "0x00",
      "ts4_client_tokens": ["eng_us", "en_us", "en-us", "en"],
      "direction": "ltr"
    },
    {
      "code": "pt-BR",
      "base_subtag": "pt",
      "display_name": "Português (Brasil)",
      "llm_language_name": "Português do Brasil (pt-BR)",
      "ts4_stbl_byte": "0x11",
      "ts4_client_tokens": ["por_br", "pt_br", "pt-br", "pt"],
      "direction": "ltr"
    }
  ]
}
```

### Contribuindo uma Tradução
1. Faça fork do repo.
2. Adicione `<novo-locale>.json` em `sidecar/locales/ui/` e `sidecar/locales/content/`.
3. Adicione a entrada do locale no `manifest.json` (copie uma existente, ajuste `code`, `base_subtag`, `ts4_stbl_byte`, `ts4_client_tokens`, `llm_language_name`).
4. Rode `make package` para compilar STBLs no `.package`.
5. Envie PR.

### Flexão de Gênero & Rotação de Listas
- **Macro de gênero**: `{g:masculino|feminino|neutro}` em qualquer string. Em runtime, o motor escolhe a forma correta baseada no gênero do Sim (`M`/`F`/`N`).
- **Rotação de lista**: Qualquer valor de string pode ser `list[str]`. O motor escolhe um determinísticamente via `hash(seed + key) % len(lista)`. Seed padrão: `sim_id:hora_sim`.

---

## Build & Desenvolvimento

### Targets do Make
```bash
make all        # mod + package (padrão)
make mod        # apenas .ts4script (requer py -3.7)
make package    # apenas .package (requer Python 3.10+)
make test       # verificação de sintaxe (3.7 para mod, 3.10 para build scripts)
make install    # copia artefatos para pasta Mods
make doctor     # roda diagnósticos (scripts/doctor.ps1)
make clean      # remove dist/ e __pycache__
make sidecar    # roda sidecar dev server
make dev        # helper interativo (build/test/clean/sidecar/install/doctor/decompile)
make decompile  # decompila scripts TS4 para referência (precisa unpyc3)
```

### Scripts PowerShell
| Script | Finalidade |
|--------|------------|
| `scripts/dev.ps1 build` | Compila ambos artefatos |
| `scripts/dev.ps1 test` | Verificação de sintaxe |
| `scripts/dev.ps1 clean` | Limpa artefatos |
| `scripts/dev.ps1 sidecar` | Roda sidecar |
| `scripts/dev.ps1 install` | Instala no Mods |
| `scripts/dev.ps1 doctor` | Diagnósticos |
| `scripts/dev.ps1 decompile` | Decompila scripts TS4 |
| `scripts/install-mod.ps1` | Instalação direta |
| `scripts/doctor.ps1` | Verificação completa do ambiente |

### Detalhes do Build
- **`.ts4script`**: Compilado com Python 3.7 (`py -3.7 -m py_compile`). Verifica magic number `42 0d 0d 0a`. Inclui arquivos JSON de `locales/`.
- **`.package`**: DBPF com XML tuning + compilação STBL guiada por manifesto. Lê `manifest.json`, itera locales, converte `ts4_stbl_byte` para Resource Key, compila chaves com hash FNV-1. Emite `stbl_keys.json` com mapeamento.

---

## Solução de Problemas

### `make doctor` / `.\scripts\doctor.ps1`
Verifica:
- Disponibilidade de Python 3.7 (`py -3.7`) e 3.10+ (`python`)
- Todos arquivos fonte do mod presentes
- Validade JSON dos locales + paridade de chaves (en-US vs pt-BR)
- XMLs de tuning presentes + `dist/stbl_keys.json` e `dist/tuning_ids.json` gerados
- Artefatos de build (`.ts4script`, `.package`) existem e são ZIP/DBPF válidos
- Diretório sidecar + `python.txt` + `main.py`
- Pasta Mods do TS4 + artefatos instalados

### Problemas Comuns
| Sintoma | Causa | Correção |
|---------|-------|----------|
| Mod não carrega | Script Mods desabilitado | Opções de Jogo → Outro → ✅ Modos de Script Permitidos |
| Sidecar não inicia | `python.txt` ausente/errado | Crie `sidecar/python.txt` com caminho completo para Python 3.10+ |
| Sem strings STBL no jogo | `.package` não instalado/desatualizado | `make package && make install` |
| Chat mostra `[missing:key]` | Locale sem a chave | Verifique `data/locales/ui/<lang>.json` overlay ou bundle sidecar |
| Pulsos de autonomia não disparam | Lot 51 Core não carregado | Instale Lot 51 Core; cheque `doctor.ps1` |
| `py -3.7` não encontrado | Python 3.7 não instalado | Instale Python 3.7.9 do python.org; garanta que `py` launcher funciona |

### Logs
- **Logs do Mod**: `Documentos/Electronic Arts/The Sims 4/mod_data/Sensewright.log` (via S4CL CommonLogUtils)
- **Logs do Sidecar**: Saída do console (configurado por `log_level` no `config.toml`)
- **Trace IDs**: Toda requisição carrega header `X-Trace-Id`; aparece nos logs do mod e sidecar para correlação.

---

## Licença

**Sensewright v2** — Licença MIT (veja `LICENSE`)

### Avisos de Terceiros
| Componente | Licença | Fonte |
|------------|---------|-------|
| The Sims 4 Community Library (S4CL) | **CC BY 4.0** | `research/s4cl/` (apenas referência) |
| Lot 51 Core Library | **MIT** | `research/lot51_core/` (apenas referência) |
| FastAPI | MIT | `sidecar/requirements.txt` |
| Uvicorn | BSD-3-Clause | `sidecar/requirements.txt` |
| Pydantic | MIT | `sidecar/requirements.txt` |
| Tomli | MIT | `sidecar/requirements.txt` |
| HTTPX | MIT | `sidecar/requirements.txt` |
| Pytest | MIT | `sidecar/requirements.txt` |

> **Nota**: S4CL e Lot 51 Core são **dependências de runtime** — jogadores devem instalá-los separadamente. Eles estão em `research/` apenas como referência para desenvolvimento. Sensewright não os empacota ou redistribui.

---

## Não Verificado / Lacunas Conhecidas

- `requirements.txt` do sidecar não presente no repo (dependências inferidas dos imports: `fastapi`, `uvicorn`, `pydantic`, `tomli`, `httpx`, `pytest`).
- Licença S4CL confirmada como CC BY 4.0 via README; sem arquivo LICENSE separado em `research/s4cl/`.
- Licença Lot 51 Core confirmada como MIT via seu arquivo `LICENSE`.
- Matriz exata de compatibilidade com packs TS4 não codificada; spec diz "Apenas jogo base, DLC não obrigatório" mas alguns tunings podem referenciar conteúdo de packs.
- Fonte do frontend Web Studio (`/ui`) não inspecionada — descrita a partir da spec e registro de router apenas.