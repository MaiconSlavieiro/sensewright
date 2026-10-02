# Sensewright v2 — Status de Implementação (M0 → M8)

> **Data:** 2026-10-02
> **Branch:** `v2-remake`
> **Base de referência:** [`sensewright-v2-requirements.md`](../sensewright-v2-requirements.md)
> **Objetivo:** registrar com precisão o que **já está implementado e verificado** e o que
> **ainda falta de fato** do plano total (22 features, 33 propósitos, ajustes A1–A11 e
> features complementares FC1–FC5).

Este documento é a fonte de verdade sobre a lacuna entre a especificação e o código.
Referências no formato `arquivo:linha`.

---

## 1. Resumo executivo

O projeto tem uma **fundação sólida e testada**: os dois processos (Mod Python 3.7 e
Sidecar FastAPI) conversam, o ciclo transacional de save funciona, o motor i18n
manifest-driven está completo, a camada LLM (limites triplos, circuit breaker, scheduler
single-queue, ContextAssembler por tier) existe, e o build gera `.ts4script` (bytecode 3.7)
e `.package` (DBPF + STBL) válidos.

O que **falta de fato** não é fundação, é **fiação (wiring) e gatilhos**:

- **18 dos 33 propósitos** só possuem fallback determinístico — não têm gatilho nem
  handler de produção (ex.: `sim.dream`, `sim.cognition`, `god.cast`, `world.gossip`,
  `mem.compact`, `mem.legacy`, `ops.panel.summary`).
- **Três propósitos parciais** (`sim.dream`, `sim.cognition`, `evo.reflect`) têm motor e
  prompt prontos, mas **nada os dispara** e o resultado não é aplicado de volta ao perfil.
- **God Director**: arcos/beats são planejados mas nunca consumidos; `god.cast`,
  `god.scene` e `god.react` não existem; `god.puppeteer` não spawna/aborda NPC e não
  injeta o objetivo assimétrico em `sim.social`.
- **World Layer**: o modelo de rumor está pronto e testado, mas **nenhum código de
  produção cria/espalha rumores**; crônica, caixa de correio e aftermath ausentes.
- **Hooks nativos (M5/M6)**: faltam Diário/"Bisbilhotar", Livro de Autobiografia,
  `VisitSituation` (NPC tocando a campainha), Epitáfio na Lápide, balões de sono e a
  interação "Refletir" no espelho.
- **Speech Policy (F11)**: `max_lines_per_minute` e `min_interval_between_lines` estão
  definidos mas **não são aplicados**; o roteamento visual em 4 canais está incompleto.
- **Settings/Concurrency (F15/F16)**: cooldown por modelo (120 s) é código morto;
  concorrência por tier não é aplicada; o "refund assimétrico" é logicamente inócuo.

Tudo o que existe hoje é coberto por **474 testes** (sidecar) e compila nos dois
interpretadores corretos.

---

## 2. Validação executada nesta revisão

| Verificação | Comando | Resultado |
|---|---|---|
| Suíte de testes do sidecar | `python -m pytest -q` em `sidecar/` | **474 passed**, 1 warning |
| Sintaxe do Mod (Python 3.7) | `py -3.7 -m py_compile` em `mod/sensewright_mod/*.py` | **OK** (16 arquivos) |
| Sintaxe dos scripts de build (3.10+) | `python -m py_compile mod/build.py mod/build_package.py` | **OK** |
| Build `.package` | `python mod/build_package.py` | **OK** — 25 recursos (19 buffs, 3 interactions, 1 trait, 2 STBL) |
| Build `.ts4script` | `python mod/build.py` | **OK** — 69.488 bytes, magic number Python 3.7 `42 0d 0d 0a` verificado |
| Varredura de segredos no diff | `git diff` por `sk-…`/`api_key=` | **Limpo** |
| `.gitignore` | `git check-ignore` | `sidecar/config.toml` e `dist/` ignorados |

> A validação é **unitária/estática**. Os critérios de aceitação do M8 (transição de lote,
> *Save As*, *Alt+F4*, autoboot invisível) **exigem execução dentro do The Sims 4** e ainda
> não foram realizados.

---

## 3. Marcos M0 → M8

