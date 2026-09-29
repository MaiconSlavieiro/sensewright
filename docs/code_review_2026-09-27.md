# Code Review — SimsSense Mod (in-game, Python 3.7)

> **Status (resolved in build `2026-09-29.1`):** the correction plan below was
> applied — C1, H1–H6, M1–M8, L1–L9 (see `CHANGELOG.md` [Unreleased]). Deferred:
> **M9** (split the 1.5k-line `state_collector`), **L10** (harden the hand-rolled
> TOML parser), **L3** (duplicate Sim-ref helpers). `tool_executor` R1 native-lever
> hardening is defensive and still needs live validation.

> Escopo: `mod/simssense_mod/` (o mod in-game). Revisão de 2026-09-27.
> Método: leitura integral dos módulos + verificação manual dos achados mais
> críticos antes de registrar (falsos positivos descartados em §5).
> Referências de arquitetura: `.agents/skills/sims_mod_guidelines/SKILL.md`.

Arquivos revisados: `state_collector.py`, `events.py`, `tool_executor.py`,
`rails.py`, `sim_context.py`, `main.py`, `__init__.py`, `config.py`,
`http_client.py`, `chat_ui.py`, `hud.py`, `god_ui.py`, `i18n.py`,
`debug_log.py`, `probe.py` + paridade de `locales/en.json` × `pt-BR.json`.

---

## 1. Resumo executivo

A base é sólida: acesso tardio a services, `_safe_getattr`/`_safe_call`,
sanitização de payload para primitivas, exceções HTTP tipadas, fallback em
3 camadas de notificação e i18n com fallback para `en`. **Paridade de locales
100%** e **conformidade Python 3.7 sem violações de sintaxe**.

Os problemas concentram-se em duas frentes:

1. **Swallow silencioso de `except Exception:`** — dezenas de blocos engolem
   erros sem log, violando a §2 do guia ("log, don't swallow"). Isso torna o
   debug em campo quase impossível (ex.: `_send` descarta eventos em silêncio).
2. **Rails de prioridade do jogador nunca armadas** — `record_player_activity`
   só é chamado nos testes; em produção o lock de 10 s fica inoperante, então o
   agente pode competir com o jogador.

Prioridades: (1) armar o player-priority lock; (2) adicionar log a todos os
`except Exception:` relevantes; (3) validação de tipo dos argumentos de tools.

---

## 2. Achados por severidade

### CRITICAL

**C1 — Player-priority lock nunca é armado em produção.**
`mod/simssense_mod/rails.py:74` define `record_player_activity`, mas o único uso
fora de `rails.py` são os testes (`mod/tests/test_executor.py`,
`mod/tests/test_rails.py`). Nenhum caminho de produção (main/state_collector/
tool_executor/events) chama esse método. Resultado: `_last_activity` fica vazio
e `DirectiveRails._decide` (`rails.py:65-67`) nunca retorna
`player_priority`. O trilho de segurança "o agente não age enquanto o jogador
age" está morto.

*Fix sugerido:* registrar atividade do jogador quando ele interage. Ex.: em
`main.py` (comandos `ai.*` executados pelo jogador) e/ou no heartbeat de
`state_collector` ao detectar interação do Sim ativo, chamar
`tool_executor.get_rails().record_player_activity(sim_id)`. Alternativa: expor
um endpoint no mod para o sidecar sinalizar atividade do jogador.

---

### HIGH

**H1 — `_send` descarta eventos silenciosamente.**
`state_collector.py:1110-1117`: ambos os `except` (`SidecarUnreachable`/
`SidecarError` e `Exception`) fazem `pass`. Eventos (buffs, relacionamentos,
social, snapshot) somem sem rastro. O `except` em `_emit`
(`state_collector.py:1123`) nunca dispara porque `_send` absorve tudo.

*Fix:* logar via `validation_log`/`debug_log`, ex.:
`except Exception as exc: log_exception("state_collector._send", exc)`.

**H2 — Outros envios HTTP engolem erro sem log.**
`state_collector.py` em `send_autonomy_tick` (~681-684), `_pull_intents`
(~830-831), `send_census` (~929-932), `notify_player_activity` (~1103-1106):
o `except Exception` final retorna `None` sem log.

*Fix:* logar cada bloco.

**H3 — Registro/remoção de eventos sem log.**
`events.py:132-136` (`_flush` falha ao registrar) e `events.py:218-222`
(`unregister_all`) fazem `pass`. Falha de registro de evento = silêncio total
na coleta.

*Fix:* `debug_log("events.register failed: ...")`.

