import pytest
from sensewright_sidecar.config import DEFAULT_CONFIG, Config
from sensewright_sidecar.llm.context import ContextAssembler
from sensewright_sidecar.purposes import PURPOSES
from sensewright_sidecar.llm.limits import estimate_tokens

def _assembler():
    return ContextAssembler(Config(DEFAULT_CONFIG))

@pytest.mark.parametrize("purpose", PURPOSES)
def test_priority_packing_respects_tier_budget(purpose):
    assembler = _assembler()
    budget = assembler.tier_budget(purpose.tier)
    
    context = {
        "profile": {
            "core_personality": "Amigável, extrovertido, adora festas e música alta. Sempre tenta fazer os outros rirem.",
            "current_demeanor": "Muito animado e um pouco distraído.",
            "speech_style": "Usa gírias como 'maneiro', 'da hora', 'sacou?'. Fala rápido.",
            "life_story": "Nasceu em Oasis Springs. Perdeu os pais cedo e foi criado pela avó. Sempre quis ser músico profissional.",
            "psyche_blocks": ["Trauma de fogo", "Medo de palhaços"],
            "dream_residue": "Sonhou que estava voando sobre Willow Creek.",
            "daily_plan": "Praticar violão por 3 horas, fazer uma refeição e ir ao parque.",
            "backstory": "Costumava ser um criminoso antes de decidir mudar de vida."
        },
        "mood": "happy",
        "activity": "playing_guitar",
        "current_needs": "Fome baixa",
        "room_id": 123,
        "is_sleeping": False,
        "is_off_lot_duty": False,
        "message": "E aí, cara, beleza? Vamos fazer uma jam session hoje à noite!",
        "event": "sim_chat",
        "target": "sim_123",
        "directives": "Tente convencê-lo a tocar.",
        "active_arc": "Formar uma banda",
        "zeitgeist_tags": ["festival_de_musica", "verão", "calor"],
        "schedule_blocks": "18h: Ensaio.",
        "obligatory_tasks": "Pagar contas",
        "native_wants": "Comprar instrumento",
        "location": {"is_outside": True, "is_at_home": False, "venue": "Park"},
        "action": {"a_name": "Bob", "a_current": "Conversando", "a_queued": ["Tocar violão", "Contar piada"]},
        "puppeteer_objective": "Faça-o confessar um segredo.",
        "scene_subtext": "Tensão por causa de uma briga antiga.",
        "history": [
            {"role": "user", "content": "Oi, há quanto tempo!"},
            {"role": "assistant", "content": "Verdade, mano! Saudade."},
            {"role": "user", "content": "Trouxe o violão?"},
            {"role": "assistant", "content": "Claro, sempre comigo."}
        ],
        "relationship": {"tier": "friend", "friendship": 85, "friendship_delta": 2, "romance": 10},
        "rumor": "Dizem que o parque vai fechar.",
        "family": [{"name": "Bella", "relation": "Irmã"}],
        "dream_urge": "Comer macarrão com queijo.",
        "player_facts": "O jogador cancelou a ação de dormir.",
        "memories": [
            {"content": "Foi rejeitado ao tentar um beijo com fulana.", "timestamp": 12345},
            {"content": "Aprendeu a tocar violão.", "timestamp": 12345},
            {"content": "Conseguiu promoção.", "timestamp": 12345},
            {"content": "Incêndio na cozinha.", "timestamp": 12345},
            {"content": "Briga com Mortimer.", "timestamp": 12345},
            {"content": "Pescou um peixe raro.", "timestamp": 12345},
            {"content": "Ganhou na loteria.", "timestamp": 12345},
            {"content": "Se mudou para uma casa nova.", "timestamp": 12345},
            {"content": "Adotou um cachorro.", "timestamp": 12345}
        ]
    }
    
    msgs = assembler.assemble(purpose.id, context, "pt-BR")
    sys_text = msgs[0]["content"]
    usr_text = msgs[1]["content"]
    toks = estimate_tokens(sys_text + "\n" + usr_text)
    
    assert toks <= budget + 20
