# Sensewright

**Sensewright** dá aos Sims de *The Sims 4* uma camada de **agência por LLM** e um
**"God agent"** que orquestra o mundo. Os agentes não *puppeteiam* o Sim: emitem
**intents** (nudges) que são traduzidos para as alavancas nativas do jogo, e o
jogador continua no controle.

> Ex-**SimsSense**. Os cheats são `sw.*`, o artefato é `Sensewright.ts4script` e a
> pasta de instalação é `Mods\Sensewright\`. Nomes antigos (`ss.*`, SimsSense) foram
> removidos.

## Status

| | |
|---|---|
| Build in-game | `2026-09-29.26` (`mod/sensewright_mod/main.py` → `_BUILD`) |
| Branch | `main` |
| Testes | sidecar **546** · mod **412** · `ruff` limpo · `py -3.7 mod/build.py` ok |
| Migração de stack | **S4CL + Lot 51 Core**: offline-completa, validação em jogo **pendente** |

## Como funciona

Dois processos estritamente isolados:

| Camada | Pacote | Runtime | Dependências |
|---|---|---|---|
| **Mod in-game** | `mod/sensewright_mod/` | Python **3.7** | stdlib + **S4CL** + **Lot 51 Core** (via `integrations.py`) |
| **Sidecar** | `sidecar/sensewright_sidecar/` | Python **3.12+** | FastAPI, Pydantic v2, httpx, SQLite |

O mod **nunca** importa bibliotecas de terceiros fora do *stack seam*
(`integrations.py`); o sidecar **nunca** importa módulos do jogo. A comunicação é
por HTTP em `127.0.0.1:8765` (rotas `/v1/*`), com o contrato de wire modelado em
`sidecar/sensewright_sidecar/schemas.py`.

Além do agente por Sim, um **God agent** intervém no bairro (presets de narrativa,
backgrounds, zeitgeist) e um **painel** (web e in-game) expõe os controles.

## Requisitos

- The Sims 4 e **Python 3.7** (build do `.ts4script`) + **Python 3.12+** (sidecar).
- **S4CL** (`sims4communitylib*.ts4script`) e **Lot 51 Core** (`lot51_core*.ts4script`)
  no **root** de `Mods` — as bibliotecas **não** são redistribuídas (XmlInjector não é mais usado).
- Uma chave de provider de LLM (OpenRouter `:free`, OpenCode Zen ou Gemini).

## Instalação

```powershell
# 1. dependências do sidecar
make install            # ou: cd sidecar; uv sync --extra dev

# 2. build dos artefatos (Sensewright.ts4script + Sensewright.package)
py -3.7 mod\build.py

# 3. instala o mod + sidecar em Mods\Sensewright\
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1

# 4. abra o jogo (script mods só carregam no boot)
```

O sidecar **sobe sozinho** com o jogo (o mod o auto-inicia) e **encerra junto**.
Há um painel web em <http://127.0.0.1:8765/> para acompanhar o sidecar em paralelo
ao jogo, e o painel nativo in-game abre com `sw.panel`. Reinstale após qualquer
mudança de venv ou de código.

## Cheats `sw.*`

| Comando | Ação |
|---|---|
| `sw.help` | ajuda de todos os comandos |
| `sw.status` | status do sidecar + saúde dos providers |
| `sw.start` | inicia o sidecar manualmente |
| `sw.chat <texto>` | conversa com o Sim selecionado |
| `sw.hey` | dispara um cumprimento espontâneo do Sim |
| `sw.profile <1 frase>` | gera o perfil do Sim (1 sentença → JSON) |
| `sw.autonomy off\|observe\|suggest\|semi\|full` | nível de autonomia do Sim |
| `sw.agents [<seats> \| <sim_id> <freq>]` | roster de agentes + dial de impulso |
| `sw.god [on\|off\|tick\|scan\|preset <nome>\|set <k> <v>]` | controle do God |
| `sw.zeitgeist <tags_csv\|auto\|empty>` | define o zeitgeist do bairro |
| `sw.evolve [save]` | roda o loop de reflexão/evolução |
| `sw.reset session\|sim\|save\|all` | limpa sessão/memória |
| `sw.forget sim\|save\|all` | apaga memória |
| `sw.panel` | abre o painel de configuração in-game |
| `sw.hud on\|off\|now\|status` | HUD de debug do loop |
| `sw.probe` | dump da superfície de autonomia (dev) |
| `sw.lang auto\|<locale>` | idioma da UI (persiste no config) |

## Configuração

Toda a configuração vive em `config.toml` — a fonte da verdade do arquivo é
**`config.example.toml`**. Com **nenhuma chave**, o mod já roda em "modo nativo".
Blocos: `[ui]`, `[network]`, `[logging]`, `[llm]`, `[memory]`, `[agents]`,
`[runtime]`, `[god]`.

Os ajustes expostos ao painel são os **ControlSpec** (`god/controls.py`); os
overrides do painel são gravados em `data/panel.toml`, sem tocar no `config.toml`.
Dois locales acompanham o projeto: `en` (default) e `pt-BR`; adicionar idioma é
JSON + manifest, sem mudança de código.

## Documentação

A **fonte única da verdade** é **[`docs/feature-review.html`](docs/feature-review.html)**
(abra no navegador). Segue a divisão Diátaxis, com cada assunto em um único lugar:

| Aba | Para quê |
|---|---|
| **Início** | visão geral, status e quick start |
| **Arquitetura** | os dois processos, mapa de módulos, wire protocol, base S4CL/Lot51 |
| **Desenvolvimento** | loop, convenções, constraints, recipes e gotchas |
| **Validação** | logs/DB, checklist live e como provar cada feature |
| **Referência** | config, cheats `sw.*`, endpoints, locales, providers |
| **Internals TS4** | APIs do jogo confirmadas (autonomy, buffs, alarms, genealogia) |
| **Roadmap** | fases, v0.2/v0.3, pendências e riscos |
| **Changelog** | histórico por build |
| **Review** | checklist interativo por feature (exporta JSON) |

As regras de código do dia a dia estão em
`.agents/skills/sensewright_development/SKILL.md`.

## Desenvolvimento

```powershell
# testes
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q   # sidecar — 546
python -m pytest mod\tests -q                               # mod — 412

# build + install
py -3.7 mod\build.py
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1
```

Outros helpers: `make doctor` / `scripts\doctor.ps1` (valida o ambiente),
`make status` (health do sidecar) e `make dev` (helper de desenvolvimento).

## Licença

MIT — veja [`LICENSE`](LICENSE). As dependências de runtime (S4CL, Lot 51 Core) e o
código adaptado (SimAI) estão creditados em
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