**H4 — Swallow silencioso generalizado em UI/config/log.**
Padrão `except Exception: pass`/`return default` sem log em:
`chat_ui.py:63,64,75,181,188,215`; `hud.py:170,177,201,205`;
`god_ui.py:35,45,219,224,240,261,294,363,401,447`;
`probe.py:130,158,191,221,299,312,324,352,373,392`;
`config.py:22,30,38,46,54,82,98,156,200,236,355,417`.
Viola §2 do guia. `debug_log.py` pode ser exceção aceitável (logger folha), mas
os demais não.

*Fix:* helper compartilhado de log e logar cada ponto.

**H5 — `_safe_getattr`/`_safe_call` duplicados (6 cópias), algumas sem log.**
`sim_context.py:14-29` e `tool_executor.py:199-212` logam;
`god_ui.py:31-36` e `events.py:60-71` **não** logam. Correções precisam ser
aplicadas em 6 lugares.

*Fix:* centralizar em `debug_log.py` (`safe_getattr`/`safe_call` sempre logando)
e importar em todos os módulos.

**H6 — Argumentos de tools sem validação de tipo.**
`tool_executor.py` (vários handlers) aceita qualquer tipo: ex.
`str(args.get("tone", ...)).lower()` converte `123` → `"123"` e cai no
affordance default em silêncio; IDs podem chegar como `"abc"`.
O sidecar é confiável, mas mudanças de contrato/serialização não são detectadas.

*Fix:* validar tipo por chave do schema antes de usar, retornando
`{"ok": False, "error": "invalid_argument"}`.

---

### MEDIUM

**M1 — `health()` envia header de auth apesar do comentário "no auth".**
`http_client.py:200-203` chama `_make_request`, que em `http_client.py:92`
sempre adiciona `get_auth_header()`. Comentário/código divergentes. Impacto
baixo (o sidecar provavelmente ignora), mas é uma inconsistência perigosa.

*Fix:* remover o header para `/v1/health` (parâmetro `no_auth` em
`_make_request`) ou corrigir o comentário.

**M2 — `json.dumps` fora do `try`.**
`http_client.py:102` serializa antes do `try` (linha 106). Hoje
`_sanitize_payload` garante primitivas, então não deve falhar — mas qualquer
regressão no sanitizador causa `TypeError` antes de qualquer tratamento.

*Fix:* mover `json.dumps` para dentro do `try`.

**M3 — `_resolve_alarm_owner` cai em owners que não tickam.**
`events.py:320-327` prioriza o Sim instance (correto) mas faz fallback para
`current_zone`/`active_household`/`client_manager`, que **registram o handle mas
não avançam o alarme** (causa histórica validada). É a raiz da necessidade do
`zone.Zone.update` hook.

*Fix:* retornar `None` quando não houver Sim instance vivo (deixar o zone hook
criar o alarme quando estiver pronto) em vez de usar fallback não-tickável.

**M4 — `_try_add_alarm` loga só o último erro.**
`events.py:360-375`: erros das tentativas anteriores são perdidos.

*Fix:* acumular/logar cada tentativa.

**M5 — Detecção de buff pode retornar nome de exibição.**
`state_collector.py` `_buff_type_name` faz fallback para `_buff_name`, que
checa `name` antes de `__name__` — pode devolver nome localizado em vez do
tuning id. A §7 do guia exige tuning id exato.

*Fix:* em `_buff_type_name`, usar apenas `buff_type.__name__` (e
`buff_type.buff_type.__name__`); não cair para `_buff_name(buff)`.

**M6 — Strings hardcoded em fallbacks de UI.**
`god_ui.py:393-398` e `439-444` (`_output_hint`) montam texto fixo em vez de
`i18n.t(...)`; `chat_ui.py:196,201` usam títulos `"SimsSense"` /
`"SimsSense Error"` fixos. São visíveis ao jogador.

*Fix:* adicionar chaves em `en.json`/`pt-BR.json` e usar `i18n.t`.

**M7 — HUD mistura token de status com texto localizado.**
`hud.py:129-132,147-151`: passa `_t("hud.on")` ("LIGADO") para o placeholder
`{sidecar}` de `hud.line`, que espera token canônico `ON`/`OFF`/`ERR`.

*Fix:* usar tokens canônicos (`_ON`/`_OFF`/`_ERROR`) no `{sidecar}` ou criar
`hud.line.on/off/error`.

**M8 — `i18n` format não cobre `AttributeError`.**
`i18n.py:274` captura `KeyError, ValueError, IndexError`, mas se o valor for
não-string (`None`, `int`), `str.format` pode levantar `AttributeError` e
quebrar a UI.