| Marco | Foco | Status | Observação |
|---|---|---|---|
| **M0** | Fundação, IPC & Save Vault | ✅ **Completo** | Thread isolation, dual-clock, SaveVault (working/committed/ring buffer), `/v1/lifecycle/*`. |
| **M1** | Roteamento, TPM & Idioma | 🟡 **Parcial** | Limites triplos, circuit breaker 60 s, `free_only`, 6 provedores e i18n completos. **Falta**: cooldown por modelo 120 s (`chain.py:28-29` é código morto). |
| **M2** | Scheduler, ContextAssembler & Intents | 🟡 **Parcial** | Scheduler single-queue, SLO, teto de input, dedup e config em 2 camadas OK. **Falta**: enforcement de concorrência por tier; refund assimétrico inócuo. |
| **M3** | Cognição, Sonhos & FTS5 | 🟡 **Parcial** | FTS5 (BM25) e tabelas completas; motores de sonho/cognição e prompts existem. **Falta**: gatilhos de sono, `apply_cognition`, decay/prune de psique, VACUUM. |
| **M4** | God Director & Catalisadores | 🟡 **Parcial** | `god.zeitgeist`, `god.narration`, `god.plan` (submetido) e lease/puppeteer básico. **Falta**: construir/consultar arcos, `god.cast`/`god.scene`/`god.react`/`god.background`, spawn de NPC, `BackgroundScheduler`. |
| **M5** | Levers, ArchetypeResolver & Hooks | 🟡 **Parcial** | Buffs/moodlets/sentimentos/traços e 14 bias buffs. **Falta**: mapas de atividade/archetype vazios, `VisitSituation`, gostos/desgostos, espelho. |
| **M6** | Chat Hidden SimInfo, Diário & Mundo | 🟡 **Parcial** | Hidden SimInfo + canais de chat (SMS) + loop encadeado básico. **Falta**: `pc_chat`/`pc_email` navegáveis, Diário/"Bisbilhotar", caixa de correio, SMS de fofoca. |
| **M7** | UI Dual & Logs | 🟡 **Parcial** | Quick Menu + Web Studio SPA real; `trace_id` e rotação 10 MB × 3. **Falta**: wiring de vários controles do Web Studio; `trace_id` se perde em jobs `bg`. |
| **M8** | Validação In-Game & Release | ❌ **Não iniciado** | Só há validação unitária. `/v1/i18n/compile-addon` é stub. Critérios de aceitação não executados. |

---

## 4. Features F01 → F22

