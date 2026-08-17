"""Atendimento por IA no WhatsApp — camada de serviço (sem blueprint próprio).

Chamada pelo meta_webhook_bp (condução da conversa) e pelo admin_bp (tela de
configuração do menu/informações do estabelecimento). Disponível somente para
tenants com Empresa.tem_atendimento_ia() (plano PRO + toggle ativo) — ver
gating.py, que é o ponto único de checagem de elegibilidade.
"""