*Fix:* incluir `AttributeError` ou retornar `str(value)` quando não-string.

**M9 — `state_collector.py` monolítico (1467 linhas).**
Responsabilidades: alarms, evento handlers, sampling, pulso de zona, pull de
diretivas, census, household. Difícil de testar/revisar.

*Fix:* dividir (alarms/event_handlers/sampler/directive_poller/census).

---

### LOW

- **L1 — Dead code:** `state_collector.py` `_register_handlers` (~1181) nunca é
  chamado (`start()` registra direto).
- **L2 — `pass` em `note_executed`:** `tool_executor.py:896-897,943-944`
  engolem erro do rails sem log.
- **L3 — Duplicação:** `_current_sim_ref` × `_active_sim_ref` e
  `_register_handlers`/`_handlers` em `state_collector.py`.
- **L4 — `cmd_autonomy` não persiste o nível** (`main.py:475-495`): reset ao
  reiniciar o sidecar. `cmd_lang` persiste; autonomia não.
- **L5 — `cmd_zeitgeist "auto"` não passa `lang`** para `suggest_zeitgeist`.
- **L6 — `probe.py:406` usa `json.dumps(..., default=str)`**, mascarando leaks
  de objetos que o sanitizador deveria pegar (ferramenta de debug, baixo risco).
- **L7 — `DEBUG_MODE`/`VALIDATION_MODE` default `True`**
  (`debug_log.py:33,44`): verbose em produção.
- **L8 — `print()` em vez de `debug_log`:** `chat_ui.py:186`, `hud.py:204`,
  `god_ui.py:222`, `main.py:30,177`, `state_collector.py:744`.
- **L9 — `NEVER_TOOLS` inclui `"shell"`/`"http"`** que não existem no registry
  (`rails.py:15-22`). Inofensivo, mas confuso.
- **L10 — Parser TOML artesanal** (`config.py:336-418`) não trata `#` inline,
  `key="v"` sem espaços etc. Frágil para edição manual do `config.toml`.

---

## 3. Conformidade Python 3.7

✅ Sem violações de sintaxe: nenhum walrus, `match`, `int | str`,
`from __future__ import annotations`, `asyncio` ou import não-stdlib.
Uso de f-strings (3.6+) e `typing` genéricos é compatível.

Observação: o guia **proíbe apenas** `from __future__ import annotations`
(quebra o parser de comandos). Anotações normais em parâmetros de
`@sims4.commands.Command` (ex.: `main.py:435,455,476,499,522`) são o mecanismo
**esperado** de parsing — não são bug (ver §5).

---

## 4. Pontos positivos

- `_sanitize_payload` (`http_client.py:41-72`) + coerção de primitivas na
  origem mantêm o wire limpo.
- Deferred-flush de eventos (`events.py:90-148`) honra "services não existem no
  import".
- Fallback de notificação em 3 camadas (`chat_ui`) e fallback de locale para
  `en`.
- i18n de arquivo e de zip `.ts4script` com UTF-8 e fallback.
- Paridade `en.json` × `pt-BR.json` verificada: **idêntica** (131 chaves).
- `probe.py` limita profundidade/nº de itens e nunca emite valores de objetos.

---

## 5. Falsos positivos descartados (não são bugs)

- ❌ "Anotações em comandos quebram o parser TS4." **Incorreto.** O game
  introspecciona anotações para tipar argumentos; o guia proíbe só
  `from __future__ import annotations`. As assinaturas atuais estão corretas.
- ❌ "`tool_executor.py:70` acessa `client.active_sim_info` sem guarda."
  **Incorreto.** Está dentro de `try/except Exception` (`tool_executor.py:60-74`)
  que retorna `None`.
- ❌ "`_safe_call` não é usado em `services.sim_info_manager`."
  **Incorreto.** `state_collector._get_sim_info_manager` faz `_safe_call(getter)`.

---

## 6. Plano de correção sugerido (ordem)

1. **C1** — armar `record_player_activity` (segurança).
2. **H1/H2/H3/H4** — logar todos os `except Exception:` relevantes
   (usar helper compartilhado de **H5**).
3. **M1/M2** — corrigir `health()` e mover `json.dumps` para o `try`.
4. **M3/M5** — endurecer alarm owner e detecção de tuning id de buff.
5. **M6/M7/M8** — i18n de fallbacks e token do HUD.
6. **M9/L\*** — refactor de tamanho, dead code e polimentos.

> Todo novo comportamento/formato deve vir com testes (`mod/tests/`) e entrada
> no `CHANGELOG.md`, conforme §§10 e 11 do guia.