| Feature | Status | Evidência / lacuna principal |
|---|---|---|
| **F01** Chat multicanal, Hidden SimInfo & UI contínua | 🟡 Parcial | Hidden SimInfo completo (`native_hooks.py:85-160`); UI encadeada básica (`chat_ui.py:75-209`). Falta canal `pc_chat`/`pc_email`, Wants nativos (fallback via moodlet `native_hooks.py:340-363`), deferral local inerte. |
| **F02** Profile Generation & bootstrap | ✅ Completo | `normalize_profile` (`agent/profile.py:31`), hidratação via census (`services.py:111-121`), 2 estágios (template + `bg`). |
| **F03** Initiative / Impulse | 🟡 Parcial | Impulso `idle` e poda de fala OK (`services.py:146-153`). Guarda de sobrevivência calculada mas **não aplicada** (schedule vazio em `agent/impulse.py:81`; sem filtro no executor). |
| **F04** Social Layer & diálogo assimétrico | 🟡 Parcial | Pre-flight simétrico OK (`agent/social.py:17-43`). **Assimétrico não roteado**: `build_social_context` nunca recebe `puppeteer` (`services.py:269`); limite de falas/min não aplicado; CHILD não bloqueado. |
| **F05** IntentBus | ✅ Completo | Shape canônico, TTL, `expires_on`, `retry_count`/`max_retries` (`intent_bus.py:37,44,272`), freeze na pausa. |
| **F06** SeatManager | ✅ Completo | Prioridade estrita, lease anti-thrashing, evicção por distância (`agent/seats.py:18-133`). Ressalva: pool pode exceder `max_seats` com muitos leases protegidos. |
| **F07** Cognição híbrida & Motor Onírico | 🟡 Parcial | Fórmula de surrealismo e `dream`/`cognition` prontos (`agent/dreams.py`, `agent/cognition.py`). **Nenhum gatilho de sono**; balões de sono e tokens de tooltip ausentes; `apply_cognition` nunca chamado. |
| **F08** Personality & Psique | 🟡 Parcial | Salience por metadados + reforço ligados (`services.py:393-406`). **Falta**: decay exponencial por `sim_tick` e prune nunca chamados; limite de Life Story (20 linhas/2 000 chars) não aplicado. |
| **F09** Evolution, Demeanor & Gostos | 🟡 Parcial | `evo.reflect` responde, mas `apply_reflection` **não é chamado** (`services.py:456-471`); sem escritor de gostos/desgostos; proposta de swap não emitida. |
| **F10** Memory, FTS5 & Shadow DB | ✅ Núcleo / 🟡 Periferia | Núcleo completo e testado. Periferia: prune de 180 dias sem agendamento, "Save As" não lê `previous_save_id`, VACUUM ausente. |
| **F11** Speech Policy (Pre-Flight) & roteamento | 🟡 Parcial / ❌ | `hearing_radius` OK; `max_lines_per_minute`/`min_interval` **não aplicados**. Canais: card compacto `SPEECH` ausente; banner/portrait parciais. |
| **F12** Presence Policy & Capability Matrix | 🟡 Parcial | Capacidades e exclusão de BABY OK (`agent/presence.py:19-45`). **`hard_blocked_social` (CHILD flirty/intimate) definido mas nunca chamado**; tier `off` morto. |
| **F13** Coordinator & arbitragem | 🟡 Parcial | Prioridades/constantes e 3 leases (`coordinator.py:23-30`). `SANDBOX_OVERRIDE` não atribuído; expiração de lease não checada. |
| **F14** God Director & `god.puppeteer` | 🟡 Parcial | 7 presets/5 dials definidos, mas só `intervention_frequency` influencia (`orchestrator.py:54`). `CO_DIRECTOR` ≡ `AUTONOMOUS`; casting/spawn ausente; sem `BackgroundScheduler`. |
| **F15** LLM Provider Chain, TPM & idioma | 🟡 Parcial | RPM/RPD/TPM, circuit breaker, `free_only`, 6 provedores — OK. Falta cooldown por modelo. |
| **F16** ModelRouter, Tiers & ContextAssembler | 🟡 Parcial | SLO/teto/dedup/2 camadas OK. Concorrência por tier não aplicada; refund assimétrico inócuo; `thinking_budget` só vira `temperature=0`. |
| **F17** Tools, Levers, ArchetypeResolver & Hooks | 🟡 Parcial | 9 intents com `_safe_call`; buffs/moodlets/sentimentos/traços. Mapas de atividade/archetype **vazios** (`tuning.py:229,232`); várias linhas da matriz nativa ausentes. |
| **F18** Sistema i18n & STBL | ✅ Motor / 🟡 Export | Cascata 4 níveis, manifesto, gênero, rotação, hot-reload e compilador no Mod — OK. `/v1/i18n/compile-addon` é stub. |
| **F19** Observability & rotação | 🟡 Parcial | `trace_id` propagado e rotação 10 MB × 3 OK. Worker `bg` perde o `trace_id` (ContextVar não herdado). |
| **F20** Build, Deploy & autoboot | ✅ Completo | `.ts4script` 3.7 + `.package` DBPF/STBL; autoboot `CREATE_NO_WINDOW` (`http_client.py:94-155`). |
| **F21** UI dual (Quick Menu + Web Studio) | 🟡 Parcial | Quick Menu OK; Web Studio SPA real (`webui/`). Wiring incompleto: salvar perfil/keys e botões de cena não persistem. |
| **F22** World Layer & epidemiologia de rumores | 🟡 Parcial | Modelo `RumorNode` completo e testado (`world/rumors.py`). **Nenhuma chamada de produção** cria/espalha rumor; crônica/mailbox/aftermath ausentes. |

---

## 5. Catálogo dos 33 propósitos

Estados: **Full** = fiação + consumo completos · **Parcial** = pipeline existe mas sem
gatilho/aplicação · **Fallback-only** = apenas `fallbacks.py` + declaração em
`purposes.py` (nenhum gatilho de produção) · **Ausente** = não implementado.

> Todos os 33 possuem fallback determinístico 0-key (garantia de projeto), portanto
> "Fallback-only" significa *o serviço responde, mas nunca é acionado com dados reais*.

