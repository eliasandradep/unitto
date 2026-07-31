"""Normaliza os payloads de webhook da Meta para uma lista de eventos.

Cada evento normalizado: {identificador_externo, external_thread_id, phone, nome, mensagem, canal}.
"""


def parse_whatsapp(body):
    eventos = []
    for entry in body.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            phone_number_id = value.get('metadata', {}).get('phone_number_id')
            if not phone_number_id:
                continue
            nomes = {c.get('wa_id'): c.get('profile', {}).get('name')
                     for c in value.get('contacts', [])}
            for msg in value.get('messages', []):
                wa_id = msg.get('from')
                if not wa_id:
                    continue
                texto = msg.get('text', {}).get('body') or f'[{msg.get("type", "mensagem")}]'
                eventos.append({
                    'identificador_externo': phone_number_id,
                    'external_thread_id': wa_id,
                    'phone': wa_id,
                    'nome': nomes.get(wa_id),
                    'mensagem': texto,
                    'canal': 'whatsapp',
                })
    return eventos


def _parse_messaging(body, canal):
    eventos = []
    for entry in body.get('entry', []):
        for msg_evt in entry.get('messaging', []):
            message = msg_evt.get('message')
            if not message or message.get('is_echo'):
                continue
            page_id = msg_evt.get('recipient', {}).get('id')
            psid = msg_evt.get('sender', {}).get('id')
            if not page_id or not psid:
                continue
            texto = message.get('text') or '[anexo]'
            eventos.append({
                'identificador_externo': page_id,
                'external_thread_id': psid,
                'phone': None,
                'nome': None,
                'mensagem': texto,
                'canal': canal,
            })
    return eventos


def parse_messenger(body):
    return _parse_messaging(body, 'messenger')


def parse_instagram(body):
    return _parse_messaging(body, 'instagram')
