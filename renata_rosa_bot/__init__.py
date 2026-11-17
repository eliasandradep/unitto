"""Funil de qualificação de leads via WhatsApp — bespoke, exclusivo do tenant
Renata Rosa Beauty Concept (slug 'renatarosa').

Isolado de propósito do motor genérico `ai_attendance/`: este pacote nunca é
importado por `ai_attendance/` (dependência unidirecional), e só é acionado
quando `renata_rosa_bot.gating.funil_ativo(empresa)` é True — ver o ponto de
desvio em `meta_webhook/routes.py::_processar_turno_whatsapp`.
"""