| ID | Propósito | Status | Evidência / lacuna |
|---|---|---|---|
| P01 | `sim.chat` | ✅ Full | `services.py:333-382` |
| P02 | `sim.profile` | ✅ Full | `services.py:426-453` (ignora `profile` postado) |
| P03 | `sim.impulse` | ✅ Full | `services.py:245-260` (guarda de sobrevivência inerte) |
| P04 | `sim.reaction` | ✅ Full | `services.py:386-422` |
| P05 | `sim.social` | ✅ Full | `services.py:262-276` (assimétrico não roteado) |
| P06 | `sim.social.close` | ⚪ Fallback-only | Sem handler; `social_sessions` sempre `[]` (`services.py:296`) |
| P07 | `sim.dream` | 🟡 Parcial | Motor/prompt/fallback prontos; **sem gatilho de sono** |
| P08 | `sim.cognition` | 🟡 Parcial | `apply_cognition` nunca chamado (`agent/cognition.py:33`) |
| P09 | `sim.sleep` | ⚪ Fallback-only | Sem contexto/handler/gatilho |
| P10 | `sim.diary` | ⚪ Fallback-only | Sem handler/gatilho |
| P11 | `sim.lifestory` | ⚪ Fallback-only | Limites de Life Story não aplicados |
| P12 | `sim.aspiration` | ⚪ Fallback-only | Sem handler/gatilho |
| P13 | `sim.background.expand` | ⚪ Fallback-only | Sem handler; `sim_GetToKnow` ausente |
| P14 | `god.zeitgeist` | ✅ Full | `god/zeitgeist.py:20`, `services.py:517` |
| P15 | `god.plan` | 🟡 Parcial | Submetido (`orchestrator.py:56`), **resultado descartado**; `create_arc` sem caller |
| P16 | `god.cast` | ⚪ Fallback-only | Sem casting/reuso de townie/spawn |
| P17 | `god.scene` | ⚪ Fallback-only | Beat é armado mas `god.scene` nunca chamado |
| P18 | `god.puppeteer` | 🟡 Parcial | Lease + fala inicial (`god/puppeteer.py:38-57`); sem spawn/abordagem/objetivo assimétrico/continuação |
| P19 | `god.react` | ⚪ Fallback-only | `advance_arc` sem caller (`god/arcs.py:36`) |
| P20 | `god.narration` | ✅ Full | `god/orchestrator.py:17-80` |
| P21 | `god.background` | ⚪ Fallback-only | `set_sim_background` sem caller |
| P22 | `world.npc.backstory` | ⚪ Fallback-only | Sem gatilho |
| P23 | `world.household.chronicle` | ⚪ Fallback-only | `append_chronicle` sem caller; sem gatilho fim-do-dia |
| P24 | `world.gossip` | ⚪ Fallback-only | `create_rumor`/`save_rumors` sem caller (só testes); mod stub `tool_executor.py:425-427` |
| P25 | `world.aftermath` | ⚪ Fallback-only | Constante/flag sem uso |
| P26 | `mem.consolidate` | 🟡 Parcial | Endpoint funciona (`services.py:474`); **sem gatilho automático** (300 s/zona) |
| P27 | `mem.compact` | ⚪ Fallback-only | `count_consolidated`/`archive_memories` sem caller |
| P28 | `mem.legacy` | ⚪ Fallback-only | Sem gatilho de morte/casamento/nascimento |
| P29 | `mem.relationship.review` | ⚪ Fallback-only | `qualitative_note` nunca escrito |
| P30 | `evo.reflect` | 🟡 Parcial | Responde mas `apply_reflection` não aplicado |
| P31 | `evo.trait` | 🟡 Parcial | Helpers prontos; sem `run_purpose`/emissão |
| P32 | `ops.recap` | 🟡 Parcial | Submetido no bootstrap (`services.py:61`); `recap_job_id` sempre `None`; resultado descartado |
| P33 | `ops.panel.summary` | ⚪ Fallback-only | Sem caller |

**Total: 7 Full · 8 Parciais · 18 Fallback-only.**

---

## 6. Ajustes A1–A11 e Features Complementares

| Item | Status | Evidência / lacuna |
|---|---|---|
| **A1** Autoboot em 3 camadas | 🟡 Parcial | Camadas 2 (Popen) e degradada existem; **launcher externo ausente**; orientação manual só na doc. |
| **A2** Restrições Python 3.7 extras | ✅ Completo | Sem walrus/match/union/future/`cached_property` no Mod. |
| **A3** Freeze detalhado na pausa | ✅ Completo | `intent_bus.py:173-180`; sidecar congela (`services.py:216-218`). |
| **A4** Wants → moodlet | 🟡 Parcial | Moodlet "Saudade" implementado (`native_hooks.py:340-363`); Wants nativos ausentes. |
| **A5** `queue_interaction` → `bias_activity` | ✅ Resolvido | Intent canônico é `bias_interaction` (`intent_bus.py:16`). |
| **A6** `retry_count` no IntentBus | ✅ Completo | `intent_bus.py:37,58,272`; `agent/intents.py:65-66`. |
| **A7** Pool de 4 buffs de sonho | ✅ Completo | `mod/tuning/buffs/buff_dream_*.xml`; seleção em `native_hooks.py:212-233`. |
| **A8** Interação "Refletir" no espelho | ❌ Ausente | Só a chave de locale existe; sem classe/XML. |
| **A9** VACUUM após `mem.compact` | ❌ Ausente | `MemoryStore.vacuum()` existe mas nunca chamado (`sqlite_store.py:565`). |
| **A10** Guard de Expansion Packs | ❌ Ausente | Mod envia `installed_packs` (`state_collector.py:490`); sidecar ignora. |
| **A11** Priorização de hooks | 🟡 Parcial | Alta prioridade parcial; itens médios/baixos ausentes. |
| **FC1** Onboarding Wizard | 🟡 Parcial | Notificação única (`main.py:149-206`); sem as 3 opções (Quick/Web/Jogar). |
| **FC2** Export/Import de Sim | ❌ Ausente | Backlog (M8+). |
| **FC3** Dashboard de custo/consumo | ❌ Ausente | Aba 3 só mostra RPM/RPD/TPM atuais. |
| **FC4** Panic Button (Ctrl+Shift+S) | ❌ Ausente | `IntentBus.clear_all` definido e nunca chamado (`intent_bus.py:283`). |
| **FC5** Camada de compatibilidade (MCCC/Whims) | ❌ Ausente | Backlog. |

---

## 7. Gaps priorizados (o que falta implementar de fato)

### P0 — Destravar o núcleo narrativo (maior impacto, menor esforço)

1. **Gatilhos de sono** (Mod → Sidecar): disparar `sim.dream`, depois `sim.cognition` e
   `sim.sleep`; aplicar `apply_cognition` no perfil. Sem isso, F07 inteira fica inerte.
2. **Aplicar `evo.reflect`**: chamar `apply_reflection` em `handle_evolve` e persistir
   `current_demeanor` (`services.py:456-471`).
3. **Decay/prune de psique agendado** por `sim_tick` (chamar `decay_blocks`) e limite de
   Life Story (`constants.py:98-100`).
4. **Speech Policy enforcement**: aplicar `max_lines_per_minute` e
   `min_interval_between_lines` no pre-flight e/ou executor; aplicar
   `hard_blocked_social` (CHILD) e `physical_actions_allowed` de verdade no impulso.
5. **`world.gossip` + contágio social**: criar rumor a partir de evento saliente,
   chamar `spread` ao fim de `sim.social` e enviar SMS; hoje nada cria rumores.

### P1 — God Director completo e World Layer

6. **Consumir `god.plan`** (`create_arc`) e implementar `god.cast` (reuso de townie),
   `god.scene`, `god.react`, `god.background`.
7. **`god.puppeteer` de verdade**: spawn/`VisitSituation`, abordagem, injeção do
   `puppeteer_objective` em `sim.social` e ramificação pós-reação.
8. **`sim.social.close`, `sim.diary`, `mem.compact`, `mem.legacy`,
   `mem.relationship.review`, `ops.panel.summary`**: handlers + gatilhos.
9. **`BackgroundScheduler`** com prioridade `PLAYER > HOUSEHOLD > ACTIVE > RELATED`.
10. **Crônica da família + caixa de correio** e `world.aftermath`.

### P2 — Hooks nativos (M5/M6)

11. `VisitSituation` (NPC catalisador pela calçada/campainha).
12. Diário com *TooltipComponent* + interação **"Bisbilhotar"**; Livro de Autobiografia.
13. `sim_GetToKnow` revelando `secrets[]`/`background`.
14. Epitáfio na Lápide; balões de sono; interação custom "Refletir" no Espelho (A8).

### P3 — LLM, Config & Observabilidade

15. Cooldown por modelo 120 s (A2 original) em `chain.py`.
16. Enforcement de concorrência por tier no `LLMScheduler`.
17. Corrigir o refund assimétrico (debita no envio, estorna só o Game Budget).
18. `installed_packs` no Census → guards de EP (A10).
19. `trace_id` nos logs de jobs `bg`/`deep`.
20. VACUUM após `mem.compact` (A9).

### P4 — UI, Release & Backlog

21. Web Studio: persistir perfil/keys/casting/beats (hoje o backend ignora).
22. `/v1/i18n/compile-addon` real (gerar `Sensewright_Locale_<code>.package`).
23. Panic Button (FC4), Onboarding Wizard (FC1), Dashboard de custo (FC3).
24. **M8 in-game**: transição de lote, *Save As*, *Alt+F4* rollback, autoboot invisível.
25. Export/Import de Sim (FC2) e camada de compatibilidade (FC5).

---

## 8. Notas de higiene do repositório

- `sidecar/python.txt` é um arquivo de configuração **local** (aponta para o interpretador
  3.10+ do usuário). Foi adicionado ao `.gitignore` e removido do índice para não
  versionar caminhos absolutos de máquina; crie-o manualmente após o clone.
- `research/s4cl/` e `research/lot51_core/` são clones de referência e permanecem
  ignorados (não redistribuídos).
